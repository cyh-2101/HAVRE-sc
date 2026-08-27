[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$RuntimeRoot = Join-Path $ProjectRoot ".runtime\stage9a-candidate"
$StatePath = Join-Path $RuntimeRoot "runtime-state.json"
$PidPath = Join-Path $RuntimeRoot "server.pid"
$OwnerStatePath = Join-Path $RuntimeRoot "owner-local-state.json"
$ClusterRoot = Join-Path $ProjectRoot "var\postgres"

if (-not (Test-Path -LiteralPath $OwnerStatePath -PathType Leaf)) {
    throw "HAVRE candidate owner-local state is missing; refusing to stop unverified processes"
}
$ownerState = Get-Content -Raw -LiteralPath $OwnerStatePath | ConvertFrom-Json
if ([int]$ownerState.schema_version -ne 1 -or -not [bool]$ownerState.candidate_only) {
    throw "HAVRE candidate owner-local state is invalid"
}
if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
    throw "HAVRE candidate runtime state is missing"
}
$runtimeState = Get-Content -Raw -LiteralPath $StatePath | ConvertFrom-Json
$pidText = (Get-Content -Raw -LiteralPath $PidPath).Trim()
$candidateLauncherPid = 0
if (-not [int]::TryParse($pidText, [ref]$candidateLauncherPid)) {
    throw "HAVRE candidate PID is invalid"
}
if (
    $candidateLauncherPid -ne [int]$ownerState.candidate_launcher_pid -or
    $candidateLauncherPid -ne [int]$runtimeState.launcher_pid
) {
    throw "HAVRE candidate launcher PID does not match verified state"
}
$process = Get-Process -Id $candidateLauncherPid -ErrorAction SilentlyContinue
if ($null -ne $process) {
    $expectedPython = [IO.Path]::GetFullPath(
        (Join-Path $ProjectRoot "var\stage9a\env-windows\Scripts\python.exe")
    )
    if (-not $process.Path.Equals($expectedPython, [StringComparison]::OrdinalIgnoreCase)) {
        throw "HAVRE candidate PID is not the sealed Stage 9A Python process"
    }
    $serverProcess = Get-Process -Id ([int]$runtimeState.pid) -ErrorAction SilentlyContinue
    if ($null -ne $serverProcess) {
        Stop-Process -Id $serverProcess.Id -ErrorAction Stop
        $serverProcess.WaitForExit(30000) | Out-Null
    }
    Stop-Process -Id $candidateLauncherPid -ErrorAction Stop
    $process.WaitForExit(30000) | Out-Null
}
Remove-Item -LiteralPath $PidPath -Force
Remove-Item -LiteralPath $StatePath -Force

if ([bool]$ownerState.postgres_started_by_this_run) {
    $pgCtl = (Get-Command pg_ctl -ErrorAction Stop).Source
    & $pgCtl -D $ClusterRoot stop -m fast
    if ($LASTEXITCODE -ne 0) { throw "HAVRE PostgreSQL failed to stop" }
}
Remove-Item -LiteralPath $OwnerStatePath -Force
Write-Host "HAVRE Seed 9201 owner-local runtime stopped cleanly."
