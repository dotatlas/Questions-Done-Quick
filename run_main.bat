@echo off
setlocal

cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    ".venv\Scripts\pythonw.exe" "src\main.py"
    goto :eof
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "src\main.py"
    goto :eof
)

python "src\main.py"
