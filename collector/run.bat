@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente virtual...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 (
        echo.
        echo Python 3.10+ nao encontrado. Instale com:
        echo     winget install Python.Python.3.12
        echo e abra um novo terminal.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo Falha ao instalar dependencias.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" run.py
pause
