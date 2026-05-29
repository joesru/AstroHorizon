@echo off
title Orquestador LiDAR-Stellarium

echo Iniciando entorno Miniforge...
:: Intentamos activar el entorno directamente
call conda activate lidar-stellarium >nul 2>&1

:: Si falla (porque Conda no está en las variables de entorno globales), 
:: forzamos la carga desde la ruta por defecto de Miniforge.
if errorlevel 1 (
    call "%USERPROFILE%\miniforge3\Scripts\activate.bat" lidar-stellarium
)

echo Accediendo al directorio...
cd /d C:\GIS\LiDAR-Stellarium

echo Lanzando Dashboard...
python main.py

:: Si sales del programa con el 0, cerramos la ventana automáticamente. 
:: Si hay un error crítico, pausamos para que puedas leerlo.
if errorlevel 1 pause