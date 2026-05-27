#!/usr/bin/env python3
"""
find_highest_point_v4.py — AstroHorizon-LiDAR
=============================================================
Realiza una doble búsqueda topográfica (Global y Local) 
adaptado a la nueva arquitectura modular de proyectos.
Devuelve coordenadas UTM y geográficas (Google Maps).
Guarda los resultados en un archivo JSON en output/reports/.
"""

import argparse
import sys
import collections.abc
import json
from pathlib import Path
from datetime import datetime

import numpy as np
import rasterio
import yaml
from pyproj import Transformer
from rasterio.windows import from_bounds

# ==============================================================================
# 1. UTILIDADES DE CONFIGURACIÓN Y LOG
# ==============================================================================
def deep_update(d, u):
    """Fusiona diccionarios anidados recursivamente."""
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = deep_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d

def load_merged_config(project_dir: Path) -> dict:
    """Carga el config maestro y lo fusiona con el del proyecto local."""
    base_dir = project_dir.parents[1]
    master_path = base_dir / "scripts" / "core" / "config_master.yaml"
    project_path = project_dir / "config.yaml"

    master_config = yaml.safe_load(open(master_path, encoding="utf-8")) if master_path.exists() else {}
    project_config = yaml.safe_load(open(project_path, encoding="utf-8")) if project_path.exists() else {}

    return deep_update(master_config, project_config)

def log_execution(log_file: Path, script_name: str, status: str, message: str = ""):
    """Escribe un registro sencillo en ejecuciones.log"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] | Script: {script_name} | Estado: {status} | {message}\n"
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(log_entry)

# ==============================================================================
# 2. FUNCIONES MATEMÁTICAS
# ==============================================================================
def extract_max_point(data: np.ndarray, transform: rasterio.Affine, nodata: float) -> tuple:
    """Encuentra el Z_max y sus coordenadas UTM (X, Y) en una matriz."""
    valid_mask = (data != nodata) & np.isfinite(data) & (data > -1000)
    
    if not np.any(valid_mask):
        return None, None, None

    data_safe = np.where(valid_mask, data, -np.inf)
    max_idx = np.nanargmax(data_safe)
    row, col = np.unravel_index(max_idx, data_safe.shape)
    max_z = data_safe[row, col]

    max_x, max_y = transform * (col + 0.5, row + 0.5)
    return float(max_x), float(max_y), float(max_z) # Forzamos a float nativo para el JSON

def print_result_block(title: str, max_x: float, max_y: float, max_z: float, lat: float, lon: float, offset: float = None):
    """Imprime un bloque de resultados formateado."""
    print("\n" + "-"*65)
    print(f" >> {title} <<")
    print("-" * 65)
    print(f"Cota Máx (Z)       : {max_z:.3f} m s.n.m.")
    if offset is not None:
        print(f"Desplazamiento     : {offset:.2f} metros desde coordenada original.")
    
    print("\n  [COORDENADAS UTM]")
    print(f"    x: {max_x:.3f}")
    print(f"    y: {max_y:.3f}")
    
    print("\n  [COORDENADAS GOOGLE MAPS]")
    print(f"    {lat:.7f}, {lon:.7f}")


# ==============================================================================
# 3. FLUJO PRINCIPAL
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="Búsqueda topográfica de cota máxima (Global y Local).")
    parser.add_argument("--project_dir", required=True, help="Ruta absoluta al directorio del proyecto.")
    parser.add_argument("--layer", "-l", default="all", choices=["all", "edificios", "vegetacion_alta"],
                        help="Capa sobre la que buscar. Por defecto: all")
    parser.add_argument("--radius", "-r", type=float, default=20.0,
                        help="Radio de búsqueda local alrededor del target. Por defecto: 20m")
    args = parser.parse_args()

    project_dir = Path(args.project_dir)
    log_path = project_dir / "ejecuciones.log"
    reports_dir = project_dir / "output" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    print("\n" + "="*65)
    print("   BÚSQUEDA DE COTA MÁXIMA - GLOBAL Y TARGET (V4)")
    print("="*65)

    cfg = load_merged_config(project_dir)
    target = cfg.get("target", {})
    crs = cfg.get("crs", "EPSG:25830")
    transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    
    dsm_dir = project_dir / "workspace" / "dsm"
    tif_path = dsm_dir / f"dsm_{args.layer}.tif"
    
    if not tif_path.exists():
        msg = f"No se encuentra el archivo: {tif_path.name}. Debes extraer las clases primero."
        print(f"[ERROR] {msg}")
        log_execution(log_path, "find_highest_point_v4.py", "ERROR", msg)
        sys.exit(1)

    print(f"[INFO] Analizando capa : {tif_path.name}")
    log_msg_parts = []
    
    # Diccionario para guardar los resultados
    results_data = {
        "timestamp": datetime.now().isoformat(),
        "layer_analyzed": args.layer,
        "global": None,
        "local": None
    }

    with rasterio.open(tif_path) as src:
        nodata = src.nodata if src.nodata is not None else -9999.0
        
        # ==========================================
        # FASE 1: BÚSQUEDA GLOBAL
        # ==========================================
        print("\n[INFO] Realizando escaneo GLOBAL en todo el ráster...")
        data_global = src.read(1)
        g_x, g_y, g_z = extract_max_point(data_global, src.transform, nodata)
        
        if g_z is not None:
            g_lon, g_lat = transformer.transform(g_x, g_y)
            print_result_block("RESULTADO GLOBAL (PUNTO MÁS ALTO DEL MAPA)", g_x, g_y, g_z, g_lat, g_lon)
            log_msg_parts.append(f"Z_Max Global: {g_z:.2f}m")
            
            results_data["global"] = {
                "utm_x": g_x, "utm_y": g_y, "z": g_z,
                "lat": float(g_lat), "lon": float(g_lon)
            }
        else:
            print("\n[AVISO] No se encontraron datos válidos en el ráster completo.")
            log_msg_parts.append("Global Fallido")

        # ==========================================
        # FASE 2: BÚSQUEDA LOCAL (TARGET)
        # ==========================================
        if not target or target.get("x", 0.0) == 0.0:
            print("\n[AVISO] No se definió un objetivo ('target') válido en config.yaml. Se omite búsqueda local.")
            log_msg_parts.append("Búsqueda Local omitida (Sin Target)")
        else:
            t_x = float(target.get("x", 0))
            t_y = float(target.get("y", 0))
            print(f"\n[INFO] Realizando escaneo LOCAL en radio de {args.radius}m desde Target...")
            
            left, bottom = t_x - args.radius, t_y - args.radius
            right, top   = t_x + args.radius, t_y + args.radius
            window = from_bounds(left, bottom, right, top, transform=src.transform)
            
            data_local = src.read(1, window=window)
            win_transform = src.window_transform(window)
            
            l_x, l_y, l_z = extract_max_point(data_local, win_transform, nodata)
            
            if l_z is not None:
                l_lon, l_lat = transformer.transform(l_x, l_y)
                offset = float(np.sqrt((l_x - t_x)**2 + (l_y - t_y)**2))
                print_result_block(f"RESULTADO LOCAL (TARGET ± {args.radius}m)", l_x, l_y, l_z, l_lat, l_lon, offset)
                log_msg_parts.append(f"Z_Max Local: {l_z:.2f}m (Offset: {offset:.1f}m)")
                
                results_data["local"] = {
                    "search_radius_m": args.radius,
                    "utm_x": l_x, "utm_y": l_y, "z": l_z,
                    "lat": float(l_lat), "lon": float(l_lon),
                    "offset_from_target_m": offset
                }
            else:
                print(f"\n[AVISO] No hay datos válidos en un radio de {args.radius}m.")
                log_msg_parts.append("Local Fallido")

    # Guardar resultados en JSON
    json_output_path = reports_dir / f"highest_point_{args.layer}.json"
    with open(json_output_path, "w", encoding="utf-8") as f:
        json.dump(results_data, f, indent=4)
        
    print(f"\n[INFO] Resultados guardados en: {json_output_path}")
    print("\n" + "="*65 + "\n")
    
    # Escribir resumen en el log
    final_log_msg = " | ".join(log_msg_parts)
    log_execution(log_path, "find_highest_point_v4.py", "OK", final_log_msg)

if __name__ == "__main__":
    main()