@echo off
title Sistema de Control de Lavanderia
cd /d "%~dp0"

echo ============================================
echo   Sistema de Control de Lavanderia
echo ============================================
echo.
echo Verificando dependencias (solo la primera vez tarda unos segundos)...
python -m pip install -r requirements.txt --quiet --disable-pip-version-check

echo.
echo Iniciando el sistema...
echo NO CIERRES ESTA VENTANA mientras uses el sistema.
echo.

REM Abre el navegador automaticamente despues de 3 segundos
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000"

REM Inicia el servidor (esto deja la ventana ocupada, es normal)
python -m uvicorn main:app --host 0.0.0.0 --port 8000

pause
