[CmdletBinding()]
param(
    [ValidateRange(1, 120)]
    [int]$WaitSeconds = 15
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$RuntimeRoot = Join-Path $ProjectRoot ".runtime\stage3"
$StatePath = Join-Path $RuntimeRoot "runtime-state.json"
$PidPath = Join-Path $RuntimeRoot "run\llama-server.pid"
$AttestationPath = Join-Path $RuntimeRoot "run\runtime-attestation.json"
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Resolve-RuntimeChild {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    if ([IO.Path]::IsPathRooted($RelativePath)) {
        throw "Runtime state must contain relative paths only"
    }
    $candidate = [IO.Path]::GetFullPath((Join-Path $RuntimeRoot $RelativePath))
    $runtimePrefix = $RuntimeRoot.TrimEnd('\') + '\'
    if (-not $candidate.StartsWith($runtimePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Runtime state path escaped .runtime/stage3"
    }
    return $candidate
}

if (-not (Test-Path -LiteralPath $PidPath -PathType Leaf)) {
    Write-Host "No Stage 3 llama-server PID file exists; nothing to stop."
    return
}
if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
    throw "Runtime state is missing; refusing to stop a process from an unverified PID file"
}
if (
    -not (Test-Path -LiteralPath $AttestationPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $PythonPath -PathType Leaf)
) {
    throw "Runtime attestation is missing; refusing to stop an unverified process"
}
$verifiedJson = & $PythonPath -m services.api.cli attest-runtime
if ($LASTEXITCODE -ne 0) {
    throw "Active runtime attestation failed; refusing to stop any process"
}
$verifiedAttestation = [string]::Join("`n", [string[]]$verifiedJson) | ConvertFrom-Json
$state = Get-Content -Raw -LiteralPath $StatePath | ConvertFrom-Json
$expectedServerPath = Resolve-RuntimeChild ([string]$state.server_executable_relative_path)

$pidText = (Get-Content -Raw -LiteralPath $PidPath).Trim()
$serverPid = 0
if (-not [int]::TryParse($pidText, [ref]$serverPid)) {
    throw "Stage 3 PID file is invalid; refusing to stop any process"
}
if ($serverPid -ne [int]$verifiedAttestation.server_pid) {
    throw "Stage 3 PID does not match the active runtime attestation"
}
$process = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
if ($null -eq $process) {
    Remove-Item -LiteralPath $PidPath -Force
    Remove-Item -LiteralPath $AttestationPath -Force -ErrorAction SilentlyContinue
    Write-Host "Removed stale Stage 3 PID file; no process was running."
    return
}

$actualProcessPath = $process.Path
if ([string]::IsNullOrWhiteSpace($actualProcessPath)) {
    throw "Cannot verify PID $serverPid executable path; refusing to stop it"
}
if (
    -not [IO.Path]::GetFullPath($actualProcessPath).Equals(
        [IO.Path]::GetFullPath($expectedServerPath),
        [StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "PID $serverPid is not the verified Stage 3 llama-server; refusing to stop it"
}

Stop-Process -Id $serverPid -ErrorAction Stop
$deadline = [DateTimeOffset]::UtcNow.AddSeconds($WaitSeconds)
while ([DateTimeOffset]::UtcNow -lt $deadline) {
    if ($null -eq (Get-Process -Id $serverPid -ErrorAction SilentlyContinue)) {
        Remove-Item -LiteralPath $PidPath -Force
        Remove-Item -LiteralPath $AttestationPath -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped verified Stage 3 llama-server PID $serverPid"
        return
    }
    Start-Sleep -Milliseconds 200
}
throw "Verified Stage 3 llama-server PID $serverPid did not exit within $WaitSeconds seconds"
