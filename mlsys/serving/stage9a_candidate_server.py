"""Loopback-only OpenAI-compatible server for one sealed Stage 9A candidate.

This module is executed with the immutable Stage 9A Python environment.  It
does not train, write evaluation evidence, or change candidate lifecycle
status.  Requests are never logged.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

from companion.hashing import content_hash
from mlsys.serving.runtime_attestation import file_sha256
from mlsys.training.stage9a_registry import require_candidate_registry


SERVER_VERSION = "stage9a-candidate-runtime-v1"
MODEL_ALIAS = "qwen3-8b-stage9a-seed-9201"
MAX_REQUEST_BYTES = 1_048_576
MAX_CONTEXT_TOKENS = 8_192
MAX_OUTPUT_TOKENS = 512


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="havre-stage9a-candidate-server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument(
        "--adapter-version",
        default="qwen3-8b-stage9a-qlora-seed-9201",
    )
    parser.add_argument("--state-path", type=Path, required=True)
    return parser


def _candidate_binding(adapter_version: str) -> tuple[dict[str, Any], dict[str, Any]]:
    registry = require_candidate_registry()
    if (
        registry.get("status") != "candidate_only"
        or registry.get("local_only") is not True
        or registry.get("promotion_authorized") is not False
        or registry.get("deployment_authorized") is not False
    ):
        raise ValueError("Stage 9A registry is not a local candidate-only registry")
    matches = [
        item
        for item in registry["adapters"]
        if item.get("adapter_version_id") == adapter_version
    ]
    if len(matches) != 1:
        raise ValueError("requested Stage 9A candidate is not uniquely registered")
    adapter = matches[0]
    if (
        adapter.get("lifecycle_status") != "candidate"
        or adapter.get("candidate_only") is not True
        or adapter.get("promotion_authorized") is not False
        or adapter.get("deployment_authorized") is not False
        or adapter.get("deployed") is not False
        or int(adapter.get("rank", 0)) != 4
    ):
        raise ValueError("requested adapter is outside the development-candidate boundary")
    return registry, adapter


def _load_candidate(adapter_version: str):
    import bitsandbytes
    import peft
    import torch
    import transformers
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    registry, adapter = _candidate_binding(adapter_version)
    model_root = Path(registry["model"]["artifact_uri"]).resolve()
    adapter_root = Path(adapter["artifact_uri"]).resolve()
    adapter_file = adapter_root / "adapter_model.safetensors"
    if not model_root.is_dir() or not adapter_file.is_file():
        raise FileNotFoundError("sealed Stage 9A model or adapter is unavailable")
    if file_sha256(adapter_file) != adapter["artifact_hash"]:
        raise ValueError("Stage 9A adapter bytes do not match the candidate registry")
    if adapter["required_base_revision"] != registry["model"]["upstream_revision"]:
        raise ValueError("Stage 9A adapter requires a different exact base revision")

    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    base = AutoModelForCausalLM.from_pretrained(
        model_root,
        local_files_only=True,
        trust_remote_code=False,
        quantization_config=quantization,
        device_map={"": 0},
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
        attn_implementation="sdpa",
    )
    model = PeftModel.from_pretrained(base, adapter_root, is_trainable=False)
    model.eval()
    tokenizer = AutoTokenizer.from_pretrained(
        model_root,
        local_files_only=True,
        trust_remote_code=False,
        use_fast=True,
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    versions = {
        "server_version": SERVER_VERSION,
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "peft": peft.__version__,
        "bitsandbytes": bitsandbytes.__version__,
    }
    engine_version = (
        f"{SERVER_VERSION}:torch-{versions['torch']}:"
        f"transformers-{versions['transformers']}:peft-{versions['peft']}:"
        f"bnb-{versions['bitsandbytes']}"
    )
    serving_config = {
        "schema_version": 1,
        "load": "nf4-double-quant-bfloat16-sdpa-device0",
        "thinking": False,
        "max_context_tokens": MAX_CONTEXT_TOKENS,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "request_logging": False,
        "web_ui": False,
    }
    return (
        model,
        tokenizer,
        registry,
        adapter,
        model_root,
        adapter_root,
        engine_version,
        content_hash(serving_config),
        versions,
    )


def _messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        raise ValueError("messages must be a non-empty list")
    normalized: list[dict[str, str]] = []
    for raw in raw_messages:
        if not isinstance(raw, dict) or raw.get("role") not in {
            "system",
            "user",
            "assistant",
        }:
            raise ValueError("message role is invalid")
        content = raw.get("content")
        if not isinstance(content, list) or not content:
            raise ValueError("message content must be a non-empty part list")
        texts: list[str] = []
        for part in content:
            if (
                not isinstance(part, dict)
                or part.get("type") != "text"
                or not isinstance(part.get("text"), str)
                or not part["text"]
            ):
                raise ValueError("only non-empty text parts are supported")
            texts.append(part["text"])
        normalized.append({"role": raw["role"], "content": "\n".join(texts)})
    return normalized


class CandidateRuntime:
    def __init__(self, *, adapter_version: str, state_path: Path) -> None:
        (
            self.model,
            self.tokenizer,
            self.registry,
            self.adapter,
            self.model_root,
            self.adapter_root,
            self.engine_version,
            self.serving_config_version,
            self.package_versions,
        ) = _load_candidate(adapter_version)
        self.adapter_version = adapter_version
        self.state_path = state_path.resolve()
        self.lock = threading.Lock()

    def state(self, *, host: str, port: int) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "provider_id": "stage9a-candidate-local",
            "candidate_only": True,
            "promotion_authorized": False,
            "deployment_authorized": False,
            "request_logging_disabled": True,
            "web_ui_disabled": True,
            "host": host,
            "port": port,
            "pid": os.getpid(),
            "launcher_pid": os.getppid(),
            "server_script": str(Path(__file__).resolve()),
            "server_script_hash": file_sha256(Path(__file__).resolve()),
            "registry_hash": self.registry["content_hash"],
            "model_version_id": self.registry["model"]["model_version_id"],
            "model_artifact_hash": self.registry["model"]["artifact_manifest_hash"],
            "model_root": str(self.model_root),
            "model_size_bytes": self.registry["model"]["artifact_size_bytes"],
            "base_revision": self.registry["model"]["upstream_revision"],
            "adapter_version_id": self.adapter_version,
            "adapter_artifact_hash": self.adapter["artifact_hash"],
            "adapter_root": str(self.adapter_root),
            "adapter_manifest_hash": self.adapter["adapter_manifest_hash"],
            "model_alias": MODEL_ALIAS,
            "serving_engine": "transformers-peft",
            "serving_engine_version": self.engine_version,
            "serving_config_version": self.serving_config_version,
            "tokenizer_version_id": (
                f"Qwen/Qwen3-8B@{self.registry['model']['upstream_revision']}:tokenizer"
            ),
            "package_versions": self.package_versions,
            "started_at": datetime.now(UTC).isoformat(),
        }

    def write_state(self, *, host: str, port: int) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.state(host=host, port=port), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.state_path)

    def generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        import torch

        if payload.get("model") != MODEL_ALIAS:
            raise LookupError("model alias is not loaded")
        messages = _messages(payload)
        max_tokens = payload.get("max_tokens")
        temperature = payload.get("temperature")
        top_p = payload.get("top_p")
        if (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or max_tokens <= 0
            or max_tokens > MAX_OUTPUT_TOKENS
        ):
            raise ValueError("max_tokens is outside the candidate runtime boundary")
        if not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
            raise ValueError("temperature is invalid")
        if not isinstance(top_p, (int, float)) or not 0 < top_p <= 1:
            raise ValueError("top_p is invalid")
        if payload.get("chat_template_kwargs", {}).get("enable_thinking") is not False:
            raise ValueError("Stage 9A candidate runtime requires thinking disabled")
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            enable_thinking=False,
            return_tensors="pt",
        ).to("cuda:0")
        prompt_tokens = int(prompt.shape[-1])
        if prompt_tokens + max_tokens > MAX_CONTEXT_TOKENS:
            raise OverflowError("context length exceeded")
        seed = payload.get("seed")
        if seed is not None:
            if isinstance(seed, bool) or not isinstance(seed, int):
                raise ValueError("seed is invalid")
            torch.manual_seed(seed)
            torch.cuda.manual_seed_all(seed)
        started = time.perf_counter()
        generation_args: dict[str, Any] = {
            "input_ids": prompt,
            "attention_mask": torch.ones_like(prompt),
            "max_new_tokens": max_tokens,
            "do_sample": float(temperature) > 0,
            "pad_token_id": self.tokenizer.pad_token_id,
            "eos_token_id": self.tokenizer.eos_token_id,
            "use_cache": True,
        }
        if generation_args["do_sample"]:
            generation_args["temperature"] = float(temperature)
            generation_args["top_p"] = float(top_p)
        with self.lock, torch.inference_mode():
            output = self.model.generate(**generation_args)
            torch.cuda.synchronize()
        generated = output[0, prompt_tokens:]
        text = self.tokenizer.decode(generated, skip_special_tokens=True).strip()
        if not text:
            raise RuntimeError("candidate returned an empty response")
        stops = payload.get("stop", [])
        if stops:
            if not isinstance(stops, list) or not all(
                isinstance(item, str) and item for item in stops
            ):
                raise ValueError("stop must contain non-empty strings")
            positions = [text.find(item) for item in stops if text.find(item) >= 0]
            if positions:
                text = text[: min(positions)].rstrip()
        output_tokens = int(generated.shape[-1])
        finish_reason = (
            "length"
            if output_tokens >= max_tokens
            and int(generated[-1]) != self.tokenizer.eos_token_id
            else "stop"
        )
        return {
            "id": f"havre-stage9a-{uuid4()}",
            "model": MODEL_ALIAS,
            "system_fingerprint": SERVER_VERSION,
            "text": text,
            "finish_reason": finish_reason,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": prompt_tokens + output_tokens,
            },
            "timings": {"generation_ms": round((time.perf_counter() - started) * 1000, 3)},
        }


class CandidateHandler(BaseHTTPRequestHandler):
    runtime: CandidateRuntime
    server_version = "HAVREStage9A/1"
    sys_version = ""

    def log_message(self, _format: str, *args: object) -> None:
        return

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"status": "ok"})
        elif self.path == "/props":
            self._json(
                200,
                {
                    "serving_engine": "transformers-peft",
                    "serving_engine_version": self.runtime.engine_version,
                    "version": self.runtime.engine_version,
                },
            )
        elif self.path == "/v1/models":
            self._json(200, {"object": "list", "data": [{"id": MODEL_ALIAS}]})
        else:
            self._json(404, {"error": {"code": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self._json(404, {"error": {"code": "not_found"}})
            return
        try:
            raw_length = self.headers.get("Content-Length")
            length = int(raw_length or "0")
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("request size is invalid")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("request must be a JSON object")
            result = self.runtime.generate(payload)
            if payload.get("stream") is True:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                chunks = (
                    {
                        "id": result["id"],
                        "model": result["model"],
                        "system_fingerprint": result["system_fingerprint"],
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": result["text"]},
                                "finish_reason": result["finish_reason"],
                            }
                        ],
                        "timings": result["timings"],
                    },
                    {
                        "id": result["id"],
                        "model": result["model"],
                        "system_fingerprint": result["system_fingerprint"],
                        "choices": [],
                        "usage": result["usage"],
                    },
                )
                for chunk in chunks:
                    data = json.dumps(chunk, separators=(",", ":"), ensure_ascii=False)
                    self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            else:
                self._json(
                    200,
                    {
                        "id": result["id"],
                        "model": result["model"],
                        "system_fingerprint": result["system_fingerprint"],
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": result["text"]},
                                "finish_reason": result["finish_reason"],
                            }
                        ],
                        "usage": result["usage"],
                        "timings": result["timings"],
                    },
                )
        except OverflowError:
            self._json(
                400,
                {"error": {"code": "context_length_exceeded", "message": "context length exceeded"}},
            )
        except (ValueError, LookupError):
            self._json(400, {"error": {"code": "invalid_request", "message": "invalid request"}})
        except Exception as error:
            print(f"candidate_request_failed:{type(error).__name__}", flush=True)
            self._json(500, {"error": {"code": "internal_error", "message": "generation failed"}})


def main() -> None:
    args = _parser().parse_args()
    if args.host != "127.0.0.1" or args.port != 8081:
        raise ValueError("Stage 9A candidate server is fixed to 127.0.0.1:8081")
    runtime = CandidateRuntime(
        adapter_version=args.adapter_version,
        state_path=args.state_path,
    )
    CandidateHandler.runtime = runtime
    server = ThreadingHTTPServer((args.host, args.port), CandidateHandler)
    runtime.write_state(host=args.host, port=args.port)
    print(
        json.dumps(
            {
                "status": "ready",
                "provider_id": "stage9a-candidate-local",
                "adapter_version_id": args.adapter_version,
                "candidate_only": True,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
