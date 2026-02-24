@echo off
setlocal

cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    ".venv\Scripts\pythonw.exe" "src\main.py"
    if not errorlevel 1 goto :eof
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "src\main.py"
    if not errorlevel 1 goto :eof
)

where pythonw >nul 2>nul
if not errorlevel 1 (
    pythonw "src\main.py"
    if not errorlevel 1 goto :eof
)

where python >nul 2>nul
if not errorlevel 1 (
    python "src\main.py"
    if not errorlevel 1 goto :eof
)

echo Failed to launch Python. Checked .venv\Scripts\pythonw.exe, .venv\Scripts\python.exe, and PATH pythonw/python.
exit /b 1
