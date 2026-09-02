# Starts the web JARBAI (dashboard server + app window).
# The desktop shortcut runs launcher.pyw directly; this script is the
# equivalent from a terminal.
#
# The old Tk window is still on disk if you ever want it:
#     .venv\Scripts\python.exe -m jarbai.ui.app

$root = $PSScriptRoot
$pyw = Join-Path $root ".venv\Scripts\pythonw.exe"
$launcher = Join-Path $root "launcher.pyw"

if (-not (Test-Path $pyw)) {
    Write-Host "Missing $pyw - create the virtualenv first." -ForegroundColor Red
    exit 1
}

Start-Process -FilePath $pyw -ArgumentList "`"$launcher`"" -WorkingDirectory $root
