@echo off
REM ============================================================
REM  Drone Compressor - One-click Windows builder
REM  Double-click file ini di Windows. Hasil akhir:
REM     dist\DroneCompressor-Setup.exe             (installer 1 file)
REM     dist\DroneCompressor-windows-portable.zip  (cadangan portable)
REM
REM  Python, FFmpeg, dan Inno Setup diurus otomatis oleh skrip.
REM ============================================================
setlocal
cd /d "%~dp0"

echo ============================================
echo   DRONE COMPRESSOR - BUILD WINDOWS
echo ============================================
echo.
echo Proses ini butuh internet, sekitar 5-10 menit.
echo Mohon tunggu sampai selesai.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\build_windows_installer.ps1"
set BUILD_ERR=%errorlevel%

echo.
if %BUILD_ERR% neq 0 (
    echo ======================================
    echo   BUILD GAGAL
    echo ======================================
    echo Baca pesan error di atas.
    echo Kalau soal Python: tutup jendela ini, install Python,
    echo lalu jalankan BUILD_WINDOWS.bat lagi.
    pause
    exit /b 1
)

echo ============================================
echo   SELESAI
echo ============================================

if exist "dist\DroneCompressor-Setup.exe" (
    echo Installer 1 file ^(kirim ini ke user^):
    echo    %CD%\dist\DroneCompressor-Setup.exe
) else (
    if exist "dist\DroneCompressor-windows-portable.zip" (
        echo Installer dilewati. Gunakan versi portable:
        echo    %CD%\dist\DroneCompressor-windows-portable.zip
    )
)

echo.
if exist "dist" explorer "%CD%\dist"
pause
