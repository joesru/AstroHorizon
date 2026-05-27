#!/usr/bin/env python3
"""
build_horizon_v3.py — AstroHorizon-LiDAR (Versión Completa Producción)
========================================================================
Motor geométrico de horizonte con Raycasting Vectorizado 360º.
Exporta un archivo landscape.ini con auditoría completa de metadatos.
"""

import argparse
import collections.abc
import csv
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
import yaml

# ==============================================================================
# 1. UTILIDADES DE CONFIGURACIÓN Y LOG
# ==============================================================================
def deep_update(d, u):
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = deep_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d

def load_merged_config(project_dir: Path) -> dict:
    base_dir = project_dir.parents[1]
    master_path = base_dir / "scripts" / "core" / "config_master.yaml"
    project_path = project_dir / "config.yaml"

    master_config = yaml.safe_load(open(master_path, encoding="utf-8")) if master_path.exists() else {}
    project_config = yaml.safe_load(open(project_path, encoding="utf-8")) if project_path.exists() else {}

    return deep_update(master_config, project_config)

def log_execution(log_file: Path, script_name: str, status: str, message: str = ""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] | Script: {script_name:<20} | {status:<7} | {message}\n"
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(log_entry)

def print_progress_bar(iteration, total, prefix='Progreso:', suffix='Completado', length=40, fill='█'):
    percent = f"{100 * (iteration / float(total)):.1f}"
    filled_length = int(length * iteration // total)
    bar = fill * filled_length + '─' * (length - filled_length)
    print(f'\r  {prefix} ├{bar}┤ {percent}% {suffix}', end='', flush=True)
    if iteration == total: print()

# ==============================================================================
# 2. MOTOR DE ÁNGULOS Y AZIMUTS
# ==============================================================================
def calculate_target_azimuth(obs_x: float, obs_y: float, tgt_x: float, tgt_y: float) -> float:
    dx = tgt_x - obs_x
    dy = tgt_y - obs_y
    return (90 - math.degrees(math.atan2(dy, dx))) % 360.0

def generate_azimuths(skyline_cfg: dict, fallback_step: float, target_azimuth: float = None) -> tuple:
    """Devuelve un tuple: (array_azimuts, start_az_fino, end_az_fino)"""
    default_step = float(skyline_cfg.get("default_azimuth_step_deg", fallback_step))
    azimuths = list(np.arange(0, 360, default_step))
    
    start_az, end_az = None, None
    if target_azimuth is not None:
        window = float(skyline_cfg.get("target_fine_window_deg", 5.0))
        fine_step = float(skyline_cfg.get("target_fine_step_deg", 0.001))
        
        start_az = (target_azimuth - window) % 360
        end_az = (target_azimuth + window) % 360
        
        print(f"[INFO] 🎯 Target detectado en {target_azimuth:.2f}º")
        print(f"[INFO] 🔍 Creado sector de ultra-precisión [{start_az:.1f}º a {end_az:.1f}º] con paso {fine_step}º")
        
        if start_az < end_az:
            fine_az = list(np.arange(start_az, end_az + fine_step/2.0, fine_step))
        else:
            fine_az = list(np.arange(start_az, 360, fine_step)) + list(np.arange(0, end_az + fine_step/2.0, fine_step))
        
        azimuths.extend(fine_az)

    azimuths = np.array(azimuths)
    azimuths = azimuths % 360.0
    return np.unique(np.round(azimuths, 5)), start_az, end_az

# ==============================================================================
# 3. MOTOR TOPOGRÁFICO (RAYCASTING VECTORIZADO)
# ==============================================================================
def calculate_precise_horizon(data: np.ndarray, transform: rasterio.Affine, nodata: float,
                              obs_x: float, obs_y: float, obs_z: float,
                              azimuths: np.ndarray, radius_m: float,
                              min_dist: float, step_m: float) -> list:
    rows, cols = data.shape
    dist_vector = np.arange(min_dist, radius_m + step_m, step_m)
    horizon_points = []
    total_rays = len(azimuths)

    print(f"[INFO] 🚀 Iniciando barrido topográfico analítico ({total_rays} rayos)...")
    
    for idx, az in enumerate(azimuths, 1):
        theta = np.radians(90 - az)
        x_ray = obs_x + dist_vector * np.cos(theta)
        y_ray = obs_y + dist_vector * np.sin(theta)
        
        c_frac, r_frac = ~transform * (x_ray, y_ray)
        r_idx = np.floor(r_frac).astype(int)
        c_idx = np.floor(c_frac).astype(int)
        
        valid_bounds = (r_idx >= 0) & (r_idx < rows) & (c_idx >= 0) & (c_idx < cols)
        
        if not np.any(valid_bounds):
            horizon_points.append((float(az), 0.0, 0.0, obs_z))
        else:
            r_idx_v = r_idx[valid_bounds]
            c_idx_v = c_idx[valid_bounds]
            d_vals_v = dist_vector[valid_bounds]
            z_vals = data[r_idx_v, c_idx_v]
            
            valid_z = (z_vals != nodata) & np.isfinite(z_vals) & (z_vals > -1000)
            
            if not np.any(valid_z):
                horizon_points.append((float(az), 0.0, 0.0, obs_z))
            else:
                final_d = d_vals_v[valid_z]
                final_z = z_vals[valid_z]
                
                dz = final_z - obs_z
                altitudes = np.degrees(np.arctan2(dz, final_d))
                
                max_i = int(np.argmax(altitudes))
                horizon_points.append((
                    float(az), float(altitudes[max_i]), float(final_d[max_i]), float(final_z[max_i])
                ))
        
        if idx % 1000 == 0 or idx == total_rays: print_progress_bar(idx, total_rays)
            
    return horizon_points

# ==============================================================================
# 4. EXPORTADORES CON META-INYECCIÓN COMPLETOS
# ==============================================================================
def export_landscape_ini(out_path: Path, name: str, proj_name: str, 
                         lat: float, lon: float, alt: float, 
                         obs_x: float, obs_y: float, crs: str,
                         target_az: float, start_az: float, end_az: float,
                         layer: str, radius_m: float, dist_step: float,
                         stel_cfg: dict, skyline_cfg: dict, author: str):
    """Genera un archivo landscape.ini con un volcado total de metadatos del procesado."""
    compilation_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    rot_z = stel_cfg.get("polygonal_angle_rotatez", 0.00001)
    ext = stel_cfg.get("atmospheric_extinction_coefficient", 0.27)
    temp = stel_cfg.get("atmospheric_temperature", 35)
    pres = stel_cfg.get("atmospheric_pressure", 1005)
    lp = stel_cfg.get("light_pollution", 5)
    
    base_ang_res = skyline_cfg.get("default_azimuth_step_deg", 0.005)
    tgt_ang_res = skyline_cfg.get("target_fine_step_deg", 0.001)
    
    # 1. Construcción de la descripción visible en la UI de Stellarium
    desc = f"LiDAR {layer} | Proyecto: {proj_name} | Creado: {compilation_date} | "
    if target_az is not None:
        desc += f"Max Res: {tgt_ang_res}º en Az {target_az:.2f}º (+/-5º)"
    else:
        desc += f"Res base: {base_ang_res}º (Sin Target)"

    content = f"""[landscape]
name = {name}
author = {author}
description = {desc}
type = polygonal

polygonal_horizon_list = horizon.txt
polygonal_horizon_list_mode = azDeg_altDeg
polygonal_angle_rotatez = {rot_z}

minimal_altitude = -5
ground_color = 0.0,0.0,0.0
horizon_line_color = 0.95,0.40,0.10
minimal_brightness = 0.15

[location]
planet = Earth
latitude = {lat:.7f}
longitude = {lon:.7f}
altitude = {alt:.3f}
timezone = Europe/Madrid

atmospheric_extinction_coefficient = {ext}
atmospheric_temperature = {temp}
atmospheric_pressure = {pres}
light_pollution = {lp}

[compilation_metadata]
project_name = {proj_name}
compilation_timestamp = {compilation_date}
lidar_layer_used = {layer}
lidar_search_radius_m = {radius_m}
lidar_radial_precision_m = {dist_step}
source_crs = {crs}
observer_utm_x = {obs_x:.3f}
observer_utm_y = {obs_y:.3f}
base_angular_resolution_deg = {base_ang_res}
target_fine_resolution_deg = {tgt_ang_res if target_az is not None else "N/A"}
target_azimuth_deg = {f"{target_az:.4f}" if target_az is not None else "N/A"}
target_fine_range_start_deg = {f"{start_az:.4f}" if start_az is not None else "N/A"}
target_fine_range_end_deg = {f"{end_az:.4f}" if end_az is not None else "N/A"}
"""
    with open(out_path, 'w', encoding='utf-8') as f: f.write(content)

def export_stellarium_horizon(horizon_points: list, out_path: Path):
    with open(out_path, 'w', encoding='utf-8') as f:
        for p in horizon_points: f.write(f"{p[0]:.5f} {p[1]:.5f}\n")

def export_csv_report(horizon_points: list, out_path: Path):
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Azimut", "Altitud_grados", "Distancia_m", "Cota_m"])
        for p in horizon_points:
            writer.writerow([f"{p[0]:.5f}", f"{p[1]:.5f}", f"{p[2]:.2f}", f"{p[3]:.3f}"])

# ==============================================================================
# 5. ORQUESTACIÓN
# ==============================================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project_dir", required=True)
    parser.add_argument("--layer", "-l", default="all")
    parser.add_argument("--step", "-s", type=float, default=0.5)
    args = parser.parse_args()

    project_dir = Path(args.project_dir)
    log_path = project_dir / "ejecuciones.log"
    reports_dir = project_dir / "output" / "reports"
    stellarium_dir = project_dir / "output" / "stellarium"
    dsm_dir = project_dir / "workspace" / "dsm"
    
    print("\n" + "="*65)
    print("   GENERADOR DE HORIZONTES 360º — ALTA PRECISIÓN (V3)")
    print("="*65)

    config = load_merged_config(project_dir)
    
    obs = config.get("observer", {})
    obs_x, obs_y = float(obs.get("x", 0)), float(obs.get("y", 0))
    total_obs_z = float(obs.get("ground_z", 0)) + float(obs.get("camera_height", 1.6))
    
    target = config.get("target", {})
    tgt_x, tgt_y = float(target.get("x", 0)), float(target.get("y", 0))
    
    target_az = None
    if tgt_x != 0.0 and tgt_y != 0.0:
        target_az = calculate_target_azimuth(obs_x, obs_y, tgt_x, tgt_y)

    raster_cfg = config.get("raster", {})
    radius_m = float(raster_cfg.get("radius_m", 1500))
    res_m = float(raster_cfg.get("resolution_m", 0.5))
    crs = config.get("crs", "EPSG:25830")
    
    skyline_cfg = config.get("skyline", {})
    min_dist = float(skyline_cfg.get("min_distance_m", 2.0))
    dist_step = float(skyline_cfg.get("distance_step_m", res_m / 4.0)) 
    
    azimuths, start_az, end_az = generate_azimuths(skyline_cfg, args.step, target_az)
    
    geo_transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    obs_lon, obs_lat = geo_transformer.transform(obs_x, obs_y)
    
    tif_path = dsm_dir / f"dsm_{args.layer}.tif"
    if not tif_path.exists():
        sys.exit(1)

    print(f"[INFO] Capa objetivo     : {tif_path.name}")
    print(f"[INFO] Observador (X,Y)  : {obs_x}, {obs_y}")
    print(f"[INFO] Altitud observador: {total_obs_z:.3f} m s.n.m.")
    
    t0 = time.time()
    
    with rasterio.open(tif_path) as src:
        data = src.read(1)
        nodata = src.nodata if src.nodata is not None else -9999.0
        horizon = calculate_precise_horizon(
            data=data, transform=src.transform, nodata=nodata,
            obs_x=obs_x, obs_y=obs_y, obs_z=total_obs_z,
            azimuths=azimuths, radius_m=radius_m,
            min_dist=min_dist, step_m=dist_step
        )

    landscape_name = config.get("project", {}).get("landscape_name", project_dir.name)
    target_landscape_dir = stellarium_dir / landscape_name
    target_landscape_dir.mkdir(parents=True, exist_ok=True)
    
    export_stellarium_horizon(horizon, target_landscape_dir / "horizon.txt")
    
    # Llamada al exportador con el volcado total de metadatos
    export_landscape_ini(
        out_path=target_landscape_dir / "landscape.ini", name=landscape_name, proj_name=project_dir.name,
        lat=obs_lat, lon=obs_lon, alt=total_obs_z, obs_x=obs_x, obs_y=obs_y, crs=crs,
        target_az=target_az, start_az=start_az, end_az=end_az, layer=args.layer,
        radius_m=radius_m, dist_step=dist_step, stel_cfg=config.get("stellarium", {}),
        skyline_cfg=skyline_cfg, author=config.get("project", {}).get("author", "Jose")
    )
    export_csv_report(horizon, reports_dir / f"horizon_{args.layer}.csv")
    
    elapsed = time.time() - t0
    print(f"\n[ÉXITO] Entorno Stellarium generado en: {target_landscape_dir.name} ({elapsed:.1f}s)")
    log_execution(log_path, "build_horizon_v3.py", "OK", f"Horizonte 360º con metadatos extendidos")

if __name__ == "__main__": main()