[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$ClusterRoot = Join-Path $ProjectRoot "var\postgres"
$RunRoot = Join-Path $ProjectRoot ".runtime\stage3\run"
$StatePath = Join-Path $RunRoot "havre-local-state.json"
$ApiPidPath = Join-Path $RunRoot "havre-api.pid"
Import-Module (Join-Path $PSScriptRoot "HavreLocalRuntime.psm1") -Force

if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
    throw "HAVRE local runtime state is missing; refusing to stop unverified processes"
}
$state = Get-Content -Raw -LiteralPath $StatePath | ConvertFrom-Json
if ([int]$state.schema_version -ne 2) {
    throw "HAVRE local runtime state schema is not supported; refusing to stop unverified resources"
}
if (-not [bool]$state.resources.havre_api.started_by_this_run) {
    throw "HAVRE API is not owned by this local runtime state; refusing to stop it"
}

Assert-HavreOwnedApiPidFile `
    -StateOwnsApi ([bool]$state.resources.havre_api.started_by_this_run) `
    -PidPath $ApiPidPath
if (Test-Path -LiteralPath $ApiPidPath -PathType Leaf) {
    $apiPid = 0
    $apiPidText = (Get-Content -Raw -LiteralPath $ApiPidPath).Trim()
    if (-not [int]::TryParse($apiPidText, [ref]$apiPid)) {
        throw "HAVRE API PID file is invalid; refusing to stop any process"
    }
    if ($apiPid -ne [int]$state.api_pid) {
        throw "HAVRE API PID does not match verified runtime state"
    }
    $apiProcess = Get-Process -Id $apiPid -ErrorAction SilentlyContinue
    if ($null -ne $apiProcess) {
        Assert-HavreProcessIdentity `
            -Process $apiProcess `
            -ExpectedPid ([int]$state.api_pid) `
            -ExpectedExecutable ([string]$state.api_executable) `
            -ExpectedStartedAt ([DateTime]::Parse([string]$state.api_started_at))
        Stop-Process -Id $apiPid -ErrorAction Stop
        $apiProcess.WaitForExit(15000) | Out-Null
    }
    Remove-Item -LiteralPath $ApiPidPath -Force
}

if ([bool]$state.resources.llama_cpp.started_by_this_run) {
    & (Join-Path $PSScriptRoot "stop_stage3_local_serving.ps1")
}

if ([bool]$state.resources.postgres.started_by_this_run) {
    $pgCtl = (Get-Command pg_ctl -ErrorAction Stop).Source
    $resolvedCluster = [IO.Path]::GetFullPath($ClusterRoot)
    $expectedCluster = [IO.Path]::GetFullPath([string]$state.resources.postgres.cluster)
    if (-not $resolvedCluster.Equals($expectedCluster, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unexpected PostgreSQL cluster path; refusing to stop it"
    }
    & $pgCtl -D $resolvedCluster stop -m fast
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL failed to stop"
    }
}

Remove-Item -LiteralPath $StatePath -Force
Write-Host "HAVRE Stage 10 stopped cleanly."
