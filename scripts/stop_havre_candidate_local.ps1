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
$WslExecutable = Join-Path $env:SystemRoot "System32\wsl.exe"
$WslDistribution = "Ubuntu"
$WslClusterRoot = "/home/OWNER/.local/share/havre/postgres18-owner-20260828"
$WslPostgresRoot = "/home/OWNER/.local/opt/havre-pg18/root/usr"
$WslPgCtl = "$WslPostgresRoot/lib/postgresql/18/bin/pg_ctl"
$WslLibraryPath = "$WslPostgresRoot/lib/x86_64-linux-gnu"

if (-not (Test-Path -LiteralPath $OwnerStatePath -PathType Leaf)) {
    throw "HAVRE candidate owner-local state is missing; refusing to stop unverified processes"
}
$ownerState = Get-Content -Raw -LiteralPath $OwnerStatePath | ConvertFrom-Json
if ([int]$ownerState.schema_version -notin @(1,2) -or -not [bool]$ownerState.candidate_only) {
    throw "HAVRE candidate owner-local state is invalid"
}
$runtimeKind = if (
    [int]$ownerState.schema_version -eq 2 -and
    $ownerState.PSObject.Properties.Name -contains "runtime_kind"
) { [string]$ownerState.runtime_kind } else { "stage9a-seed-9201" }

if ($runtimeKind -eq "stage3-base") {
    $basePidPath = Join-Path $ProjectRoot ".runtime\stage3\run\llama-server.pid"
    if (-not (Test-Path -LiteralPath $basePidPath -PathType Leaf)) {
        throw "HAVRE base runtime PID is missing"
    }
    $basePid = 0
    if (-not [int]::TryParse((Get-Content -Raw -LiteralPath $basePidPath).Trim(), [ref]$basePid)) {
        throw "HAVRE base runtime PID is invalid"
    }
    if ($basePid -ne [int]$ownerState.model_server_pid) {
        throw "HAVRE base runtime PID does not match verified owner state"
    }
    if ([bool]$ownerState.model_started_by_this_run) {
        & (Join-Path $PSScriptRoot "stop_stage3_local_serving.ps1")
        if ($LASTEXITCODE -ne 0) { throw "HAVRE base runtime failed to stop" }
    }
}
elseif ($runtimeKind -eq "stage9a-seed-9201") {
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
}
else {
    throw "HAVRE owner-local runtime kind is invalid"
}

if ([bool]$ownerState.postgres_started_by_this_run) {
    $backend = if ($ownerState.PSObject.Properties.Name -contains "postgres_backend") {
        [string]$ownerState.postgres_backend
    } else {
        "windows"
    }
    if ($backend -eq "wsl") {
        & $WslExecutable -d $WslDistribution -- env "LD_LIBRARY_PATH=$WslLibraryPath" $WslPgCtl -D $WslClusterRoot -w stop -m fast
    }
    elseif ($backend -eq "windows") {
        $pgCtl = (Get-Command pg_ctl -ErrorAction Stop).Source
        & $pgCtl -D $ClusterRoot stop -m fast
    }
    else {
        throw "HAVRE PostgreSQL backend in owner state is invalid"
    }
    if ($LASTEXITCODE -ne 0) { throw "HAVRE PostgreSQL failed to stop" }
}
Remove-Item -LiteralPath $OwnerStatePath -Force
Write-Host "HAVRE owner-local runtime stopped cleanly ($runtimeKind)."
