[CmdletBinding()]
param(
    [ValidateSet(
        "qwen3-14b-q4-k-m.json",
        "qwen3-6-35b-a3b-q4-k-m.json"
    )]
    [string]$ModelManifestName = "qwen3-14b-q4-k-m.json",
    [ValidateRange(1, 120)]
    [int]$WaitSeconds = 15
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-TextSha256 {
    param([Parameter(Mandatory = $true)][string]$Text)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
        return (($algorithm.ComputeHash($bytes) | ForEach-Object ToString x2) -join '')
    }
    finally {
        $algorithm.Dispose()
    }
}

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$ManifestPath = Join-Path $ProjectRoot "mlsys\serving\manifests\$ModelManifestName"
if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    throw "Candidate manifest is missing"
}
$manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
$CandidateRoot = [IO.Path]::GetFullPath((Join-Path $ProjectRoot ".runtime\model-candidates\$($manifest.manifest_id)"))
$AllowedRoot = [IO.Path]::GetFullPath((Join-Path $ProjectRoot ".runtime\model-candidates"))
if (-not $CandidateRoot.StartsWith($AllowedRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "Candidate runtime escaped .runtime/model-candidates"
}
$PidPath = Join-Path $CandidateRoot "run\llama-server.pid"
$StatePath = Join-Path $CandidateRoot "run\candidate-runtime-state.json"
if (-not (Test-Path -LiteralPath $PidPath -PathType Leaf)) {
    Write-Host "No candidate llama-server PID file exists; nothing to stop."
    return
}
if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
    throw "Candidate runtime state is missing; refusing to stop an unverified process"
}
$state = Get-Content -Raw -LiteralPath $StatePath | ConvertFrom-Json
if ([int]$state.schema_version -ne 1 -or [string]$state.manifest_id -ne [string]$manifest.manifest_id) {
    throw "Candidate runtime state does not match the selected manifest"
}
$pidValue = 0
if (-not [int]::TryParse((Get-Content -Raw -LiteralPath $PidPath).Trim(), [ref]$pidValue)) {
    throw "Candidate PID file is invalid; refusing to stop any process"
}
if ($pidValue -ne [int]$state.server_pid) {
    throw "Candidate PID does not match runtime state"
}
$process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
if ($null -eq $process) {
    Remove-Item -LiteralPath $PidPath -Force
    Remove-Item -LiteralPath $StatePath -Force
    Write-Host "Removed stale candidate runtime state; no process was running."
    return
}
if (
    [string]::IsNullOrWhiteSpace($process.Path) -or
    -not [IO.Path]::GetFullPath($process.Path).Equals([IO.Path]::GetFullPath([string]$state.server_path), [StringComparison]::OrdinalIgnoreCase)
) {
    throw "Candidate PID executable path mismatch; refusing to stop it"
}
$startedAt = ([DateTimeOffset]$state.process_started_at).ToUniversalTime()
$actualStartedAt = ([DateTimeOffset]$process.StartTime).ToUniversalTime()
if ([Math]::Abs(($actualStartedAt - $startedAt).TotalSeconds) -gt 1) {
    throw "Candidate PID start time mismatch; refusing to stop it"
}
$commandLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $pidValue").CommandLine
if ([string]::IsNullOrWhiteSpace($commandLine)) {
    throw "Candidate command line is unavailable; refusing to stop it"
}
$commandHash = "sha256:$(Get-TextSha256 $commandLine)"
if ($commandHash -ne [string]$state.command_line_sha256) {
    throw "Candidate command line hash mismatch; refusing to stop it"
}
Stop-Process -Id $pidValue -ErrorAction Stop
$deadline = [DateTimeOffset]::UtcNow.AddSeconds($WaitSeconds)
while ([DateTimeOffset]::UtcNow -lt $deadline) {
    if ($null -eq (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) {
        Remove-Item -LiteralPath $PidPath -Force
        Remove-Item -LiteralPath $StatePath -Force
        Write-Host "Stopped verified candidate llama-server PID $pidValue"
        return
    }
    Start-Sleep -Milliseconds 200
}
throw "Verified candidate llama-server PID $pidValue did not exit within $WaitSeconds seconds"
