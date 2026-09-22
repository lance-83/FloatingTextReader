@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/2] 安装依赖...
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 exit /b 1

echo [2/2] 打包...
python -m PyInstaller --noconfirm --onefile --windowed --name FloatingTextReader --icon icon.ico main.py
if errorlevel 1 exit /b 1

echo.
echo 打包完成：dist\FloatingTextReader.exe
pause
