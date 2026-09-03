# Datasphere Cleanup — Launcher
# This file is invoked by the Desktop shortcut.

$ErrorActionPreference = "Stop"

$INSTALL_DIR = "$env:USERPROFILE\DatasphereCleanup"
$APP_HOME     = "$env:USERPROFILE\Documents\Datasphere Cleanup"
$python       = "$INSTALL_DIR\venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "ERROR: Datasphere Cleanup is not installed. Please run install.ps1 first." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Set-Location $APP_HOME
& $python "$INSTALL_DIR\src\combined.py"
