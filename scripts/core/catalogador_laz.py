#!/usr/bin/env python3
import csv
from pathlib import Path
import laspy

# ==========================================
# RUTAS
# ==========================================
RAW_DIR = Path(r"C:\GIS\LiDAR-Stellarium\data_raw\laz")
OUTPUT_CSV = Path(r"C:\GIS\LiDAR-Stellarium\catalogo_pnoa.csv")

def main():
    print(f"Buscando archivos .laz en: {RAW_DIR}")
    
    # Comprobar si existe el directorio
    if not RAW_DIR.exists():
        print("¡Error! La carpeta no existe. Comprueba la ruta.")
        return

    archivos_laz = list(RAW_DIR.glob('*.laz'))
    
    if not archivos_laz:
        print("No se han encontrado archivos .laz en la carpeta.")
        return

    print(f"Se han encontrado {len(archivos_laz)} archivos. Generando catálogo...")

    # Crear el CSV
    with open(OUTPUT_CSV, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        # Cabecera del CSV
        writer.writerow(['Archivo', 'X_Min', 'X_Max', 'Y_Min', 'Y_Max'])

        for laz_file in archivos_laz:
            try:
                # laspy.open lee solo la cabecera (muy rápido), no la nube de puntos
                with laspy.open(laz_file) as f_las:
                    header = f_las.header
                    writer.writerow([
                        laz_file.name,
                        round(header.x_min, 2),
                        round(header.x_max, 2),
                        round(header.y_min, 2),
                        round(header.y_max, 2)
                    ])
                print(f"  [OK] Registrado: {laz_file.name}")
            except Exception as e:
                print(f"  [ERROR] No se pudo leer {laz_file.name}: {e}")

    print("\n" + "="*50)
    print(f"¡Catálogo generado con éxito en:\n{OUTPUT_CSV}")
    print("="*50)

if __name__ == "__main__":
    main()