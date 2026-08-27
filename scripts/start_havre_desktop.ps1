[CmdletBinding()]
param([switch]$NoBrowser)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$RuntimeRoot = Join-Path $ProjectRoot ".runtime\desktop"
$StatePath = Join-Path $RuntimeRoot "state.json"
$LogRoot = Join-Path $RuntimeRoot "logs"
$SecretRoot = Join-Path $RuntimeRoot "secrets"
$DatabaseSecret = Join-Path $SecretRoot "database-url.secret"
$OwnerTokenSecret = Join-Path $SecretRoot "owner-api-token.secret"
$BootstrapSecret = Join-Path $SecretRoot "desktop-bootstrap-token.secret"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$BaseUrl = "http://127.0.0.1:8765"

New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
if (Test-Path -LiteralPath $StatePath) {
    $state = Get-Content -Raw -LiteralPath $StatePath | ConvertFrom-Json
    $process = Get-Process -Id ([int]$state.api_pid) -ErrorAction SilentlyContinue
    if ($null -eq $process) { throw "Stale HAVRE desktop state must be inspected before restart" }
    $version = Invoke-RestMethod -Uri "$BaseUrl/version" -TimeoutSec 10
    if ([string]$version.provider.active_adapter_version_id -ne [string]$state.adapter_version_id) {
        throw "Running desktop API does not match its exact candidate state"
    }
    if (-not (Test-Path -LiteralPath $BootstrapSecret -PathType Leaf)) {
        throw "Running desktop lacks its protected browser bootstrap; restart it cleanly"
    }
    if (-not $NoBrowser) {
        $bootstrap = Get-Content -Raw -LiteralPath $BootstrapSecret
        Start-Process "$BaseUrl/chat#desktop-bootstrap=$([uri]::EscapeDataString($bootstrap.Trim()))"
    }
    Write-Host "HAVRE desktop is already ready at $BaseUrl/chat"
    return
}

& (Join-Path $PSScriptRoot "start_havre_candidate_local.ps1")
if ($LASTEXITCODE -ne 0) { throw "Candidate runtime startup failed" }

$AdminDatabaseUrl = "postgresql://postgres@127.0.0.1:55432/havre_local_20260822"
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
New-Item -ItemType Directory -Path $SecretRoot -Force | Out-Null
$secretAcl = New-Object System.Security.AccessControl.DirectorySecurity
$secretAcl.SetAccessRuleProtection($true,$false)
$secretRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    $identity,"FullControl","ContainerInherit,ObjectInherit","None","Allow"
)
$secretAcl.AddAccessRule($secretRule)
Set-Acl -LiteralPath $SecretRoot -AclObject $secretAcl
$verifiedAcl = Get-Acl -LiteralPath $SecretRoot
if (-not $verifiedAcl.AreAccessRulesProtected -or $verifiedAcl.Access.Count -ne 1 -or
    -not $verifiedAcl.Access[0].IdentityReference.Value.Equals(
        $identity,[StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Desktop secret directory is not owner-only"
}
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

$PreviousDatabaseUrl = [Environment]::GetEnvironmentVariable("HAVRE_DATABASE_URL","Process")
$PreviousDatabaseUrlFile = [Environment]::GetEnvironmentVariable("HAVRE_DATABASE_URL_FILE","Process")
Remove-Item Env:HAVRE_DATABASE_URL -ErrorAction SilentlyContinue
$env:HAVRE_DATABASE_URL_FILE = $DatabaseSecret
$env:HAVRE_OWNER_API_TOKEN_FILE = $OwnerTokenSecret
$env:HAVRE_DESKTOP_BOOTSTRAP_TOKEN_FILE = $BootstrapSecret
$env:HAVRE_PROVIDER_ID = "stage9a-candidate-local"
$env:HAVRE_SELF_HOSTED_BASE_URL = "http://127.0.0.1:8081"
$env:HAVRE_RUNTIME_ADAPTER_VERSION = "qwen3-8b-stage9a-qlora-seed-9201"
$env:HAVRE_RUNTIME_ADAPTER_HASH = "sha256:ac9f8530fd6fb0818808b3432557334fa40f9d49b8126c86152b15a076a8f969"

$timestamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$stdout = Join-Path $LogRoot "api-$timestamp.stdout.log"
$stderr = Join-Path $LogRoot "api-$timestamp.stderr.log"
$api = Start-Process -FilePath $Python `
    -ArgumentList @("-m","services.api.cli","serve","--host","127.0.0.1","--port","8765") `
    -WorkingDirectory $ProjectRoot -WindowStyle Hidden `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
Remove-Item Env:HAVRE_DATABASE_URL_FILE -ErrorAction SilentlyContinue
if ($null -ne $PreviousDatabaseUrl) { $env:HAVRE_DATABASE_URL = $PreviousDatabaseUrl }
if ($null -ne $PreviousDatabaseUrlFile) { $env:HAVRE_DATABASE_URL_FILE = $PreviousDatabaseUrlFile }
try {
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(120)
    $version = $null
    do {
        if ($api.HasExited) { throw "HAVRE desktop API exited during startup" }
        Start-Sleep -Milliseconds 500
        try { $version = Invoke-RestMethod -Uri "$BaseUrl/version" -TimeoutSec 3 } catch {}
    } until ($null -ne $version -or [DateTimeOffset]::UtcNow -ge $deadline)
    if ($null -eq $version) { throw "HAVRE desktop API did not become ready" }
    if (
        [string]$version.provider.provider_id -ne "stage9a-candidate-local" -or
        [string]$version.provider.active_adapter_version_id -ne $env:HAVRE_RUNTIME_ADAPTER_VERSION
    ) { throw "Desktop API did not bind the exact Seed 9201 candidate" }
    [ordered]@{
        schema_version=1; api_pid=$api.Id; api_executable=$Python
        api_started_at=$api.StartTime.ToUniversalTime().ToString("o")
        base_url=$BaseUrl; database="havre_local_20260822"
        adapter_version_id=$env:HAVRE_RUNTIME_ADAPTER_VERSION
        adapter_artifact_hash=$env:HAVRE_RUNTIME_ADAPTER_HASH
        candidate_only=$true; promotion_authorized=$false; deployment_authorized=$false
    } | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding utf8
} catch {
    if (-not $api.HasExited) { Stop-Process -Id $api.Id -ErrorAction SilentlyContinue }
    throw
}
if (-not $NoBrowser) {
    $bootstrap = Get-Content -Raw -LiteralPath $BootstrapSecret
    Start-Process "$BaseUrl/chat#desktop-bootstrap=$([uri]::EscapeDataString($bootstrap.Trim()))"
}
Write-Host "HAVRE desktop is ready at $BaseUrl/chat"
Write-Host "Seed 9201 remains a development candidate; no promotion or deployment occurred."
