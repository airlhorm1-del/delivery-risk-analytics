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

# Keep Windows from going to sleep while the run is working (on 1 Oct 2026 the laptop fell asleep
# in the middle of the BigQuery upload). This only stops sleep from inactivity: closing the lid or
# choosing Sleep still sleeps, and the next run (or the upload retries) then catch up.
Add-Type -Namespace DeliveryRisk -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
$ES_CONTINUOUS = [uint32]2147483648      # 0x80000000
$ES_SYSTEM_REQUIRED = [uint32]1          # 0x00000001
[DeliveryRisk.Power]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED) | Out-Null

try {
    & $uv run python run_pipeline.py --daily --bigquery --log-file $log
    $exitCode = $LASTEXITCODE
}
finally {
    [DeliveryRisk.Power]::SetThreadExecutionState($ES_CONTINUOUS) | Out-Null   # back to normal sleep rules
}

Get-ChildItem $logDir -Filter "daily_*.log" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 30 | Remove-Item -Force
exit $exitCode
