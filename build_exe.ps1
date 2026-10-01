# Builds dist\PCBPro\PCBPro.exe (a self-contained Windows application folder).
# Usage:  powershell -ExecutionPolicy Bypass -File build_exe.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) {
    python -m venv .venv
}
.\.venv\Scripts\python.exe -m pip install --upgrade pip -q
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller -q

.\.venv\Scripts\python.exe tools\make_icon.py

.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed `
    --name PCBPro `
    --icon pcbpro\resources\pcbpro.ico `
    --add-data "pcbpro\resources;pcbpro\resources" `
    --collect-submodules pcbpro `
    --exclude-module pygerber --exclude-module pytest --exclude-module tkinter `
    pcbpro_launcher.py

Write-Host ""
Write-Host "Built: $PSScriptRoot\dist\PCBPro\PCBPro.exe"
