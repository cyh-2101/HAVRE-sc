[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$RuntimeRoot = Join-Path $ProjectRoot ".runtime\stage9a-candidate"
$StatePath = Join-Path $RuntimeRoot "runtime-state.json"
$PidPath = Join-Path $RuntimeRoot "server.pid"
$OwnerStatePath = Join-Path $RuntimeRoot "owner-local-state.json"
$LogRoot = Join-Path $RuntimeRoot "logs"
$ClusterRoot = Join-Path $ProjectRoot "var\postgres"
$MainPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$CandidatePython = Join-Path $ProjectRoot "var\stage9a\env-windows\Scripts\python.exe"
$ServerScript = Join-Path $ProjectRoot "mlsys\serving\stage9a_candidate_server.py"
$DatabaseName = "havre_local_20260822"
$DatabaseUrl = "postgresql://postgres@127.0.0.1:55432/$DatabaseName"
$AdapterVersion = "qwen3-8b-stage9a-qlora-seed-9201"
$AdapterHash = "sha256:ac9f8530fd6fb0818808b3432557334fa40f9d49b8126c86152b15a076a8f969"
$PreviousDatabaseUrl = [Environment]::GetEnvironmentVariable("HAVRE_DATABASE_URL","Process")
$PreviousDatabaseUrlFile = [Environment]::GetEnvironmentVariable("HAVRE_DATABASE_URL_FILE","Process")

foreach ($path in @($ClusterRoot, $MainPython, $CandidatePython, $ServerScript)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required HAVRE owner-local path is missing: $path"
    }
}
New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null

$pgCtl = (Get-Command pg_ctl -ErrorAction Stop).Source
$pgIsReady = (Get-Command pg_isready -ErrorAction Stop).Source
$psql = (Get-Command psql -ErrorAction Stop).Source
$createdb = (Get-Command createdb -ErrorAction Stop).Source
$postgres = (Get-Command postgres -ErrorAction Stop).Source
$postgresStartedHere = $false
$postgresProcess = $null
$candidateProcess = $null

function Assert-HavrePostgres {
    $identity = & $psql -X -h 127.0.0.1 -p 55432 -U postgres -d postgres -At -F "|" -c `
        "SELECT current_setting('data_directory'), current_setting('server_version_num'), COALESCE((SELECT default_version FROM pg_available_extensions WHERE name='vector'),'')"
    if ($LASTEXITCODE -ne 0) { throw "Could not inspect HAVRE PostgreSQL" }
    $parts = ([string]$identity).Split('|')
    if ($parts.Count -ne 3) { throw "HAVRE PostgreSQL identity is malformed" }
    $reported = [IO.Path]::GetFullPath(($parts[0] -replace '/', '\'))
    $expected = [IO.Path]::GetFullPath($ClusterRoot)
    if (-not $reported.Equals($expected, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Port 55432 is not the verified HAVRE owner-local cluster"
    }
    if (-not $parts[1].StartsWith("18") -or [string]::IsNullOrWhiteSpace($parts[2])) {
        throw "HAVRE PostgreSQL 18/pgvector identity check failed"
    }
}

try {
    & $pgIsReady -h 127.0.0.1 -p 55432 *> $null
    if ($LASTEXITCODE -ne 0) {
        $pgOut = Join-Path $LogRoot "postgres.stdout.log"
        $pgErr = Join-Path $LogRoot "postgres.stderr.log"
        $postgresProcess = Start-Process `
            -FilePath $postgres `
            -ArgumentList @("-D", $ClusterRoot, "-h", "127.0.0.1", "-p", "55432") `
            -WorkingDirectory $ProjectRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $pgOut `
            -RedirectStandardError $pgErr `
            -PassThru
        $postgresStartedHere = $true
        $deadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
        do {
            Start-Sleep -Milliseconds 500
            & $pgIsReady -h 127.0.0.1 -p 55432 *> $null
        } until ($LASTEXITCODE -eq 0 -or [DateTimeOffset]::UtcNow -ge $deadline)
        if ($LASTEXITCODE -ne 0) { throw "HAVRE PostgreSQL did not become ready" }
    }
    Assert-HavrePostgres

    $exists = & $psql -X -h 127.0.0.1 -p 55432 -U postgres -d postgres -Atc `
        "SELECT 1 FROM pg_database WHERE datname='$DatabaseName'"
    if ($LASTEXITCODE -ne 0) { throw "Could not inspect owner-local database" }
    if ($exists -ne "1") {
        & $createdb -h 127.0.0.1 -p 55432 -U postgres $DatabaseName
        if ($LASTEXITCODE -ne 0) { throw "Could not create owner-local database" }
    }
    Remove-Item Env:HAVRE_DATABASE_URL_FILE -ErrorAction SilentlyContinue
    $env:HAVRE_DATABASE_URL = $DatabaseUrl
    & $MainPython -m services.api.cli migrate --bootstrap-owner
    if ($LASTEXITCODE -ne 0) { throw "Owner-local migrations failed" }

    try {
        $baseHealth = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8080/health" -TimeoutSec 2
        if ($baseHealth.StatusCode -eq 200) {
            & (Join-Path $PSScriptRoot "stop_stage3_local_serving.ps1")
            if ($LASTEXITCODE -ne 0) { throw "Could not stop the exact Stage 3 base runtime" }
        }
    }
    catch {
        if ($_.Exception.Message -like "Could not stop*") { throw }
    }

    $env:HAVRE_PROVIDER_ID = "stage9a-candidate-local"
    $env:HAVRE_SELF_HOSTED_BASE_URL = "http://127.0.0.1:8081"
    $env:HAVRE_RUNTIME_ADAPTER_VERSION = $AdapterVersion
    $env:HAVRE_RUNTIME_ADAPTER_HASH = $AdapterHash

    $candidateHealthy = $false
    try {
        $health = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8081/health" -TimeoutSec 2
        $candidateHealthy = $health.StatusCode -eq 200
    }
    catch {}
    if ($candidateHealthy) {
        & $MainPython -m services.api.cli attest-candidate-runtime | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Existing candidate runtime failed attestation" }
        Write-Host "HAVRE Seed 9201 candidate runtime is already ready."
        return
    }

    Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $PidPath -Force -ErrorAction SilentlyContinue
    $timestamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    $stdout = Join-Path $LogRoot "candidate-$timestamp.stdout.log"
    $stderr = Join-Path $LogRoot "candidate-$timestamp.stderr.log"
    $candidateProcess = Start-Process `
        -FilePath $CandidatePython `
        -ArgumentList @(
            "-m", "mlsys.serving.stage9a_candidate_server",
            "--host", "127.0.0.1",
            "--port", "8081",
            "--adapter-version", $AdapterVersion,
            "--state-path", $StatePath
        ) `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru
    $candidateProcess.Id | Set-Content -LiteralPath $PidPath -Encoding ascii
    $deadline = [DateTimeOffset]::UtcNow.AddMinutes(4)
    do {
        if ($candidateProcess.HasExited) {
            throw "Seed 9201 candidate process exited during model load"
        }
        Start-Sleep -Seconds 1
        try {
            $health = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8081/health" -TimeoutSec 2
            $candidateHealthy = $health.StatusCode -eq 200
        }
        catch { $candidateHealthy = $false }
    } until ($candidateHealthy -or [DateTimeOffset]::UtcNow -ge $deadline)
    if (-not $candidateHealthy) { throw "Seed 9201 candidate runtime did not become ready" }
    & $MainPython -m services.api.cli attest-candidate-runtime | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Seed 9201 candidate runtime failed attestation" }

    [ordered]@{
        schema_version = 1
        candidate_launcher_pid = $candidateProcess.Id
        candidate_started_by_this_run = $true
        postgres_pid = if ($null -eq $postgresProcess) { $null } else { $postgresProcess.Id }
        postgres_started_by_this_run = $postgresStartedHere
        database = $DatabaseName
        adapter_version_id = $AdapterVersion
        adapter_artifact_hash = $AdapterHash
        candidate_only = $true
        promotion_authorized = $false
        deployment_authorized = $false
        started_at = [DateTimeOffset]::UtcNow.ToString("o")
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $OwnerStatePath -Encoding utf8
}
catch {
    $startupError = $_
    if ($null -ne $candidateProcess -and -not $candidateProcess.HasExited) {
        Stop-Process -Id $candidateProcess.Id -ErrorAction SilentlyContinue
    }
    if ($postgresStartedHere) {
        & $pgCtl -D $ClusterRoot stop -m fast *> $null
    }
    Remove-Item -LiteralPath $PidPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $OwnerStatePath -Force -ErrorAction SilentlyContinue
    throw $startupError
}
finally {
    Remove-Item Env:HAVRE_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:HAVRE_DATABASE_URL_FILE -ErrorAction SilentlyContinue
    if ($null -ne $PreviousDatabaseUrl) { $env:HAVRE_DATABASE_URL = $PreviousDatabaseUrl }
    if ($null -ne $PreviousDatabaseUrlFile) { $env:HAVRE_DATABASE_URL_FILE = $PreviousDatabaseUrlFile }
}

Write-Host "HAVRE Seed 9201 development candidate is ready."
Write-Host "Run .\scripts\chat_havre_candidate_local.ps1 to chat with reviewed Memory."
