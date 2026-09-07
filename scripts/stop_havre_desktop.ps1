[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$StatePath = Join-Path $ProjectRoot ".runtime\desktop\state.json"
$SecretRoot = Join-Path $ProjectRoot ".runtime\desktop\secrets"

function Assert-HavreOwnedProcess {
    param(
        [int]$ProcessId,
        [string]$ExpectedExecutable,
        [object]$ExpectedStartedAt,
        [string]$ExpectedCommandMarker,
        [string]$Label
    )
    $candidate = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $candidate) { return $null }
    $expectedPath = [IO.Path]::GetFullPath($ExpectedExecutable)
    if (-not $candidate.Path.Equals($expectedPath,[StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label PID no longer names the recorded executable"
    }
    $observedStartedAt = $candidate.StartTime.ToUniversalTime()
    $recordedStartedAt = if ($ExpectedStartedAt -is [DateTime]) {
        ([DateTime]$ExpectedStartedAt).ToUniversalTime()
    } else {
        [DateTimeOffset]::Parse([string]$ExpectedStartedAt).UtcDateTime
    }
    if ([Math]::Abs(($observedStartedAt-$recordedStartedAt).TotalSeconds) -gt 1) {
        throw "$Label PID start time no longer matches the recorded process"
    }
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId"
    if ($null -eq $cim -or [string]$cim.CommandLine -notlike "*$ExpectedCommandMarker*") {
        throw "$Label command line no longer matches the recorded HAVRE role"
    }
    return $candidate
}
if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
    throw "HAVRE desktop state is missing; refusing to stop an unverified process"
}
$state = Get-Content -Raw -LiteralPath $StatePath | ConvertFrom-Json
if ([int]$state.schema_version -notin @(2,3) -or -not [bool]$state.candidate_only) {
    throw "HAVRE desktop state is invalid"
}
if ($null -ne $state.worker_pid) {
    $worker = Assert-HavreOwnedProcess -ProcessId ([int]$state.worker_pid) `
        -ExpectedExecutable ([string]$state.api_executable) `
        -ExpectedStartedAt $state.worker_started_at `
        -ExpectedCommandMarker ([string]$state.worker_command_marker) -Label "Desktop worker"
    if ($null -ne $worker) {
        Stop-Process -Id $worker.Id -ErrorAction Stop
        $worker.WaitForExit(30000) | Out-Null
    }
}
$process = Assert-HavreOwnedProcess -ProcessId ([int]$state.api_pid) `
    -ExpectedExecutable ([string]$state.api_executable) `
    -ExpectedStartedAt $state.api_started_at `
    -ExpectedCommandMarker ([string]$state.api_command_marker) -Label "Desktop API"
if ($null -ne $process) {
    Stop-Process -Id $process.Id -ErrorAction Stop
    $process.WaitForExit(30000) | Out-Null
}
Remove-Item -LiteralPath $StatePath -Force
& (Join-Path $PSScriptRoot "stop_havre_candidate_local.ps1")
foreach ($name in @("database-url.secret","owner-api-token.secret","desktop-bootstrap-token.secret")) {
    $path = Join-Path $SecretRoot $name
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Remove-Item -LiteralPath $path -Force
    }
}
Write-Host "HAVRE desktop stopped cleanly."
