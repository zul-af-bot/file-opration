@echo off
cd /d "%~dp0"
echo === Membangun FileOprationByZul.exe ===

python -m pip show pyinstaller >nul 2>nul
if not %errorlevel%==0 (
    echo Menginstall PyInstaller...
    python -m pip install pyinstaller
    if not %errorlevel%==0 (
        echo [ERROR] Gagal menginstall PyInstaller.
        pause
        exit /b 1
    )
)

python -m PyInstaller --noconfirm --onefile --windowed --add-data "assets;assets" --name "FileOprationByZul" app.py
if not %errorlevel%==0 (
    echo [ERROR] Build .exe gagal.
    pause
    exit /b 1
)

echo.
echo [SUKSES] File .exe ada di: dist\FileOprationByZul.exe
echo Salin FileOprationByZul.exe beserta folder bin\ dan assets\ jika pindah ke PC lain.
pause
