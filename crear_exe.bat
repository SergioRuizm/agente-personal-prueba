@echo off
setlocal
cd /d "%~dp0"

echo Creando AgentePersonal.exe con Python 3.14...
py -3.14 -m PyInstaller --noconfirm --clean --onefile --name AgentePersonal --console --collect-all langchain_google_genai --collect-all langgraph agente_web.py
if errorlevel 1 goto error

echo.
echo Ejecutable creado en: dist\AgentePersonal.exe
pause
exit /b 0

:error
echo.
echo No se pudo crear el ejecutable.
echo Comprueba que Python 3.14, PyInstaller y las dependencias del agente estan instalados.
pause
exit /b 1
