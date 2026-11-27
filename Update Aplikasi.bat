@echo off
title Update File Opration by Zul
echo ========================================================
echo   Mengunduh Pembaruan File Opration by Zul dari GitHub...
echo ========================================================
echo.

cd /d "%~dp0"

set "REPO_URL=https://github.com/zul-af-bot/file-opration.git"
set "ZIP_URL=https://github.com/zul-af-bot/file-opration/archive/refs/heads/main.zip"

:: 1. Sinkronisasi menggunakan Git jika terpasang (tanpa login untuk repo Public)
where git >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    if not exist ".git" (
        echo [INFO] Menginisialisasi Git untuk update otomatis...
        git init
        git remote add origin %REPO_URL%
        git -c credential.helper= -c credential.interactive=never fetch origin main
        if %ERRORLEVEL% EQU 0 (
            git reset --hard origin/main
            git branch -M main
            goto SELESAI
        )
    ) else (
        git remote set-url origin %REPO_URL% 2>nul
        git -c credential.helper= -c credential.interactive=never fetch origin main
        if %ERRORLEVEL% EQU 0 (
            git reset --hard origin/main
            goto SELESAI
        )
    )
)

:: 2. Fallback: Download arsip ZIP langsung via PowerShell
echo.
echo [INFO] Mengunduh pembaruan langsung via PowerShell...
powershell -NoProfile -Command ^
  "$zip = Join-Path $env:TEMP 'file_opration_update.zip';" ^
  "$extract = Join-Path $env:TEMP 'file_opration_extract';" ^
  "Remove-Item -Recurse -Force $extract -ErrorAction SilentlyContinue;" ^
  "Invoke-WebRequest -Uri '%ZIP_URL%' -Headers @{ 'User-Agent' = 'FileOprationUpdater/1.0' } -OutFile $zip -ErrorAction Stop;" ^
  "Expand-Archive -Path $zip -DestinationPath $extract -Force;" ^
  "$root = Get-ChildItem -Path $extract -Directory | Select-Object -First 1;" ^
  "Copy-Item -Path ($root.FullName + '\*') -Destination (Get-Location) -Recurse -Force;" ^
  "Remove-Item -Force $zip -ErrorAction SilentlyContinue;" ^
  "Remove-Item -Recurse -Force $extract -ErrorAction SilentlyContinue;"

:SELESAI
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ========================================================
    echo   [PERHATIAN] Gagal mengunduh pembaruan dari GitHub!
    echo   Pastikan koneksi internet aktif dan repo sudah Public.
    echo ========================================================
    echo.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ========================================================
echo   Pembaruan selesai diunduh!
echo   Silakan jalankan "Mulai Aplikasi.bat" untuk memakai versi terbaru.
echo   (Folder core\bin dan pengaturan Anda tetap aman.)
echo ========================================================
echo.
pause
