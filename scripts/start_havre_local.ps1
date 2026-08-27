[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$ClusterRoot = Join-Path $ProjectRoot "var\postgres"
$RuntimeRoot = Join-Path $ProjectRoot ".runtime\stage3"
$RunRoot = Join-Path $RuntimeRoot "run"
$LogRoot = Join-Path $RuntimeRoot "logs"
$StatePath = Join-Path $RunRoot "havre-local-state.json"
$ApiPidPath = Join-Path $RunRoot "havre-api.pid"
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ApiBaseUrl = "http://127.0.0.1:8765"
$ModelBaseUrl = "http://127.0.0.1:8080"
$ApiArguments = @("-m", "services.api.cli", "serve", "--host", "127.0.0.1", "--port", "8765")
Import-Module (Join-Path $PSScriptRoot "HavreLocalRuntime.psm1") -Force

foreach ($path in @($ClusterRoot, $PythonPath, (Join-Path $RuntimeRoot "runtime-state.json"))) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required verified HAVRE runtime path is missing: $path"
    }
}
New-Item -ItemType Directory -Path $RunRoot -Force | Out-Null
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null

$env:HAVRE_DATABASE_URL = "postgresql://postgres@127.0.0.1:55432/havre"
$env:HAVRE_PROVIDER_ID = "self-hosted-openai-compatible"
$env:HAVRE_SELF_HOSTED_BASE_URL = $ModelBaseUrl

function Get-ProcessStartUtc {
    param([Parameter(Mandatory = $true)]$Process)
    return $Process.StartTime.ToUniversalTime()
}

function Assert-ApiProcess {
    param([Parameter(Mandatory = $true)]$State)

    $process = Get-Process -Id ([int]$State.api_pid) -ErrorAction Stop
    Assert-HavreProcessIdentity `
        -Process $process `
        -ExpectedPid ([int]$State.api_pid) `
        -ExpectedExecutable ([string]$State.api_executable) `
        -ExpectedStartedAt ([DateTime]::Parse([string]$State.api_started_at))
    return $process
}

function Get-ModelAttestation {
    $output = & $PythonPath -m services.api.cli attest-runtime
    if ($LASTEXITCODE -ne 0) {
        throw "Active llama.cpp service failed process-bound runtime attestation"
    }
    return [string]::Join("`n", [string[]]$output) | ConvertFrom-Json
}

function Assert-ExactApiVersion {
    param([Parameter(Mandatory = $true)]$ModelAttestation)

    $version = Invoke-RestMethod -Uri "$ApiBaseUrl/version" -TimeoutSec 10
    if (
        [string]$version.service -ne "havre-api" -or
        [int]$version.stage -ne 10 -or
        [string]$version.provider.provider_id -ne "self-hosted-openai-compatible" -or
        [string]$version.provider.provider_class -ne "self_hosted" -or
        [string]$version.provider.execution_environment -ne "local" -or
        [string]$version.provider.model_version_id -ne [string]$ModelAttestation.model_version_id -or
        [string]$version.provider.model_artifact_hash -ne [string]$ModelAttestation.model_artifact_hash -or
        [string]$version.provider.serving_engine_version -ne [string]$ModelAttestation.serving_engine_version -or
        [string]$version.provider.serving_config_version -ne [string]$ModelAttestation.serving_config_version -or
        [string]$version.provider.runtime_attestation_id -ne [string]$ModelAttestation.attestation_id -or
        [string]$version.provider.runtime_attestation_hash -ne [string]$ModelAttestation.attestation_hash
    ) {
        throw "HAVRE API /version does not match the active process-bound model attestation"
    }
    return $version
}

if (Test-Path -LiteralPath $StatePath -PathType Leaf) {
    try {
        $existingState = Get-Content -Raw -LiteralPath $StatePath | ConvertFrom-Json
        $existingApi = Assert-ApiProcess $existingState
        $attestation = Get-ModelAttestation
        Assert-ExactApiVersion $attestation | Out-Null
        Write-Host "HAVRE Stage 10 is already ready (API PID $($existingApi.Id))."
        return
    }
    catch {
        throw "Existing HAVRE runtime cannot be safely reused: $($_.Exception.Message)"
    }
}

$pgCtl = (Get-Command pg_ctl -ErrorAction Stop).Source
$pgIsReady = (Get-Command pg_isready -ErrorAction Stop).Source
$psql = (Get-Command psql -ErrorAction Stop).Source
$createdb = (Get-Command createdb -ErrorAction Stop).Source
$postgresStartedHere = $false
$llamaStartedHere = $false
$apiProcess = $null

function Assert-ActiveHavrePostgres {
    $identityRows = & $psql -X -h 127.0.0.1 -p 55432 -U postgres -d postgres `
        -v ON_ERROR_STOP=1 -At -F "|" -c `
        "SELECT current_setting('data_directory'), current_setting('server_version_num'), COALESCE((SELECT default_version FROM pg_available_extensions WHERE name = 'vector'), '')"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not verify the active PostgreSQL instance identity"
    }
    $identityLines = @($identityRows | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) })
    if ($identityLines.Count -ne 1) {
        throw "Active PostgreSQL identity query returned an unexpected result"
    }
    $identity = ([string]$identityLines[0]).Split('|')
    if ($identity.Count -ne 3) {
        throw "Active PostgreSQL identity response is malformed"
    }
    Assert-HavrePostgresIdentity `
        -ExpectedDataDirectory $ClusterRoot `
        -ReportedDataDirectory $identity[0] `
        -ServerVersionNum $identity[1] `
        -PgvectorAvailableVersion $identity[2]
}

try {
    & $pgIsReady -h 127.0.0.1 -p 55432 *> $null
    $postgresWasRunning = $LASTEXITCODE -eq 0
    if (-not $postgresWasRunning) {
        $postgresLog = Join-Path $LogRoot "havre-postgres.log"
        & $pgCtl -D $ClusterRoot -l $postgresLog -o "-h 127.0.0.1 -p 55432" start
        if ($LASTEXITCODE -ne 0) {
            throw "PostgreSQL failed to start from the approved cluster path"
        }
        $postgresStartedHere = $true
    }

    # pg_isready proves only that something speaks PostgreSQL on the port.
    # Establish exact cluster/version/extension identity before any database
    # creation or migration can mutate that instance.
    Assert-ActiveHavrePostgres

    $databaseExists = & $psql -h 127.0.0.1 -p 55432 -U postgres -d postgres -Atc `
        "SELECT 1 FROM pg_database WHERE datname = 'havre'"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect the local PostgreSQL cluster"
    }
    if ($databaseExists -ne "1") {
        & $createdb -h 127.0.0.1 -p 55432 -U postgres havre
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create the local HAVRE database"
        }
    }

    & $PythonPath -m services.api.cli migrate
    if ($LASTEXITCODE -ne 0) {
        throw "HAVRE migrations failed"
    }

    $modelHealth200 = $false
    try {
        $health = Invoke-WebRequest -UseBasicParsing -Uri "$ModelBaseUrl/health" -TimeoutSec 2
        $modelHealth200 = $health.StatusCode -eq 200
    }
    catch {}
    if ($modelHealth200) {
        try {
            $modelAttestation = Get-ModelAttestation
        }
        catch {
            throw "Port 8080 is healthy but is not the attested pinned Stage 3 runtime; refusing reuse"
        }
    }
    else {
        & (Join-Path $PSScriptRoot "start_stage3_local_serving.ps1")
        $llamaStartedHere = $true
        $modelAttestation = Get-ModelAttestation
    }

    try {
        $unexpectedVersion = Invoke-RestMethod -Uri "$ApiBaseUrl/version" -TimeoutSec 2
        if ($null -ne $unexpectedVersion) {
            throw "An unowned HAVRE API already occupies 127.0.0.1:8765; refusing reuse"
        }
    }
    catch {
        if ($_.Exception.Message -like "An unowned HAVRE API*") { throw }
    }

    if (Test-Path -LiteralPath $ApiPidPath -PathType Leaf) {
        $stalePid = (Get-Content -Raw -LiteralPath $ApiPidPath).Trim()
        $parsedPid = 0
        if ([int]::TryParse($stalePid, [ref]$parsedPid) -and $null -ne (
            Get-Process -Id $parsedPid -ErrorAction SilentlyContinue
        )) {
            throw "An unowned HAVRE API PID is still running; refusing reuse"
        }
        Remove-Item -LiteralPath $ApiPidPath -Force
    }

    $timestamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    $apiStdout = Join-Path $LogRoot "havre-api-$timestamp.stdout.log"
    $apiStderr = Join-Path $LogRoot "havre-api-$timestamp.stderr.log"
    $apiProcess = Start-Process `
        -FilePath $PythonPath `
        -ArgumentList $ApiArguments `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $apiStdout `
        -RedirectStandardError $apiStderr `
        -PassThru
    $apiProcess.Id | Set-Content -LiteralPath $ApiPidPath -Encoding ascii

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(120)
    $apiVerified = $false
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        if ($apiProcess.HasExited) {
            throw "HAVRE API exited during startup with code $($apiProcess.ExitCode)"
        }
        try {
            Assert-ExactApiVersion $modelAttestation | Out-Null
            $apiVerified = $true
            break
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $apiVerified) {
        throw "HAVRE API did not publish the exact attested /version within 120 seconds"
    }

    [ordered]@{
        schema_version = 2
        api_pid = $apiProcess.Id
        api_executable = [IO.Path]::GetFullPath($PythonPath)
        api_started_at = (Get-ProcessStartUtc $apiProcess).ToString("o")
        api_base_url = $ApiBaseUrl
        api_arguments = $ApiArguments
        runtime_attestation_id = [string]$modelAttestation.attestation_id
        runtime_attestation_hash = [string]$modelAttestation.attestation_hash
        resources = [ordered]@{
            postgres = @{ started_by_this_run = $postgresStartedHere; cluster = [IO.Path]::GetFullPath($ClusterRoot) }
            llama_cpp = @{ started_by_this_run = $llamaStartedHere; pid = [int]$modelAttestation.server_pid }
            havre_api = @{ started_by_this_run = $true; pid = $apiProcess.Id }
        }
        started_at = [DateTimeOffset]::UtcNow.ToString("o")
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $StatePath -Encoding utf8
}
catch {
    $startupError = $_
    $ownership = [pscustomobject]@{
        api_started_by_this_run = ($null -ne $apiProcess)
        llama_started_by_this_run = $llamaStartedHere
        postgres_started_by_this_run = $postgresStartedHere
    }
    $rollbackError = $null
    try {
        Invoke-HavreOwnedRollback -Ownership $ownership `
            -StopApi {
                if (-not $apiProcess.HasExited) {
                    Stop-Process -Id $apiProcess.Id -ErrorAction Stop
                    $apiProcess.WaitForExit(15000) | Out-Null
                }
            } `
            -StopLlama { & (Join-Path $PSScriptRoot "stop_stage3_local_serving.ps1") } `
            -StopPostgres {
                & $pgCtl -D $ClusterRoot stop -m fast
                if ($LASTEXITCODE -ne 0) { throw "PostgreSQL failed to stop during rollback" }
            }
    }
    catch {
        $rollbackError = $_
    }
    finally {
        Remove-Item -LiteralPath $ApiPidPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $rollbackError) {
        throw "HAVRE startup failed: $($startupError.Exception.Message); rollback also failed: $($rollbackError.Exception.Message)"
    }
    throw $startupError
}

Write-Host "HAVRE Stage 10 is ready."
Write-Host "API: $ApiBaseUrl"
Write-Host "Model: Qwen3-8B Q4_K_M through process-attested pinned llama.cpp on $ModelBaseUrl"
