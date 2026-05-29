#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
check_visibility_line.py (v7) — Análisis de Visibilidad Timelapse (Escala Estricta)
===================================================================================
Genera un PDF multipágina con un recorte (clipping) estricto.
El eje X será exactamente el radio solicitado y el eje Y se limitará a 30m por 
encima de la cota máxima del terreno.
"""

import argparse
import collections.abc
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import rasterio
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import ephem
import yaml

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

def calculate_sun_positions(lat: float, lon: float, times_utc: list) -> list:
    obs = ephem.Observer()
    obs.lat = str(lat)
    obs.lon = str(lon)
    obs.elevation = 0
    sun = ephem.Sun()
    
    positions = []
    for t in times_utc:
        obs.date = t
        sun.compute(obs)
        positions.append({
            'time_local': t.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None),
            'az_deg': math.degrees(sun.az),
            'alt_deg': math.degrees(sun.alt)
        })
    return positions

def get_terrain_profile(tif_path: Path, obs_x: float, obs_y: float, obs_z: float, 
                        azimuth_deg: float, radius_m: float, step_m: float, min_distance_m: float):
    with rasterio.open(tif_path) as src:
        data = src.read(1)
        nodata = src.nodata if src.nodata is not None else -9999.0
        transform = src.transform

        distances = np.arange(min_distance_m, radius_m, step_m)
        az_rad = math.radians(azimuth_deg)
        
        dx = distances * math.sin(az_rad)
        dy = distances * math.cos(az_rad)
        sample_x = obs_x + dx
        sample_y = obs_y + dy

        rows, cols = rasterio.transform.rowcol(transform, sample_x, sample_y)
        rows = np.clip(rows, 0, src.height - 1)
        cols = np.clip(cols, 0, src.width - 1)

        terrain_z = data[rows, cols]
        
        valid_mask = (terrain_z != nodata) & (terrain_z > -1000)
        distances = distances[valid_mask]
        terrain_z = terrain_z[valid_mask]

        dz = terrain_z - obs_z
        terrain_alt_deg = np.degrees(np.arctan2(dz, distances))

        return distances, terrain_z, terrain_alt_deg

def generate_multipage_pdf(profiles_data, obs_z, out_pdf, landscape_name, profile_radius):
    """
    Genera el PDF con recorte estricto a los límites del terreno.
    """
    print(f"\n  Creando PDF Timelapse de {len(profiles_data)} páginas (Escala estricta)...")
    
    # ──> 1. CALCULAR COTA MÁXIMA PARA EL RECORTE <──
    global_min_z = obs_z
    global_max_terrain_z = obs_z

    for data in profiles_data:
        z = data['terrain_z']
        if len(z) > 0:
            global_min_z = min(global_min_z, min(z))
            global_max_terrain_z = max(global_max_terrain_z, max(z))

    # LÍMITES ESTRICTOS SOLICITADOS
    ylim_bottom = global_min_z - 10  # Solo 10 metros por debajo del punto más bajo
    ylim_top = global_max_terrain_z + 30  # Exactamente 30 metros por encima de la cota máxima
    xlim_max = profile_radius  # Exactamente el radio solicitado (ej. 700m)

    # ──> 2. DIBUJAR PÁGINAS <──
    with PdfPages(out_pdf) as pdf:
        for idx, data in enumerate(profiles_data):
            fig, ax = plt.subplots(figsize=(12, 6.75)) # Formato panorámico
            
            dist = data['distances']
            z = data['terrain_z']
            pos = data['solar_pos']
            blocked = data['is_blocked']
            
            time_str = pos['time_local'].strftime('%H:%M:%S')
            az_str = f"{pos['az_deg']:.2f}º"
            alt_str = f"{pos['alt_deg']:.2f}º"

            # Terreno
            ax.plot(dist, z, label=f'Perfil Terreno (Azimut: {az_str})', color='saddlebrown', linewidth=2)
            ax.scatter([0], [obs_z], color='blue', s=100, label='Observador', zorder=5)
            ax.fill_between(dist, z, -100, color='saddlebrown', alpha=0.3)

            # Rayo del Sol
            # Matplotlib recorta automáticamente (clip) las líneas que se salen de los límites de los ejes
            ray_z = obs_z + dist * math.tan(math.radians(pos['alt_deg']))
            sun_color = 'red' if blocked else '#ffaa00'
            line_style = '-' if blocked else '--'
            ax.plot(dist, ray_z, linestyle=line_style, color=sun_color, linewidth=2,
                     label=f"Línea Sol (Alt: {alt_str})")

            # Colisiones
            if blocked:
                # Solo dibujar la colisión si cae dentro del rango X solicitado
                if data['blocked_dist'] <= xlim_max:
                    ax.scatter([data['blocked_dist']], [data['blocked_z']], color='red', s=150, marker='X', zorder=10, label='Obstrucción')
                status = f"OBSTRUIDO a {data['blocked_dist']:.0f}m"
            else:
                status = "DESPEJADO"

            # Textos
            progress = f"[{idx+1}/{len(profiles_data)}]"
            ax.set_title(f"{landscape_name} | Minuto {progress} | Fase: {time_str} | Azimut: {az_str} | {status}", fontsize=13, fontweight='bold')
            ax.set_ylabel("Altitud (m.s.n.m.)", fontsize=11)
            ax.set_xlabel("Distancia hacia el objetivo (m)", fontsize=11)
            ax.grid(True, linestyle=':', alpha=0.6)
            ax.legend(loc='upper left', framealpha=0.9)  # Movido a la izquierda para que no tape el horizonte derecho
            
            # --- APLICAR LA ESCALA ESTRICTA ---
            ax.set_ylim(ylim_bottom, ylim_top)
            ax.set_xlim(0, xlim_max)

            plt.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project_dir", required=True, type=str)
    parser.add_argument("--eclipse_max", type=str, help="Hora del máximo (ISO 8601 ej. 2026-08-12T20:36:00)", default=None)
    parser.add_argument("--layer", default="all", type=str)
    parser.add_argument("--profile_radius", default=700, type=float)
    args = parser.parse_args()

    project_path = Path(args.project_dir)
    config = load_merged_config(project_path)
    
    obs_x = float(config['observer']['x'])
    obs_y = float(config['observer']['y'])
    obs_z = float(config['observer']['ground_z']) + float(config['observer'].get('camera_height', 1.6))
    lat = float(config['project'].get('latitude', '37.88'))
    lon = float(config['project'].get('longitude', '-4.78'))
    
    eclipse_str = args.eclipse_max or config.get('project', {}).get('eclipse_time', '2026-08-12T20:36:00')
    try:
        eclipse_time_local = datetime.fromisoformat(eclipse_str)
    except ValueError:
        print(f"[ERROR] Formato de fecha incorrecto: {eclipse_str}")
        sys.exit(1)
        
    eclipse_time_utc = eclipse_time_local.astimezone(timezone.utc)
    
    # Bucle de ±60 minutos
    times_utc = []
    print("\nCalculando efemérides minuto a minuto para ±1 hora...")
    for m in range(-60, 61): 
        times_utc.append(eclipse_time_utc + timedelta(minutes=m))
    
    solar_positions = calculate_sun_positions(lat, lon, times_utc)
    
    # ──> PRIORIDAD: Local DSM -> Fallback: Global VRT <──
    local_tif = project_path / "workspace" / "dsm" / f"dsm_{args.layer}.tif"
    global_vrt = Path(r"C:\GIS\LiDAR-Stellarium\data_raw\mdt\terreno_completo.vrt")

    if local_tif.exists():
        tif_path = local_tif
        print(f"\n[INFO] Usando modelo detallado local: {tif_path.name}")
    elif global_vrt.exists():
        tif_path = global_vrt
        print(f"\n[INFO] Usando terreno base global: {tif_path.name}")
    else:
        print(f"\n[ERROR] No se encontró ni el DSM local ni el VRT global.")
        sys.exit(1)
            
    print("\n" + "="*65)
    print(f" TIMELAPSE DE VISIBILIDAD: Generando 121 perfiles (Resolución 0.5m)")
    print("="*65)

    profiles_data = []
    all_clear = True
    
    for idx, pos in enumerate(solar_positions):
        t_str = pos['time_local'].strftime('%H:%M:%S')
        
        if idx % 10 == 0 or idx == len(solar_positions) - 1:
            print(f"-> Escaneando {t_str} | Azimut Sol: {pos['az_deg']:.2f}º | Altitud: {pos['alt_deg']:.2f}º")
        
        # MÁXIMA RESOLUCIÓN ACTIVA: step_m = 0.5
        distances, terrain_z, terrain_alt_deg = get_terrain_profile(
            tif_path, obs_x, obs_y, obs_z, pos['az_deg'], 
            radius_m=args.profile_radius, step_m=0.5, min_distance_m=2.0
        )
        
        if len(distances) == 0:
            continue
            
        obstructions = distances[terrain_alt_deg > pos['alt_deg']]
        
        is_blocked = len(obstructions) > 0
        blocked_dist = obstructions[0] if is_blocked else None
        
        profiles_data.append({
            'solar_pos': pos,
            'distances': distances,
            'terrain_z': terrain_z,
            'terrain_alt_deg': terrain_alt_deg,
            'is_blocked': is_blocked,
            'blocked_dist': blocked_dist,
            'blocked_z': terrain_z[np.where(distances == blocked_dist)[0][0]] if is_blocked else None
        })
        
        if is_blocked:
            all_clear = False

    print("\n" + "-"*65)
    if all_clear:
        print(">>> UBICACIÓN ÓPTIMA. Sol libre de obstáculos durante las 2 horas. <<<")
    else:
        print(">>> RIESGO: El Sol impactará contra el terreno en algún momento. <<<")
    print("-" * 65)

    if len(profiles_data) > 0:
        output_dir = project_path / "output" / "reports"
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        
        out_pdf = output_dir / f"timelapse_visibilidad_estricto_{ts}.pdf"
        
        generate_multipage_pdf(
            profiles_data, obs_z, 
            out_pdf,
            config['project'].get('landscape_name', project_path.name),
            args.profile_radius
        )
        print(f"\n¡PDF COMPLETO! Guardado en: {out_pdf.name}")

if __name__ == "__main__":
    main()