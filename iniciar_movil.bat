@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0AgentePersonal.exe" (
    echo No encuentro AgentePersonal.exe.
    echo Deja este archivo .bat en la misma carpeta que el ejecutable.
    pause
    exit /b 1
)

start "Agente Personal - modo movil" "%~dp0AgentePersonal.exe" --movil
