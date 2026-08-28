# Build DroneCompressor.exe lalu bungkus jadi satu file installer.
# Hasil akhir: dist\DroneCompressor-Setup.exe
# Jika Inno Setup tidak tersedia, tetap membuat ZIP portable.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

function Find-ISCC {
    # 1. PATH
    $cmd = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    # 2. Folder instalasi umum (semua versi: Inno Setup 5/6/7/...)
    $roots = @(
        ${env:ProgramFiles(x86)},
        $env:ProgramFiles,
        $env:LOCALAPPDATA,
        "$env:LOCALAPPDATA\Programs"
    ) | Where-Object { $_ -and (Test-Path $_) }

    foreach ($r in $roots) {
        $found = Get-ChildItem -Path $r -Directory -Filter "Inno Setup*" -ErrorAction SilentlyContinue |
            ForEach-Object { Join-Path $_.FullName "ISCC.exe" } |
            Where-Object { Test-Path $_ } |
            Select-Object -First 1
        if ($found) { return $found }
    }

    # 3. Registry (Inno Setup mendaftarkan lokasi App Path)
    $regPaths = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup*"
    )
    foreach ($rp in $regPaths) {
        $keys = Get-Item -Path $rp -ErrorAction SilentlyContinue
        foreach ($k in $keys) {
            $loc = (Get-ItemProperty $k.PSPath -ErrorAction SilentlyContinue).InstallLocation
            if ($loc) {
                $candidate = Join-Path $loc "ISCC.exe"
                if (Test-Path $candidate) { return $candidate }
            }
        }
    }

    return $null
}

function Install-InnoSetup {
    Write-Host "Menginstall Inno Setup via winget..."
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "winget tidak tersedia di sistem ini."
        return $false
    }

    # ErrorActionPreference=Stop bisa menggagalkan skrip pada exit code winget,
    # jadi jalankan dengan penanganan manual.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & winget install -e --id JRSoftware.InnoSetup `
            --accept-source-agreements --accept-package-agreements 2>&1 |
            Write-Host
    }
    finally {
        $ErrorActionPreference = $prev
    }

    Start-Sleep -Seconds 3
    return $true
}

# --- 1. Build aplikasi (venv + deps + ffmpeg + pyinstaller) ---
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "scripts\build_windows.ps1")
if ($LASTEXITCODE -ne 0) { throw "Build aplikasi gagal" }

$appDir = Join-Path $root "dist\DroneCompressor"
if (-not (Test-Path $appDir)) { throw "Folder dist\DroneCompressor tidak ditemukan" }

# --- 2. Selalu buat ZIP portable sebagai cadangan ---
$zip = Join-Path $root "dist\DroneCompressor-windows-portable.zip"
Write-Host "Membuat ZIP portable..."
Remove-Item $zip -Force -ErrorAction SilentlyContinue
Compress-Archive -Path $appDir -DestinationPath $zip -CompressionLevel Optimal
Write-Host "OK: $zip"

# --- 3. Cari / install Inno Setup ---
$iscc = Find-ISCC
if (-not $iscc) {
    Install-InnoSetup | Out-Null
    $iscc = Find-ISCC
}

if (-not $iscc) {
    Write-Host ""
    Write-Host "=============================================="
    Write-Host " Inno Setup tidak ditemukan - installer dilewati"
    Write-Host "=============================================="
    Write-Host "Kamu masih bisa mengirim file ZIP portable ini:"
    Write-Host "  $zip"
    Write-Host ""
    Write-Host "Kalau tetap ingin installer satu file, install manual:"
    Write-Host "  https://jrsoftware.org/isdl.php"
    Write-Host "lalu jalankan skrip ini lagi."
    exit 0
}

Write-Host "Inno Setup ditemukan: $iscc"

# --- 4. Compile installer ---
Write-Host "Building installer..."
& $iscc (Join-Path $root "installer\windows_setup.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup gagal (exit $LASTEXITCODE)" }

$setup = Join-Path $root "dist\DroneCompressor-Setup.exe"
if (Test-Path $setup) {
    Write-Host ""
    Write-Host "OK: $setup"
    Write-Host "Kirim file ini ke user - cukup double-click untuk install."
}
else {
    throw "Installer gagal dibuat"
}
