# Daily run of the delivery-risk pipeline with simulated live orders (SYNTHETIC DATA).
# Windows Task Scheduler starts this every day at 07:00 (set up by register_daily_task.ps1).
# It fetches today's API data, moves the simulated shop on to "now", rebuilds and tests everything,
# refreshes BigQuery, and writes a log to logs\daily_<date>_<time>.log (the last 30 are kept).

$project = Split-Path -Parent $PSScriptRoot
Set-Location $project
$logDir = Join-Path $project "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("daily_{0}.log" -f (Get-Date -Format "yyyy-MM-dd_HHmm"))

$uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
if (-not (Test-Path $uv)) { $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source }
$env:PYTHONIOENCODING = "utf-8"

& $uv run python run_pipeline.py --daily --bigquery --log-file $log
$exitCode = $LASTEXITCODE

Get-ChildItem $logDir -Filter "daily_*.log" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 30 | Remove-Item -Force
exit $exitCode
