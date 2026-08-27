"""Stage 8 unified evaluation, evidence, review, and trace contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from companion.hashing import content_hash
from companion.ids import uuid7
from companion.policy import DataPolicy, PrivacyClass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceDomain(StrEnum):
    BEHAVIORAL = "behavioral"
    RETRIEVAL = "retrieval"
    CONTEXT = "context"
    ROUTING = "routing"
    INFERENCE = "inference"
    PROACTIVE = "proactive"
    MEMORY_LIFECYCLE = "memory_lifecycle"
    ERASURE_REGENERATION = "erasure_regeneration"
    SOURCE_HEALTH = "source_health"
    REGRESSION = "regression"


REQUIRED_STAGE8_DOMAINS = frozenset(
    {
        EvidenceDomain.BEHAVIORAL,
        EvidenceDomain.RETRIEVAL,
        EvidenceDomain.CONTEXT,
        EvidenceDomain.ROUTING,
        EvidenceDomain.INFERENCE,
        EvidenceDomain.PROACTIVE,
        EvidenceDomain.MEMORY_LIFECYCLE,
        EvidenceDomain.ERASURE_REGENERATION,
        EvidenceDomain.SOURCE_HEALTH,
        EvidenceDomain.REGRESSION,
    }
)


class EvaluationCaseResult(StrictModel):
    schema_version: Literal[1] = 1
    case_result_id: UUID = Field(default_factory=uuid7)
    case_id: str = Field(min_length=1, max_length=240)
    domain: EvidenceDomain
    status: Literal["passed", "failed", "inconclusive", "error"]
    critical: bool = False
    summary: str = Field(min_length=1, max_length=2000)
    metric_values: dict[str, object] = Field(default_factory=dict)
    trace_ids: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    content_hash: str = ""

    @field_validator("trace_ids")
    @classmethod
    def validate_trace_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(len(value) != 32 or any(c not in "0123456789abcdef" for c in value) for value in values):
            raise ValueError("trace_ids must be lowercase 32-character hex values")
        return values

    @model_validator(mode="after")
    def bind_hash(self) -> "EvaluationCaseResult":
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match EvaluationCaseResult")
        object.__setattr__(self, "content_hash", expected)
        return self


class EvaluationSuiteResult(StrictModel):
    schema_version: Literal[1] = 1
    suite_result_id: UUID = Field(default_factory=uuid7)
    suite_id: str = Field(min_length=1, max_length=240)
    suite_version: str = Field(min_length=1, max_length=240)
    domain: EvidenceDomain
    fixture_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    runner_version: str = Field(min_length=1, max_length=240)
    binding: bool = False
    cases: tuple[EvaluationCaseResult, ...] = Field(min_length=1)
    aggregate_metrics: dict[str, object] = Field(default_factory=dict)
    limitations: tuple[str, ...] = ()
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_and_hash(self) -> "EvaluationSuiteResult":
        if any(case.domain != self.domain for case in self.cases):
            raise ValueError("suite cases must match the suite domain")
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("suite case IDs must be unique")
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match EvaluationSuiteResult")
        object.__setattr__(self, "content_hash", expected)
        return self


class EvaluationVersionSet(StrictModel):
    schema_version: Literal[1] = 1
    code_revision: str = Field(min_length=1, max_length=200)
    environment_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    component_versions: dict[str, str] = Field(min_length=1)
    constitution_version_id: str = Field(min_length=1)
    identity_version_id: str = Field(min_length=1)
    values_version_id: str = Field(min_length=1)
    policy_versions: dict[str, str] = Field(min_length=1)
    judge_versions: dict[str, str] = Field(default_factory=dict)


class EvaluationArtifactPolicy(StrictModel):
    schema_version: Literal[1] = 1
    policy_version: Literal["protected-local-review-v1"] = "protected-local-review-v1"
    allowed_roles: tuple[Literal["owner", "technical_reviewer", "human_reviewer"], ...]
    review_after_days: int = Field(default=30, ge=1, le=3650)
    automatic_deletion: Literal[False] = False
    deletion_requires_owner_authorization: Literal[True] = True
    external_transfer_allowed: Literal[False] = False
    hold_reason: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def require_owner(self) -> "EvaluationArtifactPolicy":
        if "owner" not in self.allowed_roles:
            raise ValueError("artifact policy must retain owner access")
        if len(self.allowed_roles) != len(set(self.allowed_roles)):
            raise ValueError("allowed roles must be unique")
        return self


class EvaluationArtifact(StrictModel):
    schema_version: Literal[1] = 1
    artifact_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    artifact_kind: Literal[
        "suite_result", "trace_export", "systems_report", "judge_calibration",
        "release_comparison", "evidence_bundle", "human_review",
    ]
    artifact_uri: str = Field(pattern=r"^(local|inline)://", max_length=1000)
    artifact_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    media_type: str = Field(min_length=1, max_length=120)
    data_policy: DataPolicy
    access_policy: EvaluationArtifactPolicy
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_and_hash(self) -> "EvaluationArtifact":
        if self.data_policy.cloud_eligible:
            raise ValueError("Stage 8 evaluation artifacts must remain local")
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match EvaluationArtifact")
        object.__setattr__(self, "content_hash", expected)
        return self


class ArtifactRetentionReview(StrictModel):
    schema_version: Literal[1] = 1
    retention_review_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    artifact_id: UUID
    decision: Literal["retain"] = "retain"
    retain_until: datetime
    reason: str = Field(min_length=1, max_length=2000)
    reviewer: Literal["owner"] = "owner"
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @field_validator("retain_until", "reviewed_at")
    @classmethod
    def normalize_times(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("retention review times must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_and_hash(self) -> "ArtifactRetentionReview":
        if self.retain_until <= self.reviewed_at:
            raise ValueError("retain_until must be after reviewed_at")
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "reviewed_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match ArtifactRetentionReview")
        object.__setattr__(self, "content_hash", expected)
        return self


class JudgeCalibrationReport(StrictModel):
    schema_version: Literal[1] = 1
    calibration_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    calibration_set_id: str = Field(min_length=1, max_length=240)
    calibration_set_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    judge_id: str = Field(min_length=1, max_length=240)
    judge_version: str = Field(min_length=1, max_length=240)
    judge_kind: Literal["deterministic_fixture", "model"]
    human_label_count: int = Field(ge=1)
    agreement_count: int = Field(ge=0)
    disagreement_case_ids: tuple[str, ...] = ()
    agreement_rate: float = Field(ge=0, le=1)
    critical_clearance_authority: Literal[False] = False
    limitations: tuple[str, ...] = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_and_hash(self) -> "JudgeCalibrationReport":
        if self.agreement_count > self.human_label_count:
            raise ValueError("agreement count cannot exceed human label count")
        expected_rate = self.agreement_count / self.human_label_count
        if abs(self.agreement_rate - expected_rate) > 1e-12:
            raise ValueError("agreement_rate must match counts")
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match JudgeCalibrationReport")
        object.__setattr__(self, "content_hash", expected)
        return self


class ReleaseComparison(StrictModel):
    schema_version: Literal[1] = 1
    comparison_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    baseline_bundle_id: UUID
    candidate_bundle_id: UUID
    controlled_differences: tuple[str, ...]
    uncontrolled_differences: tuple[str, ...]
    observed_version_differences: tuple[str, ...] = ()
    domain_deltas: dict[str, object]
    critical_regressions: tuple[str, ...] = ()
    noncritical_regressions: tuple[str, ...] = ()
    automated_recommendation: Literal["candidate_review", "reject", "inconclusive"]
    automatic_promotion_authorized: Literal[False] = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_and_hash(self) -> "ReleaseComparison":
        if self.critical_regressions and self.automated_recommendation != "reject":
            raise ValueError("critical regressions must reject the candidate")
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match ReleaseComparison")
        object.__setattr__(self, "content_hash", expected)
        return self


class HumanReviewRequest(StrictModel):
    schema_version: Literal[1] = 1
    review_request_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    target_kind: Literal["evidence_bundle", "release_comparison", "judge_calibration"]
    target_id: UUID
    required_role: Literal["technical_reviewer", "human_reviewer"]
    review_scope: str = Field(min_length=1, max_length=2000)
    release_promotion_in_scope: Literal[False] = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @model_validator(mode="after")
    def bind_hash(self) -> "HumanReviewRequest":
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match HumanReviewRequest")
        object.__setattr__(self, "content_hash", expected)
        return self


class HumanReviewDecision(StrictModel):
    schema_version: Literal[1] = 1
    review_decision_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    review_request_id: UUID
    reviewer_role: Literal["technical_reviewer", "human_reviewer"]
    reviewer_ref: str = Field(min_length=1, max_length=240)
    decision: Literal["accepted_for_candidate_evidence", "rejected", "changes_requested"]
    rationale: str = Field(min_length=1, max_length=4000)
    blocking_findings: tuple[str, ...] = ()
    release_promotion_authorized: Literal[False] = False
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_and_hash(self) -> "HumanReviewDecision":
        if self.blocking_findings and self.decision == "accepted_for_candidate_evidence":
            raise ValueError("blocking findings cannot be accepted")
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "decided_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match HumanReviewDecision")
        object.__setattr__(self, "content_hash", expected)
        return self


class TraceNode(StrictModel):
    node_id: str = Field(min_length=1, max_length=240)
    node_kind: str = Field(min_length=1, max_length=120)
    status: str | None = Field(default=None, max_length=120)
    occurred_at: datetime | None = None
    content_redacted: Literal[True] = True
    attributes: dict[str, object] = Field(default_factory=dict)


class TraceEdge(StrictModel):
    source_node_id: str
    target_node_id: str
    relation: str = Field(min_length=1, max_length=120)


class TraceExploration(StrictModel):
    schema_version: Literal[1] = 1
    owner_id: UUID
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    nodes: tuple[TraceNode, ...]
    edges: tuple[TraceEdge, ...]
    registered_source_kinds: tuple[str, ...] = Field(min_length=1)
    missing_source_kinds: tuple[str, ...] = ()
    complete_for_registered_sources: bool
    omitted_content_fields: tuple[str, ...] = (
        "event payload", "message content", "rendered content", "provider body"
    )
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_and_hash(self) -> "TraceExploration":
        node_ids = {node.node_id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("trace node IDs must be unique")
        if any(edge.source_node_id not in node_ids or edge.target_node_id not in node_ids for edge in self.edges):
            raise ValueError("trace edges must reference included nodes")
        if self.complete_for_registered_sources != (len(self.missing_source_kinds) == 0):
            raise ValueError("trace completeness must match missing registered sources")
        if not set(self.missing_source_kinds).issubset(self.registered_source_kinds):
            raise ValueError("missing trace sources must be registered")
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match TraceExploration")
        object.__setattr__(self, "content_hash", expected)
        return self


class Stage8OperationalEvidence(StrictModel):
    """Observed local Stage 6/7 outcomes consumed by the unified runner."""

    schema_version: Literal[1] = 1
    owner_id: UUID
    evidence_source: Literal["local_postgres_synthetic_stage67"] = (
        "local_postgres_synthetic_stage67"
    )
    memory_lifecycle_outcomes: dict[str, str]
    erasure_regeneration_outcomes: dict[str, str]
    source_health_outcomes: dict[str, str]
    proactive_outcomes: dict[str, bool]
    trace_ids: tuple[str, ...] = Field(min_length=1)
    trace_content_hashes: dict[str, str]
    privacy_class: Literal["LOCAL_ONLY"] = "LOCAL_ONLY"
    training_eligible: Literal[False] = False
    external_source_activated: Literal[False] = False
    real_delivery_attempted: Literal[False] = False
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_and_hash(self) -> "Stage8OperationalEvidence":
        if any(
            len(value) != 32 or any(c not in "0123456789abcdef" for c in value)
            for value in self.trace_ids
        ):
            raise ValueError("operational evidence trace IDs must be lowercase hex")
        if set(self.trace_content_hashes) != set(self.trace_ids):
            raise ValueError("operational evidence must hash every and only linked trace")
        if any(
            len(value) != 71 or not value.startswith("sha256:")
            or any(c not in "0123456789abcdef" for c in value[7:])
            for value in self.trace_content_hashes.values()
        ):
            raise ValueError("operational trace hashes must be sha256 values")
        expected = content_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match Stage8OperationalEvidence")
        object.__setattr__(self, "content_hash", expected)
        return self


class EvidenceBundle(StrictModel):
    schema_version: Literal[1] = 1
    evidence_bundle_id: UUID = Field(default_factory=uuid7)
    owner_id: UUID
    candidate_release_id: str = Field(min_length=1, max_length=240)
    runner_version: Literal["unified-evaluation-runner-v1"] = "unified-evaluation-runner-v1"
    versions: EvaluationVersionSet
    suite_results: tuple[EvaluationSuiteResult, ...] = Field(min_length=1)
    artifact_ids: tuple[UUID, ...] = ()
    trace_ids: tuple[str, ...] = ()
    judge_calibration_ids: tuple[UUID, ...] = ()
    release_comparison_ids: tuple[UUID, ...] = ()
    human_review_decision_ids: tuple[UUID, ...] = ()
    exceptions: tuple[str, ...] = ()
    critical_failures: tuple[str, ...] = ()
    automated_gate: Literal["candidate_review", "rejected", "inconclusive"]
    explicit_decision: Literal[
        "pending_human_review", "accepted_for_stage9_candidate_foundation",
        "rejected", "inconclusive",
    ] = "pending_human_review"
    decision_scope: Literal["local_candidate_evidence_only"] = "local_candidate_evidence_only"
    release_promotion_authorized: Literal[False] = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    @model_validator(mode="after")
    def validate_and_hash(self) -> "EvidenceBundle":
        domains = {suite.domain for suite in self.suite_results}
        if len(domains) != len(self.suite_results):
            raise ValueError("evidence bundle requires exactly one suite per domain")
        missing = REQUIRED_STAGE8_DOMAINS - domains
        if missing:
            raise ValueError(f"evidence bundle missing Stage 8 domains: {sorted(missing)}")
        derived_critical = tuple(sorted(
            f"{suite.domain.value}:{case.case_id}"
            for suite in self.suite_results for case in suite.cases
            if case.critical and case.status != "passed"
        ))
        if tuple(sorted(self.critical_failures)) != derived_critical:
            raise ValueError("critical_failures must exactly match critical non-passing cases")
        derived_exceptions = tuple(sorted(
            f"{suite.domain.value}:{case.case_id}:inconclusive"
            for suite in self.suite_results for case in suite.cases
            if case.status == "inconclusive"
        ))
        if tuple(sorted(self.exceptions)) != derived_exceptions:
            raise ValueError("exceptions must exactly match inconclusive cases")
        statuses = {case.status for suite in self.suite_results for case in suite.cases}
        expected_gate = (
            "rejected" if derived_critical else
            "inconclusive" if "error" in statuses else "candidate_review"
        )
        if self.automated_gate != expected_gate:
            raise ValueError("automated_gate must be derived from case results")
        if self.explicit_decision == "accepted_for_stage9_candidate_foundation":
            if self.automated_gate != "candidate_review" or self.critical_failures:
                raise ValueError("only a blocker-free candidate may be accepted for Stage 9 foundation")
            if not self.human_review_decision_ids or not self.release_comparison_ids:
                raise ValueError("accepted evidence must link human review and release comparison")
            if not self.trace_ids:
                raise ValueError("accepted evidence must link at least one explored trace")
        if self.explicit_decision == "pending_human_review" and self.human_review_decision_ids:
            raise ValueError("pending evidence cannot already link a human decision")
        if self.explicit_decision == "rejected" and self.automated_gate != "rejected":
            raise ValueError("explicit rejection requires an automated rejection in Stage 8")
        expected = content_hash(
            self.model_dump(mode="json", exclude={"content_hash", "created_at"})
        )
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash does not match EvidenceBundle")
        object.__setattr__(self, "content_hash", expected)
        return self


def local_evaluation_policy() -> DataPolicy:
    return DataPolicy(
        privacy_class=PrivacyClass.LOCAL_ONLY,
        memory_eligible=False,
        cloud_eligible=False,
        decision_source="derived_conservative",
    )
