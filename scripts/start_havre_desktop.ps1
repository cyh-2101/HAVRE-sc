[CmdletBinding()]
param([switch]$NoBrowser, [switch]$RestartApp)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$RuntimeRoot = Join-Path $ProjectRoot ".runtime\desktop"
$ConfigRoot = Join-Path $RuntimeRoot "config"
$StatePath = Join-Path $RuntimeRoot "state.json"
$LogRoot = Join-Path $RuntimeRoot "logs"
$SecretRoot = Join-Path $RuntimeRoot "secrets"
$DatabaseSecret = Join-Path $SecretRoot "database-url.secret"
$OwnerTokenSecret = Join-Path $SecretRoot "owner-api-token.secret"
$BootstrapSecret = Join-Path $SecretRoot "desktop-bootstrap-token.secret"
$BootstrapPage = Join-Path $SecretRoot "desktop-bootstrap.html"
$WebPushConfig = Join-Path $SecretRoot "web-push-config.json"
$VapidPrivate = Join-Path $SecretRoot "vapid-private.dpapi"
$TailscaleOrigin = Join-Path $RuntimeRoot "tailscale-origin.txt"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$OwnerExampleSource = Join-Path $ProjectRoot (
    "var\stage9a\evaluation\owner-alignment-set-70-v1\OWNER_ALIGNMENT_SET_70_v1.json"
)
$OwnerExampleBankPath = Join-Path $ConfigRoot "owner-example-bank-oa70-all70-v2.json"
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

function Set-HavreOwnerOnlyPath {
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path -Force
    if (
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "HAVRE protected path cannot be a reparse point: $Path"
    }
    $acl = Get-Acl -LiteralPath $Path
    $ownerIdentity = New-Object System.Security.Principal.NTAccount($identity)
    if (-not $acl.Owner.Equals($identity,[StringComparison]::OrdinalIgnoreCase)) {
        $acl.SetOwner($ownerIdentity)
    }
    $acl.SetAccessRuleProtection($true,$false)
    foreach ($existingRule in @($acl.Access)) {
        [void]$acl.RemoveAccessRuleSpecific($existingRule)
    }
    $inheritanceFlags = if ($item.PSIsContainer) {
        "ContainerInherit,ObjectInherit"
    } else {
        "None"
    }
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $identity,"FullControl",$inheritanceFlags,"None","Allow"
    )
    [void]$acl.AddAccessRule($rule)
    [System.IO.FileSystemAclExtensions]::SetAccessControl($item,$acl)
    $verified = Get-Acl -LiteralPath $Path
    $ownerRuleValid = $false
    if ($verified.Access.Count -eq 1) {
        $verifiedRule = $verified.Access[0]
        $verifiedRights = $verifiedRule.FileSystemRights -band [Security.AccessControl.FileSystemRights]::FullControl
        $ownerRuleValid = (
            $verifiedRule.IdentityReference.Value.Equals(
            $identity,[StringComparison]::OrdinalIgnoreCase
            ) -and $verifiedRule.AccessControlType -eq "Allow" -and
            $verifiedRights -eq [Security.AccessControl.FileSystemRights]::FullControl
        )
    }
    $ownerValid = $verified.Owner.Equals(
        $identity,[StringComparison]::OrdinalIgnoreCase
    )
    if (
        -not $ownerValid -or -not $verified.AreAccessRulesProtected -or -not $ownerRuleValid
    ) {
        throw "HAVRE protected path is not owner-only: $Path"
    }
}
$BaseUrl = "http://127.0.0.1:8765"
$ExpectedProviderId = "openai-codex-chatgpt"
$ExpectedModelVersion = "gpt-5.6-sol"
$ExpectedLocalProviderId = "self-hosted-openai-compatible"
$ExpectedLocalModelVersion = "model-qwen3-8b-gguf-q4-k-m-7c41481f"
$ExpectedLocalModelHash = "sha256:d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785"
$ExpectedLocalModelManifest = Join-Path $ProjectRoot (
    "mlsys\serving\manifests\qwen3-8b-q4-k-m.json"
)
$ExpectedLocalEngineManifest = Join-Path $ProjectRoot (
    "mlsys\serving\manifests\llama-cpp-b10405-win-cuda-12.4-x64.json"
)
$CodexCommand = Get-Command codex.exe -ErrorAction SilentlyContinue
if ($null -eq $CodexCommand) {
    throw "Codex CLI is required for the default GPT-5.6-sol reply route"
}
$CodexPath = [IO.Path]::GetFullPath([string]$CodexCommand.Source)
$ExpectedCodexRoot = [IO.Path]::GetFullPath(
    (Join-Path $env:LOCALAPPDATA "OpenAI\Codex\bin")
)
if (
    -not $CodexPath.StartsWith(
        $ExpectedCodexRoot + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    ) -or -not (Test-Path -LiteralPath $CodexPath -PathType Leaf)
) {
    throw "Codex CLI must be the exact executable installed by the local Codex app"
}
$codexVersion = (& $CodexPath --version 2>&1 | Out-String).Trim()
if (
    $LASTEXITCODE -ne 0 -or
    $codexVersion -notmatch (
        '^codex-cli [0-9]+\.[0-9]+\.[0-9]+' +
        '(?:-[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?$'
    )
) {
    throw "Codex CLI version check failed"
}
$codexLogin = (& $CodexPath login status 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $codexLogin -notmatch '(?i)ChatGPT') {
    throw "Codex CLI is not logged in with ChatGPT"
}

function Assert-HavreOwnedProcess {
    param(
        [int]$ProcessId,
        [string]$ExpectedExecutable,
        [object]$ExpectedStartedAt,
        [string]$ExpectedCommandMarker,
        [string]$Label
    )
    $candidate = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $candidate) { throw "$Label process is not running" }
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

function Open-HavreDesktop {
    $bootstrap = [System.Net.WebUtility]::HtmlEncode(
        (Get-Content -Raw -LiteralPath $BootstrapSecret).Trim()
    )
    @"
<!doctype html><meta charset="utf-8"><title>Opening HAVRE</title>
<form id="bootstrap" method="post" action="$BaseUrl/v1/desktop/session">
  <input type="hidden" name="desktop_bootstrap" value="$bootstrap">
</form>
<script>document.getElementById('bootstrap').submit()</script>
"@ | Set-Content -LiteralPath $BootstrapPage -Encoding utf8
    Set-HavreOwnerOnlyPath -Path $BootstrapPage
    Start-Process $BootstrapPage
}

function Wait-HavreReady {
    param(
        [DateTimeOffset]$Deadline,
        [System.Diagnostics.Process]$ApiProcess
    )
    do {
        if ($null -ne $ApiProcess -and $ApiProcess.HasExited) {
            throw "HAVRE desktop API exited before readiness was proven"
        }
        try {
            $response = Invoke-WebRequest -UseBasicParsing `
                -Uri "$BaseUrl/health/ready" -TimeoutSec 3
            if ([int]$response.StatusCode -eq 200) {
                $payload = $response.Content | ConvertFrom-Json
                if ([string]$payload.status -eq "ready") {
                    return $payload
                }
            }
        } catch {}
        Start-Sleep -Milliseconds 500
    } until ([DateTimeOffset]::UtcNow -ge $Deadline)
    throw "HAVRE desktop /health/ready did not return HTTP 200 with status=ready"
}

New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
if (Test-Path -LiteralPath $StatePath) {
    $state = Get-Content -Raw -LiteralPath $StatePath | ConvertFrom-Json
    if ([int]$state.schema_version -ne 3) {
        throw "The existing HAVRE desktop predates retirement of Seed 9201; stop it cleanly before restart"
    }
    $process = Assert-HavreOwnedProcess -ProcessId ([int]$state.api_pid) `
        -ExpectedExecutable ([string]$state.api_executable) `
        -ExpectedStartedAt $state.api_started_at `
        -ExpectedCommandMarker ([string]$state.api_command_marker) -Label "Desktop API"
    $workerProcess = Assert-HavreOwnedProcess -ProcessId ([int]$state.worker_pid) `
        -ExpectedExecutable ([string]$state.api_executable) `
        -ExpectedStartedAt $state.worker_started_at `
        -ExpectedCommandMarker ([string]$state.worker_command_marker) -Label "Desktop worker"
    $version = Invoke-RestMethod -Uri "$BaseUrl/version" -TimeoutSec 10
    if (
        [string]$version.provider.provider_id -ne $ExpectedProviderId -or
        [string]$version.provider.model_version_id -ne $ExpectedModelVersion -or
        -not [string]::IsNullOrEmpty([string]$version.provider.active_adapter_version_id)
    ) {
        throw "Running desktop API does not match the default GPT-5.6-sol reply route"
    }
    $localVersion = $version.providers.PSObject.Properties[
        $ExpectedLocalProviderId
    ].Value
    if (
        $null -eq $localVersion -or
        [string]$localVersion.model_version_id -ne $ExpectedLocalModelVersion -or
        [string]$localVersion.model_artifact_hash -ne $ExpectedLocalModelHash -or
        -not [string]::IsNullOrEmpty(
            [string]$localVersion.active_adapter_version_id
        )
    ) {
        throw "Running desktop API does not match the unadapted Qwen3-8B privacy route"
    }
    [void](Wait-HavreReady `
        -Deadline ([DateTimeOffset]::UtcNow.AddSeconds(15)) -ApiProcess $process)
    if (-not (Test-Path -LiteralPath $BootstrapSecret -PathType Leaf)) {
        throw "Running desktop lacks its protected browser bootstrap; restart it cleanly"
    }
    if (-not $RestartApp) {
        if (-not $NoBrowser) { Open-HavreDesktop }
        Write-Host "HAVRE desktop is already ready at $BaseUrl/chat"
        return
    }
    # Recycle only the verified API/worker. Keep PostgreSQL, the exact base
    # model, paired devices and protected credentials unchanged.
    foreach ($secret in @($DatabaseSecret,$OwnerTokenSecret,$BootstrapSecret)) {
        if (-not (Test-Path -LiteralPath $secret -PathType Leaf)) {
            throw "Application restart requires existing protected credentials"
        }
    }
    Stop-Process -Id $workerProcess.Id -ErrorAction Stop
    [void]$workerProcess.WaitForExit(30000)
    Stop-Process -Id $process.Id -ErrorAction Stop
    [void]$process.WaitForExit(30000)
} elseif ($RestartApp) {
    throw "Application restart requires an existing verified desktop state"
}

if (-not $RestartApp) {
& (Join-Path $PSScriptRoot "start_havre_candidate_local.ps1") -BaseOnly
if ($LASTEXITCODE -ne 0) { throw "Local database/privacy runtime startup failed" }

$AdminDatabaseUrl = "postgresql://postgres@127.0.0.1:55432/havre_local_20260822"
New-Item -ItemType Directory -Path $SecretRoot -Force | Out-Null
Set-HavreOwnerOnlyPath -Path $SecretRoot
New-Item -ItemType Directory -Path $ConfigRoot -Force | Out-Null
Set-HavreOwnerOnlyPath -Path $ConfigRoot
& $Python -m scripts.build_owner_example_bank `
    --source $OwnerExampleSource --output $OwnerExampleBankPath `
    --owner-id "00000000-0000-7000-8000-000000000001"
if ($LASTEXITCODE -ne 0) { throw "Owner example bank derivation failed" }
Set-HavreOwnerOnlyPath -Path $OwnerExampleBankPath
try {
    & $Python -m scripts.prepare_havre_desktop `
        --admin-database-url $AdminDatabaseUrl --project-root $ProjectRoot `
        --secret-root $SecretRoot
    if ($LASTEXITCODE -ne 0) { throw "Desktop least-privilege provisioning failed" }
} catch {
    foreach ($name in @("database-url.secret","owner-api-token.secret","desktop-bootstrap-token.secret")) {
        Remove-Item -LiteralPath (Join-Path $SecretRoot $name) -Force -ErrorAction SilentlyContinue
    }
    throw
}
foreach ($child in @(Get-ChildItem -LiteralPath $SecretRoot -Force)) {
    if ($child.PSIsContainer) {
        throw "Desktop secret directory may contain files only"
    }
    Set-HavreOwnerOnlyPath -Path $child.FullName
}
}

$LaunchEnvironmentNames = @(
    "HAVRE_DATABASE_URL","HAVRE_DATABASE_URL_FILE",
    "HAVRE_OWNER_API_TOKEN","HAVRE_OWNER_API_TOKEN_FILE",
    "HAVRE_DESKTOP_BOOTSTRAP_TOKEN","HAVRE_DESKTOP_BOOTSTRAP_TOKEN_FILE",
    "HAVRE_PROVIDER_ID","HAVRE_SELF_HOSTED_BASE_URL","HAVRE_CODEX_CLI_PATH",
    "HAVRE_CODEX_REASONING_EFFORT","HAVRE_OWNER_EXAMPLE_BANK_PATH",
    "HAVRE_RELATIONAL_INITIATIVE_ENABLED",
    "HAVRE_SELF_HOSTED_MODEL_MANIFEST","HAVRE_SELF_HOSTED_ENGINE_MANIFEST",
    "HAVRE_SELF_HOSTED_ADAPTER_MANIFEST",
    "HAVRE_SELF_HOSTED_API_KEY","HAVRE_SELF_HOSTED_API_KEY_FILE",
    "HAVRE_RUNTIME_ADAPTER_VERSION","HAVRE_RUNTIME_ADAPTER_HASH",
    "HAVRE_CONTEXT_TOKEN_BUDGET","HAVRE_RESERVED_OUTPUT_TOKENS","HAVRE_LOCAL_RESERVED_OUTPUT_TOKENS","HAVRE_INFERENCE_TIMEOUT_MS",
    "HAVRE_WEB_PUSH_ENABLED","HAVRE_PUBLIC_BASE_URL",
    "HAVRE_WEB_PUSH_VAPID_PUBLIC_KEY","HAVRE_WEB_PUSH_VAPID_KEY_VERSION",
    "HAVRE_WEB_PUSH_VAPID_SUBJECT","HAVRE_WEB_PUSH_VAPID_PRIVATE_KEY",
    "HAVRE_WEB_PUSH_VAPID_PRIVATE_KEY_FILE",
    "HAVRE_WEB_PUSH_VAPID_PRIVATE_KEY_DPAPI_FILE",
    "HAVRE_TAILSCALE_CLI_PATH","HAVRE_MANUAL_STRONG_BRAIN_ENABLED",
    "DEEPSEEK_API_KEY","DEEPSEEK_API_KEY_FILE","HAVRE_MEMORY_ENCODER_ROOT"
)
$PreviousLaunchEnvironment = @{}
foreach ($name in $LaunchEnvironmentNames) {
    $PreviousLaunchEnvironment[$name] = [Environment]::GetEnvironmentVariable(
        $name,"Process"
    )
    Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
}
function Restore-HavreLaunchEnvironment {
    foreach ($name in $LaunchEnvironmentNames) {
        Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        if ($null -ne $PreviousLaunchEnvironment[$name]) {
            [Environment]::SetEnvironmentVariable(
                $name,$PreviousLaunchEnvironment[$name],"Process"
            )
        }
    }
}
$env:HAVRE_DATABASE_URL_FILE = $DatabaseSecret
$env:HAVRE_MEMORY_ENCODER_ROOT = Join-Path $ProjectRoot "var\models\memory-minilm-v1"
$env:HAVRE_OWNER_API_TOKEN_FILE = $OwnerTokenSecret
$env:HAVRE_DESKTOP_BOOTSTRAP_TOKEN_FILE = $BootstrapSecret
$env:HAVRE_PROVIDER_ID = $ExpectedProviderId
$env:HAVRE_CODEX_CLI_PATH = $CodexPath
$env:HAVRE_CODEX_REASONING_EFFORT = "medium"
$env:HAVRE_OWNER_EXAMPLE_BANK_PATH = $OwnerExampleBankPath
$env:HAVRE_RELATIONAL_INITIATIVE_ENABLED = "true"
$env:HAVRE_SELF_HOSTED_BASE_URL = "http://127.0.0.1:8080"
$env:HAVRE_SELF_HOSTED_MODEL_MANIFEST = $ExpectedLocalModelManifest
$env:HAVRE_SELF_HOSTED_ENGINE_MANIFEST = $ExpectedLocalEngineManifest
$env:HAVRE_CONTEXT_TOKEN_BUDGET = "16384"
$env:HAVRE_RESERVED_OUTPUT_TOKENS = "3072"
$env:HAVRE_LOCAL_RESERVED_OUTPUT_TOKENS = "1024"
$env:HAVRE_INFERENCE_TIMEOUT_MS = "300000"
try {
    if ((Test-Path -LiteralPath $WebPushConfig -PathType Leaf) -and
        (Test-Path -LiteralPath $VapidPrivate -PathType Leaf) -and
        (Test-Path -LiteralPath $TailscaleOrigin -PathType Leaf)) {
        Set-HavreOwnerOnlyPath -Path $TailscaleOrigin
        $push = Get-Content -Raw -LiteralPath $WebPushConfig | ConvertFrom-Json
        $origin = (Get-Content -Raw -LiteralPath $TailscaleOrigin).Trim()
        if ($origin -notmatch '^https://[a-z0-9-]+\.[a-z0-9-]+\.ts\.net$') {
            throw "Tailscale origin must be one exact non-sensitive ts.net HTTPS origin"
        }
        $tailscaleExecutable = Join-Path $env:ProgramFiles "Tailscale\tailscale.exe"
        if (-not (Test-Path -LiteralPath $tailscaleExecutable -PathType Leaf)) {
            throw "Official Tailscale CLI is required for live Serve attestation"
        }
        $tailscaleSignature = Get-AuthenticodeSignature -LiteralPath $tailscaleExecutable
        if ($tailscaleSignature.Status -ne "Valid" -or $null -eq $tailscaleSignature.SignerCertificate -or
            $tailscaleSignature.SignerCertificate.Subject -notlike "*Tailscale Inc.*") {
            throw "Tailscale CLI must have a valid Tailscale Inc. Authenticode signature"
        }
        $env:HAVRE_TAILSCALE_CLI_PATH = [IO.Path]::GetFullPath($tailscaleExecutable)
        & $Python -m companion.product.tailscale --executable $env:HAVRE_TAILSCALE_CLI_PATH --origin $origin --target $BaseUrl
        if ($LASTEXITCODE -ne 0) {
            throw "Tailscale must attest private Serve to loopback with Funnel disabled"
        }
        $env:HAVRE_WEB_PUSH_ENABLED = "true"
        $env:HAVRE_PUBLIC_BASE_URL = $origin
        $env:HAVRE_WEB_PUSH_VAPID_PUBLIC_KEY = [string]$push.vapid_public_key
        $env:HAVRE_WEB_PUSH_VAPID_KEY_VERSION = [string]$push.vapid_key_version
        $env:HAVRE_WEB_PUSH_VAPID_SUBJECT = [string]$push.vapid_subject
        $env:HAVRE_WEB_PUSH_VAPID_PRIVATE_KEY_DPAPI_FILE = $VapidPrivate
    }
} catch {
    Restore-HavreLaunchEnvironment
    throw
}

$timestamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$stdout = Join-Path $LogRoot "api-$timestamp.stdout.log"
$stderr = Join-Path $LogRoot "api-$timestamp.stderr.log"
$workerStdout = Join-Path $LogRoot "worker-$timestamp.stdout.log"
$workerStderr = Join-Path $LogRoot "worker-$timestamp.stderr.log"
$api = $null
$worker = $null
try {
    try {
        $api = Start-Process -FilePath $Python `
            -ArgumentList @("-m","services.api.cli","serve","--host","127.0.0.1","--port","8765") `
            -WorkingDirectory $ProjectRoot -WindowStyle Hidden `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
        $worker = Start-Process -FilePath $Python `
            -ArgumentList @("-m","services.api.cli","worker-loop","--poll-seconds","2") `
            -WorkingDirectory $ProjectRoot -WindowStyle Hidden `
            -RedirectStandardOutput $workerStdout -RedirectStandardError $workerStderr -PassThru
    } finally {
        Restore-HavreLaunchEnvironment
    }
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(120)
    [void](Wait-HavreReady -Deadline $deadline -ApiProcess $api)
    $version = Invoke-RestMethod -Uri "$BaseUrl/version" -TimeoutSec 10
    if ($worker.HasExited) { throw "HAVRE background worker exited during startup" }
    if (
        [string]$version.provider.provider_id -ne $ExpectedProviderId -or
        [string]$version.provider.model_version_id -ne $ExpectedModelVersion -or
        -not [string]::IsNullOrEmpty([string]$version.provider.active_adapter_version_id)
    ) { throw "Desktop API did not bind the exact GPT-5.6-sol reply route" }
    $localVersion = $version.providers.PSObject.Properties[
        $ExpectedLocalProviderId
    ].Value
    if (
        $null -eq $localVersion -or
        [string]$localVersion.model_version_id -ne $ExpectedLocalModelVersion -or
        [string]$localVersion.model_artifact_hash -ne $ExpectedLocalModelHash -or
        -not [string]::IsNullOrEmpty(
            [string]$localVersion.active_adapter_version_id
        )
    ) { throw "Desktop API did not bind the exact unadapted Qwen3-8B privacy route" }
    [ordered]@{
        schema_version=3; api_pid=$api.Id; worker_pid=$worker.Id; api_executable=$Python
        api_started_at=$api.StartTime.ToUniversalTime().ToString("o")
        worker_started_at=$worker.StartTime.ToUniversalTime().ToString("o")
        api_command_marker="-m services.api.cli serve --host 127.0.0.1 --port 8765"
        worker_command_marker="-m services.api.cli worker-loop --poll-seconds 2"
        base_url=$BaseUrl; database="havre_local_20260822"
        provider_id=$ExpectedProviderId; model_version_id=$ExpectedModelVersion
        codex_reasoning_effort="medium"
        owner_example_bank="owner-example-bank-oa70-all70-v2"
        adapter_version_id=$null; adapter_artifact_hash=$null
        local_provider_id=$ExpectedLocalProviderId
        local_model_version_id=$ExpectedLocalModelVersion
        local_model_artifact_hash=$ExpectedLocalModelHash
        local_adapter_version_id=$null
        candidate_only=$true; promotion_authorized=$false; deployment_authorized=$false
    } | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding utf8
    Set-HavreOwnerOnlyPath -Path $StatePath
} catch {
    if ($null -ne $api -and -not $api.HasExited) {
        Stop-Process -Id $api.Id -ErrorAction SilentlyContinue
    }
    if ($null -ne $worker -and -not $worker.HasExited) {
        Stop-Process -Id $worker.Id -ErrorAction SilentlyContinue
    }
    throw
}
if (-not $NoBrowser) {
    Open-HavreDesktop
}
Write-Host "HAVRE desktop is ready at $BaseUrl/chat"
Write-Host "GPT-5.6-sol answers ordinary eligible turns; exact unadapted Qwen3-8B handles the local privacy route. HAVRE governs both through the same Context, Core, and Event path."
