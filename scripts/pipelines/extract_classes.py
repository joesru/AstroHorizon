#!/usr/bin/env python3
"""
extract_classes.py (v3) — Extracción Dinámica de Clases LiDAR
=============================================================
Lee el catálogo, selecciona dinámicamente los .laz necesarios,
los fusiona en memoria (PDAL) y extrae las capas como GeoTIFFs
utilizando la sintaxis robusta (v1) de filtros y compresión.
"""

import os
import sys
import json
import yaml
import argparse
import subprocess
import collections.abc
from datetime import datetime
from pathlib import Path
import pandas as pd

def log_execution(log_file, script_name, status, message=""):
    """Escribe un registro sencillo y trazable en el ejecuciones.log del proyecto."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] | Script: {script_name} | Estado: {status} | {message}\n"
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(log_entry)
    print(log_entry.strip())

def deep_update(d, u):
    """Fusiona diccionarios anidados recursivamente."""
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = deep_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d

def load_merged_config(project_dir):
    """Carga el config maestro y lo fusiona con el del proyecto."""
    base_dir = project_dir.parents[1]
    master_path = base_dir / "scripts" / "core" / "config_master.yaml"
    project_path = project_dir / "config.yaml"

    master_config = {}
    if master_path.exists():
        with open(master_path, "r", encoding="utf-8") as file:
            master_config = yaml.safe_load(file) or {}
    else:
        print(f"[ADVERTENCIA] No se encontró config maestro en {master_path}")

    project_config = {}
    if project_path.exists():
        with open(project_path, "r", encoding="utf-8") as file:
            project_config = yaml.safe_load(file) or {}
    else:
        print(f"[ERROR] No se encuentra config del proyecto en {project_path}")
        sys.exit(1)

    # El proyecto sobrescribe/complementa al maestro
    return deep_update(master_config, project_config)

def get_required_laz_files(base_dir, config):
    """Cruza las coordenadas del proyecto con el catálogo PNOA usando Pandas."""
    catalog_path = base_dir / "metadata" / "catalogo_pnoa.csv"
    raw_dir = base_dir / "data_raw" / "laz"
    
    if not catalog_path.exists():
        print(f"[ERROR] No existe el catálogo en {catalog_path}")
        sys.exit(1)

    # Parámetros del área
    obs_x = float(config['observer']['x'])
    obs_y = float(config['observer']['y'])
    radius = float(config['raster']['radius_m'])

    # Bounding Box del área de interés
    min_x, max_x = obs_x - radius, obs_x + radius
    min_y, max_y = obs_y - radius, obs_y + radius

    # Cargar catálogo y filtrar por intersección de Bounding Box
    df = pd.read_csv(catalog_path)
    
    intersect = (
        (df['X_Max'] >= min_x) & (df['X_Min'] <= max_x) &
        (df['Y_Max'] >= min_y) & (df['Y_Min'] <= max_y)
    )
    
    filtered_df = df[intersect]
    
    laz_files = []
    for _, row in filtered_df.iterrows():
        laz_path = raw_dir / row['Archivo']
        if laz_path.exists():
            laz_files.append(laz_path)
        else:
            print(f"[ADVERTENCIA] Archivo en catálogo pero no en disco: {laz_path}")

    return laz_files, min_x, max_x, min_y, max_y

def run_pdal_pipeline(pipeline_json, output_json_path):
    """Guarda el JSON del pipeline y lo ejecuta con PDAL."""
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(pipeline_json, f, indent=4)
        
    cmd = ["pdal", "pipeline", str(output_json_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"[ERROR PDAL] {result.stderr}")
        return False
    return True

def main():
    parser = argparse.ArgumentParser(description="Extrae clases LiDAR a TIF dinámicamente.")
    parser.add_argument("--project_dir", required=True, help="Ruta absoluta al directorio del proyecto.")
    args = parser.parse_args()

    project_dir = Path(args.project_dir)
    base_dir = project_dir.parents[1]
    
    log_path = project_dir / "ejecuciones.log"
    workspace_dir = project_dir / "workspace"
    dsm_dir = workspace_dir / "dsm"
    pipeline_dir = workspace_dir / "pdal_pipelines"
    
    dsm_dir.mkdir(parents=True, exist_ok=True)
    pipeline_dir.mkdir(parents=True, exist_ok=True)

    print("\n--- INICIANDO EXTRACCIÓN DINÁMICA DE CLASES ---")
    
    # Carga combinada: Maestro + Local
    config = load_merged_config(project_dir)
    
    laz_files, min_x, max_x, min_y, max_y = get_required_laz_files(base_dir, config)
    
    if not laz_files:
        msg = "No se encontraron archivos .laz que cubran el área del observador."
        log_execution(log_path, "extract_classes.py", "ERROR", msg)
        sys.exit(1)
        
    laz_names = [f.name for f in laz_files]
    print(f"[INFO] Se cargarán {len(laz_files)} archivos LAZ: {', '.join(laz_names)}")

    # Extracción de parámetros LiDAR
    res = config['raster']['resolution_m']
    nodata = config['raster']['nodata']
    obs_x = float(config['observer']['x'])
    obs_y = float(config['observer']['y'])
    radius = float(config['raster']['radius_m'])
    crs = config.get('crs', 'EPSG:25830')

    # Diccionario original de clases (Directo de tu v1)
    exc = config['raster']['exclude_classes']
    bldg = config['raster']['building_classes']
    veg = config['raster']['vegetation_classes']
    
    exc_str = " && ".join([f"Classification != {c}" for c in exc])
    bldg_str = " || ".join([f"Classification == {c}" for c in bldg])

    tasks = [
        {
            "name": "all",
            "expression": exc_str,
            "output": dsm_dir / "dsm_all.tif"
        },
        {
            "name": "suelo",
            "expression": "Classification == 2",
            "output": dsm_dir / "dsm_suelo.tif"
        },
        {
            "name": "vegetacion_baja",
            "expression": f"Classification == {veg[0]}",
            "output": dsm_dir / "dsm_vegetacion_baja.tif"
        },
        {
            "name": "vegetacion_media",
            "expression": f"Classification == {veg[1]}",
            "output": dsm_dir / "dsm_vegetacion_media.tif"
        },
        {
            "name": "vegetacion_alta",
            "expression": f"Classification == {veg[2]}",
            "output": dsm_dir / "dsm_vegetacion_alta.tif"
        },
        {
            "name": "edificios",
            "expression": bldg_str,
            "output": dsm_dir / "dsm_edificios.tif"
        }
    ]

    for task in tasks:
        if task['output'].exists():
            print(f"[SALTANDO] Ya existe {task['output'].name}")
            continue

        print(f"Procesando capa: {task['name']}...")
        
        pipeline = []
        # A) Añadir lectores con OVERRIDE (Como en tu v1, para matar el problema del CRS)
        for laz in laz_files:
            pipeline.append({
                "type": "readers.las", 
                "filename": str(laz),
                "override_srs": crs
            })
            
        # B) Fusionarlos
        if len(laz_files) > 1:
            pipeline.append({"type": "filters.merge"})

        # C) Recorte -> Expresión (v1) -> TIF
        pipeline.extend([
            {
                "type": "filters.crop", 
                "point": f"POINT({obs_x} {obs_y})", 
                "distance": radius
            },
            {
                "type": "filters.expression", 
                "expression": task['expression']
            },
            {
                "type": "writers.gdal",
                "filename": str(task['output']),
                "resolution": res,
                "dimension": "Z",
                "output_type": "max",
                "nodata": nodata,
                "data_type": "float32",
                "gdaldriver": "GTiff",
                "gdalopts": "COMPRESS=DEFLATE,TILED=YES,BIGTIFF=IF_SAFER",
                "bounds": f"([{min_x}, {max_x}], [{min_y}, {max_y}])" 
            }
        ])

        json_path = pipeline_dir / f"dsm_{task['name']}.json"
        success = run_pdal_pipeline(pipeline, json_path)
        
        if not success:
            log_execution(log_path, "extract_classes.py", "ERROR", f"Falló generación de {task['name']}")
            sys.exit(1)

    missing = [t['output'].name for t in tasks if not t['output'].exists()]
    if missing:
        msg = f"TIFs no generados o vacíos: {', '.join(missing)}"
        log_execution(log_path, "extract_classes.py", "ERROR", msg)
        sys.exit(1)

    msg = f"Generados 6 TIFs correctamente. Archivos fuente usados: {', '.join(laz_names)}"
    log_execution(log_path, "extract_classes.py", "OK", msg)
    print("\n--- EXTRACCIÓN COMPLETADA CON ÉXITO ---")

if __name__ == "__main__":
    main()