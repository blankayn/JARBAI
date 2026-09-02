# JARBAI setup - run once on a new machine.
#
#     powershell -ExecutionPolicy Bypass -File setup.ps1
#
# Creates the virtualenv, installs dependencies, generates the icon and adds
# the desktop shortcut. Paste your API key afterwards in the app's Setup panel
# (the gear icon) - no need to edit files by hand.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Step($text) { Write-Host "`n>> $text" -ForegroundColor Cyan }
function Ok($text)   { Write-Host "   $text" -ForegroundColor Green }
function Warn($text) { Write-Host "   $text" -ForegroundColor Yellow }

Write-Host "JARBAI setup" -ForegroundColor Cyan
Write-Host "============"

# --- 1. Python -------------------------------------------------------------
Step "Checking Python"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "   Python is not installed or not on PATH." -ForegroundColor Red
    Write-Host "   Install Python 3.10+ from python.org and tick 'Add to PATH', then re-run."
    exit 1
}
$version = & python --version
Ok "$version"

# --- 2. Virtualenv ---------------------------------------------------------
Step "Creating the virtualenv"
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    Ok "Already exists, reusing it"
} else {
    & python -m venv (Join-Path $root ".venv")
    Ok "Created .venv"
}

# --- 3. Dependencies -------------------------------------------------------
Step "Installing dependencies (this takes a few minutes the first time)"
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r (Join-Path $root "requirements.txt") --quiet
Ok "Dependencies installed"

# --- 4. Icon + shortcut ----------------------------------------------------
Step "Generating the icon"
& $venvPython (Join-Path $root "make_icon.py")

Step "Creating the desktop shortcut"
& powershell -ExecutionPolicy Bypass -File (Join-Path $root "install_shortcut.ps1")

# --- 5. Ollama (optional, for the offline brain) ---------------------------
Step "Checking Ollama (the offline brain)"
$ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
if (Test-Path $ollama) {
    Ok "Installed"
    $tags = $null
    try { $tags = Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 3 } catch {}
    if ($tags -and ($tags.models | Where-Object { $_.name -like "qwen2.5:3b*" })) {
        Ok "qwen2.5:3b is present"
    } else {
        Warn "Model not found. Fetching it now (about 2 GB)..."
        & $ollama pull qwen2.5:3b
    }
} else {
    Warn "Not installed - JARBAI will need the cloud brain to answer."
    Warn "For offline use, install from https://ollama.com/download then run:"
    Warn "    ollama pull qwen2.5:3b"
}

# --- 6. Done ---------------------------------------------------------------
$hasKey = (Test-Path (Join-Path $root ".env")) -and
          ((Get-Content (Join-Path $root ".env") -Raw) -match "GEMINI_API_KEY=\S")

Write-Host "`n============" -ForegroundColor Cyan
Write-Host "Setup complete." -ForegroundColor Green
Write-Host ""
Write-Host "  1. Double-click JARBAI on your Desktop"
if (-not $hasKey) {
    Write-Host "  2. Click the gear icon and paste your Google AI Studio API key"
    Write-Host "     (get one free at https://aistudio.google.com/apikey)"
    Write-Host "     Skip this if you only want the offline local brain."
} else {
    Write-Host "  2. An API key is already configured."
}
Write-Host "  3. Say `"Jarbai, what time is it`" - or just snap your fingers"
Write-Host ""
