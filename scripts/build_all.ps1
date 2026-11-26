# Indirici Pro — Tek Tikla Derleme Betigi (EXE + Portable ZIP + Setup.exe)
param(
    [string]$PythonExe = "python",
    [string]$IsccExe = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $IsccExe) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $IsccExe = $c; break }
    }
}

$StageDist = Join-Path $Root "build\stage_dist"
Write-Host "[1/4] PyInstaller ile IndiriciPro.exe derleniyor..." -ForegroundColor Cyan
& $PythonExe -m PyInstaller `
    --noconfirm --clean --onefile --windowed `
    --name IndiriciPro `
    --icon "$Root\assets\app_icon.ico" `
    --add-data "$Root\assets\app_icon.ico;assets" `
    --distpath "$StageDist" `
    --workpath "$Root\build" `
    --specpath "$Root\build" `
    "$Root\indirici_pro.py"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller derlemesi basarisiz oldu (kod: $LASTEXITCODE)" }

New-Item -ItemType Directory -Force -Path "$Root\dist" | Out-Null
try {
    Copy-Item -Force "$StageDist\IndiriciPro.exe" "$Root\dist\IndiriciPro.exe"
} catch {
    Write-Warning "dist\IndiriciPro.exe su an acik oldugu icin guncellenemedi; release paketleri yeni derleme ile olusturuluyor."
}

Write-Host "[2/4] Portable klasoru hazirlaniyor..." -ForegroundColor Cyan
$ReleaseDir = Join-Path $Root "release"
$PortableDir = Join-Path $Root "build\IndiriciPro_Portable"
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
if (Test-Path $PortableDir) { Remove-Item -Recurse -Force $PortableDir }
New-Item -ItemType Directory -Force -Path "$PortableDir\tools","$PortableDir\assets","$PortableDir\data","$PortableDir\İndirilenler" | Out-Null

Copy-Item "$StageDist\IndiriciPro.exe" "$PortableDir\IndiriciPro.exe"
Copy-Item "$Root\assets\app_icon.ico" "$PortableDir\assets\app_icon.ico"
Copy-Item "$Root\README.md" "$PortableDir\README.md"
Copy-Item "$Root\LICENSE" "$PortableDir\LICENSE"
"PORTABLE" | Out-File -Encoding ascii "$PortableDir\portable.flag"

foreach ($tool in @("N_m3u8DL-RE.exe", "ffmpeg.exe", "mp4decrypt.exe", "yt-dlp.exe")) {
    $src = Join-Path "$Root\tools" $tool
    if (Test-Path $src) {
        Copy-Item $src "$PortableDir\tools\$tool"
    } else {
        Write-Warning "Eksik arac: $src"
    }
}

Write-Host "[3/4] IndiriciPro_Portable.zip paketleniyor..." -ForegroundColor Cyan
$ZipPath = Join-Path $ReleaseDir "IndiriciPro_Portable.zip"
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
& $PythonExe -c "import zipfile; from pathlib import Path; src=Path(r'$PortableDir'); dst=Path(r'$ZipPath'); zf=zipfile.ZipFile(dst,'w',zipfile.ZIP_DEFLATED,compresslevel=6); [zf.write(p, p.relative_to(src)) for p in src.rglob('*') if p.is_file()]; zf.close()"

Write-Host "[4/4] Inno Setup ile IndiriciPro_Setup.exe olusturuluyor..." -ForegroundColor Cyan
if (Test-Path $IsccExe) {
    & $IsccExe "$Root\installer\IndiriciPro.iss"
} else {
    Write-Warning "ISCC.exe bulunamadi ($IsccExe). Setup.exe atlandi."
}

Write-Host "`nTamamlandi! Ciktilar: $ReleaseDir" -ForegroundColor Green
Get-ChildItem $ReleaseDir | Select-Object Name, Length, LastWriteTime
