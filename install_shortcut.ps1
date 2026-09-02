# Creates the JARBAI shortcuts on the Desktop and in the Start Menu. Run once:
#     powershell -ExecutionPolicy Bypass -File install_shortcut.ps1
#
#   JARBAI -> starts everything: Ollama, the dashboard app window, and the
#             always-on voice listener (say "Jarbai ...", or snap your fingers)

$root = $PSScriptRoot
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
$python = Join-Path $root ".venv\Scripts\python.exe"
$launcher = Join-Path $root "launcher.pyw"
$icon = Join-Path $root "jarbai.ico"

if (-not (Test-Path $pythonw)) {
    Write-Host "Could not find $pythonw" -ForegroundColor Red
    Write-Host "Create the virtualenv first, then re-run this script."
    exit 1
}
if (-not (Test-Path $icon)) {
    Write-Host "Icon missing - generating it..." -ForegroundColor Yellow
    & $python (Join-Path $root "make_icon.py")
}

$desktop = [Environment]::GetFolderPath('Desktop')
$startMenu = Join-Path ([Environment]::GetFolderPath('StartMenu')) "Programs"

$shortcuts = @(
    @{ Name = "JARBAI"; Target = $pythonw; Args = "`"$launcher`"";
       Desc = "JARBAI - dashboard and always-on voice" }
)

$shell = New-Object -ComObject WScript.Shell
foreach ($sc in $shortcuts) {
    foreach ($dir in @($desktop, $startMenu)) {
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        $path = Join-Path $dir "$($sc.Name).lnk"

        $lnk = $shell.CreateShortcut($path)
        $lnk.TargetPath       = $sc.Target
        $lnk.Arguments        = $sc.Args
        $lnk.WorkingDirectory = $root
        $lnk.IconLocation     = "$icon,0"
        $lnk.Description      = $sc.Desc
        $lnk.Save()

        Write-Host "Created $path" -ForegroundColor Cyan
    }
}

Write-Host ""
Write-Host 'JARBAI - dashboard + always listening. Say "Jarbai ...", or snap.' -ForegroundColor Green
