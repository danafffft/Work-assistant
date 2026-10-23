@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    py -3 -m venv .venv
    if errorlevel 1 goto :error
)
.venv\Scripts\python.exe -m pip install -r requirements-windows.txt
if errorlevel 1 goto :error
.venv\Scripts\python.exe desktop.py
if errorlevel 1 goto :error
exit /b 0
:error
echo Failed to start. Check Python, classic Outlook and network access.
pause
exit /b 1
