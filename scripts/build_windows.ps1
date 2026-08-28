# Build DroneCompressor.exe with PyInstaller (run on Windows)
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

function Test-PythonCandidate {
    <#
      Jalankan kandidat python dan kembalikan path interpreter sebenarnya.
      Mengembalikan $null kalau tidak bisa dipakai (termasuk stub Microsoft Store).
    #>
    param([string[]]$Command)

    $exe = $Command[0]
    $args = @()
    if ($Command.Count -gt 1) { $args = $Command[1..($Command.Count - 1)] }

    if (-not (Get-Command $exe -ErrorAction SilentlyContinue) -and -not (Test-Path $exe)) {
        return $null
    }

    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & $exe @args "-c" "import sys; print(sys.executable); print('%d.%d' % sys.version_info[:2])" 2>$null
    }
    catch {
        return $null
    }
    finally {
        $ErrorActionPreference = $prev
    }

    if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }

    $lines = @($out) | Where-Object { $_ -and $_.ToString().Trim() }
    if ($lines.Count -lt 2) { return $null }

    $exePath = $lines[0].ToString().Trim()
    $version = $lines[1].ToString().Trim()

    if (-not (Test-Path $exePath)) { return $null }

    # PySide6 butuh Python 3.9 - 3.13
    $parts = $version.Split(".")
    $major = [int]$parts[0]
    $minor = [int]$parts[1]
    if ($major -ne 3 -or $minor -lt 9 -or $minor -gt 13) {
        Write-Warning "Python $version di $exePath tidak didukung (butuh 3.9 - 3.13), dilewati."
        return $null
    }

    Write-Host "Python $version ditemukan: $exePath"
    return $exePath
}

function Find-Python {
    $candidates = @(
        @("py", "-3.12"),
        @("py", "-3.11"),
        @("py", "-3.13"),
        @("py", "-3"),
        @("python"),
        @("python3")
    )

    foreach ($c in $candidates) {
        $found = Test-PythonCandidate -Command $c
        if ($found) { return $found }
    }

    # Cari di lokasi instalasi umum
    $globs = @(
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
        "$env:ProgramFiles\Python3*\python.exe",
        "C:\Python3*\python.exe"
    )
    foreach ($g in $globs) {
        $hits = Get-ChildItem -Path $g -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
        foreach ($h in $hits) {
            $found = Test-PythonCandidate -Command @($h.FullName)
            if ($found) { return $found }
        }
    }

    return $null
}

$python = Find-Python

if (-not $python) {
    Write-Host "Python 3.9-3.13 tidak ditemukan. Mencoba install via winget..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & winget install -e --id Python.Python.3.12 `
                --accept-source-agreements --accept-package-agreements 2>&1 | Write-Host
        }
        finally {
            $ErrorActionPreference = $prev
        }
        Start-Sleep -Seconds 3
        # winget memperbarui PATH hanya untuk sesi baru, jadi cari via glob juga
        $python = Find-Python
    }
}

if (-not $python) {
    Write-Host ""
    Write-Host "=============================================="
    Write-Host " Python 3.9-3.13 tidak ditemukan"
    Write-Host "=============================================="
    Write-Host "Install manual:"
    Write-Host "  winget install -e --id Python.Python.3.12"
    Write-Host "  atau unduh: https://www.python.org/downloads/"
    Write-Host ""
    Write-Host "Saat install manual, centang 'Add python.exe to PATH'."
    Write-Host "Setelah itu TUTUP jendela ini dan jalankan BUILD_WINDOWS.bat lagi."
    throw "Python tidak tersedia"
}

# --- venv ---
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating venv..."
    Remove-Item -Recurse -Force (Join-Path $root ".venv") -ErrorAction SilentlyContinue
    & $python -m venv (Join-Path $root ".venv")
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        throw "Gagal membuat venv dengan $python"
    }
}
Write-Host "venv: $venvPython"

Write-Host "Installing dependencies..."
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r (Join-Path $root "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) { throw "Gagal install dependency" }

# --- FFmpeg static ---
$ffmpeg = Join-Path $root "bin\windows\ffmpeg.exe"
$ffprobe = Join-Path $root "bin\windows\ffprobe.exe"
if (-not ((Test-Path $ffmpeg) -and (Test-Path $ffprobe))) {
    Write-Host "FFmpeg belum ada di bin\windows. Mengunduh..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "scripts\fetch_static_ffmpeg_windows.ps1")

    if (-not ((Test-Path $ffmpeg) -and (Test-Path $ffprobe))) {
        Write-Host ""
        Write-Host "=============================================="
        Write-Host " FFmpeg tidak tersedia - build dihentikan"
        Write-Host "=============================================="
        Write-Host "Letakkan ffmpeg.exe dan ffprobe.exe secara manual di:"
        Write-Host "  $root\bin\windows\"
        Write-Host ""
        Write-Host "Unduh dari:"
        Write-Host "  https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        Write-Host "(kedua file ada di dalam folder bin\ pada arsip tersebut)"
        Write-Host ""
        Write-Host "Setelah itu jalankan BUILD_WINDOWS.bat lagi."
        throw "FFmpeg tidak ditemukan di bin\windows"
    }
}
Write-Host "FFmpeg OK: $ffmpeg"

# --- Tests (tidak memblokir build) ---
Write-Host "Running tests..."
$env:PATH = "$root\bin\windows;$env:PATH"
& $venvPython -m pytest -q
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Ada test yang gagal, build tetap dilanjutkan."
}

# --- Build ---
Write-Host "Building DroneCompressor.exe..."
Remove-Item -Recurse -Force (Join-Path $root "build") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $root "dist\DroneCompressor") -ErrorAction SilentlyContinue
& $venvPython -m PyInstaller --noconfirm (Join-Path $root "build_windows.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller gagal" }

$exe = Join-Path $root "dist\DroneCompressor\DroneCompressor.exe"
if (Test-Path $exe) {
    Write-Host ""
    Write-Host "OK: $exe"
}
else {
    throw "Build gagal - exe tidak ditemukan"
}
