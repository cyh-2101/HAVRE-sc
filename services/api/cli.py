"""Operational commands for the active HAVRE Stage 10 vertical slice."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import uvicorn
from fastapi.encoders import jsonable_encoder

from companion.application import InteractionCommand
from companion.ids import uuid7
from companion.identity import IdentityLoader
from companion.persistence import PostgresRepository, apply_migrations
from companion.policy import PrivacyClass
from services.api.app import create_app
from services.api.runtime import attest_self_hosted_runtime, build_runtime
from services.api.settings import Settings


logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="havre")
    subparsers = parser.add_subparsers(dest="command", required=True)
    migrate = subparsers.add_parser(
        "migrate", help="apply checksum-verified database migrations"
    )
    migrate.add_argument(
        "--bootstrap-owner",
        action="store_true",
        help="provision the configured owner and approved identity after migration",
    )
    serve = subparsers.add_parser("serve", help="run the FastAPI service")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8000, type=int)
    demo = subparsers.add_parser("demo", help="run and print one complete Companion request")
    demo.add_argument(
        "message",
        nargs="?",
        default="I have been avoiding a difficult task and want one grounded next step.",
    )
    demo.add_argument(
        "--privacy",
        choices=[item.value for item in PrivacyClass],
        default=PrivacyClass.PRIVATE.value,
    )
    demo.add_argument("--idempotency-key", default=None)
    subparsers.add_parser(
        "chat",
        help="open a LOCAL_ONLY developer chat session",
    )
    subparsers.add_parser(
        "chat-owner",
        help="open LOCAL_ONLY owner chat with explicit reviewed-memory decisions",
    )
    subparsers.add_parser(
        "attest-runtime",
        help="verify the active pinned Stage 3 model process without using the database",
    )
    subparsers.add_parser(
        "attest-candidate-runtime",
        help="verify the active local Seed 9201 development-candidate process",
    )
    evidence = subparsers.add_parser("evidence", help="print durable evidence by request ID")
    evidence.add_argument("request_id", type=UUID)
    subparsers.add_parser("worker-once", help="claim and execute one durable memory job")
    worker_loop = subparsers.add_parser(
        "worker-loop",
        help="run the durable memory, proactive-simulation, and offline queues",
    )
    worker_loop.add_argument("--poll-seconds", type=float, default=2.0)
    candidates = subparsers.add_parser("memory-candidates", help="list inspectable memory candidates")
    candidates.add_argument("--status", default="pending", choices=["pending", "accepted", "rejected", "duplicate"])
    accept = subparsers.add_parser("memory-accept", help="owner-accept a memory candidate")
    accept.add_argument("candidate_id", type=UUID)
    accept.add_argument("--reason", default="Owner reviewed and accepted")
    accept.add_argument("--importance", type=float, default=None)
    reject = subparsers.add_parser("memory-reject", help="owner-reject a memory candidate")
    reject.add_argument("candidate_id", type=UUID)
    reject.add_argument("--reason", default="Owner reviewed and rejected")
    subparsers.add_parser("memories", help="list active episodic memories")
    subparsers.add_parser(
        "audit-provenance",
        help="report source-side provenance integrity violations",
    )
    correct = subparsers.add_parser("memory-correct", help="append a corrected memory revision")
    correct.add_argument("memory_id", type=UUID)
    correct.add_argument("content_text")
    correct.add_argument("--reason", default="Owner correction")
    retract = subparsers.add_parser("memory-retract", help="append a retracted memory revision")
    retract.add_argument("memory_id", type=UUID)
    retract.add_argument("--reason", default="Owner retraction")
    benchmark = subparsers.add_parser("benchmark-retrieval", help="run retrieval gold set v1")
    benchmark.add_argument("--fixture", type=Path, default=Path("evals/fixtures/retrieval_gold_v1.json"))
    benchmark.add_argument("--output", type=Path, default=Path("var/benchmarks/stage2_retrieval.json"))
    inference_benchmark = subparsers.add_parser(
        "benchmark-inference",
        help="benchmark an already-running pinned Stage 3 local provider",
    )
    inference_benchmark.add_argument(
        "--output-directory",
        type=Path,
        default=Path("var/benchmarks/stage3-inference"),
    )
    user_model_eval = subparsers.add_parser(
        "evaluate-user-model",
        help="run the frozen synthetic Stage 4 evidence-sequence suite",
    )
    user_model_eval.add_argument(
        "--fixture",
        type=Path,
        default=Path("evals/fixtures/user_model_evidence_sequences_v1.json"),
    )
    user_model_eval.add_argument(
        "--output",
        type=Path,
        default=Path("var/evaluations/stage4-user-model.json"),
    )
    scene_eval = subparsers.add_parser(
        "evaluate-scenes",
        help="run the frozen synthetic Stage 5 intervention-policy suite",
    )
    scene_eval.add_argument(
        "--fixture",
        type=Path,
        default=Path("evals/fixtures/scene_policy_cases_v1.json"),
    )
    scene_eval.add_argument(
        "--output",
        type=Path,
        default=Path("var/evaluations/stage5-scene-policy.json"),
    )
    release_build = subparsers.add_parser(
        "release-build", help="build an immutable source-bound release manifest"
    )
    release_build.add_argument("--release-id", required=True)
    release_build.add_argument(
        "--environment", choices=["development", "staging", "production"], required=True
    )
    release_build.add_argument(
        "--scope",
        choices=["infrastructure_only", "development_candidate_fixture", "production"],
        required=True,
    )
    release_build.add_argument("--output", type=Path, required=True)
    release_build.add_argument("--adapter-version")
    release_build.add_argument("--adapter-hash")
    release_build.add_argument(
        "--adapter-deployment-authorized", action="store_true"
    )
    release_build.add_argument("--promotion-approval-ref")
    release_build.add_argument("--rollback-manifest-hash")
    release_build.add_argument("--runtime-image-reference")
    release_build.add_argument("--runtime-image-digest")
    release_validate = subparsers.add_parser(
        "release-validate", help="validate an immutable release manifest"
    )
    release_validate.add_argument("manifest", type=Path)
    release_preflight = subparsers.add_parser(
        "release-preflight",
        help="read-only verification of the actual release login and durable gate",
    )
    release_preflight.add_argument("manifest", type=Path)
    release_approval = subparsers.add_parser(
        "release-approval-record",
        help="record an explicit Product Owner release decision",
    )
    release_approval.add_argument("manifest", type=Path)
    release_approval.add_argument(
        "--scope",
        choices=[
            "infrastructure_production_release",
            "personalized_adapter_release",
        ],
        required=True,
    )
    release_approval.add_argument(
        "--decision", choices=["approved", "rejected"], required=True
    )
    release_approval.add_argument("--rationale", required=True)
    deployment_record = subparsers.add_parser(
        "deployment-record",
        help="record an immutable deploy, failure, or pinned rollback transition",
    )
    deployment_record.add_argument("manifest", type=Path)
    deployment_record.add_argument("--action", choices=["deploy", "rollback"], required=True)
    deployment_record.add_argument(
        "--status", choices=["planned", "applied", "failed"], required=True
    )
    deployment_record.add_argument("--previous-deployment-id", type=UUID)
    deployment_record.add_argument("--health-evidence", type=Path)
    deployment_record.add_argument("--failure-code")
    owner_export = subparsers.add_parser(
        "owner-export", help="write and verify a complete LOCAL_ONLY owner export"
    )
    owner_export.add_argument("output", type=Path)
    erase_source = subparsers.add_parser(
        "erase-source-event", help="erase one raw source event and its derived closure"
    )
    erase_source.add_argument("source_event_id", type=UUID)
    erase_source.add_argument("--confirm", required=True)
    erase_context = subparsers.add_parser(
        "erase-context-source",
        help="erase one complete external Context Source and retain its tombstone",
    )
    erase_context.add_argument("source_instance_id", type=UUID)
    erase_context.add_argument("--confirm", required=True)
    subparsers.add_parser(
        "context-retention-expire",
        help="erase only server-time-due external-context observations",
    )
    retention_loop = subparsers.add_parser(
        "context-retention-loop",
        help="continuously execute server-time-due context retention without sensing",
    )
    retention_loop.add_argument("--poll-seconds", type=float, default=60.0)
    backup = subparsers.add_parser(
        "backup-create", help="create a checksum-bound PostgreSQL custom backup"
    )
    backup.add_argument("--release-manifest", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    backup.add_argument("--expires-days", type=int, required=True)
    backup.add_argument("--pg-dump", type=Path, required=True)
    backup.add_argument("--pg-restore", type=Path, required=True)
    restore = subparsers.add_parser(
        "backup-restore", help="restore to an empty database and replay erasures"
    )
    restore.add_argument("--artifact", type=Path, required=True)
    restore.add_argument("--manifest", type=Path, required=True)
    restore.add_argument("--target-database-url-file", type=Path, required=True)
    restore.add_argument("--restore-id", type=UUID, required=True)
    restore.add_argument("--pg-dump", type=Path, required=True)
    restore.add_argument("--pg-restore", type=Path, required=True)
    prune = subparsers.add_parser(
        "backup-prune", help="verify and remove only expired local backup pairs"
    )
    prune.add_argument("--root", type=Path, required=True)
    prune.add_argument("--confirm", required=True)
    prune.add_argument("--pg-dump", type=Path, required=True)
    prune.add_argument("--pg-restore", type=Path, required=True)
    return parser


async def _demo(args: argparse.Namespace, settings: Settings) -> dict[str, object]:
    runtime = build_runtime(settings)
    try:
        _require_active_behavior_release(runtime, settings, actor="demo")
        result = await runtime.service.interact(
            InteractionCommand(
                message=args.message,
                privacy_class=PrivacyClass(args.privacy),
                channel="cli",
                idempotency_key=demo_idempotency_key(args.idempotency_key),
            )
        )
        evidence = runtime.repository.evidence(
            result.request_id,
            owner_id=settings.owner_id,
        )
        return {
            "result": result.model_dump(mode="json"),
            "evidence": evidence,
        }
    finally:
        await runtime.aclose()


def demo_idempotency_key(provided: str | None) -> str:
    return provided or f"stage5-demo-{uuid7()}"


async def run_local_chat_loop(
    service: object,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> UUID:
    """Run a thin developer UI over the real Companion interaction service.

    A single durable session is reused, but prior text is not copied into later
    prompts. Versioned retrieval and ContextPack rules remain the only context
    authority.
    """

    session_id = uuid7()
    turn = 0
    output_fn("HAVRE Local")
    output_fn("")
    while True:
        try:
            message = input_fn("You: ")
        except (EOFError, KeyboardInterrupt):
            output_fn("")
            break
        if message.strip().lower() in {"/exit", "/quit"}:
            break
        if not message.strip():
            continue
        turn += 1
        result = await service.interact(  # type: ignore[attr-defined]
            InteractionCommand(
                message=message,
                privacy_class=PrivacyClass.LOCAL_ONLY,
                memory_eligible=False,
                session_id=session_id,
                channel="cli",
                idempotency_key=f"stage5-chat-{session_id}-{turn}",
            )
        )
        output_fn(f"HAVRE: {result.content}")
        output_fn("")
    return session_id


async def _chat(settings: Settings) -> None:
    runtime = build_runtime(settings)
    try:
        _require_active_behavior_release(runtime, settings, actor="chat")
        await run_local_chat_loop(runtime.service)
    finally:
        await runtime.aclose()


def _print_memory_rows(rows: object, *, output_fn: Callable[[str], None]) -> None:
    if not isinstance(rows, list) or not rows:
        output_fn("No matching memories.")
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        identifier = row.get("memory_id") or row.get("candidate_id")
        output_fn(f"- {identifier}: {row.get('content_text', '')}")


async def run_owner_chat_loop(
    runtime: object,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> UUID:
    """Owner-local chat whose memory path always stops for explicit review."""

    session_id = uuid7()
    turn = 0
    output_fn("HAVRE Owner Local - Seed 9201 development candidate")
    output_fn("Memory is saved only after your explicit acceptance.")
    output_fn("Commands: /memories, /pending, /exit")
    output_fn("")
    while True:
        try:
            message = input_fn("You: ")
        except (EOFError, KeyboardInterrupt):
            output_fn("")
            break
        normalized = message.strip().lower()
        if normalized in {"/exit", "/quit"}:
            break
        if normalized == "/memories":
            rows = await asyncio.to_thread(
                runtime.memory_service.list_active,
                owner_id=runtime.settings.owner_id,
            )
            _print_memory_rows(rows, output_fn=output_fn)
            output_fn("")
            continue
        if normalized == "/pending":
            rows = await asyncio.to_thread(
                runtime.memory_service.list_candidates,
                owner_id=runtime.settings.owner_id,
                status="pending",
            )
            _print_memory_rows(rows, output_fn=output_fn)
            output_fn("")
            continue
        if not message.strip():
            continue
        turn += 1
        result = await runtime.service.interact(
            InteractionCommand(
                message=message,
                privacy_class=PrivacyClass.LOCAL_ONLY,
                memory_eligible=True,
                session_id=session_id,
                channel="cli",
                idempotency_key=f"owner-chat-{session_id}-{turn}",
            )
        )
        output_fn(f"HAVRE: {result.content}")
        output_fn("")
        candidate = await asyncio.to_thread(runtime.memory_worker.run_once)
        if candidate is None:
            output_fn("Memory: no candidate was produced.")
            output_fn("")
            continue
        if candidate.get("source_event_id") != result.user_event_id:
            raise RuntimeError("memory worker returned a candidate for a different source event")
        output_fn("Memory candidate (not saved yet):")
        output_fn(str(candidate.get("content_text", "")))
        try:
            decision = input_fn("Accept [a], reject [r], or keep pending [Enter]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            output_fn("")
            decision = ""
        if decision in {"a", "accept", "y", "yes"}:
            revision = await asyncio.to_thread(
                runtime.memory_service.accept_candidate,
                owner_id=runtime.settings.owner_id,
                candidate_id=candidate["candidate_id"],
                reason="Owner accepted during local reviewed-memory chat",
            )
            output_fn(f"Memory saved: {revision.memory_id}")
        elif decision in {"r", "reject", "n", "no"}:
            await asyncio.to_thread(
                runtime.memory_service.reject_candidate,
                owner_id=runtime.settings.owner_id,
                candidate_id=candidate["candidate_id"],
                reason="Owner rejected during local reviewed-memory chat",
            )
            output_fn("Memory rejected.")
        else:
            output_fn("Memory kept pending; it will not be retrieved until accepted.")
        output_fn("")
    return session_id


async def _chat_owner(settings: Settings) -> None:
    runtime = build_runtime(settings)
    try:
        _require_active_behavior_release(runtime, settings, actor="owner chat")
        await run_owner_chat_loop(runtime)
    finally:
        await runtime.aclose()


def _require_active_behavior_release(
    runtime: object,
    settings: Settings,
    *,
    actor: str,
) -> None:
    if settings.deployment_environment not in {"staging", "production"}:
        return
    release = runtime.release_manifest
    if release is None:
        raise RuntimeError(f"{actor} requires an immutable release")
    if (
        settings.deployment_environment == "production"
        and release.release_scope != "production"
    ):
        raise RuntimeError(
            f"{actor} is inactive for an infrastructure-only release"
        )
    runtime.operations_store.require_release_activation(release)


def _worker_loop(settings: Settings, *, poll_seconds: float) -> None:
    if poll_seconds < 0.1 or poll_seconds > 60:
        raise ValueError("worker poll interval must be between 0.1 and 60 seconds")
    runtime = build_runtime(settings)
    def require_active_release() -> None:
        _require_active_behavior_release(
            runtime,
            settings,
            actor="behavior worker",
        )

    try:
        require_active_release()
    except Exception:
        runtime.close()
        raise
    stopping = threading.Event()

    def stop(_signum, _frame) -> None:
        stopping.set()

    prior_handlers = {}
    for name in ("SIGINT", "SIGTERM"):
        candidate = getattr(signal, name, None)
        if candidate is not None:
            prior_handlers[candidate] = signal.signal(candidate, stop)
    understanding_executor = ThreadPoolExecutor(max_workers=3,thread_name_prefix="havre-understanding")
    understanding_futures = {}
    def advance_understanding(name, operation):
        prior=understanding_futures.get(name)
        if prior is not None and not prior.done():
            return
        if prior is not None:
            try:
                prior.result()
            except Exception:
                logger.exception("owner-local %s work failed; durable retry is scheduled",name)
        understanding_futures[name]=understanding_executor.submit(lambda: asyncio.run(operation()))
    try:
        heartbeat_ttl = max(15.0, min(300.0, poll_seconds * 3 + 35.0))
        last_daily_goal_schedule_at: datetime | None = None
        runtime.web_push_provider.record_worker_heartbeat(
            status="running", live_for_seconds=heartbeat_ttl
        )
        while not stopping.is_set():
            require_active_release()
            runtime.web_push_provider.record_worker_heartbeat(
                status="running", live_for_seconds=heartbeat_ttl
            )
            evaluation = runtime.proactive_evaluator.run_once()
            if (
                settings.relational_initiative_enabled
                and (
                    last_daily_goal_schedule_at is None
                    or datetime.now(UTC) - last_daily_goal_schedule_at
                    >= timedelta(minutes=15)
                )
            ):
                try:
                    runtime.proactive_store.enqueue_daily_goal_check_ins(
                        timezone_name=settings.owner_timezone,
                    )
                except Exception:
                    logger.exception(
                        "daily Goal reminder fill failed and will retry"
                    )
                finally:
                    last_daily_goal_schedule_at = datetime.now(UTC)
            diary_service = getattr(runtime, "diary_intelligence_service", None)
            daily_review = None
            if diary_service is not None:
                advance_understanding("daily-review",lambda:diary_service.run_scheduled_once(
                        worker_id="stage10-worker-diary",
                        timezone_name=settings.owner_timezone,
                    ))
            realtime_service=getattr(runtime,"realtime_memory_service",None)
            if realtime_service is not None:
                advance_understanding("realtime-memory",realtime_service.run_once)
            continuation = None
            continuation_service = getattr(
                runtime, "conversation_continuation_service", None
            )
            if continuation_service is not None:
                advance_understanding("conversation-continuation",lambda:continuation_service.run_once(
                            worker_id="stage10-worker-continuation"
                        ))
            work = (
                runtime.memory_worker.run_once(),
                runtime.proactive_store.run_work_once(worker_id="stage10-worker"),
                runtime.offline_store.run_once(worker_id="stage10-worker"),
            )
            push = runtime.web_push_provider.deliver_pending(limit=10)
            push_activity = sum(
                int(push.get(key, 0))
                for key in ("queued", "delivered", "failed", "skipped")
            )
            runtime.web_push_provider.record_worker_heartbeat(
                status="running", live_for_seconds=heartbeat_ttl
            )
            if (
                evaluation["evaluated"] == 0
                and continuation is None
                and not any(item is not None for item in work)
                and push_activity == 0
            ):
                stopping.wait(poll_seconds)
    finally:
        understanding_executor.shutdown(wait=True,cancel_futures=True)
        try:
            runtime.web_push_provider.record_worker_heartbeat(
                status="stopped", live_for_seconds=1
            )
        except Exception:
            pass
        for candidate, handler in prior_handlers.items():
            signal.signal(candidate, handler)
        runtime.close()


def _context_retention_loop(settings: Settings, *, poll_seconds: float) -> None:
    if poll_seconds < 1 or poll_seconds > 3600:
        raise ValueError("retention poll interval must be between 1 and 3600 seconds")
    if settings.privileged_database_url is None:
        raise ValueError("privileged erasure database URL is required")
    runtime = build_runtime(settings)
    stopping = threading.Event()

    def stop(_signum, _frame) -> None:
        stopping.set()

    prior_handlers = {}
    for name in ("SIGINT", "SIGTERM"):
        candidate = getattr(signal, name, None)
        if candidate is not None:
            prior_handlers[candidate] = signal.signal(candidate, stop)
    try:
        while not stopping.is_set():
            runtime.operations_store.expire_context_retention(
                ledger=runtime.erasure_ledger
            )
            stopping.wait(poll_seconds)
    finally:
        for candidate, handler in prior_handlers.items():
            signal.signal(candidate, handler)
        runtime.close()


def main() -> None:
    args = _parser().parse_args()
    offline_commands = {
        "migrate",
        "release-build",
        "release-validate",
        "release-preflight",
        "release-approval-record",
        "deployment-record",
        "owner-export",
        "erase-source-event",
        "erase-context-source",
        "context-retention-expire",
        "context-retention-loop",
        "backup-create",
        "backup-restore",
        "backup-prune",
        "attest-runtime",
        "attest-candidate-runtime",
        "worker-loop",
    }
    settings = Settings.from_env(
        require_owner_api_token=(
            args.command not in offline_commands or args.command == "worker-loop"
        ),
        enable_erasure_ledger=args.command != "worker-loop",
    )
    project_root = Path(__file__).resolve().parents[2]
    if args.command == "migrate":
        applied = apply_migrations(
            settings.database_url,
            project_root / "db" / "migrations",
        )
        owner_bootstrapped = False
        if args.bootstrap_owner:
            repository = PostgresRepository(settings.database_url)
            repository.open()
            try:
                repository.bootstrap_owner_and_identity(
                    owner_id=settings.owner_id,
                    identity=IdentityLoader(settings.identity_root).load(),
                )
                owner_bootstrapped = True
            finally:
                repository.close()
        print(
            json.dumps(
                {
                    "applied": applied,
                    "owner_bootstrapped": owner_bootstrapped,
                },
                indent=2,
            )
        )
        return
    if args.command == "serve":
        uvicorn.run(
            create_app(settings),
            host=args.host,
            port=args.port,
            reload=False,
        )
        return
    if args.command == "demo":
        payload = asyncio.run(_demo(args, settings))
        print(json.dumps(jsonable_encoder(payload), indent=2, ensure_ascii=False))
        return
    if args.command == "chat":
        asyncio.run(_chat(settings))
        return
    if args.command == "chat-owner":
        asyncio.run(_chat_owner(settings))
        return
    if args.command == "attest-runtime":
        attestation = attest_self_hosted_runtime(settings, write=True)
        print(attestation.model_dump_json(indent=2))
        return
    if args.command == "attest-candidate-runtime":
        from mlsys.serving.stage9a_candidate import attest_stage9a_candidate_runtime

        attestation = attest_stage9a_candidate_runtime(
            project_root=Path(__file__).resolve().parents[2],
            base_url=settings.self_hosted_base_url,
            write=True,
        )
        print(attestation.model_dump_json(indent=2))
        return
    if args.command == "evidence":
        runtime = build_runtime(settings)
        try:
            bundle = runtime.repository.evidence(
                args.request_id,
                owner_id=settings.owner_id,
            )
            if bundle is None:
                raise SystemExit("request not found")
            print(json.dumps(jsonable_encoder(bundle), indent=2, ensure_ascii=False))
        finally:
            runtime.close()
        return
    if args.command in {
        "worker-once", "memory-candidates", "memory-accept", "memory-reject",
        "memories", "memory-correct", "memory-retract", "audit-provenance"
    }:
        runtime = build_runtime(settings)
        try:
            if args.command == "worker-once":
                _require_active_behavior_release(
                    runtime,
                    settings,
                    actor="behavior worker",
                )
                payload = runtime.memory_worker.run_once()
            elif args.command == "memory-candidates":
                payload = runtime.memory_service.list_candidates(owner_id=settings.owner_id, status=args.status)
            elif args.command == "memory-accept":
                payload = runtime.memory_service.accept_candidate(
                    owner_id=settings.owner_id, candidate_id=args.candidate_id,
                    reason=args.reason, importance=args.importance,
                )
            elif args.command == "memory-reject":
                payload = runtime.memory_service.reject_candidate(owner_id=settings.owner_id, candidate_id=args.candidate_id, reason=args.reason)
            elif args.command == "memories":
                payload = runtime.memory_service.list_active(owner_id=settings.owner_id)
            elif args.command == "audit-provenance":
                payload = runtime.repository.audit_provenance_integrity()
            elif args.command == "memory-correct":
                payload = runtime.memory_service.correct(owner_id=settings.owner_id, memory_id=args.memory_id, content_text=args.content_text, reason=args.reason)
            else:
                payload = runtime.memory_service.retract(owner_id=settings.owner_id, memory_id=args.memory_id, reason=args.reason)
            print(json.dumps(jsonable_encoder(payload), indent=2, ensure_ascii=False))
            if args.command == "audit-provenance" and payload:
                raise SystemExit(2)
        finally:
            runtime.close()
        return
    if args.command == "worker-loop":
        _worker_loop(settings, poll_seconds=args.poll_seconds)
        return
    if args.command == "context-retention-loop":
        _context_retention_loop(settings, poll_seconds=args.poll_seconds)
        return
    if args.command in {
        "release-build", "release-validate", "release-preflight",
        "release-approval-record",
        "deployment-record", "owner-export",
        "erase-source-event", "backup-create", "backup-restore", "backup-prune",
        "erase-context-source",
        "context-retention-expire",
    }:
        from services.api.operations_cli import (
            build_release_manifest,
            create_backup,
            erase_context_source,
            erase_source,
            expire_context_retention,
            export_owner,
            load_release_manifest,
            verify_release_preflight,
            record_deployment,
            record_release_approval,
            restore_backup,
            prune_backups,
        )

        if args.command == "release-build":
            payload = build_release_manifest(
                settings=settings,
                release_id=args.release_id,
                environment=args.environment,
                release_scope=args.scope,
                output=args.output,
                adapter_version=args.adapter_version,
                adapter_hash=args.adapter_hash,
                adapter_deployment_authorized=args.adapter_deployment_authorized,
                promotion_approval_ref=args.promotion_approval_ref,
                rollback_manifest_hash=args.rollback_manifest_hash,
                runtime_image_reference=args.runtime_image_reference,
                runtime_image_digest=args.runtime_image_digest,
            )
        elif args.command == "release-validate":
            payload = load_release_manifest(args.manifest)
        elif args.command == "release-preflight":
            payload = verify_release_preflight(
                settings=settings,
                manifest_path=args.manifest,
            )
        elif args.command == "release-approval-record":
            payload = record_release_approval(
                settings=settings,
                manifest_path=args.manifest,
                approval_scope=args.scope,
                decision=args.decision,
                rationale=args.rationale,
            )
        elif args.command == "deployment-record":
            payload = record_deployment(
                settings=settings,
                manifest_path=args.manifest,
                action=args.action,
                status=args.status,
                previous_deployment_id=args.previous_deployment_id,
                health_evidence_path=args.health_evidence,
                failure_code=args.failure_code,
            )
        elif args.command == "owner-export":
            payload = export_owner(settings=settings, output=args.output)
        elif args.command == "erase-source-event":
            payload = erase_source(
                settings=settings,
                source_event_id=args.source_event_id,
                confirmation=args.confirm,
            )
        elif args.command == "erase-context-source":
            payload = erase_context_source(
                settings=settings,
                source_instance_id=args.source_instance_id,
                confirmation=args.confirm,
            )
        elif args.command == "context-retention-expire":
            payload = expire_context_retention(settings=settings)
        elif args.command == "backup-create":
            payload = create_backup(
                settings=settings,
                release_manifest_path=args.release_manifest,
                output=args.output,
                expires_days=args.expires_days,
                pg_dump=args.pg_dump,
                pg_restore=args.pg_restore,
            )
        elif args.command == "backup-restore":
            target_url = args.target_database_url_file.read_text(
                encoding="utf-8"
            ).strip()
            if not target_url:
                raise ValueError("restore target database URL secret file is empty")
            payload = restore_backup(
                settings=settings,
                artifact=args.artifact,
                manifest=args.manifest,
                target_database_url=target_url,
                restore_id=args.restore_id,
                pg_dump=args.pg_dump,
                pg_restore=args.pg_restore,
            )
        else:
            payload = prune_backups(
                settings=settings,
                root=args.root,
                confirmation=args.confirm,
                pg_dump=args.pg_dump,
                pg_restore=args.pg_restore,
            )
        print(json.dumps(jsonable_encoder(payload), indent=2, ensure_ascii=False))
        return
    if args.command == "benchmark-retrieval":
        from evals.retrieval_benchmark import run_benchmark
        payload = asyncio.run(run_benchmark(settings=settings, fixture_path=args.fixture, output_path=args.output))
        print(json.dumps(jsonable_encoder(payload), indent=2, ensure_ascii=False))
        return
    if args.command == "evaluate-user-model":
        from evals.user_model_evaluation import run_user_model_evaluation

        fixture = args.fixture if args.fixture.is_absolute() else project_root / args.fixture
        output = args.output if args.output.is_absolute() else project_root / args.output
        apply_migrations(settings.database_url, project_root / "db" / "migrations")
        repository = PostgresRepository(settings.database_url)
        repository.open()
        try:
            report = run_user_model_evaluation(
                fixture_path=fixture,
                output_path=output,
                persistence=repository,
                project_root=project_root,
            )
        finally:
            repository.close()
        print(json.dumps({
            "evaluation_run_id": str(report.evaluation_run_id),
            "suite_version": report.suite_version,
            "metrics": report.metrics,
            "content_hash": report.content_hash,
            "output": str(output),
        }, indent=2, ensure_ascii=False))
        return
    if args.command == "evaluate-scenes":
        from evals.scene_evaluation import run_scene_policy_evaluation

        fixture = args.fixture if args.fixture.is_absolute() else project_root / args.fixture
        output = args.output if args.output.is_absolute() else project_root / args.output
        apply_migrations(settings.database_url, project_root / "db" / "migrations")
        repository = PostgresRepository(settings.database_url)
        repository.open()
        try:
            report = run_scene_policy_evaluation(
                fixture_path=fixture,
                identity=IdentityLoader(settings.identity_root).load(),
                output_path=output,
                persistence=repository,
                project_root=project_root,
            )
        finally:
            repository.close()
        print(json.dumps({
            "evaluation_run_id": str(report.evaluation_run_id),
            "suite_version": report.suite_version,
            "metrics": report.metrics,
            "content_hash": report.content_hash,
            "output": str(output),
        }, indent=2, ensure_ascii=False))
        return
    if args.command == "benchmark-inference":
        from evals.inference_runner import (
            current_source_revision,
            run_live_inference_benchmark,
        )

        code_revision = current_source_revision(project_root)
        output_directory = (
            args.output_directory
            if args.output_directory.is_absolute()
            else project_root / args.output_directory
        )
        apply_migrations(settings.database_url, project_root / "db" / "migrations")
        repository = PostgresRepository(settings.database_url)
        repository.open()
        try:
            systems, compatibility = asyncio.run(
                run_live_inference_benchmark(
                    settings=settings,
                    output_directory=output_directory,
                    code_revision=code_revision,
                    persistence=repository,
                )
            )
        finally:
            repository.close()
        print(
            json.dumps(
                {
                    "systems_report": {
                        "benchmark_run_id": str(systems.benchmark_run_id),
                        "status": systems.status,
                        "content_hash": systems.content_hash,
                        "output": str(
                            output_directory / "inference-systems.json"
                        ),
                    },
                    "compatibility_report": {
                        "compatibility_run_id": str(
                            compatibility.compatibility_run_id
                        ),
                        "binding_evaluation": compatibility.binding_evaluation,
                        "gate_status": compatibility.gate_status,
                        "content_hash": compatibility.content_hash,
                        "output": str(
                            output_directory / "inference-compatibility.json"
                        ),
                    },
                    "workload_manifest": str(
                        output_directory / "inference-workload.json"
                    ),
                    "baseline_manifest": str(
                        output_directory / "inference-baseline-system.json"
                    ),
                },
                indent=2,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
