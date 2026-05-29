#!/usr/bin/env python3
"""
main.py — Orquestador de Pipeline LiDAR-Stellarium (V7)
===========================================================================
Añadida función de eliminación segura (doble confirmación estricta) para
proyectos, cámaras y lentes fotográficas.
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

# ==============================================================================
# 1. CONSTANTES Y RUTAS BASE
# ==============================================================================
ROOT_DIR     = Path(__file__).resolve().parent
PROYECTOS    = ROOT_DIR / "proyectos"
SCRIPTS_CORE = ROOT_DIR / "scripts" / "core"
SCRIPTS_PIPE = ROOT_DIR / "scripts" / "pipelines"
TEMPLATES    = ROOT_DIR / "scripts" / "templates"
METADATA     = ROOT_DIR / "metadata"
LAZ_DIR      = ROOT_DIR / "data_raw" / "laz"
CATALOGO     = METADATA / "catalogo_pnoa.csv"

MASTER_CFG   = SCRIPTS_CORE / "config_master.yaml"
EQUIPMENT_DB = SCRIPTS_CORE / "equipment_db.yaml"

# ==============================================================================
# 2. DEFINICIÓN ESTRUCTURAL DE PIPELINES
# ==============================================================================
PIPELINES = {
    "catalogador_laz": {
        "group":  "1. PREPARACIÓN",
        "script": SCRIPTS_CORE / "catalogador_laz.py",
        "desc":   "Genera/actualiza el catálogo global de archivos .laz.",
        "check":  lambda p: CATALOGO.exists()
    },
    "extract_classes": {
        "group":  "2. PROCESAMIENTO LIDAR",
        "script": SCRIPTS_PIPE / "extract_classes.py",
        "desc":   "Extrae clases LiDAR del mosaico y genera GeoTIFFs (MDS/MDT).",
        "check":  lambda p: (p / "workspace" / "dsm" / "dsm_all.tif").exists()
    },
    "find_highest_point": {
        "group":  "3. ANÁLISIS DE TERRENO",
        "script": SCRIPTS_PIPE / "find_highest_point.py",
        "desc":   "Localiza el punto más alto en el área generada.",
        "check":  lambda p: (p / "output" / "reports" / "highest_point_all.json").exists()
    },
    "build_horizon": {
        "group":  "3. ANÁLISIS DE TERRENO",
        "script": SCRIPTS_PIPE / "build_horizon_v3.py",
        "desc":   "Calcula el horizonte completo 360° para Stellarium.",
        "check":  lambda p: (p / "output" / "reports" / "horizon_all.csv").exists()
    },
    "build_alignment_path": {
        "group":  "4. EVENTOS ASTRONÓMICOS",
        "script": SCRIPTS_PIPE / "build_alignment_path.py",
        "desc":   "Ruta de alineación Sol/Luna con el objetivo.",
        "check":  lambda p: len(list((p / "output" / "reports").glob("ruta_alineacion*.csv"))) > 0
    },
    "check_visibility": {
        "group":  "4. EVENTOS ASTRONÓMICOS",
        "script": SCRIPTS_PIPE / "check_visibility_line.py",
        "desc":   "Perfil de visibilidad dinámica (Storyboard/Timelapse).",
        "check":  lambda p: len(list((p / "output" / "reports").glob("*.pdf"))) > 0
    }
}

# ==============================================================================
# 3. CORE LOGIC: GESTIÓN DE ESTADO Y EQUIPO
# ==============================================================================
class ProjectManager:
    @staticmethod
    def get_master_config() -> dict:
        if MASTER_CFG.exists():
            try:
                with open(MASTER_CFG, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except yaml.YAMLError: pass
        return {}

    @staticmethod
    def get_config(project_dir: Path) -> dict:
        cfg_path = project_dir / "config.yaml"
        if not cfg_path.exists(): return {}
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except yaml.YAMLError:
            return {"_error": "YAML_CORRUPTO"}

    @staticmethod
    def get_status_dict(project_dir: Path) -> dict:
        status = {}
        for key, pipe in PIPELINES.items():
            status[key] = pipe["check"](project_dir)
        return status

    @staticmethod
    def get_dashboard_info(project_dir: Path) -> dict:
        info = {"name": project_dir.name, "coords": "Sin configurar", "tags": [], "error": False}
        cfg = ProjectManager.get_config(project_dir)
        if cfg.get("_error"):
            info["error"] = True
            info["coords"] = "[!] config.yaml corrupto"
            return info

        obs = cfg.get("observer", {})
        tgt = cfg.get("target", {})
        
        obs_x, obs_y = obs.get("x"), obs.get("y")
        tgt_x, tgt_y = tgt.get("x"), tgt.get("y")

        coords_parts = []
        if obs_x is not None and obs_y is not None:
            coords_parts.append(f"Obs: {obs_x}, {obs_y}")
        if tgt_x is not None and tgt_y is not None:
            coords_parts.append(f"Tgt: {tgt_x}, {tgt_y}")
            info["tags"].append("Target✓")
            
        if coords_parts:
            info["coords"] = " | ".join(coords_parts)

        status = ProjectManager.get_status_dict(project_dir)
        if status["extract_classes"]: info["tags"].append("DSM✓")
        if status["build_horizon"]: info["tags"].append("Horiz✓")
        if status["check_visibility"]: info["tags"].append("Visib✓")
        
        if not info["tags"]: info["tags"] = ["Vacío/Nuevo"]
        return info

def ensure_directories():
    for d in [PROYECTOS, SCRIPTS_CORE, SCRIPTS_PIPE, TEMPLATES, METADATA, LAZ_DIR]:
        d.mkdir(parents=True, exist_ok=True)

def create_project(name: str) -> Path:
    p_dir = PROYECTOS / name
    if p_dir.exists(): return p_dir
    for sub in ["workspace/dsm", "workspace/pdal_pipelines", "output/reports", "output/stellarium", "logs", "efemerides"]:
        (p_dir / sub).mkdir(parents=True, exist_ok=True)
    tmpl = TEMPLATES / "config_template.yaml"
    dest = p_dir / "config.yaml"
    if tmpl.exists(): shutil.copy(tmpl, dest)
    else: dest.touch()
    return p_dir

# ==============================================================================
# 4. FUNCIONES DE DOBLE CONFIRMACIÓN Y GESTOR DE EQUIPO
# ==============================================================================
def double_confirm(warning_text: str) -> bool:
    """Función universal de doble seguridad para eliminación de datos."""
    print(f"\n  \033[91m[ATENCIÓN]\033[0m Estás a punto de eliminar permanentemente: {warning_text}")
    ans1 = input_seguro("  ¿Estás completamente seguro? [s/N]: ", ['s', 'S', 'n', 'N', ''], allow_empty=True).lower()
    if ans1 != 's':
        return False
        
    print("  \033[91mESTA ACCIÓN NO SE PUEDE DESHACER.\033[0m")
    ans2 = input("  Para confirmar, escribe la palabra exacta 'ELIMINAR' (en mayúsculas): ").strip()
    return ans2 == 'ELIMINAR'

def load_equipment() -> dict:
    if not EQUIPMENT_DB.exists():
        return {"sensors": {}, "lenses": {}}
    try:
        with open(EQUIPMENT_DB, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {"sensors": {}, "lenses": {}}
    except:
        return {"sensors": {}, "lenses": {}}

def save_equipment(data: dict):
    with open(EQUIPMENT_DB, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)

def prompt_add_equipment(eq: dict, category: str):
    label = "CÁMARA" if category == "sensors" else "OBJETIVO"
    print(f"\n  -- AÑADIR / EDITAR {label} --")
    name = input("  Nombre identificador (o '0' para cancelar): ").strip()
    if name in ['0', 'q', '']: return
    
    if category == "sensors":
        w = input_seguro("  Ancho del sensor en mm (ej. 36.0): ", allow_empty=False)
        h = input_seguro("  Alto del sensor en mm (ej. 24.0): ", allow_empty=False)
        try:
            eq.setdefault("sensors", {})[name] = {"width_mm": parse_float_flex(w), "height_mm": parse_float_flex(h)}
        except ValueError:
            print("  [!] Error: Formato numérico inválido.")
            input("  Presione ENTER para continuar...")
            return
            
    elif category == "lenses":
        tipo = input_seguro("  Tipo de lente [prime/zoom]: ", ['prime', 'zoom']).lower()
        try:
            if tipo == "prime":
                f = input_seguro("  Distancia focal en mm: ", allow_empty=False)
                eq.setdefault("lenses", {})[name] = {"type": "prime", "focal_mm": parse_float_flex(f)}
            else:
                fmin = input_seguro("  Focal mínima en mm: ", allow_empty=False)
                fmax = input_seguro("  Focal máxima en mm: ", allow_empty=False)
                eq.setdefault("lenses", {})[name] = {"type": "zoom", "min_focal_mm": parse_float_flex(fmin), "max_focal_mm": parse_float_flex(fmax)}
        except ValueError:
            print("  [!] Error: Formato numérico inválido.")
            input("  Presione ENTER para continuar...")
            return

    save_equipment(eq)
    print(f"  [v] ¡Guardado exitosamente! (Nombre: {name})")
    input("  Presione ENTER para continuar...")

def prompt_delete_equipment(eq: dict, category: str):
    label = "Cámara" if category == "sensors" else "Objetivo"
    items = list(eq.get(category, {}).keys())
    
    if not items:
        print(f"\n  [!] No hay ningún {label.lower()} registrado para eliminar.")
        input("  Presione ENTER para continuar...")
        return
        
    print(f"\n  -- SELECCIONA EL {label.upper()} A ELIMINAR --")
    for i, name in enumerate(items, 1):
        print(f"  {i}. {name}")
    print("  0. Cancelar")
    
    valid_opts = [str(i) for i in range(1, len(items) + 1)] + ['0']
    choice = input_seguro("\n  Número a eliminar: ", valid_opts)
    if choice == "0": return
    
    selected_name = items[int(choice) - 1]
    
    if double_confirm(f"{label}: {selected_name}"):
        del eq[category][selected_name]
        save_equipment(eq)
        print(f"  [v] {label} eliminada permanentemente del archivo.")
    else:
        print("  [i] Operación de borrado cancelada.")
    input("  Presione ENTER para continuar...")

def menu_equipment():
    while True:
        clear_screen()
        eq = load_equipment()
        sensors = eq.get("sensors", {})
        lenses = eq.get("lenses", {})
        
        print("=" * 95)
        print("  GESTOR DE EQUIPO FOTOGRÁFICO (equipment_db.yaml)")
        print("=" * 95)
        
        print("\n  [ CÁMARAS / SENSORES ]")
        if not sensors: print("    (No hay cámaras registradas)")
        for name, data in sensors.items():
            print(f"  • {name:<35} | {data.get('width_mm')} x {data.get('height_mm')} mm")
            
        print("\n  [ OBJETIVOS / LENTES ]")
        if not lenses: print("    (No hay lentes registradas)")
        for name, data in lenses.items():
            if data.get("type") == "zoom":
                print(f"  • {name:<35} | Zoom {data.get('min_focal_mm')}-{data.get('max_focal_mm')} mm")
            else:
                print(f"  • {name:<35} | Prime {data.get('focal_mm')} mm")

        print("\n" + "-" * 95)
        print("  1. Añadir/Editar Cámara")
        print("  2. Añadir/Editar Objetivo")
        print("  3. Eliminar Cámara")
        print("  4. Eliminar Objetivo")
        print("  0. Volver al Dashboard Global")
        
        choice = input_seguro("\n  Selección: ", ['1', '2', '3', '4', '0'])
        
        if choice == "0": return
        elif choice == "1": prompt_add_equipment(eq, "sensors")
        elif choice == "2": prompt_add_equipment(eq, "lenses")
        elif choice == "3": prompt_delete_equipment(eq, "sensors")
        elif choice == "4": prompt_delete_equipment(eq, "lenses")

# ==============================================================================
# 5. ASISTENTES DE CONFIGURACIÓN (GEO Y ATMÓSFERA)
# ==============================================================================
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def input_seguro(prompt: str, valid_options: list = None, allow_empty: bool = False) -> str:
    while True:
        val = input(prompt).strip()
        if not val and not allow_empty:
            print("  [!] Por favor, introduce un valor.")
            continue
        if valid_options and val not in valid_options:
            print(f"  [!] Opción no válida. Opciones permitidas: {', '.join(valid_options)}")
            continue
        return val

def prompt_cancelable(prompt: str, default: str = "") -> str:
    val = input(f"{prompt} [{default}]: ").strip()
    if val.lower() in ['q', '0']: raise KeyboardInterrupt("Usuario canceló la operación.")
    return val if val else str(default)

def parse_datetime(val_str: str) -> str:
    try:
        datetime.fromisoformat(val_str.replace('Z', '+00:00'))
        return val_str
    except ValueError:
        raise ValueError("El formato debe ser YYYY-MM-DDTHH:MM:SS")

def parse_float_flex(val_str: str) -> float:
    return float(val_str.replace(',', '.'))

def guided_config(project_dir: Path, mode: str = "geo"):
    clear_screen()
    
    cfg = ProjectManager.get_config(project_dir)
    if cfg.get("_error"):
        print("  [!] Archivo corrupto. Se inicializará vacío.")
        cfg = {}

    if mode == "geo":
        title = "CONFIGURACIÓN DE GEOMETRÍA Y UBICACIÓN"
        questions = [
            (["project", "landscape_name"], "Nombre en Stellarium", str, "Paisaje_1", False),
            (["project", "eclipse_time"], "Fecha/Hora Evento (YYYY-MM-DDTHH:MM:SS)", parse_datetime, "2026-08-12T20:36:00", False),
            (["observer", "x"], "Observador: Coordenada X (UTM)", parse_float_flex, "", False),
            (["observer", "y"], "Observador: Coordenada Y (UTM)", parse_float_flex, "", False),
            (["observer", "ground_z"], "Observador: Cota terreno Z (m)", parse_float_flex, "", False),
            (["observer", "camera_height"], "Observador: Altura trípode (m)", parse_float_flex, 1.6, False),
            (["target", "x"], "Objetivo: Coordenada X (UTM) [Vacío si no hay]", parse_float_flex, "", True),
            (["target", "y"], "Objetivo: Coordenada Y (UTM) [Vacío si no hay]", parse_float_flex, "", True),
            (["target", "ground_z"], "Objetivo: Cota terreno Z (m) [Vacío si no hay]", parse_float_flex, "", True),
            (["skyline", "radius_m"], "Raycasting: Radio máximo a procesar (m)", parse_float_flex, 1500.0, False),
            (["skyline", "min_distance_m"], "Raycasting: Distancia mínima a ignorar (m)", parse_float_flex, 50.0, False),
        ]
    else:
        title = "CONFIGURACIÓN ATMOSFÉRICA (STELLARIUM)"
        m_cfg = ProjectManager.get_master_config().get("stellarium", {})
        questions = [
            (["stellarium", "atmospheric_temperature"], "Temperatura (°C)", parse_float_flex, m_cfg.get("atmospheric_temperature", 30.0), False),
            (["stellarium", "atmospheric_pressure"], "Presión Atmosférica (mbar)", parse_float_flex, m_cfg.get("atmospheric_pressure", 1005.0), False),
            (["stellarium", "atmospheric_extinction_coefficient"], "Coef. de Extinción (k)", parse_float_flex, m_cfg.get("atmospheric_extinction_coefficient", 0.27), False),
            (["stellarium", "light_pollution"], "Contaminación Lumínica (Bortle 1-9)", parse_float_flex, m_cfg.get("light_pollution", 5.0), False),
        ]

    print("=" * 85)
    print(f"  {title} - {project_dir.name}")
    print("  [q] Cancelar | [<] Volver atrás | [Enter] Mantener actual")
    print("=" * 85)

    idx = 0
    while idx < len(questions):
        keys, prompt_text, cast_func, default_val, is_optional = questions[idx]
        
        d = cfg
        for k in keys[:-1]:
            if k not in d or d[k] is None: d[k] = {}
            d = d[k]
            
        curr_val = d.get(keys[-1])
        display_val = default_val if (curr_val is None or str(curr_val).strip() == "") else curr_val
            
        val_in = input(f"  {prompt_text} [{display_val}]: ").strip()
        
        if val_in.lower() in ['q', '0']:
            print(f"\n  [!] Asistente cancelado. No se guardaron los cambios.")
            input("  Presione ENTER para volver...")
            return
        elif val_in == '<':
            idx = max(0, idx - 1)
            continue
            
        if not val_in:
            if display_val == "" and not is_optional:
                print("  [!] Error: Este campo es obligatorio.")
                continue
            d[keys[-1]] = display_val if display_val != "" else None
            idx += 1
            continue
            
        try:
            parsed_val = cast_func(val_in)
            d[keys[-1]] = parsed_val
            idx += 1
        except ValueError as e:
            err_msg = str(e)
            if "could not convert" in err_msg: err_msg = "Debe ser un valor numérico."
            print(f"  [!] Entrada inválida: {err_msg}")
    
    if "target" in cfg and (not cfg["target"].get("x") or not cfg["target"].get("y")):
        cfg.pop("target", None)
            
    cfg_path = project_dir / "config.yaml"
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, sort_keys=False)
    print(f"\n  [v] Configuración validada y guardada exitosamente.")
    input("  Presione ENTER para volver...")

# ==============================================================================
# 6. MENÚS PRINCIPALES
# ==============================================================================
def menu_main():
    while True:
        clear_screen()
        print("=" * 120)
        print("  ORQUESTADOR LiDAR-STELLARIUM - Dashboard Global")
        print("=" * 120)
        
        projects = sorted([p for p in PROYECTOS.iterdir() if p.is_dir()])
        
        if not projects:
            print("  No hay proyectos. Escribe 'n' para crear uno nuevo.")
        else:
            print(f"  {'#':<3} | {'Proyecto':<30} | {'Estado (Avance)':<32} | {'Ubicación y Metadatos'}")
            print("  " + "-" * 116)
            for i, p in enumerate(projects, 1):
                info = ProjectManager.get_dashboard_info(p)
                estado_str = " ".join(info['tags'])
                c_inicio = "\033[91m" if info['error'] else ""
                c_fin = "\033[0m" if info['error'] else ""
                print(f"  {i:<3} | {c_inicio}{info['name']:<30}{c_fin} | {estado_str:<32} | {info['coords']}")
        
        print("\n  Opciones: [Número] Abrir Proyecto | [n] Nuevo Proyecto | [e] Gestionar Equipo (Lentes/Cámaras) | [0] Salir")
        
        valid_opts = [str(i) for i in range(1, len(projects) + 1)] + ['n', '0', 'e']
        choice = input_seguro("\n  Selección: ", valid_opts).lower()
        
        if choice == "0": sys.exit(0)
        elif choice == "e": menu_equipment()
        elif choice == "n":
            name = input("\n  Nombre del nuevo proyecto (o '0' para cancelar): ").strip()
            if name and name != "0": return create_project(name)
        else:
            return projects[int(choice) - 1]

def menu_project_actions(project_dir: Path):
    while True:
        clear_screen()
        cfg = ProjectManager.get_config(project_dir)
        status = ProjectManager.get_status_dict(project_dir)
        
        def fmt(val, suffix=""): return f"{val}{suffix}" if val not in [None, ""] else "\033[90mSin definir\033[0m"

        p_name = cfg.get("project", {}).get("landscape_name")
        p_time = cfg.get("project", {}).get("eclipse_time")
        
        obs = cfg.get("observer", {})
        obs_str = f"X: {fmt(obs.get('x'))} | Y: {fmt(obs.get('y'))} | Z: {fmt(obs.get('ground_z'), 'm')} (Cam: +{fmt(obs.get('camera_height'), 'm')})"
        
        tgt = cfg.get("target", {})
        tgt_str = f"X: {fmt(tgt.get('x'))} | Y: {fmt(tgt.get('y'))} | Z: {fmt(tgt.get('ground_z'), 'm')}" if tgt.get('x') else "\033[90mNo configurado\033[0m"
            
        stel = cfg.get("stellarium", {})
        atm_str = f"Temp: {fmt(stel.get('atmospheric_temperature'), '°C')} | Presión: {fmt(stel.get('atmospheric_pressure'), 'mb')} | Extinción: {fmt(stel.get('atmospheric_extinction_coefficient'))} | Luz: B{fmt(stel.get('light_pollution'))}"

        sky = cfg.get("skyline", {})
        rad_str = f"Radio máximo: {fmt(sky.get('radius_m'), 'm')} | Exclusión interior: {fmt(sky.get('min_distance_m'), 'm')}"

        print("=" * 95)
        print(f"  ESPACIO DE TRABAJO : {project_dir.name}")
        print("=" * 95)
        
        print("  [ CONFIGURACIÓN ACTIVA ]")
        print(f"  • Paisaje Stellarium : {fmt(p_name)} (Fecha: {fmt(p_time)})")
        print(f"  • Observador (UTM)   : {obs_str}")
        print(f"  • Objetivo (UTM)     : {tgt_str}")
        print(f"  • Raycasting LiDAR   : {rad_str}")
        print(f"  • Atmósfera / Cielo  : {atm_str}")
        
        c_ok = "\033[92m✓\033[0m"
        print("\n  [ ESTADO DEL PROYECTO ]")
        print(f"  {'['+c_ok+']' if status['catalogador_laz'] else '[ ]'} 1. Preparación         (Catálogo de LAZ locales)")
        print(f"  {'['+c_ok+']' if status['extract_classes'] else '[ ]'} 2. Procesamiento LiDAR (Modelos MDS/MDT extraídos)")
        print(f"  {'['+c_ok+']' if status['build_horizon'] else '[ ]'} 3. Análisis de Terreno (Horizonte 360º calculado)")
        print(f"  {'['+c_ok+']' if status['check_visibility'] or status['build_alignment_path'] else '[ ]'} 4. Eventos Astronóm.   (Visibilidad o Alineación)")
        
        print("-" * 95)
        print("  1. Lanzar Pipeline de Cálculos")
        print("  2. Configurar Geometría (Ubicación, Radio, Target...)")
        print("  3. Configurar Atmósfera (Variables de Stellarium)")
        print("  9. Eliminar Proyecto Completo (IRREVERSIBLE)")
        print("  0. Volver al Dashboard Global")
        
        choice = input_seguro("\n  Selección: ", ['1', '2', '3', '9', '0'])
        
        if choice == "1": menu_run_pipeline(project_dir)
        elif choice == "2": guided_config(project_dir, mode="geo")
        elif choice == "3": guided_config(project_dir, mode="atmos")
        elif choice == "9":
            if double_confirm(f"El proyecto '{project_dir.name}' y TODOS sus archivos raster/PDF"):
                try:
                    shutil.rmtree(project_dir)
                    print(f"  [v] Proyecto '{project_dir.name}' eliminado con éxito.")
                except Exception as e:
                    print(f"  [!] Error al eliminar la carpeta: {e}")
                input("  Presione ENTER para continuar...")
                return # Salimos al menú global
            else:
                print("  [i] Operación de borrado cancelada. El proyecto está a salvo.")
                input("  Presione ENTER para continuar...")
        elif choice == "0": return

def menu_run_pipeline(project_dir: Path):
    while True:
        clear_screen()
        print("─" * 95)
        print(f"  EJECUCIÓN DE SCRIPTS - {project_dir.name}")
        print("─" * 95)
        
        status = ProjectManager.get_status_dict(project_dir)
        current_group = ""
        keys = list(PIPELINES.keys())
        
        for i, key in enumerate(keys, 1):
            pipe = PIPELINES[key]
            if pipe["group"] != current_group:
                current_group = pipe["group"]
                print(f"\n  {current_group}:")
                
            marcador = "[\033[92m✓\033[0m]" if status[key] else "[ ]"
            print(f"    {i:2}. {marcador} {key:<22s} : {pipe['desc']}")
            
        print(f"\n  0. Cancelar (Volver atrás)")
        
        valid_opts = [str(i) for i in range(1, len(keys) + 1)] + ['0']
        choice = input_seguro("\n  Script a ejecutar: ", valid_opts)
        
        if choice == "0": return
            
        key = keys[int(choice) - 1]
        print(f"\n  Has seleccionado: {key}")
        dry_val = input_seguro("  ¿Modo prueba (Dry-run)? [s/N] (0 para abortar): ", ['s', 'S', 'n', 'N', '0', ''], allow_empty=True).lower()
        if dry_val == "0": continue
        
        run_pipeline(project_dir, key, dry_run=(dry_val == 's'))
        input("\n  Presione ENTER para continuar...")

# ==============================================================================
# 7. MOTOR DE EJECUCIÓN CLI
# ==============================================================================
def backup_config(project_dir: Path, step: str):
    cfg = project_dir / "config.yaml"
    if not cfg.exists(): return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = project_dir / "logs" / f"config_{step}_{ts}.yaml"
    shutil.copy(cfg, dest)

def run_pipeline(project_dir: Path, step_name: str, dry_run=False):
    pipe = PIPELINES.get(step_name)
    script = pipe["script"]
    if not script.exists():
        print(f"  [ERROR CRÍTICO] Script físico no encontrado: {script}")
        return False

    backup_config(project_dir, step_name)
    cmd = [sys.executable, str(script), "--project_dir", str(project_dir)]
    if dry_run: cmd.append("--dry-run")
    
    t0 = datetime.now()
    log_file = project_dir / "ejecuciones.log"
    with open(log_file, "a") as lf: lf.write(f"\n[{t0.isoformat()}] START {step_name}{' (DRY)' if dry_run else ''}\n")
    
    try:
        res = subprocess.run(cmd)
        dt = (datetime.now() - t0).total_seconds()
        
        if res.returncode == 0:
            print(f"\n  [EXITOSO] — Tarea finalizada en {dt:.1f} s")
            with open(log_file, "a") as lf: lf.write(f"[{datetime.now().isoformat()}] OK - {dt:.1f}s\n")
            return True
        else:
            print(f"\n  [FALLO] — El script terminó con código de error {res.returncode}")
            with open(log_file, "a") as lf: lf.write(f"[{datetime.now().isoformat()}] ERROR {res.returncode}\n")
            return False
    except KeyboardInterrupt:
        print(f"\n  [!] Ejecución abortada manualmente por el usuario (Ctrl+C).")
        return False

def parse_args():
    p = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--proyecto", metavar="NOMBRE")
    p.add_argument("--ejecutar", choices=PIPELINES.keys())
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--configurar", action="store_true")
    return p.parse_args()

def main():
    ensure_directories()
    args = parse_args()
    
    if args.proyecto and (args.ejecutar or args.configurar):
        project_dir = PROYECTOS / args.proyecto
        if not project_dir.exists(): project_dir = create_project(args.proyecto)
        if args.configurar: guided_config(project_dir)
        if args.ejecutar: run_pipeline(project_dir, args.ejecutar, dry_run=args.dry_run)
    else:
        while True:
            project_dir = menu_main()
            if project_dir:
                menu_project_actions(project_dir)

if __name__ == "__main__":
    main()