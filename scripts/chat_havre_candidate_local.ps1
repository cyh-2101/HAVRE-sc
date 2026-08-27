[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "HAVRE virtual environment is missing: $PythonPath"
}

$env:HAVRE_DATABASE_URL = "postgresql://postgres@127.0.0.1:55432/havre_local_20260822"
$env:HAVRE_PROVIDER_ID = "stage9a-candidate-local"
$env:HAVRE_SELF_HOSTED_BASE_URL = "http://127.0.0.1:8081"
$env:HAVRE_RUNTIME_ADAPTER_VERSION = "qwen3-8b-stage9a-qlora-seed-9201"
$env:HAVRE_RUNTIME_ADAPTER_HASH = "sha256:ac9f8530fd6fb0818808b3432557334fa40f9d49b8126c86152b15a076a8f969"
$env:HAVRE_INFERENCE_TIMEOUT_MS = "120000"
$env:HAVRE_RESERVED_OUTPUT_TOKENS = "192"

Push-Location $ProjectRoot
try {
    & $PythonPath -m services.api.cli chat-owner
    if ($LASTEXITCODE -ne 0) {
        throw "HAVRE owner-local chat exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
