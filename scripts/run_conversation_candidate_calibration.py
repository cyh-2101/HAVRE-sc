"""Collect a raw-model PUBLIC synthetic conversation calibration arm."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import psutil

from companion.context import ResponsePlanner
from companion.hashing import content_hash
from companion.identity import IdentityLoader
from evals.conversation_quality import (
    build_candidate_messages,
    build_synthetic_retrieval_result,
    load_calibration_suite,
    seal_report,
    surface_diagnostics,
)
from evals.inference_runner import current_source_revision


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = PROJECT_ROOT / "evals" / "fixtures" / "conversation_quality_calibration_v1.json"
ALLOWED_OUTPUT_ROOT = (PROJECT_ROOT / ".runtime" / "evaluations").resolve()
GENERATION_SETTINGS = {
    "max_tokens": 768,
    "temperature": 0.7,
    "top_p": 0.8,
    "top_k": 20,
    "min_p": 0.0,
    "presence_penalty": 1.5,
    "seed": 260902,
    "stream": False,
    "chat_template_kwargs": {"enable_thinking": False},
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run-conversation-candidate-calibration")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model-alias", required=True)
    parser.add_argument("--arm-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-state", type=Path, required=True)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    return parser


def _assert_output_path(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(ALLOWED_OUTPUT_ROOT)
    except ValueError as error:
        raise ValueError("calibration output must stay under .runtime/evaluations") from error
    if resolved.exists():
        raise FileExistsError(f"immutable calibration output already exists: {resolved}")
    return resolved


def _post_completion(*, base_url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:1_000]
        raise RuntimeError(f"candidate endpoint returned HTTP {error.code}: {detail}") from error


def _load_runtime_evidence(
    *,
    path: Path,
    base_url: str,
    model_alias: str,
) -> dict[str, Any]:
    resolved = path.resolve()
    runtime_root = (PROJECT_ROOT / ".runtime").resolve()
    try:
        relative_path = resolved.relative_to(runtime_root)
    except ValueError as error:
        raise ValueError("runtime state must stay under .runtime") from error
    state = json.loads(resolved.read_text(encoding="utf-8-sig"))
    if state.get("candidate_only") is not True:
        raise ValueError("runtime state must attest candidate_only=true")
    if state.get("promotion_authorized") is not False:
        raise ValueError("runtime state must attest promotion_authorized=false")
    if state.get("deployment_authorized") is not False:
        raise ValueError("runtime state must attest deployment_authorized=false")
    attested_alias = state.get("alias")
    if attested_alias is not None and attested_alias != model_alias:
        raise ValueError("runtime state alias does not match requested model alias")
    attested_base_url = state.get("base_url")
    if attested_base_url is not None and attested_base_url.rstrip("/") != base_url.rstrip("/"):
        raise ValueError("runtime state base URL does not match candidate endpoint")
    pid = state.get("server_pid", state.get("model_server_pid"))
    if not isinstance(pid, int) or pid < 1 or not psutil.pid_exists(pid):
        raise ValueError("runtime state does not identify a live model process")
    return {
        "state_relative_path": relative_path.as_posix(),
        "state_hash": content_hash(state),
        "schema_version": state.get("schema_version"),
        "runtime_kind": state.get("runtime_kind"),
        "manifest_id": state.get("manifest_id"),
        "model_version_id": state.get("model_version_id"),
        "model_sha256": state.get("model_sha256"),
        "adapter_version_id": state.get("adapter_version_id"),
        "server_pid": pid,
        "base_url": base_url.rstrip("/"),
        "model_alias": model_alias,
        "candidate_only": True,
        "promotion_authorized": False,
        "deployment_authorized": False,
    }


def run(
    *,
    base_url: str,
    model_alias: str,
    arm_name: str,
    output: Path,
    runtime_state_path: Path,
    suite_path: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    if timeout_seconds < 1 or timeout_seconds > 900:
        raise ValueError("timeout_seconds must be between 1 and 900")
    output = _assert_output_path(output)
    runtime_evidence = _load_runtime_evidence(
        path=runtime_state_path,
        base_url=base_url,
        model_alias=model_alias,
    )
    suite = load_calibration_suite(suite_path)
    identity = IdentityLoader(PROJECT_ROOT / "identity").load()
    identity_text = identity.system_text()
    planner = ResponsePlanner()
    owner_id = uuid5(NAMESPACE_URL, f"{suite['suite_id']}/synthetic-owner")
    session_id = uuid5(NAMESPACE_URL, f"{suite['suite_id']}/synthetic-session")
    rows = []
    started = time.perf_counter()
    for case in suite["cases"]:
        request_id = uuid5(NAMESPACE_URL, f"{suite['suite_id']}/{case['case_id']}/request")
        trace_id = uuid5(NAMESPACE_URL, f"{suite['suite_id']}/{case['case_id']}/trace").hex
        latest_message = case["turns"][-1]["content"]
        synthetic_retrieval = build_synthetic_retrieval_result(
            suite_id=suite["suite_id"],
            case=case,
            request_id=request_id,
            trace_id=trace_id,
            owner_id=owner_id,
        )
        plan = planner.plan(
            request_id=request_id,
            trace_id=trace_id,
            owner_id=owner_id,
            message=latest_message,
            source_refs=(f"synthetic-case/{case['case_id']}",),
        )
        messages = build_candidate_messages(
            identity_text=identity_text,
            response_plan=plan,
            case=case,
        )
        payload = {"model": model_alias, "messages": messages, **GENERATION_SETTINGS}
        case_started = time.perf_counter()
        response = _post_completion(base_url=base_url, payload=payload, timeout=timeout_seconds)
        if response.get("model") != model_alias:
            raise RuntimeError(
                f"candidate response model mismatch for {case['case_id']}: "
                f"expected {model_alias!r}, got {response.get('model')!r}"
            )
        elapsed_ms = round((time.perf_counter() - case_started) * 1_000, 3)
        choices = response.get("choices") or []
        if not choices or not isinstance(choices[0].get("message", {}).get("content"), str):
            raise RuntimeError(f"candidate returned no text for {case['case_id']}")
        choice = choices[0]
        text = choice["message"]["content"].strip()
        rows.append(
            {
                "case_id": case["case_id"],
                "request_id": str(request_id),
                "session_id": str(session_id),
                "response_plan": plan.model_dump(mode="json"),
                "synthetic_retrieval_result_hash": (
                    None if synthetic_retrieval is None else synthetic_retrieval.content_hash
                ),
                "provider_messages": messages,
                "provider_messages_hash": content_hash(messages),
                "raw_completion": text,
                "response_model": response["model"],
                "finish_reason": choice.get("finish_reason"),
                "response_id": response.get("id"),
                "system_fingerprint": response.get("system_fingerprint"),
                "elapsed_ms": elapsed_ms,
                "usage": response.get("usage"),
                "surface_diagnostics": surface_diagnostics(
                    text,
                    finish_reason=choice.get("finish_reason"),
                ),
            }
        )
    material = {
        "schema_version": 1,
        "evaluation_id": f"{suite['suite_id']}-{arm_name}",
        "status": "raw_candidate_screen_requires_semantic_review",
        "suite_id": suite["suite_id"],
        "suite_hash": content_hash(suite),
        "privacy_class": "PUBLIC",
        "contains_user_data": False,
        "training_eligible": False,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "arm_name": arm_name,
        "base_url": base_url,
        "model_alias": model_alias,
        "runtime_evidence": runtime_evidence,
        "identity_versions": {
            "constitution": identity.constitution.version_id,
            "identity": identity.identity.version_id,
            "values": identity.values.version_id,
        },
        "planner_version": planner.version,
        "generation_settings": GENERATION_SETTINGS,
        "source_revision": current_source_revision(PROJECT_ROOT),
        "results": rows,
        "limitations": [
            "This is a raw Replyer screen, not an end-to-end HAVRE acceptance run.",
            "Synthetic Memory is materialized as a contract-valid planner signal and injected directly; retrieval and durable admission are not scored here.",
            "Surface diagnostics are not semantic quality judgments.",
            "No result changes a model lifecycle, runtime binding, training set, or release state.",
        ],
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "completed_at": datetime.now(UTC).isoformat(),
    }
    report = seal_report(material)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    args = _parser().parse_args()
    report = run(
        base_url=args.base_url,
        model_alias=args.model_alias,
        arm_name=args.arm_name,
        output=args.output,
        runtime_state_path=args.runtime_state,
        suite_path=args.suite.resolve(),
        timeout_seconds=args.timeout_seconds,
    )
    print(report["content_hash"])


if __name__ == "__main__":
    main()
