[CmdletBinding()]
param(
    [ValidateSet(
        "qwen3-14b-q4-k-m.json",
        "qwen3-6-35b-a3b-q4-k-m.json"
    )]
    [string]$ModelManifestName = "qwen3-14b-q4-k-m.json",
    [ValidateRange(1, 900)]
    [int]$ReadyTimeoutSeconds = 300
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$processPathValue = $env:Path
[Environment]::SetEnvironmentVariable("PATH", $null, "Process")
[Environment]::SetEnvironmentVariable("Path", $processPathValue, "Process")

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$ManifestRoot = Join-Path $ProjectRoot "mlsys\serving\manifests"
$EngineManifestPath = Join-Path $ManifestRoot "llama-cpp-b10405-win-cuda-12.4-x64.json"
$ModelManifestPath = Join-Path $ManifestRoot $ModelManifestName
$Stage3Root = [IO.Path]::GetFullPath((Join-Path $ProjectRoot ".runtime\stage3"))
$Stage3StatePath = Join-Path $Stage3Root "runtime-state.json"
$DailyPidPath = Join-Path $Stage3Root "run\llama-server.pid"

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)
    if (-not (Test-Path -LiteralPath $LiteralPath -PathType Leaf)) {
        throw "Required local candidate file is missing: $LiteralPath"
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

function Assert-PinnedFile {
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath,
        [Parameter(Mandatory = $true)][long]$ExpectedSizeBytes,
        [Parameter(Mandatory = $true)][string]$ExpectedQualifiedSha256
    )
    if (-not (Test-Path -LiteralPath $LiteralPath -PathType Leaf)) {
        throw "Pinned candidate artifact is missing: $LiteralPath"
    }
    if ((Get-Item -LiteralPath $LiteralPath).Length -ne $ExpectedSizeBytes) {
        throw "Pinned candidate artifact size mismatch: $LiteralPath"
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $LiteralPath).Hash.ToLowerInvariant()
    if ($actual -ne (Get-UnqualifiedSha256 $ExpectedQualifiedSha256)) {
        throw "Pinned candidate artifact SHA-256 mismatch: $LiteralPath"
    }
}

function Resolve-Child {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$RelativePath
    )
    if ([IO.Path]::IsPathRooted($RelativePath)) {
        throw "Runtime state must contain relative paths only"
    }
    $candidate = [IO.Path]::GetFullPath((Join-Path $Root $RelativePath))
    if (-not $candidate.StartsWith($Root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Runtime state path escaped its verified root"
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
$stage3State = Read-JsonFile $Stage3StatePath
if (
    [string]$modelManifest.artifact_kind -ne "model" -or
    [string]$modelManifest.lifecycle_status -ne "candidate" -or
    -not [bool]$modelManifest.immutable -or
    [string]$modelManifest.serving_profile.host -ne "127.0.0.1" -or
    [bool]$modelManifest.serving_profile.request_logging -or
    [bool]$modelManifest.serving_profile.web_ui
) {
    throw "Candidate manifest violates the isolated local evaluation boundary"
}
if ([string]$stage3State.engine_manifest_id -ne [string]$engineManifest.manifest_id) {
    throw "Prepared Stage 3 serving engine does not match the pinned engine manifest"
}
$engineManifestHash = "sha256:$((Get-FileHash -Algorithm SHA256 -LiteralPath $EngineManifestPath).Hash.ToLowerInvariant())"
if ([string]$stage3State.engine_manifest_sha256 -ne $engineManifestHash) {
    throw "Serving engine manifest changed after verified setup"
}

$serverPath = Resolve-Child -Root $Stage3Root -RelativePath ([string]$stage3State.server_executable_relative_path)
if (-not (Test-Path -LiteralPath $serverPath -PathType Leaf)) {
    throw "Verified llama-server executable is missing"
}
$serverHash = "sha256:$((Get-FileHash -Algorithm SHA256 -LiteralPath $serverPath).Hash.ToLowerInvariant())"
if ($serverHash -ne [string]$stage3State.server_executable_sha256) {
    throw "llama-server executable changed after verified extraction"
}

$CandidateRoot = [IO.Path]::GetFullPath((Join-Path $ProjectRoot ".runtime\model-candidates\$($modelManifest.manifest_id)"))
$AllowedCandidateRoot = [IO.Path]::GetFullPath((Join-Path $ProjectRoot ".runtime\model-candidates"))
if (-not $CandidateRoot.StartsWith($AllowedCandidateRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "Candidate runtime escaped .runtime/model-candidates"
}
$modelPath = Join-Path $CandidateRoot ([string]$modelManifest.artifact.filename)
Assert-PinnedFile `
    -LiteralPath $modelPath `
    -ExpectedSizeBytes ([long]$modelManifest.artifact.size_bytes) `
    -ExpectedQualifiedSha256 ([string]$modelManifest.artifact.sha256)

if (Test-Path -LiteralPath $DailyPidPath -PathType Leaf) {
    $dailyPidValue = 0
    if ([int]::TryParse((Get-Content -Raw -LiteralPath $DailyPidPath).Trim(), [ref]$dailyPidValue)) {
        if ($null -ne (Get-Process -Id $dailyPidValue -ErrorAction SilentlyContinue)) {
            throw "Daily Stage 3 model is still running; use the governed desktop stop before candidate evaluation"
        }
    }
}

$RunRoot = Join-Path $CandidateRoot "run"
$LogRoot = Join-Path $CandidateRoot "logs"
$PidPath = Join-Path $RunRoot "llama-server.pid"
$RuntimeStatePath = Join-Path $RunRoot "candidate-runtime-state.json"
New-Item -ItemType Directory -Path $RunRoot -Force | Out-Null
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
if (Test-Path -LiteralPath $PidPath -PathType Leaf) {
    $existingPid = 0
    if ([int]::TryParse((Get-Content -Raw -LiteralPath $PidPath).Trim(), [ref]$existingPid)) {
        if ($null -ne (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
            throw "Candidate llama-server is already running with PID $existingPid"
        }
    }
    Remove-Item -LiteralPath $PidPath -Force
    Remove-Item -LiteralPath $RuntimeStatePath -Force -ErrorAction SilentlyContinue
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
if (
    $profile.PSObject.Properties.Name -contains "cpu_moe" -and
    [bool]$profile.cpu_moe
) {
    $arguments += "--cpu-moe"
}
if ($profile.PSObject.Properties.Name -contains "kv_cache_type_k") {
    $arguments += @("--cache-type-k", [string]$profile.kv_cache_type_k)
}
if ($profile.PSObject.Properties.Name -contains "kv_cache_type_v") {
    $arguments += @("--cache-type-v", [string]$profile.kv_cache_type_v)
}
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
        $stderrTail = if (Test-Path -LiteralPath $stderrPath) {
            (Get-Content -LiteralPath $stderrPath -Tail 30) -join "`n"
        } else { "" }
        $exitCode = $process.ExitCode
        Remove-Item -LiteralPath $PidPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $RuntimeStatePath -Force -ErrorAction SilentlyContinue
        throw "Candidate llama-server exited during startup with code ${exitCode}: $stderrTail"
    }
    try {
        $health = Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl$([string]$engineManifest.api.health_path)" -TimeoutSec 2
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
    Remove-Item -LiteralPath $PidPath -Force -ErrorAction SilentlyContinue
    throw "Candidate llama-server did not become healthy within $ReadyTimeoutSeconds seconds"
}

try {
    $metrics = Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl$([string]$engineManifest.api.metrics_path)" -TimeoutSec 10
    if ($metrics.StatusCode -ne 200) {
        throw "Candidate metrics endpoint returned HTTP $($metrics.StatusCode)"
    }
    $probeBody = @{
        model = [string]$modelManifest.alias
        messages = @(@{role = "user"; content = "Reply with OK."})
        max_tokens = 2
        temperature = 0
        stream = $true
        chat_template_kwargs = @{enable_thinking = $false}
    } | ConvertTo-Json -Depth 6
    $probePath = Join-Path $RunRoot "sse-startup-probe.json"
    [IO.File]::WriteAllText($probePath, $probeBody, [Text.Encoding]::UTF8)
    try {
        $probeLines = & (Join-Path $env:SystemRoot "System32\curl.exe") `
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
    if ($probeExitCode -ne 0 -or $probeOutput -notmatch '(?im)^Content-Type:\s*text/event-stream' -or $probeOutput -notmatch 'data:\s*\[DONE\]') {
        throw "Candidate streaming probe failed"
    }
    $process.Refresh()
    $commandLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($process.Id)").CommandLine
    if ([string]::IsNullOrWhiteSpace($commandLine) -or $commandLine -notlike "*$modelPath*") {
        throw "Candidate process command line is not bound to the verified model"
    }
    $state = [ordered]@{
        schema_version = 1
        runtime_kind = "isolated-local-model-candidate"
        manifest_id = [string]$modelManifest.manifest_id
        manifest_sha256 = "sha256:$((Get-FileHash -Algorithm SHA256 -LiteralPath $ModelManifestPath).Hash.ToLowerInvariant())"
        model_path = $modelPath
        model_sha256 = [string]$modelManifest.artifact.sha256
        server_path = $serverPath
        server_sha256 = $serverHash
        server_pid = $process.Id
        process_started_at = $process.StartTime.ToUniversalTime().ToString("o")
        command_line_sha256 = "sha256:$(Get-TextSha256 $commandLine)"
        base_url = $baseUrl
        alias = [string]$modelManifest.alias
        candidate_only = $true
        promotion_authorized = $false
        deployment_authorized = $false
        request_logging_disabled = $true
        web_ui_disabled = $true
        verified_at = [DateTimeOffset]::UtcNow.ToString("o")
    }
    $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $RuntimeStatePath -Encoding utf8
}
catch {
    Stop-StartedProcess $process
    Remove-Item -LiteralPath $PidPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $RuntimeStatePath -Force -ErrorAction SilentlyContinue
    throw
}

Write-Host "Candidate llama-server is healthy on $baseUrl (PID $($process.Id))"
Write-Host "Exact model: $($modelManifest.manifest_id)"
Write-Host "Request logging and Web UI are disabled."
