@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
if errorlevel 1 goto error
.venv\Scripts\python.exe -m pip install -r requirements-windows.txt pyinstaller==6.16.0
if errorlevel 1 goto error
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --windowed --name WorkAssistant --add-data "web;web" --collect-all webview --collect-all msal --hidden-import win32com.client --hidden-import pythoncom desktop.py
if errorlevel 1 goto error
where ISCC >nul 2>nul
if errorlevel 1 (
  echo Portable build: dist\WorkAssistant\WorkAssistant.exe
  echo Install Inno Setup 6 and add ISCC to PATH to build the installer.
  exit /b 0
)
ISCC packaging\installer.iss
if errorlevel 1 goto error
echo Installer is in installer-output. This build is not digitally signed.
exit /b 0
:error
echo Build failed. Review the error above.
pause
exit /b 1
