# Download static ffmpeg/ffprobe for Windows into bin\windows
# Mencoba beberapa sumber; kalau semua gagal, pakai FFmpeg yang sudah ada di sistem.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dest = Join-Path $root "bin\windows"
New-Item -ItemType Directory -Force -Path $dest | Out-Null

$targetFfmpeg = Join-Path $dest "ffmpeg.exe"
$targetFfprobe = Join-Path $dest "ffprobe.exe"

if ((Test-Path $targetFfmpeg) -and (Test-Path $targetFfprobe)) {
    Write-Host "FFmpeg sudah ada di bin\windows, dilewati."
    exit 0
}

# TLS 1.2/1.3 (Windows lama default TLS 1.0 -> download gagal)
try {
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls11
}
catch {
    Write-Warning "Tidak bisa set TLS: $($_.Exception.Message)"
}

$mirrors = @(
    @{
        Name = "BtbN GitHub (win64-gpl)"
        Url  = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    },
    @{
        Name = "gyan.dev (release-essentials)"
        Url  = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    },
    @{
        Name = "gyan.dev (git-essentials)"
        Url  = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-git-essentials.7z"
    }
)

function Download-File {
    param([string]$Url, [string]$OutFile)

    # 1. curl.exe (tersedia di Windows 10 1803+, paling andal untuk redirect)
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        Write-Host "  via curl.exe ..."
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & curl.exe -L --fail --retry 3 --retry-delay 2 -o $OutFile $Url
            $code = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $prev
        }
        if ($code -eq 0 -and (Test-Path $OutFile) -and (Get-Item $OutFile).Length -gt 1MB) {
            return $true
        }
        Write-Warning "  curl gagal (exit $code)"
        Remove-Item $OutFile -Force -ErrorAction SilentlyContinue
    }

    # 2. Invoke-WebRequest
    Write-Host "  via Invoke-WebRequest ..."
    try {
        $ProgressPreference = "SilentlyContinue"
        Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing -TimeoutSec 600
        if ((Test-Path $OutFile) -and (Get-Item $OutFile).Length -gt 1MB) {
            return $true
        }
    }
    catch {
        Write-Warning "  Invoke-WebRequest gagal: $($_.Exception.Message)"
    }
    Remove-Item $OutFile -Force -ErrorAction SilentlyContinue
    return $false
}

function Extract-Archive {
    param([string]$Archive, [string]$Into)

    if ($Archive -like "*.7z") {
        $sevenZip = @(
            "$env:ProgramFiles\7-Zip\7z.exe",
            "${env:ProgramFiles(x86)}\7-Zip\7z.exe"
        ) | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $sevenZip) {
            Write-Warning "  Arsip .7z butuh 7-Zip, dilewati."
            return $false
        }
        & $sevenZip x $Archive "-o$Into" -y | Out-Null
        return ($LASTEXITCODE -eq 0)
    }

    try {
        Expand-Archive -Path $Archive -DestinationPath $Into -Force
        return $true
    }
    catch {
        Write-Warning "  Gagal extract: $($_.Exception.Message)"
        return $false
    }
}

function Install-From-Archive {
    param([string]$Url, [string]$Name)

    $tmp = Join-Path $env:TEMP ("dc_ffmpeg_" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    try {
        $ext = if ($Url -like "*.7z") { ".7z" } else { ".zip" }
        $archive = Join-Path $tmp ("ffmpeg" + $ext)

        Write-Host "Mencoba: $Name"
        if (-not (Download-File -Url $Url -OutFile $archive)) { return $false }

        Write-Host "  Extract..."
        if (-not (Extract-Archive -Archive $archive -Into $tmp)) { return $false }

        $ffmpeg = Get-ChildItem -Path $tmp -Recurse -Filter "ffmpeg.exe" -ErrorAction SilentlyContinue |
            Select-Object -First 1
        $ffprobe = Get-ChildItem -Path $tmp -Recurse -Filter "ffprobe.exe" -ErrorAction SilentlyContinue |
            Select-Object -First 1

        if (-not $ffmpeg -or -not $ffprobe) {
            Write-Warning "  ffmpeg.exe/ffprobe.exe tidak ada dalam arsip"
            return $false
        }

        Copy-Item $ffmpeg.FullName $targetFfmpeg -Force
        Copy-Item $ffprobe.FullName $targetFfprobe -Force
        return $true
    }
    catch {
        Write-Warning "  Error: $($_.Exception.Message)"
        return $false
    }
    finally {
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    }
}

function Install-From-System {
    <# Pakai FFmpeg yang sudah terpasang (PATH / winget / choco). #>
    Write-Host "Mencari FFmpeg yang sudah terpasang di sistem..."

    $ffmpegCmd = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
    $ffprobeCmd = Get-Command ffprobe.exe -ErrorAction SilentlyContinue

    if (-not $ffmpegCmd -or -not $ffprobeCmd) {
        $globs = @(
            "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\*\**\ffmpeg.exe",
            "$env:ProgramData\chocolatey\bin\ffmpeg.exe",
            "C:\ffmpeg\bin\ffmpeg.exe"
        )
        foreach ($g in $globs) {
            $hit = Get-ChildItem -Path $g -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($hit) {
                $probe = Join-Path $hit.DirectoryName "ffprobe.exe"
                if (Test-Path $probe) {
                    Copy-Item $hit.FullName $targetFfmpeg -Force
                    Copy-Item $probe $targetFfprobe -Force
                    return $true
                }
            }
        }
        return $false
    }

    Copy-Item $ffmpegCmd.Source $targetFfmpeg -Force
    Copy-Item $ffprobeCmd.Source $targetFfprobe -Force
    return $true
}

function Install-Via-Winget {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { return $false }
    Write-Host "Mencoba winget install FFmpeg..."
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & winget install -e --id Gyan.FFmpeg `
            --accept-source-agreements --accept-package-agreements 2>&1 | Write-Host
    }
    finally {
        $ErrorActionPreference = $prev
    }
    Start-Sleep -Seconds 3
    return (Install-From-System)
}

# --- Eksekusi berurutan ---
$ok = $false

foreach ($m in $mirrors) {
    if (Install-From-Archive -Url $m.Url -Name $m.Name) { $ok = $true; break }
    Write-Host ""
}

if (-not $ok) { $ok = Install-From-System }
if (-not $ok) { $ok = Install-Via-Winget }

if (-not $ok) {
    Write-Host ""
    Write-Host "=============================================="
    Write-Host " GAGAL mendapatkan FFmpeg"
    Write-Host "=============================================="
    Write-Host "Cara manual:"
    Write-Host "  1. Unduh: https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    Write-Host "  2. Extract, cari ffmpeg.exe dan ffprobe.exe di folder bin\"
    Write-Host "  3. Copy kedua file itu ke:"
    Write-Host "     $dest"
    Write-Host "  4. Jalankan BUILD_WINDOWS.bat lagi"
    exit 1
}

Write-Host ""
Write-Host "Installed:"
Get-ChildItem $dest -Filter "ff*.exe" | Format-Table Name, Length -AutoSize
& $targetFfmpeg -version | Select-Object -First 1
