@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/2] Installing dependencies...
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 exit /b 1

echo [2/2] Building exe...
python -m PyInstaller --noconfirm --onefile --windowed --name FloatingTextReader --icon icon.ico main.py
if errorlevel 1 exit /b 1

echo.
echo Done: dist\FloatingTextReader.exe
pause
