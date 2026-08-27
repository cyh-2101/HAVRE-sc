[CmdletBinding()]
param(
    [ValidateRange(1, 900)]
    [int]$ReadyTimeoutSeconds = 180,
    [switch]$SkipSseProbe
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Some automation hosts expose both PATH and Path in the inherited environment.
# Windows PowerShell's Start-Process treats them as duplicate dictionary keys.
$processPathValue = $env:Path
[Environment]::SetEnvironmentVariable("PATH", $null, "Process")
[Environment]::SetEnvironmentVariable("Path", $processPathValue, "Process")

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$ManifestRoot = Join-Path $ProjectRoot "mlsys\serving\manifests"
$RuntimeRoot = Join-Path $ProjectRoot ".runtime\stage3"
$StatePath = Join-Path $RuntimeRoot "runtime-state.json"
$RunRoot = Join-Path $RuntimeRoot "run"
$LogRoot = Join-Path $RuntimeRoot "logs"
$PidPath = Join-Path $RunRoot "llama-server.pid"
$EngineManifestPath = Join-Path $ManifestRoot "llama-cpp-b10405-win-cuda-12.4-x64.json"
$ModelManifestPath = Join-Path $ManifestRoot "qwen3-8b-q4-k-m.json"
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$RuntimeAttestationPath = Join-Path $RunRoot "runtime-attestation.json"

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)

    if (-not (Test-Path -LiteralPath $LiteralPath -PathType Leaf)) {
        throw "Required Stage 3 file is missing: $LiteralPath"
    }
    return Get-Content -Raw -LiteralPath $LiteralPath | ConvertFrom-Json
}

function Get-UnqualifiedSha256 {
    param([Parameter(Mandatory = $true)][string]$QualifiedHash)

    if ($QualifiedHash -notmatch '^sha256:[0-9a-f]{64}$') {
        throw "Invalid pinned SHA-256 value: $QualifiedHash"
    }
    return $QualifiedHash.Substring(7)
}

function Assert-PinnedFile {
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath,
        [Parameter(Mandatory = $true)][long]$ExpectedSizeBytes,
        [Parameter(Mandatory = $true)][string]$ExpectedQualifiedSha256
    )

    if (-not (Test-Path -LiteralPath $LiteralPath -PathType Leaf)) {
        throw "Pinned artifact is missing: $LiteralPath"
    }
    if ((Get-Item -LiteralPath $LiteralPath).Length -ne $ExpectedSizeBytes) {
        throw "Pinned artifact size mismatch for $LiteralPath"
    }
    $expected = Get-UnqualifiedSha256 $ExpectedQualifiedSha256
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $LiteralPath).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        throw "Pinned artifact SHA-256 mismatch for $LiteralPath"
    }
}

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

function Stop-StartedProcess {
    param([Parameter(Mandatory = $true)]$Process)

    if (-not $Process.HasExited) {
        Stop-Process -Id $Process.Id -ErrorAction SilentlyContinue
        $Process.WaitForExit(10000) | Out-Null
    }
}

$engineManifest = Read-JsonFile $EngineManifestPath
$modelManifest = Read-JsonFile $ModelManifestPath
$state = Read-JsonFile $StatePath
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Pinned HAVRE Python environment is missing: $PythonPath"
}
if (
    [string]$state.engine_manifest_id -ne [string]$engineManifest.manifest_id -or
    [string]$state.model_manifest_id -ne [string]$modelManifest.manifest_id
) {
    throw "Runtime state does not match the pinned manifests; run setup again"
}

$engineManifestHash = "sha256:$((Get-FileHash -Algorithm SHA256 -LiteralPath $EngineManifestPath).Hash.ToLowerInvariant())"
$modelManifestHash = "sha256:$((Get-FileHash -Algorithm SHA256 -LiteralPath $ModelManifestPath).Hash.ToLowerInvariant())"
if (
    [string]$state.engine_manifest_sha256 -ne $engineManifestHash -or
    [string]$state.model_manifest_sha256 -ne $modelManifestHash
) {
    throw "Pinned manifest bytes changed after runtime setup; run setup again"
}

foreach ($archive in $state.verified_archives) {
    $archivePath = Resolve-RuntimeChild ([string]$archive.relative_path)
    Assert-PinnedFile `
        -LiteralPath $archivePath `
        -ExpectedSizeBytes ([long]$archive.size_bytes) `
        -ExpectedQualifiedSha256 ([string]$archive.sha256)
}

$serverPath = Resolve-RuntimeChild ([string]$state.server_executable_relative_path)
if (-not (Test-Path -LiteralPath $serverPath -PathType Leaf)) {
    throw "Verified llama-server executable is missing; run setup again"
}
$expectedServerHash = Get-UnqualifiedSha256 ([string]$state.server_executable_sha256)
$actualServerHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $serverPath).Hash.ToLowerInvariant()
if ($actualServerHash -ne $expectedServerHash) {
    throw "llama-server executable changed after verified extraction"
}

$modelPath = Resolve-RuntimeChild ([string]$state.model_relative_path)
Assert-PinnedFile `
    -LiteralPath $modelPath `
    -ExpectedSizeBytes ([long]$modelManifest.artifact.size_bytes) `
    -ExpectedQualifiedSha256 ([string]$modelManifest.artifact.sha256)

if ([string]$modelManifest.serving_profile.host -ne "127.0.0.1") {
    throw "Pinned local-serving profile must bind only to 127.0.0.1"
}
if ([bool]$modelManifest.serving_profile.request_logging) {
    throw "Pinned local-serving profile must disable request logging"
}

New-Item -ItemType Directory -Path $RunRoot -Force | Out-Null
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
if (Test-Path -LiteralPath $PidPath -PathType Leaf) {
    $existingPidText = (Get-Content -Raw -LiteralPath $PidPath).Trim()
    $existingPid = 0
    if ([int]::TryParse($existingPidText, [ref]$existingPid)) {
        $existing = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($null -ne $existing) {
            throw "Stage 3 llama-server is already running with PID $existingPid"
        }
    }
}

$profile = $modelManifest.serving_profile
$arguments = @(
    "--model", $modelPath,
    "--alias", [string]$modelManifest.alias,
    "--host", "127.0.0.1",
    "--port", [string]$profile.port,
    "--ctx-size", [string]$profile.context_tokens,
    "--parallel", [string]$profile.parallel_slots,
    "--n-gpu-layers", [string]$profile.gpu_layers_cli_value,
    "--flash-attn", "on",
    "--jinja",
    "--metrics",
    "--log-disable",
    "--no-webui"
)
$timestamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$stdoutPath = Join-Path $LogRoot "llama-server-$timestamp.stdout.log"
$stderrPath = Join-Path $LogRoot "llama-server-$timestamp.stderr.log"
$process = Start-Process `
    -FilePath $serverPath `
    -ArgumentList $arguments `
    -WorkingDirectory (Split-Path -Parent $serverPath) `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -PassThru
$process.Id | Set-Content -LiteralPath $PidPath -Encoding ascii

$baseUrl = "http://127.0.0.1:$([int]$profile.port)"
$deadline = [DateTimeOffset]::UtcNow.AddSeconds($ReadyTimeoutSeconds)
$healthy = $false
while ([DateTimeOffset]::UtcNow -lt $deadline) {
    if ($process.HasExited) {
        throw "llama-server exited during startup with code $($process.ExitCode)"
    }
    try {
        $health = Invoke-WebRequest `
            -UseBasicParsing `
            -Uri "$baseUrl$([string]$engineManifest.api.health_path)" `
            -TimeoutSec 2
        if ($health.StatusCode -eq 200) {
            $healthy = $true
            break
        }
    }
    catch {
        Start-Sleep -Milliseconds 500
    }
}
if (-not $healthy) {
    Stop-StartedProcess $process
    throw "llama-server did not become healthy within $ReadyTimeoutSeconds seconds"
}

try {
    $metrics = Invoke-WebRequest `
        -UseBasicParsing `
        -Uri "$baseUrl$([string]$engineManifest.api.metrics_path)" `
        -TimeoutSec 10
    if ($metrics.StatusCode -ne 200) {
        throw "Metrics endpoint returned HTTP $($metrics.StatusCode)"
    }

    if (-not $SkipSseProbe) {
        $probeBody = @{
            model = [string]$modelManifest.alias
            messages = @(@{ role = "user"; content = "Reply with OK." })
            max_tokens = 2
            temperature = 0
            stream = $true
            chat_template_kwargs = @{ enable_thinking = $false }
        } | ConvertTo-Json -Depth 6
        $curlPath = Join-Path $env:SystemRoot "System32\curl.exe"
        if (-not (Test-Path -LiteralPath $curlPath -PathType Leaf)) {
            throw "Windows curl.exe is required for the bounded SSE startup probe"
        }
        $probePath = Join-Path $RunRoot "sse-startup-probe.json"
        [IO.File]::WriteAllText($probePath, $probeBody, [Text.Encoding]::UTF8)
        try {
            $probeLines = & $curlPath `
                --silent --show-error --include --no-buffer --max-time 60 `
                --header "Accept: text/event-stream" `
                --header "Content-Type: application/json" `
                --data-binary "@$probePath" `
                "$baseUrl$([string]$engineManifest.api.chat_completions_path)" 2>&1
            $probeExitCode = $LASTEXITCODE
            $probeOutput = [string]::Join("`n", [string[]]$probeLines)
        }
        finally {
            Remove-Item -LiteralPath $probePath -Force -ErrorAction SilentlyContinue
        }
        if ($probeExitCode -ne 0) {
            throw "Streaming probe failed with curl exit code $probeExitCode"
        }
        if ($probeOutput -notmatch '(?im)^Content-Type:\s*text/event-stream') {
            throw "Streaming probe did not return text/event-stream"
        }
        if ($probeOutput -notmatch '(?m)^data:\s*\{') {
            throw "Streaming probe did not contain an SSE data frame"
        }
        if ($probeOutput -notmatch 'data:\s*\[DONE\]') {
            throw "Streaming probe did not contain the terminal SSE frame"
        }
    }

    $attestationJson = & $PythonPath -m services.api.cli attest-runtime
    if ($LASTEXITCODE -ne 0) {
        throw "Process-bound Stage 3 runtime attestation failed"
    }
    $runtimeAttestation = [string]::Join("`n", [string[]]$attestationJson) | ConvertFrom-Json
    if (
        [int]$runtimeAttestation.server_pid -ne $process.Id -or
        [string]$runtimeAttestation.loaded_model_alias -ne [string]$modelManifest.alias
    ) {
        throw "Runtime attestation is not bound to the process that was just started"
    }
}
catch {
    Stop-StartedProcess $process
    Remove-Item -LiteralPath $RuntimeAttestationPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $PidPath -Force -ErrorAction SilentlyContinue
    throw
}

$startupAttestation = [ordered]@{
    schema_version = 1
    server_pid = $process.Id
    base_url = $baseUrl
    health_verified = $true
    metrics_verified = $true
    sse_verified = (-not $SkipSseProbe)
    request_logging_disabled = $true
    runtime_attestation_id = [string]$runtimeAttestation.attestation_id
    runtime_attestation_hash = [string]$runtimeAttestation.attestation_hash
    process_started_at = [string]$runtimeAttestation.process_started_at
    verified_at = [DateTimeOffset]::UtcNow.ToString("o")
}
$startupAttestation | ConvertTo-Json -Depth 4 | Set-Content `
    -LiteralPath (Join-Path $RunRoot "startup-attestation.json") `
    -Encoding utf8

Write-Host "Stage 3 llama-server is healthy on $baseUrl (PID $($process.Id))"
Write-Host "Metrics: $baseUrl$([string]$engineManifest.api.metrics_path)"
Write-Host "Request logging is disabled; operational logs remain under ignored .runtime/stage3."
