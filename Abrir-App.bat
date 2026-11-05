@echo off
title Hoja Diaria — Unidad Renal

:: Cambiar al directorio de la app
cd /d "%~dp0"

:: Verificar si ya hay algo escuchando en 8000
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo El servidor ya esta corriendo en puerto 8000
    start "" "http://localhost:8000"
    exit /b
)

:: Iniciar el servidor en segundo plano
echo Iniciando servidor...
start "Servidor Renal" /min cmd /c "python -m uvicorn main:app --port 8000 2>&1"

:: Esperar 2 segundos y abrir el navegador
timeout /t 2 /nobreak >nul
start "" "http://localhost:8000"

echo Servidor iniciado. Puede cerrar esta ventana.
