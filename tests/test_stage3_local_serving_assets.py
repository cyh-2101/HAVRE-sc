from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_ROOT = PROJECT_ROOT / "mlsys" / "serving" / "manifests"
ENGINE_PATH = MANIFEST_ROOT / "llama-cpp-b10405-win-cuda-12.4-x64.json"
MODEL_PATH = MANIFEST_ROOT / "qwen3-8b-q4-k-m.json"
CANDIDATE_MODEL_PATH = MANIFEST_ROOT / "qwen3-14b-q4-k-m.json"
QWEN36_35B_CANDIDATE_MODEL_PATH = (
    MANIFEST_ROOT / "qwen3-6-35b-a3b-q4-k-m.json"
)
ENVIRONMENT_PATH = MANIFEST_ROOT / "stage3-environment-template-v1.json"
SETUP_PATH = PROJECT_ROOT / "scripts" / "setup_stage3_local_serving.ps1"
START_PATH = PROJECT_ROOT / "scripts" / "start_stage3_local_serving.ps1"
STOP_PATH = PROJECT_ROOT / "scripts" / "stop_stage3_local_serving.ps1"
LOCAL_START_PATH = PROJECT_ROOT / "scripts" / "start_havre_local.ps1"
LOCAL_CHAT_PATH = PROJECT_ROOT / "scripts" / "chat_havre_local.ps1"
LOCAL_STOP_PATH = PROJECT_ROOT / "scripts" / "stop_havre_local.ps1"
LOCAL_RUNTIME_MODULE_PATH = PROJECT_ROOT / "scripts" / "HavreLocalRuntime.psm1"
CANDIDATE_FETCH_PATH = PROJECT_ROOT / "scripts" / "fetch_local_model_candidate.ps1"
CANDIDATE_START_PATH = PROJECT_ROOT / "scripts" / "start_local_model_candidate.ps1"
CANDIDATE_STOP_PATH = PROJECT_ROOT / "scripts" / "stop_local_model_candidate.ps1"


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


class Stage3LocalServingAssetTests(unittest.TestCase):
    def test_llama_cpp_manifest_pins_reviewed_release_artifacts(self) -> None:
        manifest = _json(ENGINE_PATH)
        self.assertEqual(
            manifest["manifest_id"],
            "serving-engine-llama-cpp-b10405-win-cuda-12.4-x64",
        )
        self.assertTrue(manifest["immutable"])
        self.assertEqual(manifest["upstream"]["release_tag"], "b10405")
        self.assertEqual(
            manifest["upstream"]["commit"],
            "e79e4bf660e19f2ad851e06c6913f7a8c5852621",
        )
        self.assertEqual(manifest["upstream"]["published_at"], "2026-08-13T07:32:37Z")
        artifacts = {item["role"]: item for item in manifest["artifacts"]}
        self.assertEqual(set(artifacts), {"server_bundle", "cuda_runtime_bundle"})
        self.assertEqual(artifacts["server_bundle"]["size_bytes"], 250767461)
        self.assertEqual(
            artifacts["server_bundle"]["url"],
            "https://github.com/ggml-org/llama.cpp/releases/download/b10405/llama-b10405-bin-win-cuda-12.4-x64.zip",
        )
        self.assertEqual(
            artifacts["server_bundle"]["sha256"],
            "sha256:7da18847181aa668a77b02fa8bd47bb9588b82ca077cf184bccc3bf016b46e79",
        )
        self.assertEqual(artifacts["cuda_runtime_bundle"]["size_bytes"], 391443627)
        self.assertEqual(
            artifacts["cuda_runtime_bundle"]["url"],
            "https://github.com/ggml-org/llama.cpp/releases/download/b10405/cudart-llama-bin-win-cuda-12.4-x64.zip",
        )
        self.assertEqual(
            artifacts["cuda_runtime_bundle"]["sha256"],
            "sha256:8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
        )
        for artifact in artifacts.values():
            self.assertIn("/releases/download/b10405/", artifact["url"])
            self.assertRegex(artifact["sha256"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(manifest["expected_executable_name"], "llama-server.exe")
        self.assertEqual(manifest["security_defaults"]["bind_host"], "127.0.0.1")
        self.assertFalse(manifest["security_defaults"]["request_logging"])
        self.assertEqual(manifest["api"]["streaming"]["content_type"], "text/event-stream")

    def test_model_manifest_pins_reviewed_gguf_and_safe_profile(self) -> None:
        manifest = _json(MODEL_PATH)
        self.assertTrue(manifest["immutable"])
        self.assertEqual(manifest["lifecycle_status"], "candidate")
        self.assertEqual(manifest["alias"], "qwen3-8b-q4-k-m")
        self.assertEqual(manifest["upstream"]["repository"], "Qwen/Qwen3-8B-GGUF")
        self.assertEqual(
            manifest["upstream"]["revision"],
            "7c41481f57cb95916b40956ab2f0b139b296d974",
        )
        artifact = manifest["artifact"]
        self.assertEqual(artifact["filename"], "Qwen3-8B-Q4_K_M.gguf")
        self.assertEqual(
            artifact["url"],
            "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/7c41481f57cb95916b40956ab2f0b139b296d974/Qwen3-8B-Q4_K_M.gguf",
        )
        self.assertEqual(artifact["size_bytes"], 5027783488)
        self.assertEqual(
            artifact["sha256"],
            "sha256:d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785",
        )
        self.assertEqual(artifact["lfs_blob_id"], "d4ee8ae7f4de3a5046b1a29776a3f011ba28017e")
        self.assertEqual(manifest["license"]["identifier"], "Apache-2.0")
        profile = manifest["serving_profile"]
        self.assertEqual(profile["host"], "127.0.0.1")
        self.assertEqual(profile["port"], 8080)
        self.assertEqual(profile["context_tokens"], 8192)
        self.assertEqual(profile["parallel_slots"], 2)
        self.assertEqual(profile["gpu_layers"], "all")
        self.assertTrue(profile["flash_attention"])
        self.assertTrue(profile["jinja_chat_template"])
        self.assertTrue(profile["metrics"])
        self.assertFalse(profile["request_logging"])
        self.assertFalse(
            profile["adapter_request_defaults"]["chat_template_kwargs"][
                "enable_thinking"
            ]
        )

    def test_qwen3_14b_candidate_manifest_pins_exact_official_artifact(self) -> None:
        manifest = _json(CANDIDATE_MODEL_PATH)
        self.assertEqual(
            manifest["manifest_id"],
            "model-qwen3-14b-gguf-q4-k-m-530227a7",
        )
        self.assertTrue(manifest["immutable"])
        self.assertEqual(manifest["lifecycle_status"], "candidate")
        self.assertEqual(manifest["upstream"]["repository"], "Qwen/Qwen3-14B-GGUF")
        self.assertEqual(
            manifest["upstream"]["revision"],
            "530227a7d994db8eca5ab5ced2fb692b614357fd",
        )
        artifact = manifest["artifact"]
        self.assertEqual(artifact["filename"], "Qwen3-14B-Q4_K_M.gguf")
        self.assertIn("/resolve/530227a7d994db8eca5ab5ced2fb692b614357fd/", artifact["url"])
        self.assertNotIn("/resolve/main/", artifact["url"])
        self.assertEqual(artifact["size_bytes"], 9001752960)
        self.assertEqual(
            artifact["sha256"],
            "sha256:500a8806e85ee9c83f3ae08420295592451379b4f8cf2d0f41c15dffeb6b81f0",
        )
        self.assertEqual(artifact["lfs_blob_id"], "1805f4dd32443cb776a843d7902a385132b23ade")
        profile = manifest["serving_profile"]
        self.assertEqual(profile["host"], "127.0.0.1")
        self.assertEqual(profile["port"], 8082)
        self.assertEqual(profile["context_tokens"], 8192)
        self.assertEqual(profile["parallel_slots"], 1)
        self.assertFalse(profile["request_logging"])
        self.assertFalse(profile["web_ui"])

    def test_qwen36_35b_candidate_manifest_pins_exact_ggml_artifact(self) -> None:
        manifest = _json(QWEN36_35B_CANDIDATE_MODEL_PATH)
        self.assertEqual(
            manifest["manifest_id"],
            "model-qwen3-6-35b-a3b-gguf-q4-k-m-baec3ebe",
        )
        self.assertTrue(manifest["immutable"])
        self.assertEqual(manifest["lifecycle_status"], "candidate")
        self.assertEqual(
            manifest["upstream"]["repository"],
            "ggml-org/Qwen3.6-35B-A3B-GGUF",
        )
        self.assertEqual(
            manifest["upstream"]["revision"],
            "baec3ebee244827cda0f4557eafa8b28f7545fa6",
        )
        self.assertEqual(
            manifest["upstream"]["base_model_repository"],
            "Qwen/Qwen3.6-35B-A3B",
        )
        artifact = manifest["artifact"]
        self.assertEqual(
            artifact["filename"],
            "Qwen3.6-35B-A3B-Q4_K_M.gguf",
        )
        self.assertIn(
            "/resolve/baec3ebee244827cda0f4557eafa8b28f7545fa6/",
            artifact["url"],
        )
        self.assertNotIn("/resolve/main/", artifact["url"])
        self.assertEqual(artifact["size_bytes"], 20419565568)
        self.assertEqual(
            artifact["sha256"],
            "sha256:671e47e0ec53c665d048b98c3ecbfd5236b5ca9c3e02ed19fc8f81f7b85140c7",
        )
        self.assertEqual(
            artifact["lfs_blob_id"],
            "0582665a37dd1d972d772d693d69746bb326cc12",
        )
        profile = manifest["serving_profile"]
        self.assertEqual(profile["host"], "127.0.0.1")
        self.assertEqual(profile["port"], 8083)
        self.assertEqual(profile["context_tokens"], 4096)
        self.assertEqual(profile["parallel_slots"], 1)
        self.assertEqual(profile["gpu_layers_cli_value"], "auto")
        self.assertTrue(profile["cpu_moe"])
        self.assertEqual(profile["kv_cache_type_k"], "q8_0")
        self.assertEqual(profile["kv_cache_type_v"], "q8_0")
        self.assertFalse(profile["request_logging"])
        self.assertFalse(profile["web_ui"])

    def test_candidate_fetch_is_path_fenced_and_verifies_before_publish(self) -> None:
        script = CANDIDATE_FETCH_PATH.read_text(encoding="utf-8")
        self.assertIn('"qwen3-14b-q4-k-m.json"', script)
        self.assertIn('"qwen3-6-35b-a3b-q4-k-m.json"', script)
        self.assertIn(".runtime\\model-candidates", script)
        self.assertIn("Candidate path escaped the local runtime root", script)
        self.assertIn("Get-FileHash -Algorithm SHA256", script)
        self.assertIn("Candidate artifact size mismatch", script)
        self.assertIn("Candidate artifact SHA-256 mismatch", script)
        self.assertIn("Get-Command aria2c.exe", script)
        self.assertIn('"--disable-ipv6=true"', script)
        self.assertIn('"--max-connection-per-server=16"', script)
        self.assertIn('"--split=16"', script)
        self.assertIn("Get-Command curl.exe", script)
        self.assertIn('"--continue-at" "-"', script)
        self.assertIn("resumable partial retained", script)
        self.assertIn(".partial", script)
        self.assertLess(script.index("Assert-CandidateArtifact -Path $partial"), script.rindex("Move-Item"))
        self.assertNotIn("/resolve/main/", script)
        self.assertNotIn("500a8806e85ee9c83f3ae08420295592451379b4f8cf2d0f41c15dffeb6b81f0", script)

    def test_candidate_runtime_is_isolated_attested_and_log_disabled(self) -> None:
        start = CANDIDATE_START_PATH.read_text(encoding="utf-8")
        stop = CANDIDATE_STOP_PATH.read_text(encoding="utf-8")
        for expected in (
            "Assert-PinnedFile",
            "Get-FileHash -Algorithm SHA256",
            '"--host", "127.0.0.1"',
            '"--port"',
            '"--parallel"',
            '"--log-disable"',
            '"--no-webui"',
            "Daily Stage 3 model is still running",
            "candidate-runtime-state.json",
            "Get-CimInstance Win32_Process",
            "command_line_sha256",
            "[Security.Cryptography.SHA256]::Create()",
            "text/event-stream",
            "data:\\s*\\[DONE\\]",
        ):
            self.assertIn(expected, start)
        self.assertNotIn("0.0.0.0", start)
        self.assertIn('"--cpu-moe"', start)
        self.assertIn('"--cache-type-k"', start)
        self.assertIn('"--cache-type-v"', start)
        self.assertIn("executable path mismatch", stop)
        self.assertIn("start time mismatch", stop)
        self.assertIn("[DateTimeOffset]$state.process_started_at", stop)
        self.assertNotIn("[DateTimeOffset]::Parse([string]$state.process_started_at)", stop)
        self.assertIn("command line hash mismatch", stop)
        self.assertIn("[Security.Cryptography.SHA256]::Create()", stop)
        self.assertLess(stop.index("command line hash mismatch"), stop.index("Stop-Process"))

    def test_environment_template_references_the_exact_baseline(self) -> None:
        engine = _json(ENGINE_PATH)
        model = _json(MODEL_PATH)
        environment = _json(ENVIRONMENT_PATH)
        self.assertTrue(environment["immutable"])
        system = environment["system_under_test"]
        self.assertEqual(system["serving_engine_manifest_id"], engine["manifest_id"])
        self.assertEqual(system["model_manifest_id"], model["manifest_id"])
        self.assertIsNone(system["code_revision"])
        self.assertIsNone(environment["captured_at"])
        self.assertEqual(environment["serving"]["base_url"], "http://127.0.0.1:8080")
        self.assertFalse(environment["serving"]["request_logging"])
        self.assertFalse(environment["serving"]["thinking_enabled"])

    def test_setup_downloads_only_pins_and_hashes_before_extraction(self) -> None:
        script = SETUP_PATH.read_text(encoding="utf-8")
        self.assertIn(".runtime\\stage3", script)
        self.assertIn("Invoke-WebRequest", script)
        self.assertIn("Get-FileHash -Algorithm SHA256", script)
        self.assertIn("Assert-PinnedFile", script)
        self.assertIn("Expand-Archive", script)
        self.assertRegex(
            script,
            r"(?s)foreach \(\$archive in \$verifiedArchives\).*?"
            r"Assert-PinnedFile.*?Expand-Archive",
        )
        self.assertIn("Get-ChildItem", script)
        self.assertIn("expected_executable_name", script)
        self.assertNotIn("/releases/latest/", script)
        self.assertNotIn("/resolve/main/", script)
        for pinned_hash in (
            "7da18847181aa668a77b02fa8bd47bb9588b82ca077cf184bccc3bf016b46e79",
            "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
            "d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785",
        ):
            self.assertNotIn(pinned_hash, script, "pins belong only in manifests")

    def test_start_reverifies_artifacts_and_enforces_local_sse_profile(self) -> None:
        script = START_PATH.read_text(encoding="utf-8")
        for expected in (
            "Get-FileHash -Algorithm SHA256",
            '"--host", "127.0.0.1"',
            '"--ctx-size"',
            '"--parallel"',
            '"--n-gpu-layers"',
            '"--flash-attn", "on"',
            '"--jinja"',
            '"--metrics"',
            '"--log-disable"',
            '"--no-webui"',
            "-WindowStyle Hidden",
            '"Accept: text/event-stream"',
            "chat_template_kwargs",
            "enable_thinking = $false",
            "data:\\s*\\[DONE\\]",
            'SetEnvironmentVariable("PATH", $null, "Process")',
            'startup-attestation.json',
        ):
            self.assertIn(expected, script)
        self.assertNotIn("0.0.0.0", script)
        self.assertRegex(
            script,
            r"(?s)\$serverPath = Resolve-RuntimeChild.*?"
            r"\$actualServerHash = \(Get-FileHash -Algorithm SHA256.*?"
            r"\$process = Start-Process",
        )
        self.assertRegex(
            script,
            r"(?s)\$modelPath = Resolve-RuntimeChild.*?"
            r"Assert-PinnedFile.*?\$process = Start-Process",
        )

    def test_stop_verifies_executable_path_before_stopping_pid(self) -> None:
        script = STOP_PATH.read_text(encoding="utf-8")
        self.assertIn("expectedServerPath", script)
        self.assertIn("actualProcessPath", script)
        self.assertIn("refusing to stop", script)
        self.assertLess(script.index("actualProcessPath"), script.index("Stop-Process"))

    def test_runtime_outputs_are_ignored(self) -> None:
        ignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertRegex(ignore, r"(?m)^\.runtime/$")
        self.assertRegex(ignore, r"(?m)^\*\.log$")

    def test_local_developer_wrappers_use_the_stage3_core_and_safe_runtime(self) -> None:
        start = LOCAL_START_PATH.read_text(encoding="utf-8")
        chat = LOCAL_CHAT_PATH.read_text(encoding="utf-8")
        stop = LOCAL_STOP_PATH.read_text(encoding="utf-8")
        self.assertIn("services.api.cli chat", chat)
        self.assertIn('HAVRE_PROVIDER_ID = "self-hosted-openai-compatible"', chat)
        self.assertIn("start_stage3_local_serving.ps1", start)
        self.assertIn("services.api.cli", start)
        self.assertIn('"serve"', start)
        self.assertIn('"127.0.0.1"', start)
        self.assertIn("havre-local-state.json", start)
        self.assertIn("api_started_at", start)
        self.assertIn("api_started_at", stop)
        self.assertIn("refusing to stop", stop)
        self.assertIn("stop_stage3_local_serving.ps1", stop)
        self.assertIn("resources.postgres.started_by_this_run", stop)
        self.assertIn("attest-runtime", start)
        self.assertIn("Assert-ExactApiVersion", start)
        self.assertIn("[int]$version.stage -ne 10", start)
        self.assertIn("Assert-ActiveHavrePostgres", start)
        identity_check = start.index("Assert-ActiveHavrePostgres", start.index("try {"))
        self.assertLess(identity_check, start.index("$databaseExists"))
        self.assertLess(identity_check, start.index("services.api.cli migrate"))
        self.assertIn("Assert-HavreOwnedApiPidFile", stop)

    def test_owned_rollback_stops_only_resources_started_by_current_run(self) -> None:
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell is not installed")
        module = str(LOCAL_RUNTIME_MODULE_PATH).replace("'", "''")
        command = f"""
        $ErrorActionPreference='Stop'
        Import-Module '{module}' -Force
        $results=@()
        foreach($ownership in @(
            [pscustomobject]@{{api_started_by_this_run=$true;llama_started_by_this_run=$false;postgres_started_by_this_run=$false}},
            [pscustomobject]@{{api_started_by_this_run=$true;llama_started_by_this_run=$true;postgres_started_by_this_run=$true}},
            [pscustomobject]@{{api_started_by_this_run=$false;llama_started_by_this_run=$false;postgres_started_by_this_run=$false}}
        )) {{
            $calls=[Collections.Generic.List[string]]::new()
            Invoke-HavreOwnedRollback -Ownership $ownership `
                -StopApi {{ $calls.Add('api') }} `
                -StopLlama {{ $calls.Add('llama') }} `
                -StopPostgres {{ $calls.Add('postgres') }}
            $results += ,@($calls)
        }}
        [ordered]@{{first=$results[0];second=$results[1];third=$results[2]}} | ConvertTo-Json -Compress
        """
        completed = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        result = json.loads(completed.stdout.strip())
        self.assertEqual(result["first"], ["api"])
        self.assertEqual(result["second"], ["api", "llama", "postgres"])
        self.assertEqual(result["third"], [])

    def test_owned_rollback_attempts_every_resource_and_aggregates_errors(self) -> None:
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell is not installed")
        module = str(LOCAL_RUNTIME_MODULE_PATH).replace("'", "''")
        command = f"""
        $ErrorActionPreference='Stop'
        Import-Module '{module}' -Force
        $calls=[Collections.Generic.List[string]]::new()
        $message=$null
        try {{
            Invoke-HavreOwnedRollback `
                -Ownership ([pscustomobject]@{{api_started_by_this_run=$true;llama_started_by_this_run=$true;postgres_started_by_this_run=$true}}) `
                -StopApi {{ $calls.Add('api'); throw 'api-stop-failed' }} `
                -StopLlama {{ $calls.Add('llama') }} `
                -StopPostgres {{ $calls.Add('postgres'); throw 'postgres-stop-failed' }}
        }} catch {{ $message=$_.Exception.Message }}
        [ordered]@{{calls=$calls;message=$message}} | ConvertTo-Json -Compress
        """
        completed = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True, text=True, timeout=20, check=True,
        )
        result = json.loads(completed.stdout.strip())
        self.assertEqual(result["calls"], ["api", "llama", "postgres"])
        self.assertIn("api-stop-failed", result["message"])
        self.assertIn("postgres-stop-failed", result["message"])

    def test_postgres_identity_and_missing_owned_api_pid_fail_closed(self) -> None:
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell is not installed")
        module = str(LOCAL_RUNTIME_MODULE_PATH).replace("'", "''")
        command = f"""
        $ErrorActionPreference='Stop'
        Import-Module '{module}' -Force
        $root=[IO.Path]::GetFullPath((Join-Path $env:TEMP 'havre-postgres-identity-test'))
        Assert-HavrePostgresIdentity -ExpectedDataDirectory $root -ReportedDataDirectory ($root + [IO.Path]::DirectorySeparatorChar) -ServerVersionNum '180004' -PgvectorAvailableVersion '0.8.6'
        $errors=[Collections.Generic.List[string]]::new()
        foreach($case in @(
            {{ Assert-HavrePostgresIdentity -ExpectedDataDirectory $root -ReportedDataDirectory ($root + '-foreign') -ServerVersionNum '180004' -PgvectorAvailableVersion '0.8.6' }},
            {{ Assert-HavrePostgresIdentity -ExpectedDataDirectory $root -ReportedDataDirectory $root -ServerVersionNum '170009' -PgvectorAvailableVersion '0.8.6' }},
            {{ Assert-HavrePostgresIdentity -ExpectedDataDirectory $root -ReportedDataDirectory $root -ServerVersionNum '180004' -PgvectorAvailableVersion '' }},
            {{ Assert-HavreOwnedApiPidFile -StateOwnsApi $true -PidPath (Join-Path $root 'missing.pid') }}
        )) {{ try {{ & $case }} catch {{ $errors.Add($_.Exception.Message) }} }}
        $errors | ConvertTo-Json -Compress
        """
        completed = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True, text=True, timeout=20, check=True,
        )
        errors = json.loads(completed.stdout.strip())
        self.assertEqual(len(errors), 4)
        self.assertIn("data_directory", errors[0])
        self.assertIn("version 18", errors[1])
        self.assertIn("pgvector", errors[2])
        self.assertIn("PID file is missing", errors[3])

    def test_process_identity_rejects_pid_path_and_start_time_reuse(self) -> None:
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell is not installed")
        module = str(LOCAL_RUNTIME_MODULE_PATH).replace("'", "''")
        command = f"""
        $ErrorActionPreference='Stop'
        Import-Module '{module}' -Force
        $started=[DateTime]::Parse('2026-08-14T00:00:00Z')
        $process=[pscustomobject]@{{Id=42;Path='C:\\verified\\python.exe';StartTime=$started.ToLocalTime()}}
        Assert-HavreProcessIdentity -Process $process -ExpectedPid 42 -ExpectedExecutable 'C:\\verified\\python.exe' -ExpectedStartedAt $started
        $rejected=@()
        foreach($case in @(
            @{{pid=43;path='C:\\verified\\python.exe';start=$started}},
            @{{pid=42;path='C:\\other\\python.exe';start=$started}},
            @{{pid=42;path='C:\\verified\\python.exe';start=$started.AddSeconds(1)}}
        )) {{
            try {{
                Assert-HavreProcessIdentity -Process $process -ExpectedPid $case.pid -ExpectedExecutable $case.path -ExpectedStartedAt $case.start
            }} catch {{ $rejected += $true }}
        }}
        [ordered]@{{rejected=$rejected.Count}} | ConvertTo-Json -Compress
        """
        completed = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        self.assertEqual(json.loads(completed.stdout.strip())["rejected"], 3)

    def test_powershell_scripts_parse_without_execution(self) -> None:
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell is not installed")
        for path in (
            SETUP_PATH,
            START_PATH,
            STOP_PATH,
            LOCAL_START_PATH,
            LOCAL_CHAT_PATH,
            LOCAL_STOP_PATH,
            LOCAL_RUNTIME_MODULE_PATH,
            CANDIDATE_FETCH_PATH,
            CANDIDATE_START_PATH,
            CANDIDATE_STOP_PATH,
        ):
            escaped = str(path).replace("'", "''")
            command = (
                "$ErrorActionPreference='Stop'; "
                f"$null=[scriptblock]::Create((Get-Content -Raw -LiteralPath '{escaped}'))"
            )
            with self.subTest(script=path.name):
                completed = subprocess.run(
                    [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    completed.stdout + completed.stderr,
                )


if __name__ == "__main__":
    unittest.main()
