"""Export deterministic JSON Schemas from the authoritative Pydantic contracts."""

from __future__ import annotations

import json
from pathlib import Path

from companion.application import InteractionCommand, InteractionResult
from companion.consolidation import ConsolidationProposal
from companion.context import (
    ContextPack,
    OwnerExampleBank,
    PersonalContextItem,
    ResponsePlan,
    ResponsePlanV1,
    ResponsePlanV2,
)
from companion.evidence import EvidenceRef
from companion.events import EventEnvelope
from companion.goals import Goal, GoalProgressRecord, GoalProjectionMaterial
from companion.feedback import (
    CommunicationPreference,
    ConversationEpisode,
    EpisodeMemorySuggestion,
    PersonalizationFeedback,
    PersonalizationFeedbackReview,
)
from companion.identity import IdentityBundle
from companion.policy import DataPolicy, ResponsePolicyDecision
from companion.policy.intervention import InterventionDecision
from companion.scenes import GuidanceOutcomeObservation, SceneRecord, SceneSession, SceneView
from companion.state import CurrentStateSnapshot
from companion.user_model import BeliefRevision, BeliefSnapshot, BeliefTransition
from evals.user_model_evaluation import UserModelEvaluationReport
from evals.scene_evaluation import ScenePolicyEvaluationReport
from mlsys.contracts import (
    InferenceCompatibilityReport,
    InferenceFailure,
    InferenceRequest,
    InferenceResponse,
    InferenceStreamEvent,
    InferenceSystemBenchmarkReport,
    InferenceSystemUnderTestManifest,
    InferenceWorkloadManifest,
    ProviderVersion,
    RouteDecision,
)
from companion.memory import MemoryCandidate, MemoryRevision
from companion.mobile import MobileEnrollmentReceipt
from companion.life_context import (
    CalendarAvailabilityWindow,
    CalendarContextActivationBundle,
    CalendarImportPolicy,
    ConsentScopeRevision,
    ContextIngestResult,
    ContextObservationDraft,
    ContextSourceHealthDraft,
    ContextSourceCapability,
    ContextSourceDescriptor,
    ContextSourceHealth,
    ContextSourceHealthV2,
    ContextSourceStateRevision,
    ContextCapabilityStateRevision,
    ContextCollectionPermit,
    ContextCollectionPermitRequest,
    ContextRetentionExpiryIntent,
    ContextRetentionExpiryReceipt,
    ContextRestoreQuarantine,
    ContextSourceErasureTombstone,
    WindowsContextActivationBundle,
    DeviceActivitySummary,
    LifeContextObservation,
    LifeContextObservationV2,
    RetentionPolicy,
    SamplingPolicy,
    SignalFreshness,
)
from companion.proactive import (
    DeliveryAttempt,
    InterruptionDecision,
    ProactiveContextPack,
    ProactiveInboxItem,
    ProactiveLifecycleView,
    ProactiveOwnerAction,
    ProactivePreferenceRevision,
    ProactiveProposal,
    ProactiveWorkCommand,
    RenderedProactiveMessage,
    TriggerRecord,
)
from companion.offline import (
    ArtifactManifest,
    CanonicalDatasetSnapshot,
    DatasetRejection,
    MemoryLifecycleProposal,
    MemoryLifecycleReview,
    ReflectionProposal,
)
from companion.operations import (
    BackupManifest,
    ComponentReference,
    ComponentPromotionAuthorization,
    DeploymentHealthEvidence,
    DeploymentRecord,
    ErasureDirective,
    ExportArtifact,
    OwnerExportManifest,
    ReleaseApprovalRecord,
    ReleaseManifest,
    RestoreErasureReplay,
)
from companion.evaluation import (
    ArtifactRetentionReview,
    EvidenceBundle,
    EvaluationArtifact,
    EvaluationArtifactPolicy,
    EvaluationCaseResult,
    EvaluationSuiteResult,
    EvaluationVersionSet,
    HumanReviewDecision,
    HumanReviewRequest,
    JudgeCalibrationReport,
    ReleaseComparison,
    Stage8OperationalEvidence,
    TraceExploration,
)
from evals.proactive_evaluation import ProactiveEvaluationReport
from mlsys.retrieval import RetrievalRequest, RetrievalResult
from mlsys.training import (
    AdapterCompatibilityReport,
    AdapterRejectionRecord,
    AdapterVersion,
    CanonicalTrainingExample,
    EvaluationHoldoutCase,
    EvaluationHoldoutSuite,
    FactorialEvaluationReport,
    ModelVersion,
    RenderedTrainingArtifact,
    TrainingDatasetSnapshot,
    TrainingRun,
)


CONTRACTS = {
    "context-pack-v1": ContextPack,
    "response-plan-v1": ResponsePlanV1,
    "response-plan-v2": ResponsePlanV2,
    "response-plan-v3": ResponsePlan,
    "owner-example-bank-v1": OwnerExampleBank,
    "data-policy-v1": DataPolicy,
    "core-response-policy-decision-v1": ResponsePolicyDecision,
    "evidence-ref-v1": EvidenceRef,
    "event-envelope-v1": EventEnvelope,
    "identity-bundle-v1": IdentityBundle,
    "mobile-enrollment-receipt-v1": MobileEnrollmentReceipt,
    "inference-request-v1": InferenceRequest,
    "inference-response-v1": InferenceResponse,
    "inference-failure-v1": InferenceFailure,
    "inference-stream-event-v1": InferenceStreamEvent,
    "inference-benchmark-report-v1": InferenceSystemBenchmarkReport,
    "inference-compatibility-report-v1": InferenceCompatibilityReport,
    "inference-system-manifest-v1": InferenceSystemUnderTestManifest,
    "inference-workload-manifest-v1": InferenceWorkloadManifest,
    "interaction-command-v1": InteractionCommand,
    "interaction-result-v1": InteractionResult,
    "personalization-feedback-v1": PersonalizationFeedback,
    "personalization-feedback-review-v1": PersonalizationFeedbackReview,
    "communication-preference-v1": CommunicationPreference,
    "conversation-episode-v1": ConversationEpisode,
    "episode-memory-suggestion-v1": EpisodeMemorySuggestion,
    "intervention-decision-v1": InterventionDecision,
    "belief-revision-v1": BeliefRevision,
    "belief-transition-v1": BeliefTransition,
    "belief-snapshot-v1": BeliefSnapshot,
    "consolidation-proposal-v1": ConsolidationProposal,
    "current-state-snapshot-v1": CurrentStateSnapshot,
    "goal-v1": Goal,
    "goal-projection-material-v1": GoalProjectionMaterial,
    "goal-progress-record-v1": GoalProgressRecord,
    "memory-candidate-v1": MemoryCandidate,
    "memory-revision-v1": MemoryRevision,
    "provider-version-v1": ProviderVersion,
    "retrieval-request-v1": RetrievalRequest,
    "retrieval-result-v1": RetrievalResult,
    "route-decision-v1": RouteDecision,
    "personal-context-item-v1": PersonalContextItem,
    "scene-session-v1": SceneSession,
    "scene-record-v1": SceneRecord,
    "scene-view-v1": SceneView,
    "scene-policy-evaluation-report-v1": ScenePolicyEvaluationReport,
    "guidance-outcome-observation-v1": GuidanceOutcomeObservation,
    "user-model-evaluation-report-v1": UserModelEvaluationReport,
    "context-source-health-v1": ContextSourceHealth,
    "life-context-observation-v1": LifeContextObservation,
    "signal-freshness-v1": SignalFreshness,
    "context-source-descriptor-v1": ContextSourceDescriptor,
    "calendar-availability-window-v1": CalendarAvailabilityWindow,
    "calendar-context-activation-bundle-v1": CalendarContextActivationBundle,
    "calendar-import-policy-v1": CalendarImportPolicy,
    "context-source-capability-v1": ContextSourceCapability,
    "context-consent-scope-revision-v1": ConsentScopeRevision,
    "context-sampling-policy-v1": SamplingPolicy,
    "context-retention-policy-v1": RetentionPolicy,
    "device-activity-summary-v1": DeviceActivitySummary,
    "context-observation-draft-v1": ContextObservationDraft,
    "context-source-health-draft-v1": ContextSourceHealthDraft,
    "context-source-state-revision-v1": ContextSourceStateRevision,
    "context-capability-state-revision-v1": ContextCapabilityStateRevision,
    "context-collection-permit-v1": ContextCollectionPermit,
    "context-collection-permit-request-v1": ContextCollectionPermitRequest,
    "context-retention-expiry-intent-v1": ContextRetentionExpiryIntent,
    "context-retention-expiry-receipt-v1": ContextRetentionExpiryReceipt,
    "context-restore-quarantine-v1": ContextRestoreQuarantine,
    "context-source-erasure-tombstone-v1": ContextSourceErasureTombstone,
    "windows-context-activation-bundle-v1": WindowsContextActivationBundle,
    "life-context-observation-v2": LifeContextObservationV2,
    "context-source-health-v2": ContextSourceHealthV2,
    "context-ingest-result-v1": ContextIngestResult,
    "proactive-trigger-v1": TriggerRecord,
    "proactive-preference-revision-v1": ProactivePreferenceRevision,
    "proactive-proposal-v1": ProactiveProposal,
    "interruption-decision-v1": InterruptionDecision,
    "proactive-context-pack-v1": ProactiveContextPack,
    "proactive-inbox-item-v1": ProactiveInboxItem,
    "rendered-proactive-message-v1": RenderedProactiveMessage,
    "delivery-attempt-v1": DeliveryAttempt,
    "proactive-lifecycle-view-v1": ProactiveLifecycleView,
    "proactive-owner-action-v1": ProactiveOwnerAction,
    "proactive-work-command-v1": ProactiveWorkCommand,
    "proactive-evaluation-report-v1": ProactiveEvaluationReport,
    "reflection-proposal-v1": ReflectionProposal,
    "memory-lifecycle-proposal-v1": MemoryLifecycleProposal,
    "memory-lifecycle-review-v1": MemoryLifecycleReview,
    "dataset-rejection-v1": DatasetRejection,
    "canonical-dataset-snapshot-v1": CanonicalDatasetSnapshot,
    "offline-artifact-manifest-v1": ArtifactManifest,
    "evaluation-case-result-v1": EvaluationCaseResult,
    "evaluation-suite-result-v1": EvaluationSuiteResult,
    "evaluation-version-set-v1": EvaluationVersionSet,
    "evaluation-artifact-policy-v1": EvaluationArtifactPolicy,
    "evaluation-artifact-v1": EvaluationArtifact,
    "artifact-retention-review-v1": ArtifactRetentionReview,
    "judge-calibration-report-v1": JudgeCalibrationReport,
    "release-comparison-v1": ReleaseComparison,
    "human-review-request-v1": HumanReviewRequest,
    "human-review-decision-v1": HumanReviewDecision,
    "trace-exploration-v1": TraceExploration,
    "stage8-operational-evidence-v1": Stage8OperationalEvidence,
    "evidence-bundle-v1": EvidenceBundle,
    "canonical-training-example-v1": CanonicalTrainingExample,
    "evaluation-holdout-case-v1": EvaluationHoldoutCase,
    "evaluation-holdout-suite-v1": EvaluationHoldoutSuite,
    "training-dataset-snapshot-v1": TrainingDatasetSnapshot,
    "model-version-v1": ModelVersion,
    "rendered-training-artifact-v1": RenderedTrainingArtifact,
    "training-run-v1": TrainingRun,
    "adapter-version-v1": AdapterVersion,
    "adapter-compatibility-report-v1": AdapterCompatibilityReport,
    "factorial-evaluation-report-v1": FactorialEvaluationReport,
    "adapter-rejection-record-v1": AdapterRejectionRecord,
    "release-manifest-v1": ReleaseManifest,
    "release-approval-record-v1": ReleaseApprovalRecord,
    "release-component-reference-v1": ComponentReference,
    "component-promotion-authorization-v1": ComponentPromotionAuthorization,
    "deployment-record-v1": DeploymentRecord,
    "deployment-health-evidence-v1": DeploymentHealthEvidence,
    "backup-manifest-v1": BackupManifest,
    "erasure-directive-v1": ErasureDirective,
    "owner-export-artifact-v1": ExportArtifact,
    "owner-export-manifest-v1": OwnerExportManifest,
    "restore-erasure-replay-v1": RestoreErasureReplay,
}


def main() -> None:
    destination = Path(__file__).resolve().parents[1] / "contracts" / "schemas"
    destination.mkdir(parents=True, exist_ok=True)
    for name, contract in CONTRACTS.items():
        output = json.dumps(
            contract.model_json_schema(),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        (destination / f"{name}.json").write_text(output + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
