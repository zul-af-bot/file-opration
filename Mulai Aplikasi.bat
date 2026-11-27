@echo off
cd /d "%~dp0core"

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw app.py
    exit /b 0
)

where python >nul 2>nul
if %errorlevel%==0 (
    python app.py
    exit /b %errorlevel%
)

echo [ERROR] Python tidak ditemukan di perangkat ini.
echo Silakan install Python 3.10+ dari https://www.python.org/downloads/
echo Pastikan centang "Add Python to PATH" saat instalasi.
pause
exit /b 1
