# Datasphere Cleanup — Windows Installer
# Run this once on a new Windows PC.
# Right-click -> "Run with PowerShell"

$ErrorActionPreference = "Stop"

$REPO_ZIP_URL = "https://github.com/eddiesheehanbritas-sketch/Datasphere-Cleanup-Windows/archive/refs/heads/main.zip"
$INSTALL_DIR  = "$env:USERPROFILE\DatasphereCleanup"
$PYTHON_URL   = "https://www.python.org/ftp/python/3.9.13/python-3.9.13-amd64.exe"
$PYTHON_EXE   = "$env:LOCALAPPDATA\Programs\Python\Python39\python.exe"

function Write-Step($msg) {
    Write-Host ""
    Write-Host ">>> $msg" -ForegroundColor Cyan
}

# ── 1. Install Python 3.9 if not present ─────────────────────────────────────
Write-Step "Checking Python 3.9..."

if (-not (Test-Path $PYTHON_EXE)) {
    Write-Host "Python 3.9 not found. Downloading installer..."
    $pyInstaller = "$env:TEMP\python-3.9.13-amd64.exe"
    Invoke-WebRequest -Uri $PYTHON_URL -OutFile $pyInstaller -MaximumRedirection 5
    Write-Host "Installing Python 3.9 (just for you, no admin needed)..."
    Start-Process -FilePath $pyInstaller -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=0" -Wait
    Remove-Item $pyInstaller
    if (-not (Test-Path $PYTHON_EXE)) {
        Write-Host "ERROR: Python install failed. Please install Python 3.9 manually from python.org" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "Python 3.9 installed."
} else {
    Write-Host "Python 3.9 found at $PYTHON_EXE"
}

# ── 2. Download and extract the repo ─────────────────────────────────────────
Write-Step "Downloading Datasphere Cleanup..."

$zipPath = "$env:TEMP\datasphere-cleanup.zip"
$extractPath = "$env:TEMP\datasphere-cleanup-extract"

Invoke-WebRequest -Uri $REPO_ZIP_URL -OutFile $zipPath -MaximumRedirection 5
if (Test-Path $extractPath) { Remove-Item -Recurse -Force $extractPath }
Expand-Archive -Path $zipPath -DestinationPath $extractPath
Remove-Item $zipPath

# The zip contains a single top-level folder (the repo name + branch)
$repoFolder = Get-ChildItem $extractPath | Select-Object -First 1

if (Test-Path $INSTALL_DIR) {
    Write-Host "Removing previous installation at $INSTALL_DIR..."
    Remove-Item -Recurse -Force $INSTALL_DIR
}
Move-Item -Path $repoFolder.FullName -Destination $INSTALL_DIR
Remove-Item -Recurse -Force $extractPath
Write-Host "Installed to $INSTALL_DIR"

# ── 3. Create virtual environment ────────────────────────────────────────────
Write-Step "Creating Python virtual environment..."

& $PYTHON_EXE -m venv "$INSTALL_DIR\venv"
$pip  = "$INSTALL_DIR\venv\Scripts\pip.exe"
$python = "$INSTALL_DIR\venv\Scripts\python.exe"

# ── 4. Install Python dependencies ───────────────────────────────────────────
Write-Step "Installing dependencies (this may take a minute)..."

& $pip install --upgrade pip | Out-Null
# Pin greenlet to a version with a pre-built Windows wheel (avoids needing C++ Build Tools)
& $pip install "greenlet==3.1.1"
& $pip install -r "$INSTALL_DIR\requirements.txt"

# ── 5. Install Playwright and download Chromium ───────────────────────────────
Write-Step "Installing Playwright and downloading Chromium (this may take a few minutes)..."

& $python -m playwright install chromium

# ── 6. Create app home folder structure ──────────────────────────────────────
Write-Step "Setting up app data folder..."

$APP_HOME = "$env:USERPROFILE\Documents\Datasphere Cleanup"
$dirs = @(
    "$APP_HOME\config",
    "$APP_HOME\outputs\logs",
    "$APP_HOME\outputs\reports",
    "$APP_HOME\outputs\user_lists"
)
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}

# Seed config files if not already present
$settingsSrc = "$INSTALL_DIR\config\settings.yaml"
$settingsDst = "$APP_HOME\config\settings.yaml"
if (-not (Test-Path $settingsDst)) {
    Copy-Item $settingsSrc $settingsDst
}

$allowlistSrc = "$INSTALL_DIR\config\allowlist.txt"
$allowlistDst = "$APP_HOME\config\allowlist.txt"
if (-not (Test-Path $allowlistDst)) {
    if (Test-Path $allowlistSrc) { Copy-Item $allowlistSrc $allowlistDst }
    else { New-Item -ItemType File -Path $allowlistDst | Out-Null }
}

# Ensure deleted.txt exists (permanent audit log — never delete)
$deletedFiles = @(
    "outputs/user_lists/deleted_eu10.txt",
    "outputs/user_lists/deleted_us10.txt",
    "outputs/user_lists/deleted_ap11.txt",
    "outputs/user_lists/deleted_ap11_2.txt",
    "outputs/user_lists/deleted_eu10_2.txt",
    "outputs/user_lists/deleted_us10_2.txt"
)
foreach ($f in $deletedFiles) {
    $dst = "$APP_HOME\$f"
    if (-not (Test-Path $dst)) { New-Item -ItemType File -Path $dst | Out-Null }
}

# ── 7. Copy launch.ps1 to a stable location and create desktop shortcut ───────
Write-Step "Creating desktop shortcut..."

$launchSrc = "$INSTALL_DIR\windows\launch.ps1"

# Use SpecialFolders to find Desktop reliably (works with OneDrive-redirected desktops)
$shell = New-Object -ComObject WScript.Shell
$desktopPath = $shell.SpecialFolders("Desktop")
$shortcutPath = "$desktopPath\Datasphere Cleanup.lnk"
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launchSrc`""
$shortcut.WorkingDirectory = $INSTALL_DIR
$shortcut.Description = "Datasphere Cleanup"
$shortcut.Save()

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  Installation complete!" -ForegroundColor Green
Write-Host "  Shortcut created on your Desktop." -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Read-Host "Press Enter to close"
