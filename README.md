# 🌌 AstroHorizon LiDAR-Stellarium v1 (27/05/2026)

> **Planificación fotográfica astronómica de alta precisión con datos LiDAR del PNOA**

AstroHorizon es un ecosistema de scripts geoespaciales *open source* diseñado para convertir nubes de puntos LiDAR en bruto (ficheros `.laz` del PNOA) en herramientas de alta precisión para astrofotógrafos y planificadores. 

## Origen y Motivación del Proyecto

Este proyecto nace como **complemento a herramientas estándar de la industria como [PhotoPills](https://www.photopills.com/)**, no como una alternativa. Mientras que PhotoPills es insustituible para la planificación rápida y general de alineaciones, AstroHorizon surge para responder a una pregunta mucho más específica y crítica: ***¿Qué hay exactamente entre mi cámara y ese monumento, metro a metro?***

Al trabajar directamente sobre nubes de puntos LiDAR topográficas, el sistema calcula obstrucciones físicas con una precisión que los modelos de elevación globales (DEM estándar) no pueden ofrecer. Esto es vital en entornos urbanos densos, pasos estrechos, o cuando el margen entre "encuadrado" y "tapado por un edificio/árbol" se mide en décimas de grado.

El caso de uso de referencia que motivó este desarrollo es el proyecto **Eclipse-Mezquita**: la necesidad de calcular si, desde un puente sobre el río Guadalquivir en Córdoba, la torre de la Mezquita-Catedral quedará perfectamente encuadrada durante el eclipse parcial de Sol al atardecer, teniendo en cuenta la orografía real, los edificios y la vegetación exacta (en el momento de la realización de la ortofoto) que se interpone en la línea de visión.

Para resolver este problema, el ecosistema automatiza dos entregables clave:
1. **Un horizonte real 360° para Stellarium** — calculado por *raycasting* vectorizado contra el modelo digital de superficie, recreando el entorno real para simular el evento con obstáculos exactos.
2. **Un cono de visión fotográfico para QGIS** — que proyecta el FOV matemático exacto de tu cámara y objetivo sobre el mapa, indicando la cobertura métrica real en el terreno.

*(Nota sobre el alcance: En cuanto a parámetros atmosféricos, el sistema se limita a los valores configurables en `config_master.yaml` (extinción, temperatura, presión) que Stellarium utiliza para sus cálculos de refracción estándar. No se modelan condiciones atmosféricas avanzadas).*

---

## 📑 Tabla de Contenidos

1. [Requisitos previos](#1-requisitos-previos)
2. [Instalación del entorno con Miniforge](#2-instalación-del-entorno-con-miniforge)
3. [Arquitectura de directorios](#3-arquitectura-de-directorios)
4. [Obtención de datos LiDAR (PNOA)](#4-obtención-de-datos-lidar-pnoa)
5. [Configuración](#5-configuración)
6. [Uso — Orquestador principal](#6-uso--orquestador-principal)
7. [Pipelines en detalle](#7-pipelines-en-detalle)
8. [Integración con Stellarium](#8-integración-con-stellarium)
9. [Integración con QGIS](#9-integración-con-qgis)
10. [Referencia de parámetros](#10-referencia-de-parámetros)
11. [Notas técnicas y decisiones de diseño](#11-notas-técnicas-y-decisiones-de-diseño)

---

## 1. Requisitos previos

| Componente | Versión mínima | Notas |
|---|---|---|
| Windows 10/11 ó Linux | — | Probado en Windows 11 con Miniforge |
| Miniforge | Última | Recomendado sobre Anaconda/Miniconda |
| Stellarium | 23.x o superior | Para importar el `landscape.ini` generado |
| QGIS | 3.28 o superior | Para visualizar el GeoJSON de FOV |
| Datos PNOA | LiDAR 3ª cobertura | Ficheros `.laz` o `.copc.laz` del IGN |

> **¿Por qué Miniforge y no pip?**
> Las librerías geoespaciales pesadas (PDAL, GDAL, Rasterio) incluyen binarios nativos compilados con dependencias C/C++ que `pip` no resuelve bien en Windows. Conda-forge tiene builds pre-compilados y testeados para todas las plataformas.

---

## 2. Instalación del entorno con Miniforge

### 2.1 Instalar Miniforge

Descarga el instalador desde [https://conda-forge.org/download/](https://conda-forge.org/download/) y ejecútalo. Cuando el instalador pregunte, **no es necesario** añadirlo al PATH del sistema (usa siempre el *Miniforge Prompt*).

### 2.2 Clonar o descargar el repositorio

```bash
git clone [https://github.com/joesru/AstroHorizon.git](https://github.com/joesru/AstroHorizon.git)
cd AstroHorizon
```

O descarga el ZIP y descomprímelo en tu ordenador.

### 2.3 Crear el entorno conda

En la raíz del proyecto hay un fichero `environment.yml` con todas las dependencias pinned. Crea el entorno con un solo comando:

```bash
conda env create -f environment.yml
```

Esto descarga e instala automáticamente Python 3.12, PDAL, Rasterio, laspy, pyproj, NumPy, pandas, PyYAML, matplotlib y todas sus dependencias nativas. El proceso tarda entre 5 y 15 minutos según la conexión.

> **Si prefieres crearlo manualmente** (sin `environment.yml`), el subconjunto mínimo necesario es:
>
> ```bash
> conda create -n lidar-stellarium -c conda-forge python=3.12 pdal python-pdal rasterio laspy pyproj pandas numpy pyyaml openpyxl matplotlib shapely geopandas
> ```

### 2.4 Activar el entorno

```bash
conda activate lidar-stellarium
```

**Debes activar el entorno cada vez** que abras un Miniforge Prompt y quieras ejecutar scripts del proyecto. Si ves `(lidar-stellarium)` al inicio del prompt, estás dentro.

### 2.5 Verificar la instalación

```bash
python -c "import pdal, rasterio, laspy, pyproj; print('OK')"
```

Si imprime `OK` sin errores, el entorno está listo.

---

## 3. Arquitectura de directorios

```
LiDAR-Stellarium/
│
├── main.py                          # 🎮 Orquestador principal (punto de entrada)
│
├── environment.yml                  # 📦 Dependencias conda reproducibles
│
├── data_raw/
│   └── laz/                         # 📥 Deposita aquí los .laz del PNOA
│
├── metadata/
│   └── catalogo_pnoa.csv            # 🗂️ Índice espacial autogenerado (no editar a mano)
│
├── proyectos/
│   └── <Nombre-Proyecto>/           # 📁 Un directorio por planificación
│       ├── config.yaml              # ⚙️  Configuración local (sobrescribe al maestro)
│       ├── ejecuciones.log          # 📋 Log de auditoría con hashes MD5 de los LAZ
│       ├── workspace/
│       │   ├── dsm/                 # 🗺️  GeoTIFFs generados por extract_classes
│       │   └── pdal_pipelines/      # 🔧 JSONs de pipeline PDAL (para depuración)
│       ├── output/
│       │   ├── reports/             # 📊 CSVs de horizonte, JSONs de punto más alto, GeoJSONs
│       │   └── stellarium/          # 🌠 Paquete listo para importar en Stellarium
│       └── logs/                    # 🗃️  Snapshots de config.yaml por ejecución
│
└── scripts/
    ├── core/
    │   ├── catalogador_laz.py       # Indexa los .laz disponibles
    │   ├── config_master.yaml       # ⚙️  Configuración global (valores por defecto)
    │   └── equipment_db.yaml        # 📷 Base de datos de cuerpos y objetivos fotográficos
    ├── pipelines/
    │   ├── extract_classes.py       # LAZ → GeoTIFFs por clase LiDAR
    │   ├── find_highest_point_v4.py # Búsqueda de cota máxima (global y local)
    │   ├── build_horizon_v3.py      # Raycasting 360° → landscape.ini para Stellarium
    │   └── build_alignment_path_v3.py # FOV fotográfico → GeoJSON para QGIS
    └── templates/                   # Plantilla de config.yaml para proyectos nuevos
```

---

## 4. Obtención de datos LiDAR (PNOA)

Los datos LiDAR utilizados provienen del **Plan Nacional de Ortofotografía Aérea (PNOA)** del IGN, disponibles gratuitamente.

### Descargar por hoja MTN50

1. Accede al [Centro de Descargas del CNIG](https://centrodedescargas.cnig.es/CentroDescargas/home).
2. Selecciona **LIDAR** → **PNOA 3ª cobertura**.
3. Descarga las hojas que cubren tu área. Los ficheros tienen el formato `PNOA_<año>_<provincia>_<hoja>_H30_NPC01.laz`.
4. Deposita los `.laz` descargados en `data_raw/laz/`.

### Nomenclatura de hojas

El nombre de archivo codifica la posición: `343-4193` significa hoja MTN50 con origen en X=343000, Y=4193000 (UTM ETRS89 huso 30). Para una zona de radio 1 km alrededor de tu observador necesitarás habitualmente entre 1 y 4 hojas.

> El catálogo se genera automáticamente mediante `catalogador_laz.py`, que lee las cabeceras de los `.laz` con `laspy` (sin cargar la nube de puntos completa) y extrae los bounding boxes en un CSV. No es necesario abrir QGIS para esto.

---

## 5. Configuración

El sistema usa **dos capas de configuración** que se fusionan en tiempo de ejecución:

### 5.1 Configuración Maestra (`scripts/core/config_master.yaml`)

Contiene los valores globales y por defecto que se aplican a todos los proyectos. Raramente necesitas modificarla a mano; el asistente de `main.py` la actualiza cuando tocas el campo *Autor*.

```yaml
author: Pepito El Grillo
crs: EPSG:25830          # UTM ETRS89 Huso 30N — estándar PNOA España peninsular

raster:
  resolution_m: 0.25     # Resolución del GeoTIFF de salida en metros
  nodata: -9999
  exclude_classes: [7, 12, 18]          # Ruido, solapamiento, agua
  building_classes: [6, 65, 71, 72, 73, 74, 75]
  vegetation_classes: [3, 4, 5]         # Vegetación baja, media, alta

stellarium:
  polygonal_angle_rotatez: 0.00001
  atmospheric_extinction_coefficient: 0.27
  atmospheric_temperature: 30
  atmospheric_pressure: 1005
  light_pollution: 5

skyline:
  min_distance_m: 2.0           # Radio ciego mínimo (evita que el propio trípode tape el horizonte)
  distance_step_m: 0.1          # Paso de muestreo radial en metros
  default_azimuth_step_deg: 0.005   # Resolución angular base (360° / 0.005° = 72.000 rayos)
  target_fine_window_deg: 5.0   # ±5° alrededor del azimut al Target con resolución ultra-fina
  target_fine_step_deg: 0.001   # Resolución en la ventana fina
```

### 5.2 Configuración de Proyecto (`proyectos/<Proyecto>/config.yaml`)

Contiene los parámetros específicos de cada planificación. **Cualquier clave aquí sobrescribe el valor equivalente del maestro.** El asistente interactivo de `main.py` te guía para rellenarlo.

```yaml
project:
  landscape_name: Eclipse-Mezquita   # Nombre del paisaje en Stellarium

observer:
  x: 344037.08          # Coordenada UTM X del punto de disparo (trípode)
  y: 4193797.72         # Coordenada UTM Y del punto de disparo
  ground_z: 98.683      # Cota del suelo en metros s.n.m. (del LiDAR o del DSM)
  camera_height: 1.6    # Altura del ojo de la cámara sobre el suelo en metros

target:
  x: 343430.965         # Coordenada UTM X del objetivo (monumento, cima, etc.)
  y: 4193943.647        # Coordenada UTM Y del objetivo
  z: 161.849            # Cota del objetivo en metros s.n.m.

raster:
  radius_m: 1000        # Radio de procesamiento en metros alrededor del observador

photography:            # Rellenado automáticamente por build_alignment_path
  camera_body: Nikon D3400 (DX / APS-C)
  lens_used: Nikon AF-P DX NIKKOR 70-300mm f/4.5-6.3G
  focal_length_mm: 250.0
  aperture: f/8
  orientation: Vertical
  fov_horizontal_deg: 3.5741
  fov_vertical_deg: 5.3818
```

### 5.3 Base de datos de equipo (`scripts/core/equipment_db.yaml`)

Registra tus cuerpos de cámara y objetivos. El pipeline de FOV carga este fichero para calcular los ángulos de campo reales. Añade tu equipo aquí antes de ejecutar `build_alignment_path`.

```yaml
sensors:
  "Nikon D3400 (DX / APS-C)":
    width_mm: 23.5
    height_mm: 15.6

lenses:
  "Nikon AF-P DX NIKKOR 70-300mm f/4.5-6.3G":
    type: zoom
    min_focal_mm: 70.0
    max_focal_mm: 300.0
```

---

## 6. Uso — Orquestador principal

Todo el ecosistema se controla desde **un único punto de entrada**:

```bash
conda activate lidar-stellarium
python main.py
```

### Modo interactivo (recomendado)

Al ejecutar sin argumentos se abre un menú de texto:

```
════════════════════════════════════════════════════════════
  ORQUESTADOR LiDAR-STELLARIUM
════════════════════════════════════════════════════════════

  Proyectos existentes:
    1. Eclipse-Mezquita
    2. Crear proyecto nuevo
    0. Salir
```

Desde el menú de proyecto puedes:
- **Ejecutar un pipeline** (con opción de dry-run para previsualizar el comando)
- **Configurar el proyecto** con el asistente guiado
- **Ver estado del pipeline** — checklist visual de qué ficheros de salida existen

### Modo CLI directo

Para automatización o scripting:

```bash
# Crear proyecto y ejecutar un pipeline directamente
python main.py --proyecto Eclipse-Mezquita --ejecutar extract_classes

# Previsualizar el comando sin ejecutar nada
python main.py --proyecto Eclipse-Mezquita --ejecutar build_horizon --dry-run

# Ver el estado actual del pipeline
python main.py --proyecto Eclipse-Mezquita --estado

# Lanzar el asistente de configuración sin pasar por el menú
python main.py --proyecto Eclipse-Mezquita --configurar
```

### Log de auditoría (`ejecuciones.log`)

Cada ejecución queda registrada automáticamente con:
- Timestamp de inicio y duración
- Nombre del script y código de salida
- Lista de ficheros `.laz` procesados con sus hashes MD5
- Comando exacto ejecutado (reproducible)
- Estado `EXITOSO` / `ERROR`

---

## 7. Pipelines en detalle

Los pipelines se ejecutan **secuencialmente**. Cada uno depende de los ficheros generados por el anterior.

```
catalogador_laz → extract_classes → find_highest_point → build_horizon
                                                        ↘ build_alignment_path
```

### 7.1 `catalogador_laz`

**Script:** `scripts/core/catalogador_laz.py`

Lee la cabecera de cada `.laz` en `data_raw/laz/` usando `laspy` (sin cargar los puntos) y extrae el bounding box. Genera `metadata/catalogo_pnoa.csv` con las columnas `Archivo, X_Min, X_Max, Y_Min, Y_Max`.

Este catálogo es usado por todos los pipelines posteriores para seleccionar automáticamente los ficheros LAZ que intersectan con el área de interés de cada proyecto. **Ejecuta este pipeline una sola vez** después de añadir nuevos `.laz`.

---

### 7.2 `extract_classes`

**Script:** `scripts/pipelines/extract_classes.py`

Selecciona dinámicamente los `.laz` necesarios cruzando el catálogo con el bounding box del proyecto, los fusiona en memoria con PDAL y extrae **seis capas GeoTIFF** independientes:

| Fichero | Contenido |
|---|---|
| `dsm_all.tif` | Superficie total (todas las clases menos ruido/agua) |
| `dsm_suelo.tif` | Solo clase 2 — terreno desnudo |
| `dsm_vegetacion_baja.tif` | Clase 3 |
| `dsm_vegetacion_media.tif` | Clase 4 |
| `dsm_vegetacion_alta.tif` | Clase 5 |
| `dsm_edificios.tif` | Clases 6, 65, 71–75 |

Los GeoTIFFs se guardan en `workspace/dsm/` con compresión DEFLATE y tiling para acceso eficiente. El pipeline es **idempotente**: si un fichero ya existe, se salta esa tarea.

Los JSON de pipeline PDAL se guardan en `workspace/pdal_pipelines/` para facilitar la depuración.

---

### 7.3 `find_highest_point`

**Script:** `scripts/pipelines/find_highest_point_v4.py`

Realiza dos búsquedas de cota máxima sobre el GeoTIFF seleccionado (`all` por defecto):

- **Búsqueda global:** escanea el ráster completo y devuelve el punto más alto del área.
- **Búsqueda local:** escanea un radio configurable (por defecto 20 m) alrededor de las coordenadas del Target y devuelve la cota real del monumento en el modelo LiDAR, junto con el desplazamiento en metros desde el Target nominal.

Los resultados se guardan en `output/reports/highest_point_<capa>.json` y se muestran en consola con coordenadas UTM y geográficas (listas para pegar en Google Maps).

```bash
# Buscar en la capa de edificios, radio de 30m
python scripts/pipelines/find_highest_point_v4.py \
  --project_dir proyectos/Eclipse-Mezquita \
  --layer edificios \
  --radius 30
```

---

### 7.4 `build_horizon`

**Script:** `scripts/pipelines/build_horizon_v3.py`

Motor principal del proyecto. Implementa raycasting vectorizado 360° contra el GeoTIFF seleccionado.

**Funcionamiento:**

1. Calcula el azimut exacto desde el observador hasta el Target.
2. Genera el array de azimuts con dos resoluciones:
   - **Base:** 0.005°/rayo → 72.000 rayos para el horizonte completo.
   - **Ultra-fina:** 0.001°/rayo en una ventana de ±5° alrededor del azimut al Target → ~10.000 rayos adicionales en la zona crítica.
3. Para cada rayo, lanza un vector radial desde `min_distance_m` hasta `radius_m` con paso `distance_step_m`.
4. Recupera los valores Z del ráster vectorialmente (sin bucles Python) con indexado NumPy directo.
5. Calcula el ángulo de altitud de cada punto y se queda con el máximo (`argmax`).

**Salidas en `output/stellarium/<landscape_name>/`:**

- `horizon.txt` — lista de pares `azimut altitud` para Stellarium (formato `polygonal`)
- `landscape.ini` — fichero de configuración completo con metadatos extendidos incrustados: coordenadas geográficas del observador, parámetros atmosféricos, resolución angular utilizada, CRS fuente, etc.
- `output/reports/horizon_<capa>.csv` — mismos datos más distancia y cota del punto obstructor en cada azimut.

```bash
# Calcular horizonte sobre la capa completa con paso espacial de 0.25 m
python scripts/pipelines/build_horizon_v3.py \
  --project_dir proyectos/Eclipse-Mezquita \
  --layer all \
  --step 0.25
```

---

### 7.5 `build_alignment_path`

**Script:** `scripts/pipelines/build_alignment_path_v3.py`

Genera el cono de visión fotográfico y lo exporta como GeoJSON para QGIS.

Al ejecutarse, abre un **asistente interactivo** en terminal que pregunta:

1. Cuerpo de cámara (selección del `equipment_db.yaml`)
2. Objetivo montado (con soporte de zooms: te pide la focal exacta a usar)
3. Orientación: Horizontal (paisaje) o Vertical (retrato)
4. Apertura del diafragma

Con estos datos calcula el FOV horizontal y vertical exactos usando la fórmula `2 * atan(sensor / (2 * focal))` y construye un GeoJSON con cuatro features:

| Feature | Tipo | Color |
|---|---|---|
| Punto observador | Point | Rojo `#ff0000` |
| Punto objetivo (Target) | Point | Azul `#0000ff` |
| Línea de visión central | LineString | Blanco `#ffffff` |
| Cono FOV | Polygon | Naranja `#ffaa00`, opacidad 30% |

El GeoJSON se nombra dinámicamente según la óptica: `fov_cone_250mm_Vertical.geojson`. La configuración de cámara queda guardada en `config.yaml` del proyecto para futuras ejecuciones.

---

## 8. Integración con Stellarium

### Instalar el paisaje generado

1. Localiza la carpeta del paisaje generada en `output/stellarium/<landscape_name>/`.
2. Copia esa carpeta entera al directorio de paisajes de Stellarium:
   - **Windows:** `C:\Users\<usuario>\AppData\Roaming\Stellarium\landscapes\`
   - **Linux:** `~/.stellarium/landscapes/`
3. Abre Stellarium → `F4` (Configuración del cielo y de la vista) → pestaña **Paisaje**.
4. Selecciona `<landscape_name>` en el desplegable.

El paisaje importará automáticamente las coordenadas geográficas del observador, los parámetros atmosféricos y el perfil de horizonte poligonal calculado desde el LiDAR.

### Qué esperar

Con la ventana de alta resolución de ±5° alrededor del azimut al Target, Stellarium mostrará con precisión de 0.001° si el Sol, la Luna o cualquier objeto celeste se encuentra por encima o por debajo del skyline real en el momento de la planificación. Puedes avanzar el tiempo en Stellarium para simular el tránsito completo del evento.

---

## 9. Integración con QGIS

1. Abre QGIS y carga como capa base una ortofoto (PNOA) o bien los GeoTIFFs de `workspace/dsm/` para visualizar el modelo de elevaciones generado.
2. Arrastra el fichero `fov_cone_<focal>mm_<orientacion>.geojson` desde `output/reports/` a la ventana de capas.
3. Verás superpuestos sobre el mapa:
   - Tu posición de disparo.
   - El monumento objetivo.
   - La línea de visión exacta.
   - El polígono que representa el encuadre físico de tu lente.


---

## 10. Referencia de parámetros

### Parámetros de `skyline`

| Parámetro | Descripción | Valor típico |
|---|---|---|
| `min_distance_m` | Radio ciego mínimo. Evita que estructuras inmediatas (pretil, mástil) obstruyan el cálculo. Ajusta según la distancia a la estructura más cercana a la cámara. | `2.0` |
| `distance_step_m` | Paso de muestreo radial. Valores menores dan más precisión pero aumentan el tiempo de cómputo. | `0.1` |
| `default_azimuth_step_deg` | Resolución angular base. `0.005°` genera ~72.000 rayos para los 360°. | `0.005` |
| `target_fine_window_deg` | Semiancho de la ventana de alta resolución alrededor del Target. | `5.0` |
| `target_fine_step_deg` | Resolución angular en la ventana fina. | `0.001` |

### Clases LiDAR estándar ASPRS

| Código | Descripción |
|---|---|
| 2 | Suelo |
| 3 | Vegetación baja |
| 4 | Vegetación media |
| 5 | Vegetación alta |
| 6 | Edificios |
| 7 | Ruido (excluido) |
| 12 | Solapamiento (excluido) |
| 18 | Ruido alto (excluido) |
| 65–75 | Clases extendidas de edificaciones (PNOA) |

---

## 11. Notas técnicas y decisiones de diseño

**Fusión de configuración por capas.** Cada script carga primero `config_master.yaml` y luego aplica encima el `config.yaml` del proyecto mediante un `deep_update` recursivo. Esto permite tener defaults globales sensatos y sobreescribir solo lo necesario por proyecto, sin duplicar parámetros.

**Raycasting con NumPy vectorizado.** El motor de horizonte evita loops Python a nivel de punto utilizando operaciones de array para calcular todas las posiciones de muestreo de un rayo de una vez. La indexación `~transform * (x_ray, y_ray)` de rasterio devuelve coordenadas de píxel fraccionarias que se truncan con `floor` para acceder al ráster directamente.

**Ventana de ultra-precisión en el Target.** En lugar de aumentar la resolución de todo el horizonte (que multiplicaría el tiempo de cómputo por 5x), el script añade rayos extra solo en la ventana angular donde cae el Target. Esto permite tener 0.001° de precisión donde importa sin sacrificar velocidad en el resto.

**Idempotencia en `extract_classes`.** Si un GeoTIFF ya existe en `workspace/dsm/`, ese paso se salta. Esto permite re-ejecutar el pipeline después de un fallo parcial sin reprocesar todo desde cero.

**Log de auditoría con hashes MD5.** El orquestador calcula el hash MD5 de cada `.laz` usado antes de registrar la ejecución en `ejecuciones.log`. Esto permite verificar en el futuro que los resultados se calcularon sobre los mismos datos fuente, útil si el PNOA publica nuevas coberturas.

**GeoJSON con estilos incrustados.** El fichero de FOV usa las propiedades estándar de la especificación simplestyle (`stroke`, `fill`, `fill-opacity`) que QGIS interpreta directamente sin necesidad de configurar simbología manualmente.

---

## Licencia

Libre para uso personal y académico. Si lo usas para publicar resultados, una mención al proyecto se agradece.

---

## Autor y contacto

**José Estepa Ruiz** — Físico (Universidad de Córdoba)

- 📷 Instagram: [@joesru_fotografia](https://www.instagram.com/joesru_fotografia/)
- 💼 LinkedIn: [www.linkedin.com/in/jose-estepa-ruiz](www.linkedin.com/in/jose-estepa-ruiz)
- ✉️ Correo: joseesteparuiz@gmail.com
