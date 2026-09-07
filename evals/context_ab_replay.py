"""Read-only historical input replay for the context comparison.

Uses current selectors/compiler. Only Goal projection and correction/feedback
heads need historical adapters; no production query, model or target is changed.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
from pathlib import Path
from time import perf_counter
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from companion.context import ContextBuilder, load_owner_example_bank
from companion.context.corrections import owner_fact_corrections
from companion.context.presentation import render_inference_messages
from companion.context.recall import recalled_history
from companion.context.event_search import query_terms
from companion.context.response_plan import ResponsePlanner
from companion.events.models import GoalLifecyclePayload
from companion.identity import IdentityLoader
from companion.memory.semantic import LocalSemanticEmbeddingProvider
from companion.persistence.postgres import PostgresRepository
from companion.policy import PrivacyClass
from mlsys.retrieval.models import RetrievalRequest, RetrievalQuery, RetrievalFilters
from mlsys.retrieval.service import RetrievalService

ROOT = Path(__file__).resolve().parents[1]
SHARED_PERSONAL = {"owner_response_instruction", "owner_wording_correction",
                   "owner_fact_correction", "communication_preference"}


class HistoricalConnection:
    def __init__(self, connection, instant):
        self.connection, self.instant = connection, instant

    def execute(self, query, params=None):
        # Keep the current correction logic, but use the head known at T. The
        # inserted timestamp is a bound SQL parameter, never source text.
        if isinstance(query, str) and "WITH RECURSIVE corrected AS" in query:
            query = query.replace("WITH RECURSIVE corrected AS", """WITH RECURSIVE historical_heads AS (
                SELECT DISTINCT ON (owner_id,memory_id) owner_id,memory_id,revision AS current_revision,status
                FROM havre.memory_revisions WHERE created_at<=%s
                ORDER BY owner_id,memory_id,revision DESC
            ), corrected AS""").replace("FROM havre.memory_heads h", "FROM historical_heads h")
            params = (self.instant, *params)
        if isinstance(query, str) and "revision.revision=head.current_revision" in query and "response_feedback_heads" in query:
            query = query.replace("revision.revision=head.current_revision", """revision.revision=(
                SELECT max(prior.revision) FROM havre.response_feedback_revisions prior
                WHERE prior.owner_id=head.owner_id AND prior.feedback_id=head.feedback_id
                  AND prior.created_at<=%s)""")
            params = (self.instant, *params)
        return self.connection.execute(query, params)


class SnapshotPool:
    def __init__(self, connection):
        self.connection_instance = connection
        self.instant = None

    @contextmanager
    def connection(self):
        yield HistoricalConnection(self.connection_instance, self.instant)


class HistoricalRepository(PostgresRepository):
    def __init__(self, connection, encoder):
        self.pool = SnapshotPool(connection)
        self.memory_encoder = encoder

    def list_goals(self, *, owner_id, include_inactive=False):
        with self.pool.connection() as c:
            rows = c.execute("""
                SELECT DISTINCT ON (payload->>'goal_id') * FROM havre.events
                WHERE owner_id=%s AND event_type IN ('GOAL_CREATED','GOAL_UPDATED','GOAL_COMPLETED')
                  AND recorded_at<=%s
                ORDER BY payload->>'goal_id',(payload->>'goal_revision')::int DESC
            """, (owner_id, self.pool.instant)).fetchall()
        result = []
        for row in rows:
            payload = GoalLifecyclePayload.model_validate(row["payload"])
            if payload.projection_canonical_json is None:
                raise ValueError("historical Goal lacks a verifiable canonical projection")
            projected = json.loads(payload.projection_canonical_json)
            if projected["owner_id"] != str(owner_id) or projected["last_event_id"] != str(row["event_id"]):
                raise ValueError("historical Goal owner/event mismatch")
            policy = projected.pop("data_policy")
            projected.update({k: policy[k] for k in ("privacy_class", "cloud_eligible", "memory_eligible", "training_eligible", "policy_version", "policy_revision_id")})
            projected.update(policy_decision_source=policy["decision_source"],
                             policy_authorization_ref=policy["authorization_ref"],
                             updated_at=row["recorded_at"], progress_records=[])
            if include_inactive or projected["status"] in {"active", "paused"}:
                result.append(projected)
        return result


def prepare(packet: Path, database: str):
    manifest = packet / "artifact-manifest.LOCAL_ONLY.json"
    approval = json.loads((packet / "owner-approval.LOCAL_ONLY.json").read_text("utf-8"))
    if approval["decision"] != "approved" or approval["packet_manifest_sha256"] != hashlib.sha256(manifest.read_bytes()).hexdigest():
        raise ValueError("exact packet approval required")
    sealed = json.loads(manifest.read_text("utf-8"))
    corpus_path = packet / "candidate-corpus.LOCAL_ONLY.json"
    if sealed["files"][corpus_path.name] != hashlib.sha256(corpus_path.read_bytes()).hexdigest():
        raise ValueError("approved corpus changed")
    corpus = json.loads(corpus_path.read_text("utf-8"))
    allowed_ids = {UUID(s["event_id"]) for s in corpus["sources"]}
    owner = UUID(corpus["owner_id"])
    identity = IdentityLoader(ROOT / "identity").load()
    encoder = LocalSemanticEmbeddingProvider(ROOT / "var/models/memory-minilm-v1")
    bank = load_owner_example_bank(ROOT / ".runtime/desktop/config/owner-example-bank-oa70-all70-v2.json", owner_id=owner)
    full = ContextBuilder(max_input_tokens=16384, reserved_output_tokens=3072,
                          owner_timezone="America/Chicago", owner_example_bank=bank)
    simple = ContextBuilder(max_input_tokens=16384, reserved_output_tokens=3072,
                            owner_timezone="America/Chicago")
    planner = ResponsePlanner(semantic_memory=True)
    rows = []
    destination = packet / "replay-inputs.LOCAL_ONLY.json"
    if destination.exists():
        raise ValueError("input replay is immutable; choose a new packet revision")
    with psycopg.connect(database, row_factory=dict_row,
                         options="-c default_transaction_read_only=on -c timezone=UTC -c statement_timeout=15000") as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        verified = c.execute("select current_database() db,inet_server_port() port,current_setting('transaction_read_only') ro").fetchone()
        if verified != {"db": "havre_local_20260822", "port": 55432, "ro": "on"}:
            raise ValueError("exact read-only source target required")
        repository = HistoricalRepository(c, encoder)
        retrieval = RetrievalService(repository=repository, embedding_provider=encoder)
        revoked = c.execute("SELECT source_event_id FROM havre.offline_source_revocations WHERE owner_id=%s AND source_event_id=ANY(%s::uuid[])", (owner, list(allowed_ids))).fetchall()
        if revoked:
            raise ValueError("approved source was revoked; invalidate packet")
        for case in corpus["cases"]:
            user = repository.event_by_id(owner_id=owner, event_id=UUID(case["current_event_id"]))
            if user.content_hash != next(s["source_content_hash"] for s in corpus["sources"] if s["event_id"] == case["current_event_id"]):
                raise ValueError("current source differs from reviewed source")
            repository.pool.instant = user.recorded_at
            query = "\n".join(p.text for p in user.payload.content_parts)
            started = perf_counter()
            personal = repository.select_personal_context(owner_id=owner, query_text=query,
                maximum_privacy_class=PrivacyClass.NORMAL, as_of=user.recorded_at)
            recent = repository.select_conversation_history(owner_id=owner, session_id=user.session_id,
                exclude_event_id=user.event_id, maximum_privacy_class=PrivacyClass.NORMAL,
                continuous_chat=True, as_of=user.recorded_at)
            recent = tuple(t for t in recent if t.event_id in allowed_ids)
            history = recalled_history(repository, owner_id=owner, query=query, current_event=user,
                recent=recent, explicit=planner.refers_to_prior_context(query), timezone_name="America/Chicago")
            history = tuple(t for t in history if t.event_id in allowed_ids)
            if any(t.recorded_at >= user.recorded_at or t.request_id == user.request_id for t in history):
                raise ValueError("future or target-answer leakage")
            plan = planner.plan(request_id=user.request_id, trace_id=user.trace_id, owner_id=owner,
                message=query, source_refs=(f"event/{user.event_id}",), conversation_history=history, personal_context=personal)
            request = RetrievalRequest(request_id=user.request_id, trace_id=user.trace_id, owner_id=owner,
                query=RetrievalQuery(text=plan.memory_query or query, event_id=user.event_id), as_of=user.recorded_at,
                filters=RetrievalFilters(allowed_privacy_classes=(PrivacyClass.PUBLIC, PrivacyClass.NORMAL)),
                algorithm_version=retrieval.default_algorithm)
            result = (retrieval.retrieve_empty(request, persist=False) if plan.memory_need == "none"
                      else retrieval.retrieve(request, persist=False))
            corrections = owner_fact_corrections(repository, owner_id=owner, current_event=user,
                history=history, retrieval_result=result)
            args = dict(request_id=user.request_id, trace_id=user.trace_id, owner_id=owner, identity=identity,
                        user_event=user, conversation_history=history)
            full_pack = full.build(**args, personal_context=(*personal, *corrections), retrieval_result=result, response_plan=plan)
            full_ms = (perf_counter()-started)*1000
            # Independent compilation returns freed budget to the raw history;
            # it is not a post-hoc deletion from a full pack.
            simple_started = perf_counter()
            simple_history = recalled_history(repository, owner_id=owner, query=query, current_event=user,
                recent=recent, explicit=bool(query_terms(query)) or planner.refers_to_prior_context(query),
                timezone_name="America/Chicago")
            simple_history = tuple(t for t in simple_history if t.event_id in allowed_ids)
            if any(t.recorded_at >= user.recorded_at or t.request_id == user.request_id for t in simple_history):
                raise ValueError("simple history contains future or target-answer leakage")
            simple_corrections = owner_fact_corrections(repository, owner_id=owner, current_event=user,
                history=simple_history, retrieval_result=retrieval.retrieve_empty(request, persist=False))
            simple_args = {**args, "conversation_history":simple_history}
            simple_pack = simple.build(**simple_args, personal_context=tuple(p for p in (*personal, *simple_corrections)
                                                                             if p.section_type in SHARED_PERSONAL))
            simple_ms = (perf_counter()-simple_started)*1000
            for pack in (full_pack, simple_pack):
                if any(s.data_policy.privacy_class not in {PrivacyClass.PUBLIC, PrivacyClass.NORMAL}
                       or not s.data_policy.cloud_eligible or s.data_policy.training_eligible for s in pack.sections):
                    raise ValueError("an input source is not ordinary-cloud eligible")
            rows.append({"case_id":case["case_id"], "as_of":case["as_of"], "current_text":query,
                         "historical_adapter":"canonical-goal-event/latest-known-correction-and-feedback-head-v1",
                         "full_prepare_ms":full_ms, "simple_incremental_prepare_ms":simple_ms,
                         "prepare_timing_limit":"simple excludes shared preference selection; report generation latency separately",
                         "full":full_pack.model_dump(mode="json"), "simple":simple_pack.model_dump(mode="json"),
                         "raw_prior_evidence":[s for s in corpus["sources"] if s["event_id"] in case["available_prior_event_ids"]]})
            print(json.dumps({"prepared":case["case_id"], "full_layers":sorted({s.section_type for s in full_pack.sections}),
                              "full_tokens":full_pack.estimated_total_tokens, "simple_tokens":simple_pack.estimated_total_tokens}), flush=True)
    destination.write_text(json.dumps({"policy":corpus["policy"], "source_packet_hash":approval["packet_manifest_sha256"],
                                      "cases":rows}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return destination


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--packet",type=Path,required=True)
    parser.add_argument("--database-url",required=True)
    args=parser.parse_args()
    prepare(args.packet,args.database_url)
