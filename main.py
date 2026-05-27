#!/usr/bin/env python3
"""
main.py — Orquestador de Pipeline LiDAR-Stellarium
====================================================
Uso interactivo : python main.py
Uso CLI directo : python main.py --proyecto MiProyecto --ejecutar build_horizon_v3
Dry-run         : python main.py --proyecto MiProyecto --ejecutar extract_classes --dry-run
Estado          : python main.py --proyecto MiProyecto --estado
"""

import argparse
import csv
import hashlib
import os
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path

import yaml

# ==============================================================================
# 1. RUTAS BASE
# ==============================================================================
ROOT_DIR     = Path(__file__).resolve().parent
PROYECTOS    = ROOT_DIR / "proyectos"
SCRIPTS_CORE = ROOT_DIR / "scripts" / "core"
SCRIPTS_PIPE = ROOT_DIR / "scripts" / "pipelines"
TEMPLATES    = ROOT_DIR / "scripts" / "templates"
METADATA     = ROOT_DIR / "metadata"
LAZ_DIR      = ROOT_DIR / "data_raw" / "laz"
CATALOGO     = METADATA / "catalogo_pnoa.csv"

# ==============================================================================
# 2. REGISTRO DE PIPELINES DISPONIBLES
# ==============================================================================
PIPELINES = {
    "catalogador_laz": {
        "script": SCRIPTS_CORE / "catalogador_laz.py",
        "desc":   "Genera/actualiza el catálogo de archivos .laz disponibles.",
        "output": CATALOGO,
        "args":   [],
    },
    "extract_classes": {
        "script": SCRIPTS_PIPE / "extract_classes.py",
        "desc":   "Extrae clases LiDAR del mosaico y genera GeoTIFFs por capa.",
        "output": None,
        "args":   [],
    },
    "find_highest_point": {
        "script": SCRIPTS_PIPE / "find_highest_point_v4.py",
        "desc":   "Localiza el punto más alto global y local (radio configurable) y lo guarda en JSON.",
        "output": None,
        "args":   [],
    },
    "build_horizon": {
        "script": SCRIPTS_PIPE / "build_horizon_v3.py",
        "desc":   "Calcula el horizonte completo 360° con raycasting y metadatos extendidos.",
        "output": None,
        "args":   [],
    },
    "build_alignment_path": {
        "script": SCRIPTS_PIPE / "build_alignment_path_v3.py",
        "desc":   "Calcula la ruta de alineación Sol/Luna con el objetivo e integra ópticas.",
        "output": None,
        "args":   [],
    },
}

# ==============================================================================
# 3. UTILIDADES DE LOGGING Y FORMATO
# ==============================================================================
def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _line(char="─", n=60) -> str:
    return char * n

def log_event(log_path: Path, entries: dict):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n{_line()}\n")
        for k, v in entries.items():
            f.write(f"{k:<20}: {v}\n")
        f.write(_line() + "\n")

def print_header(title: str):
    print(f"\n{_line()}")
    print(f"  {title}")
    print(_line())

# ==============================================================================
# 4. GESTIÓN DE PROYECTOS
# ==============================================================================
def list_projects() -> list[Path]:
    if not PROYECTOS.exists():
        return []
    return sorted(p for p in PROYECTOS.iterdir() if p.is_dir())

def create_project(name: str) -> Path:
    project_dir = PROYECTOS / name
    if project_dir.exists():
        print(f"  [!] El proyecto '{name}' ya existe.")
        return project_dir

    for sub in ["workspace/dsm", "workspace/pdal_pipelines", "output/reports",
                "output/stellarium", "logs"]:
        (project_dir / sub).mkdir(parents=True, exist_ok=True)

    if TEMPLATES.exists():
        for tpl in TEMPLATES.iterdir():
            dest = project_dir / tpl.name
            if not dest.exists():
                shutil.copy2(tpl, dest)
        print(f"  [OK] Plantillas copiadas desde {TEMPLATES.name}/")
    else:
        # Crea un config.yaml limpio con la estructura esperada por defecto
        (project_dir / "config.yaml").write_text(
            "# Configuración local del proyecto\n"
            "project:\n  author: \"Jose\"\n  landscape_name: \"\"\n"
            "observer:\n  x: 0.0\n  y: 0.0\n  ground_z: 0.0\n  camera_height: 1.6\n"
            "raster:\n  radius_m: 1000\n",
            encoding="utf-8"
        )

    print(f"  [OK] Proyecto '{name}' creado en: {project_dir}")
    return project_dir

# ==============================================================================
# 5. ASISTENTE DE CONFIGURACIÓN
# ==============================================================================
def _ask(prompt: str, default=None, cast=str):
    hint = f" [{default}]" if default is not None else ""
    raw = input(f"  {prompt}{hint}: ").strip()
    if not raw and default is not None:
        return default
    try:
        return cast(raw) if raw else default
    except ValueError:
        print(f"  [!] Valor inválido, se usa: {default}")
        return default

def guided_config(project_dir: Path):
    cfg_path = project_dir / "config.yaml"
    master_path = SCRIPTS_CORE / "config_master.yaml"

    cfg = {}
    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

    m_cfg = {}
    if master_path.exists():
        with open(master_path, encoding="utf-8") as f:
            m_cfg = yaml.safe_load(f) or {}

    print_header("ASISTENTE DE CONFIGURACIÓN (Variables Locales)")
    print("  Pulsa Enter para conservar el valor actual.\n")

    proj = cfg.setdefault("project", {})
    
    # Sincronización inteligente de Autor (Local <-> Maestro)
    default_author = proj.get("author", m_cfg.get("author", "Jose"))
    author_input = _ask("Autor del proyecto (Se actualizará en el Maestro)", default=default_author)
    proj["author"] = author_input
    
    # Guardar en caliente en el config_master.yaml
    m_cfg["author"] = author_input
    SCRIPTS_CORE.mkdir(parents=True, exist_ok=True)
    with open(master_path, "w", encoding="utf-8") as f:
        yaml.dump(m_cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    proj["landscape_name"] = _ask("Nombre del paisaje (Stellarium)", default=proj.get("landscape_name", project_dir.name))

    obs = cfg.setdefault("observer", {})
    obs["x"]             = _ask("Observador X (UTM m)",    default=obs.get("x", 0.0),   cast=float)
    obs["y"]             = _ask("Observador Y (UTM m)",    default=obs.get("y", 0.0),   cast=float)
    obs["ground_z"]      = _ask("Cota suelo Z (m s.n.m.)", default=obs.get("ground_z", 0.0), cast=float)
    obs["camera_height"] = _ask("Altura trípode/cámara (m)", default=obs.get("camera_height", 1.6), cast=float)

    add_target = input("\n  ¿Configurar punto objetivo (target)? [s/N]: ").strip().lower()
    if add_target == "s":
        tgt = cfg.setdefault("target", {})
        tgt["x"] = _ask("Target X (UTM m)", default=tgt.get("x", 0.0), cast=float)
        tgt["y"] = _ask("Target Y (UTM m)", default=tgt.get("y", 0.0), cast=float)
        tgt["z"] = _ask("Target Z (m)",     default=tgt.get("z", 0.0), cast=float)

    rst = cfg.setdefault("raster", {})
    rst["radius_m"] = _ask("Radio de cobertura (m)", default=rst.get("radius_m", 1000), cast=int)

    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"\n  [OK] Configuración guardada en: {cfg_path}")

# ==============================================================================
# 6. VALIDACIONES
# ==============================================================================
def _hash_file(path: Path, algo="md5") -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def get_laz_for_project(project_dir: Path) -> list[dict]:
    if not CATALOGO.exists(): return []
    cfg_path = project_dir / "config.yaml"
    if not cfg_path.exists(): return []

    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    obs   = cfg.get("observer", {})
    obs_x = float(obs.get("x", 0))
    obs_y = float(obs.get("y", 0))
    rad   = float(cfg.get("raster", {}).get("radius_m", 1000))

    relevant = []
    with open(CATALOGO, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                if (float(row["X_Min"]) <= obs_x + rad and float(row["X_Max"]) >= obs_x - rad and
                        float(row["Y_Min"]) <= obs_y + rad and float(row["Y_Max"]) >= obs_y - rad):
                    relevant.append(row)
            except (KeyError, ValueError):
                continue
    return relevant

def validate_inputs(project_dir: Path) -> tuple[bool, list[str]]:
    warnings = []
    cfg_path = project_dir / "config.yaml"
    if not cfg_path.exists():
        return False, ["No existe config.yaml en el proyecto."]

    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    obs = cfg.get("observer", {})
    if not obs.get("x") or not obs.get("y"):
        warnings.append("El observador no tiene coordenadas X/Y definidas en config.yaml.")

    return (len(warnings) == 0), warnings

def check_pipeline_status(project_dir: Path):
    print_header(f"ESTADO DEL PIPELINE — {project_dir.name}")
    ws = project_dir / "workspace" / "dsm"
    rep = project_dir / "output" / "reports"
    stl = project_dir / "output" / "stellarium"

    cfg_path = project_dir / "config.yaml"
    landscape_name = project_dir.name
    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8") as f:
            c = yaml.safe_load(f) or {}
            landscape_name = c.get("project", {}).get("landscape_name", project_dir.name)

    checks = {
        "Catálogo .laz":         CATALOGO.exists(),
        "DSM all.tif":           (ws / "dsm_all.tif").exists(),
        "DSM edificios.tif":     (ws / "dsm_edificios.tif").exists(),
        "DSM vegetacion_alta":   (ws / "dsm_vegetacion_alta.tif").exists(),
        "Reporte Punto Más Alto":(rep / "highest_point_all.json").exists(),
        "Horizonte CSV":         any(rep.glob("horizon_*.csv")) if rep.exists() else False,
        "Horizonte Stellarium":  (stl / landscape_name / "horizon.txt").exists() if stl.exists() else False,
        "Config Landscape INI":  (stl / landscape_name / "landscape.ini").exists() if stl.exists() else False,
    }
    for step, done in checks.items():
        mark = "✓" if done else "✗"
        print(f"  [{mark}] {step}")
    print()

# ==============================================================================
# 7. EJECUCIÓN
# ==============================================================================
def run_pipeline(project_dir: Path, pipeline_key: str, dry_run: bool = False):
    pipe = PIPELINES.get(pipeline_key)
    if not pipe: return

    script = pipe["script"]
    if not script.exists():
        print(f"  [ERROR] Script no encontrado: {script}")
        return

    ok, warnings = validate_inputs(project_dir)
    for w in warnings: print(f"  [!] {w}")
    if not ok:
        print("  [!] Corrección necesaria antes de ejecutar. Abortando.")
        return

    cmd = [sys.executable, str(script), "--project_dir", str(project_dir)]
    cmd += pipe.get("args", [])

    log_dir = project_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    cfg_src = project_dir / "config.yaml"
    if cfg_src.exists():
        ts_label = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(cfg_src, log_dir / f"config_{pipeline_key}_{ts_label}.yaml")

    laz_files = get_laz_for_project(project_dir)
    laz_info  = ", ".join(r["Archivo"] for r in laz_files) if laz_files else "ninguno detectado"

    if dry_run:
        print_header("DRY-RUN — Sin ejecución real")
        print(f"  Comando: {' '.join(cmd)}\n")
        return

    print(f"\n  Lanzando: {script.name} ...")
    t_start = datetime.now()
    result  = subprocess.run(cmd)
    elapsed = (datetime.now() - t_start).total_seconds()

    hashes = {}
    for row in laz_files:
        laz_path = LAZ_DIR / row["Archivo"]
        if laz_path.exists(): hashes[row["Archivo"]] = _hash_file(laz_path)

    output_ok = "N/A"
    if pipe["output"]:
        out = Path(pipe["output"])
        if out.exists() and out.stat().st_size > 0:
            output_ok = f"OK ({out.stat().st_size // 1024} KB)"
        else:
            output_ok = "VACÍO o NO GENERADO"

    log_event(
        project_dir / "ejecuciones.log",
        {
            "Fecha": _ts(), "Script": script.name, "Proyecto": project_dir.name,
            "Archivos_LAZ": laz_info, "Hashes_MD5": str(hashes) if hashes else "no calculados",
            "Comando": " ".join(cmd), "Duracion_s": f"{elapsed:.1f}",
            "Exit_Code": result.returncode, "Output_Check": output_ok,
            "Estado": "EXITOSO" if result.returncode == 0 else "ERROR",
        }
    )
    status = "EXITOSO" if result.returncode == 0 else f"ERROR (código {result.returncode})"
    print(f"\n  [{status}] — {elapsed:.1f} s")

# ==============================================================================
# 8. MENÚS INTERACTIVOS
# ==============================================================================
def menu_select_project() -> Path | None:
    projects = list_projects()
    print_header("GESTIÓN DE PROYECTOS")
    if projects:
        print("  Proyectos existentes:")
        for i, p in enumerate(projects, 1): print(f"    {i}. {p.name}")
        print(f"    {len(projects)+1}. Crear proyecto nuevo\n    0. Salir")
    else:
        print("  No hay proyectos todavía.\n    1. Crear proyecto nuevo\n    0. Salir")

    choice = input("\n  Selección: ").strip()
    if choice == "0": return None
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(projects): return projects[idx]
    except ValueError: pass

    name = input("  Nombre del nuevo proyecto: ").strip()
    if not name: return None
    return create_project(name)

def menu_project_actions(project_dir: Path):
    while True:
        print_header(f"PROYECTO: {project_dir.name}")
        print("  1. Ejecutar un pipeline\n  2. Configurar proyecto (asistente)")
        print("  3. Ver estado del pipeline\n  4. Volver al menú principal")
        choice = input("\n  Selección: ").strip()
        if choice == "1": menu_run_pipeline(project_dir)
        elif choice == "2": guided_config(project_dir)
        elif choice == "3": check_pipeline_status(project_dir)
        elif choice == "4": break

def menu_run_pipeline(project_dir: Path):
    print_header("SELECCIÓN DE PIPELINE")
    keys = list(PIPELINES.keys())
    for i, key in enumerate(keys, 1):
        print(f"  {i}. {key:30s}  {PIPELINES[key]['desc']}")
    print(f"  0. Cancelar")
    choice = input("\n  Selección: ").strip()
    if choice == "0": return
    try: key = keys[int(choice) - 1]
    except (ValueError, IndexError): return
    dry = input("  ¿Modo dry-run? [s/N]: ").strip().lower() == "s"
    run_pipeline(project_dir, key, dry_run=dry)

def parse_args():
    p = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--proyecto", metavar="NOMBRE")
    p.add_argument("--ejecutar", choices=PIPELINES.keys())
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--estado", action="store_true")
    p.add_argument("--configurar", action="store_true")
    return p.parse_args()

def main():
    args = parse_args()
    if args.proyecto:
        project_dir = PROYECTOS / args.proyecto
        if not project_dir.exists(): project_dir = create_project(args.proyecto)
        if args.estado: check_pipeline_status(project_dir)
        elif args.configurar: guided_config(project_dir)
        elif args.ejecutar: run_pipeline(project_dir, args.ejecutar, dry_run=args.dry_run)
        else: menu_project_actions(project_dir)
        return

    print(f"\n{'='*60}\n  ORQUESTADOR LiDAR-STELLARIUM\n{'='*60}")
    while True:
        project_dir = menu_select_project()
        if project_dir is None: break
        menu_project_actions(project_dir)

if __name__ == "__main__":
    main()