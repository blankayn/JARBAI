$root = $PSScriptRoot
$py = "$root\.venv\Scripts\python.exe"

$inUse = $false
try { $inUse = (Test-NetConnection -ComputerName 127.0.0.1 -Port 8470 -InformationLevel Quiet -WarningAction SilentlyContinue) } catch { $inUse = $false }

if (-not $inUse) {
    Start-Process -FilePath $py -ArgumentList "`"$root\dashboard_server.py`"" -WindowStyle Hidden
    Start-Sleep -Seconds 2
}

Start-Process "http://127.0.0.1:8470"
