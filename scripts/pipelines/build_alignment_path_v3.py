#!/usr/bin/env python3
"""
build_alignment_path_v3.py — AstroHorizon-LiDAR
========================================================================
Genera un archivo GeoJSON estático con el cono de visión (FOV) y la
línea central, anclados en el Observer y apuntando al Target del config.
Incluye nombres dinámicos de archivo y estilos (colores/opacidad) integrados.
"""

import argparse
import collections.abc
import json
import math
import sys
from pathlib import Path

import yaml

# ==============================================================================
# 1. UTILIDADES DE CONFIGURACIÓN
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

def save_project_config(project_dir: Path, new_data: dict):
    project_path = project_dir / "config.yaml"
    cfg = yaml.safe_load(open(project_path, encoding="utf-8")) if project_path.exists() else {}
    cfg = deep_update(cfg, new_data)
    with open(project_path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

def print_ui_header(title: str):
    print(f"\n{'-'*65}\n >> {title}\n{'-'*65}")

# ==============================================================================
# 2. MOTOR FOTOGRÁFICO
# ==============================================================================
def calculate_fov(sensor_w: float, sensor_h: float, focal_length: float) -> tuple:
    fov_h = 2 * math.degrees(math.atan(sensor_w / (2 * focal_length)))
    fov_v = 2 * math.degrees(math.atan(sensor_h / (2 * focal_length)))
    return fov_h, fov_v

def setup_camera_interactive(project_dir: Path) -> dict:
    db_path = project_dir.parents[1] / "scripts" / "core" / "equipment_db.yaml"
    if not db_path.exists():
        print(f"[ERROR] No se encontró la base de datos de equipo en: {db_path}")
        sys.exit(1)

    db = yaml.safe_load(open(db_path, encoding="utf-8"))
    sensors, lenses = list(db.get("sensors", {}).items()), list(db.get("lenses", {}).items())
    
    print_ui_header("PLANIFICADOR DE ÓPTICAS Y ENCUADRE")
    
    print("  [1] Selecciona la cámara o tipo de sensor:")
    for i, (name, data) in enumerate(sensors, 1): 
        print(f"    {i}. {name} ({data['width_mm']}x{data['height_mm']} mm)")
    s_idx = int(input("\n  Selección de cámara (por defecto 1): ") or 1) - 1
    s_name, s_data = sensors[max(0, min(s_idx, len(sensors)-1))]
    
    print("\n  [2] Selecciona el objetivo a montar:")
    for i, (name, data) in enumerate(lenses, 1): 
        print(f"    {i}. {name}")
    print("    0. Introducir distancia focal manual")
    l_input = input("\n  Selección de objetivo (por defecto 1): ") or "1"
    
    if l_input.strip() == "0":
        focal_length = float(input("  Introduce la distancia focal en mm: ") or 50.0)
        l_name = f"Focal Fija Custom {focal_length}mm"
    else:
        l_idx = int(l_input) - 1
        l_name, l_data = lenses[max(0, min(l_idx, len(lenses)-1))]
        if l_data["type"] == "zoom":
            focal_length = float(input(f"  Es un Zoom ({l_data['min_focal_mm']}-{l_data['max_focal_mm']}mm). Focal a usar: ") or l_data['max_focal_mm'])
        else: 
            focal_length = float(l_data["focal_mm"])

    print("\n  [3] Orientación de la toma:")
    print("    1. Horizontal (Paisaje)\n    2. Vertical (Retrato)")
    o_input = input("\n  Selección (1/2): ") or "1"
    
    if o_input.strip() == "2": 
        orientation, active_w, active_h = "Vertical", s_data['height_mm'], s_data['width_mm']
    else: 
        orientation, active_w, active_h = "Horizontal", s_data['width_mm'], s_data['height_mm']

    aperture = input("\n  [4] Apertura del diafragma (ej. 8): f/") or "8"

    fov_h, fov_v = calculate_fov(active_w, active_h, focal_length)
    cam_config = {
        "photography": {
            "camera_body": s_name, "lens_used": l_name, "focal_length_mm": focal_length,
            "aperture": f"f/{aperture}", "orientation": orientation,
            "fov_horizontal_deg": round(fov_h, 4), "fov_vertical_deg": round(fov_v, 4),
            "sensor_active_width_mm": active_w, "sensor_active_height_mm": active_h
        }
    }
    save_project_config(project_dir, cam_config)
    print(f"\n[OK] Configuración registrada. FOV H: {fov_h:.2f}º | V: {fov_v:.2f}º")
    return cam_config["photography"]

# ==============================================================================
# 3. CONSTRUCCIÓN DEL GEOJSON CON ESTILOS
# ==============================================================================
def build_static_fov_geojson(obs_x, obs_y, tgt_x, tgt_y, fov_h_deg, layer_name):
    """
    Construye un GeoJSON con colores incrustados.
    """
    dx = tgt_x - obs_x
    dy = tgt_y - obs_y
    dist_m = math.hypot(dx, dy)
    
    if dist_m == 0:
        return None
        
    camera_az = (90 - math.degrees(math.atan2(dy, dx))) % 360.0
    length = dist_m * 1.20 # Cono sobrepasa el target un 20%
    
    left_az = camera_az - (fov_h_deg / 2.0)
    right_az = camera_az + (fov_h_deg / 2.0)
    
    cone_coords = [[float(obs_x), float(obs_y)]]
    left_rad = math.radians(left_az)
    right_rad = math.radians(right_az)
    
    cone_coords.append([float(obs_x + length * math.sin(left_rad)), float(obs_y + length * math.cos(left_rad))])
    cone_coords.append([float(obs_x + length * math.sin(right_rad)), float(obs_y + length * math.cos(right_rad))])
    cone_coords.append([float(obs_x), float(obs_y)])
    
    features = [
        {
            "type": "Feature",
            "properties": {
                "id": 1, 
                "tipo": "observador",
                "stroke": "#ff0000",          # Punto rojo
                "stroke-width": 4
            },
            "geometry": {"type": "Point", "coordinates": [obs_x, obs_y]}
        },
        {
            "type": "Feature",
            "properties": {
                "id": 2, 
                "tipo": "objetivo",
                "stroke": "#0000ff",          # Punto azul
                "stroke-width": 4
            },
            "geometry": {"type": "Point", "coordinates": [tgt_x, tgt_y]}
        },
        {
            "type": "Feature",
            "properties": {
                "id": 3, 
                "tipo": "linea_vision",
                "stroke": "#ffffff",          # Línea blanca
                "stroke-width": 1
            },
            "geometry": {"type": "LineString", "coordinates": [[obs_x, obs_y], [tgt_x, tgt_y]]}
        },
        {
            "type": "Feature",
            "properties": {
                "id": 4, 
                "tipo": "cono_fov", 
                "fov_horizontal": fov_h_deg,
                "stroke": "#ff3300",          # Borde naranja fuerte
                "stroke-width": 2,
                "fill": "#ffaa00",            # Relleno naranja amarillento
                "fill-opacity": 0.3           # Transparencia del 30%
            },
            "geometry": {"type": "Polygon", "coordinates": [cone_coords]}
        }
    ]
    
    return {
        "type": "FeatureCollection",
        "name": layer_name, # Nombre dinámico incrustado en el propio GeoJSON
        "crs": { "type": "name", "properties": { "name": "urn:ogc:def:crs:EPSG::25830" } },
        "features": features
    }

# ==============================================================================
# 4. FLUJO PRINCIPAL
# ==============================================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project_dir", required=True)
    args = parser.parse_args()

    project_dir = Path(args.project_dir)
    reports_dir = project_dir / "output" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    print("\n" + "="*65)
    print("   GENERADOR DE FOV ESTÁTICO (QGIS)")
    print("="*65)

    config = load_merged_config(project_dir)
    obs = config.get("observer", {})
    target = config.get("target", {})
    
    obs_x, obs_y = float(obs.get("x", 0)), float(obs.get("y", 0))
    tgt_x, tgt_y = float(target.get("x", 0)), float(target.get("y", 0))

    if tgt_x == 0.0 or obs_x == 0.0:
        print("[ERROR] Faltan coordenadas X,Y de Observer o Target en config.yaml.")
        sys.exit(1)

    # 1. Configurar Cámara
    cam = setup_camera_interactive(project_dir)
    fov_h = cam['fov_horizontal_deg']
    
    # Extraer valores para nombre dinámico
    focal_mm = int(cam['focal_length_mm'])
    orientacion = cam['orientation']
    capa_name = f"fov_cone_{focal_mm}mm_{orientacion}"

    # 2. Generar GeoJSON
    geojson_data = build_static_fov_geojson(obs_x, obs_y, tgt_x, tgt_y, fov_h, capa_name)
    
    if not geojson_data:
        print("[ERROR] No se pudo generar la geometría.")
        sys.exit(1)

    # 3. Guardar archivo con nombre dinámico
    output_file = reports_dir / f"{capa_name}.geojson"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(geojson_data, f, indent=2)
        
    print(f"\n[ÉXITO] Archivo GeoJSON generado correctamente en:")
    print(f"        {output_file.resolve()}")
    print("="*65 + "\n")

if __name__ == "__main__":
    main()