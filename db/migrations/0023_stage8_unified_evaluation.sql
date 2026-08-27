-- Stage 8 unified evaluation and observability operations.
-- All artifacts remain local, training-ineligible, candidate-only, and owner scoped.

CREATE TABLE havre.evaluation_retention_policies (
    retention_policy_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    policy_version text NOT NULL CHECK (policy_version = 'protected-local-review-v1'),
    allowed_roles text[] NOT NULL CHECK (
        cardinality(allowed_roles) > 0
        AND allowed_roles <@ ARRAY['owner','technical_reviewer','human_reviewer']::text[]
        AND 'owner' = ANY(allowed_roles)
    ),
    review_after_days integer NOT NULL CHECK (review_after_days BETWEEN 1 AND 3650),
    automatic_deletion boolean NOT NULL CHECK (automatic_deletion = false),
    deletion_requires_owner_authorization boolean NOT NULL
        CHECK (deletion_requires_owner_authorization = true),
    external_transfer_allowed boolean NOT NULL CHECK (external_transfer_allowed = false),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (owner_id, retention_policy_id),
    UNIQUE (owner_id, policy_version, content_hash)
);

CREATE TABLE havre.evaluation_runs (
    evaluation_run_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    suite_id text NOT NULL CHECK (length(suite_id) BETWEEN 1 AND 240),
    suite_version text NOT NULL CHECK (length(suite_version) BETWEEN 1 AND 240),
    domain text NOT NULL CHECK (domain IN (
        'behavioral','retrieval','context','routing','inference','proactive',
        'memory_lifecycle','erasure_regeneration','source_health','regression'
    )),
    fixture_hash text NOT NULL CHECK (fixture_hash ~ '^sha256:[0-9a-f]{64}$'),
    runner_version text NOT NULL CHECK (length(runner_version) BETWEEN 1 AND 240),
    binding_evaluation boolean NOT NULL,
    status text NOT NULL CHECK (status IN ('passed','failed','inconclusive','error')),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (owner_id, evaluation_run_id),
    UNIQUE (owner_id, suite_id, suite_version, fixture_hash, runner_version, content_hash)
);
CREATE INDEX evaluation_runs_owner_domain_idx
    ON havre.evaluation_runs(owner_id, domain, created_at, evaluation_run_id);

CREATE TABLE havre.evaluation_case_results (
    case_result_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL,
    evaluation_run_id uuid NOT NULL,
    case_id text NOT NULL CHECK (length(case_id) BETWEEN 1 AND 240),
    domain text NOT NULL CHECK (domain IN (
        'behavioral','retrieval','context','routing','inference','proactive',
        'memory_lifecycle','erasure_regeneration','source_health','regression'
    )),
    status text NOT NULL CHECK (status IN ('passed','failed','inconclusive','error')),
    critical boolean NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    UNIQUE (owner_id, case_result_id),
    UNIQUE (owner_id, evaluation_run_id, case_id),
    FOREIGN KEY (owner_id, evaluation_run_id)
        REFERENCES havre.evaluation_runs(owner_id, evaluation_run_id)
);
CREATE INDEX evaluation_case_results_owner_run_idx
    ON havre.evaluation_case_results(owner_id, evaluation_run_id);

CREATE TABLE havre.judge_calibration_runs (
    calibration_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    calibration_set_id text NOT NULL CHECK (length(calibration_set_id) BETWEEN 1 AND 240),
    calibration_set_hash text NOT NULL CHECK (calibration_set_hash ~ '^sha256:[0-9a-f]{64}$'),
    judge_id text NOT NULL CHECK (length(judge_id) BETWEEN 1 AND 240),
    judge_version text NOT NULL CHECK (length(judge_version) BETWEEN 1 AND 240),
    judge_kind text NOT NULL CHECK (judge_kind IN ('deterministic_fixture','model')),
    human_label_count integer NOT NULL CHECK (human_label_count > 0),
    agreement_count integer NOT NULL CHECK (
        agreement_count >= 0 AND agreement_count <= human_label_count
    ),
    critical_clearance_authority boolean NOT NULL CHECK (critical_clearance_authority = false),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    UNIQUE (owner_id, calibration_id)
);

CREATE TABLE havre.evidence_bundles (
    evidence_bundle_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    candidate_release_id text NOT NULL CHECK (length(candidate_release_id) BETWEEN 1 AND 240),
    runner_version text NOT NULL CHECK (runner_version = 'unified-evaluation-runner-v1'),
    automated_gate text NOT NULL CHECK (automated_gate IN ('candidate_review','rejected','inconclusive')),
    explicit_decision text NOT NULL CHECK (explicit_decision IN (
        'pending_human_review','accepted_for_stage9_candidate_foundation',
        'rejected','inconclusive'
    )),
    decision_scope text NOT NULL CHECK (decision_scope = 'local_candidate_evidence_only'),
    release_promotion_authorized boolean NOT NULL CHECK (release_promotion_authorized = false),
    critical_failure_count integer NOT NULL CHECK (critical_failure_count >= 0),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    UNIQUE (owner_id, evidence_bundle_id),
    CHECK (payload ?& ARRAY[
        'evidence_bundle_id','owner_id','candidate_release_id','versions','suite_results',
        'artifact_ids','trace_ids','judge_calibration_ids','release_comparison_ids',
        'human_review_decision_ids','critical_failures','exceptions',
        'automated_gate','explicit_decision','content_hash'
    ]),
    CHECK (jsonb_typeof(payload->'versions') = 'object'
       AND jsonb_typeof(payload->'suite_results') = 'array'
       AND jsonb_typeof(payload->'artifact_ids') = 'array'
       AND jsonb_typeof(payload->'trace_ids') = 'array'
       AND jsonb_typeof(payload->'judge_calibration_ids') = 'array'
       AND jsonb_typeof(payload->'release_comparison_ids') = 'array'
       AND jsonb_typeof(payload->'human_review_decision_ids') = 'array'
       AND jsonb_typeof(payload->'critical_failures') = 'array'
       AND jsonb_typeof(payload->'exceptions') = 'array'),
    CHECK ((payload->>'evidence_bundle_id')::uuid = evidence_bundle_id
       AND (payload->>'owner_id')::uuid = owner_id
       AND payload->>'candidate_release_id' = candidate_release_id
       AND payload->>'automated_gate' = automated_gate
       AND payload->>'explicit_decision' = explicit_decision
       AND payload->>'content_hash' = content_hash
       AND jsonb_array_length(payload->'critical_failures') = critical_failure_count),
    CHECK (critical_failure_count = 0 OR automated_gate = 'rejected'),
    CHECK (explicit_decision <> 'rejected' OR automated_gate = 'rejected'),
    CHECK (explicit_decision <> 'accepted_for_stage9_candidate_foundation'
           OR (automated_gate = 'candidate_review' AND critical_failure_count = 0))
);

CREATE TABLE havre.evidence_bundle_runs (
    owner_id uuid NOT NULL,
    evidence_bundle_id uuid NOT NULL,
    evaluation_run_id uuid NOT NULL,
    PRIMARY KEY (owner_id, evidence_bundle_id, evaluation_run_id),
    FOREIGN KEY (owner_id, evidence_bundle_id)
        REFERENCES havre.evidence_bundles(owner_id, evidence_bundle_id),
    FOREIGN KEY (owner_id, evaluation_run_id)
        REFERENCES havre.evaluation_runs(owner_id, evaluation_run_id)
);
CREATE INDEX evidence_bundle_runs_owner_run_idx
    ON havre.evidence_bundle_runs(owner_id, evaluation_run_id);

CREATE TABLE havre.evidence_bundle_calibrations (
    owner_id uuid NOT NULL,
    evidence_bundle_id uuid NOT NULL,
    calibration_id uuid NOT NULL,
    PRIMARY KEY (owner_id, evidence_bundle_id, calibration_id),
    FOREIGN KEY (owner_id, evidence_bundle_id)
        REFERENCES havre.evidence_bundles(owner_id, evidence_bundle_id),
    FOREIGN KEY (owner_id, calibration_id)
        REFERENCES havre.judge_calibration_runs(owner_id, calibration_id)
);
CREATE INDEX evidence_bundle_calibrations_owner_calibration_idx
    ON havre.evidence_bundle_calibrations(owner_id, calibration_id);

CREATE TABLE havre.evidence_bundle_traces (
    owner_id uuid NOT NULL,
    evidence_bundle_id uuid NOT NULL,
    trace_id char(32) NOT NULL,
    PRIMARY KEY (owner_id, evidence_bundle_id, trace_id),
    FOREIGN KEY (owner_id, evidence_bundle_id)
        REFERENCES havre.evidence_bundles(owner_id, evidence_bundle_id),
    FOREIGN KEY (owner_id, trace_id) REFERENCES havre.traces(owner_id, trace_id)
);
CREATE INDEX evidence_bundle_traces_owner_trace_idx
    ON havre.evidence_bundle_traces(owner_id, trace_id);

CREATE TABLE havre.evaluation_artifacts (
    artifact_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    evidence_bundle_id uuid NULL,
    retention_policy_id uuid NOT NULL,
    artifact_kind text NOT NULL CHECK (artifact_kind IN (
        'suite_result','trace_export','systems_report','judge_calibration',
        'release_comparison','evidence_bundle','human_review'
    )),
    artifact_uri text NOT NULL CHECK (artifact_uri ~ '^(local|inline)://'),
    artifact_content_hash text NOT NULL CHECK (artifact_content_hash ~ '^sha256:[0-9a-f]{64}$'),
    media_type text NOT NULL CHECK (length(media_type) BETWEEN 1 AND 120),
    privacy_class text NOT NULL CHECK (privacy_class = 'LOCAL_ONLY'),
    memory_eligible boolean NOT NULL CHECK (memory_eligible = false),
    training_eligible boolean NOT NULL CHECK (training_eligible = false),
    cloud_eligible boolean NOT NULL CHECK (cloud_eligible = false),
    external_transfer_allowed boolean NOT NULL CHECK (external_transfer_allowed = false),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    UNIQUE (owner_id, artifact_id),
    FOREIGN KEY (owner_id, evidence_bundle_id)
        REFERENCES havre.evidence_bundles(owner_id, evidence_bundle_id),
    FOREIGN KEY (owner_id, retention_policy_id)
        REFERENCES havre.evaluation_retention_policies(owner_id, retention_policy_id)
);
CREATE INDEX evaluation_artifacts_owner_bundle_idx
    ON havre.evaluation_artifacts(owner_id, evidence_bundle_id);
CREATE INDEX evaluation_artifacts_owner_retention_idx
    ON havre.evaluation_artifacts(owner_id, retention_policy_id);

CREATE TABLE havre.evaluation_retention_reviews (
    retention_review_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL,
    artifact_id uuid NOT NULL,
    decision text NOT NULL CHECK (decision = 'retain'),
    retain_until timestamptz NOT NULL,
    reviewer text NOT NULL CHECK (reviewer = 'owner'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    reviewed_at timestamptz NOT NULL,
    UNIQUE (owner_id, retention_review_id),
    FOREIGN KEY (owner_id, artifact_id)
        REFERENCES havre.evaluation_artifacts(owner_id, artifact_id),
    CHECK (retain_until > reviewed_at)
);
CREATE INDEX evaluation_retention_reviews_owner_artifact_idx
    ON havre.evaluation_retention_reviews(owner_id, artifact_id, retain_until);

CREATE TABLE havre.evaluation_artifact_access_grants (
    access_grant_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    artifact_id uuid NOT NULL,
    actor_ref text NOT NULL CHECK (length(actor_ref) BETWEEN 1 AND 240),
    role text NOT NULL CHECK (role IN ('owner','technical_reviewer','human_reviewer')),
    purpose text NOT NULL CHECK (length(purpose) BETWEEN 1 AND 500),
    granted_by text NOT NULL CHECK (granted_by = 'owner'),
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (owner_id, access_grant_id),
    FOREIGN KEY (owner_id, artifact_id)
        REFERENCES havre.evaluation_artifacts(owner_id, artifact_id)
);
CREATE INDEX evaluation_access_grants_owner_artifact_idx
    ON havre.evaluation_artifact_access_grants(owner_id, artifact_id);

CREATE OR REPLACE FUNCTION havre.guard_evaluation_artifact_access_grant()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    allowed_until timestamptz;
    allowed_roles text[];
BEGIN
    SELECT GREATEST(
               artifact.created_at + make_interval(days => policy.review_after_days),
               COALESCE((
                   SELECT max(review.retain_until)
                   FROM havre.evaluation_retention_reviews AS review
                   WHERE review.owner_id = NEW.owner_id
                     AND review.artifact_id = NEW.artifact_id
               ), '-infinity'::timestamptz)
           ), policy.allowed_roles
      INTO allowed_until, allowed_roles
    FROM havre.evaluation_artifacts AS artifact
    JOIN havre.evaluation_retention_policies AS policy
      ON policy.owner_id = artifact.owner_id
     AND policy.retention_policy_id = artifact.retention_policy_id
    WHERE artifact.owner_id = NEW.owner_id
      AND artifact.artifact_id = NEW.artifact_id;
    IF NOT FOUND OR NOT NEW.role = ANY(allowed_roles) THEN
        RAISE EXCEPTION 'artifact access role is not allowed by retention policy'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.expires_at > allowed_until OR NEW.expires_at <= statement_timestamp() THEN
        RAISE EXCEPTION 'artifact access grant exceeds active retention review window'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER evaluation_artifact_access_grants_guard
    BEFORE INSERT ON havre.evaluation_artifact_access_grants
    FOR EACH ROW EXECUTE FUNCTION havre.guard_evaluation_artifact_access_grant();

CREATE TABLE havre.evaluation_artifact_access_log (
    access_log_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    artifact_id uuid NOT NULL,
    actor_ref text NOT NULL CHECK (length(actor_ref) BETWEEN 1 AND 240),
    role text NOT NULL CHECK (role IN ('owner','technical_reviewer','human_reviewer')),
    purpose text NOT NULL CHECK (length(purpose) BETWEEN 1 AND 500),
    decision text NOT NULL CHECK (decision IN ('allowed','denied')),
    reason_code text NOT NULL CHECK (length(reason_code) BETWEEN 1 AND 120),
    occurred_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    UNIQUE (owner_id, access_log_id),
    FOREIGN KEY (owner_id, artifact_id)
        REFERENCES havre.evaluation_artifacts(owner_id, artifact_id)
);
CREATE INDEX evaluation_access_log_owner_artifact_idx
    ON havre.evaluation_artifact_access_log(owner_id, artifact_id, occurred_at);

CREATE TABLE havre.release_comparisons (
    comparison_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    baseline_bundle_id uuid NOT NULL,
    candidate_bundle_id uuid NOT NULL,
    automated_recommendation text NOT NULL CHECK (
        automated_recommendation IN ('candidate_review','reject','inconclusive')
    ),
    critical_regression_count integer NOT NULL CHECK (critical_regression_count >= 0),
    automatic_promotion_authorized boolean NOT NULL CHECK (automatic_promotion_authorized = false),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    UNIQUE (owner_id, comparison_id),
    FOREIGN KEY (owner_id, baseline_bundle_id)
        REFERENCES havre.evidence_bundles(owner_id, evidence_bundle_id),
    FOREIGN KEY (owner_id, candidate_bundle_id)
        REFERENCES havre.evidence_bundles(owner_id, evidence_bundle_id),
    CHECK (baseline_bundle_id <> candidate_bundle_id),
    CHECK (payload ?& ARRAY[
        'comparison_id','owner_id','baseline_bundle_id','candidate_bundle_id',
        'controlled_differences','uncontrolled_differences',
        'observed_version_differences','critical_regressions',
        'automated_recommendation','content_hash'
    ]),
    CHECK (jsonb_typeof(payload->'controlled_differences') = 'array'
       AND jsonb_typeof(payload->'uncontrolled_differences') = 'array'
       AND jsonb_typeof(payload->'observed_version_differences') = 'array'
       AND jsonb_typeof(payload->'critical_regressions') = 'array'),
    CHECK ((payload->>'comparison_id')::uuid = comparison_id
       AND (payload->>'owner_id')::uuid = owner_id
       AND (payload->>'baseline_bundle_id')::uuid = baseline_bundle_id
       AND (payload->>'candidate_bundle_id')::uuid = candidate_bundle_id
       AND payload->>'automated_recommendation' = automated_recommendation
       AND payload->>'content_hash' = content_hash
       AND jsonb_array_length(payload->'critical_regressions') = critical_regression_count),
    CHECK (critical_regression_count = 0 OR automated_recommendation = 'reject')
);
CREATE INDEX release_comparisons_owner_baseline_idx
    ON havre.release_comparisons(owner_id, baseline_bundle_id);
CREATE INDEX release_comparisons_owner_candidate_idx
    ON havre.release_comparisons(owner_id, candidate_bundle_id);

CREATE OR REPLACE FUNCTION havre.guard_stage8_release_comparison()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    baseline_gate text;
    candidate_gate text;
    candidate_critical integer;
    comparable boolean;
    observed_version_differences text[];
    undeclared_version_difference boolean;
    expected_recommendation text;
BEGIN
    SELECT automated_gate INTO baseline_gate
    FROM havre.evidence_bundles
    WHERE owner_id = NEW.owner_id AND evidence_bundle_id = NEW.baseline_bundle_id;
    SELECT automated_gate, critical_failure_count
      INTO candidate_gate, candidate_critical
    FROM havre.evidence_bundles
    WHERE owner_id = NEW.owner_id AND evidence_bundle_id = NEW.candidate_bundle_id;
    SELECT NOT EXISTS (
        SELECT 1
        FROM (
            SELECT run.domain, run.suite_id, run.suite_version,
                   run.fixture_hash, run.runner_version
            FROM havre.evidence_bundle_runs AS link
            JOIN havre.evaluation_runs AS run
              ON run.owner_id=link.owner_id
             AND run.evaluation_run_id=link.evaluation_run_id
            WHERE link.owner_id=NEW.owner_id
              AND link.evidence_bundle_id=NEW.baseline_bundle_id
        ) AS baseline
        FULL JOIN (
            SELECT run.domain, run.suite_id, run.suite_version,
                   run.fixture_hash, run.runner_version
            FROM havre.evidence_bundle_runs AS link
            JOIN havre.evaluation_runs AS run
              ON run.owner_id=link.owner_id
             AND run.evaluation_run_id=link.evaluation_run_id
            WHERE link.owner_id=NEW.owner_id
              AND link.evidence_bundle_id=NEW.candidate_bundle_id
        ) AS candidate USING (domain)
        WHERE baseline.domain IS NULL OR candidate.domain IS NULL
           OR (baseline.suite_id, baseline.suite_version, baseline.fixture_hash,
               baseline.runner_version) IS DISTINCT FROM
              (candidate.suite_id, candidate.suite_version, candidate.fixture_hash,
               candidate.runner_version)
    ) INTO comparable;
    SELECT COALESCE(array_agg('versions.' || keys.key ORDER BY keys.key), ARRAY[]::text[])
      INTO observed_version_differences
    FROM havre.evidence_bundles AS baseline
    JOIN havre.evidence_bundles AS candidate ON candidate.owner_id=baseline.owner_id
    CROSS JOIN LATERAL (
        SELECT key FROM jsonb_object_keys(baseline.payload->'versions') AS item(key)
        UNION
        SELECT key FROM jsonb_object_keys(candidate.payload->'versions') AS item(key)
    ) AS keys
    WHERE baseline.owner_id=NEW.owner_id
      AND baseline.evidence_bundle_id=NEW.baseline_bundle_id
      AND candidate.evidence_bundle_id=NEW.candidate_bundle_id
      AND (baseline.payload->'versions'->keys.key)
          IS DISTINCT FROM (candidate.payload->'versions'->keys.key);
    undeclared_version_difference := EXISTS (
        SELECT 1 FROM unnest(observed_version_differences) AS difference(value)
        WHERE NOT (NEW.payload->'controlled_differences' ? difference.value)
    );
    IF NEW.payload->'observed_version_differences'
       <> to_jsonb(observed_version_differences) THEN
        RAISE EXCEPTION 'release comparison version differences are not exact'
            USING ERRCODE = '55000';
    END IF;
    expected_recommendation := CASE
        WHEN candidate_gate = 'rejected' OR candidate_critical > 0 THEN 'reject'
        WHEN baseline_gate <> 'candidate_review'
          OR candidate_gate <> 'candidate_review'
          OR jsonb_array_length(NEW.payload->'uncontrolled_differences') > 0
          OR undeclared_version_difference
          OR NOT comparable THEN 'inconclusive'
        ELSE 'candidate_review'
    END;
    IF NEW.critical_regression_count <> candidate_critical
       OR NEW.automated_recommendation <> expected_recommendation THEN
        RAISE EXCEPTION 'release comparison does not match durable bundle evidence'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$$;
CREATE CONSTRAINT TRIGGER release_comparisons_durable_guard
    AFTER INSERT ON havre.release_comparisons
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION havre.guard_stage8_release_comparison();

CREATE TABLE havre.evaluation_review_requests (
    review_request_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL REFERENCES havre.owners(owner_id),
    target_kind text NOT NULL CHECK (target_kind IN (
        'evidence_bundle','release_comparison','judge_calibration'
    )),
    target_id uuid NOT NULL,
    evidence_bundle_id uuid NULL,
    release_comparison_id uuid NULL,
    calibration_id uuid NULL,
    required_role text NOT NULL CHECK (required_role IN ('technical_reviewer','human_reviewer')),
    release_promotion_in_scope boolean NOT NULL CHECK (release_promotion_in_scope = false),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    UNIQUE (owner_id, review_request_id),
    UNIQUE (owner_id, target_kind, target_id, required_role),
    FOREIGN KEY (owner_id, evidence_bundle_id)
        REFERENCES havre.evidence_bundles(owner_id, evidence_bundle_id),
    FOREIGN KEY (owner_id, release_comparison_id)
        REFERENCES havre.release_comparisons(owner_id, comparison_id),
    FOREIGN KEY (owner_id, calibration_id)
        REFERENCES havre.judge_calibration_runs(owner_id, calibration_id),
    CHECK (
        (target_kind = 'evidence_bundle' AND target_id = evidence_bundle_id
         AND release_comparison_id IS NULL AND calibration_id IS NULL)
        OR
        (target_kind = 'release_comparison' AND target_id = release_comparison_id
         AND evidence_bundle_id IS NULL AND calibration_id IS NULL)
        OR
        (target_kind = 'judge_calibration' AND target_id = calibration_id
         AND evidence_bundle_id IS NULL AND release_comparison_id IS NULL)
    )
);
CREATE INDEX evaluation_review_requests_owner_bundle_idx
    ON havre.evaluation_review_requests(owner_id, evidence_bundle_id)
    WHERE evidence_bundle_id IS NOT NULL;
CREATE INDEX evaluation_review_requests_owner_comparison_idx
    ON havre.evaluation_review_requests(owner_id, release_comparison_id)
    WHERE release_comparison_id IS NOT NULL;
CREATE INDEX evaluation_review_requests_owner_calibration_idx
    ON havre.evaluation_review_requests(owner_id, calibration_id)
    WHERE calibration_id IS NOT NULL;

CREATE TABLE havre.evaluation_review_decisions (
    review_decision_id uuid PRIMARY KEY,
    schema_version smallint NOT NULL CHECK (schema_version = 1),
    owner_id uuid NOT NULL,
    review_request_id uuid NOT NULL,
    reviewer_role text NOT NULL CHECK (reviewer_role IN ('technical_reviewer','human_reviewer')),
    reviewer_ref text NOT NULL CHECK (length(reviewer_ref) BETWEEN 1 AND 240),
    decision text NOT NULL CHECK (decision IN (
        'accepted_for_candidate_evidence','rejected','changes_requested'
    )),
    blocking_finding_count integer NOT NULL CHECK (blocking_finding_count >= 0),
    release_promotion_authorized boolean NOT NULL CHECK (release_promotion_authorized = false),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    decided_at timestamptz NOT NULL,
    UNIQUE (owner_id, review_decision_id),
    UNIQUE (owner_id, review_request_id),
    FOREIGN KEY (owner_id, review_request_id)
        REFERENCES havre.evaluation_review_requests(owner_id, review_request_id),
    CHECK (blocking_finding_count = 0 OR decision <> 'accepted_for_candidate_evidence')
);

CREATE OR REPLACE FUNCTION havre.guard_evaluation_review_decision()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    request_record havre.evaluation_review_requests%ROWTYPE;
BEGIN
    SELECT * INTO request_record
    FROM havre.evaluation_review_requests
    WHERE owner_id = NEW.owner_id
      AND review_request_id = NEW.review_request_id;
    IF NOT FOUND OR request_record.required_role <> NEW.reviewer_role THEN
        RAISE EXCEPTION 'review decision role does not match durable request'
            USING ERRCODE = '55000';
    END IF;
    IF request_record.target_kind = 'evidence_bundle' AND EXISTS (
        SELECT 1
        FROM havre.evaluation_artifacts AS artifact
        WHERE artifact.owner_id = NEW.owner_id
          AND artifact.evidence_bundle_id = request_record.evidence_bundle_id
          AND NOT EXISTS (
              SELECT 1 FROM havre.evaluation_artifact_access_grants AS grant_record
              WHERE grant_record.owner_id = artifact.owner_id
                AND grant_record.artifact_id = artifact.artifact_id
                AND grant_record.actor_ref = NEW.reviewer_ref
                AND grant_record.role = NEW.reviewer_role
                AND grant_record.expires_at > NEW.decided_at
          )
    ) THEN
        RAISE EXCEPTION 'reviewer lacks active access to every bundle artifact'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER evaluation_review_decisions_guard
    BEFORE INSERT ON havre.evaluation_review_decisions
    FOR EACH ROW EXECUTE FUNCTION havre.guard_evaluation_review_decision();

CREATE TABLE havre.evidence_bundle_release_comparisons (
    owner_id uuid NOT NULL,
    evidence_bundle_id uuid NOT NULL,
    comparison_id uuid NOT NULL,
    PRIMARY KEY (owner_id, evidence_bundle_id, comparison_id),
    FOREIGN KEY (owner_id, evidence_bundle_id)
        REFERENCES havre.evidence_bundles(owner_id, evidence_bundle_id),
    FOREIGN KEY (owner_id, comparison_id)
        REFERENCES havre.release_comparisons(owner_id, comparison_id)
);
CREATE INDEX evidence_bundle_comparisons_owner_comparison_idx
    ON havre.evidence_bundle_release_comparisons(owner_id, comparison_id);

CREATE TABLE havre.evidence_bundle_review_decisions (
    owner_id uuid NOT NULL,
    evidence_bundle_id uuid NOT NULL,
    review_decision_id uuid NOT NULL,
    PRIMARY KEY (owner_id, evidence_bundle_id, review_decision_id),
    FOREIGN KEY (owner_id, evidence_bundle_id)
        REFERENCES havre.evidence_bundles(owner_id, evidence_bundle_id),
    FOREIGN KEY (owner_id, review_decision_id)
        REFERENCES havre.evaluation_review_decisions(owner_id, review_decision_id)
);
CREATE INDEX evidence_bundle_reviews_owner_decision_idx
    ON havre.evidence_bundle_review_decisions(owner_id, review_decision_id);

CREATE OR REPLACE FUNCTION havre.guard_stage8_evidence_bundle()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    derived_critical integer;
    error_count integer;
    expected_gate text;
    required_domain_count integer;
BEGIN
    SELECT count(*) FILTER (WHERE result.critical AND result.status <> 'passed'),
           count(*) FILTER (WHERE result.status = 'error'),
           count(DISTINCT run.domain) FILTER (WHERE run.domain IN (
               'behavioral','retrieval','context','routing','inference','proactive',
               'memory_lifecycle','erasure_regeneration','source_health','regression'
           ))
      INTO derived_critical, error_count, required_domain_count
    FROM havre.evidence_bundle_runs AS link
    JOIN havre.evaluation_runs AS run
      ON run.owner_id = link.owner_id
     AND run.evaluation_run_id = link.evaluation_run_id
    JOIN havre.evaluation_case_results AS result
      ON result.owner_id = run.owner_id
     AND result.evaluation_run_id = run.evaluation_run_id
    WHERE link.owner_id = NEW.owner_id
      AND link.evidence_bundle_id = NEW.evidence_bundle_id
      ;
    IF required_domain_count <> 10 THEN
        RAISE EXCEPTION 'evidence bundle is missing required Stage 8 domains'
            USING ERRCODE = '55000';
    END IF;
    IF (SELECT count(*) FROM havre.evidence_bundle_runs AS link
        WHERE link.owner_id = NEW.owner_id
          AND link.evidence_bundle_id = NEW.evidence_bundle_id)
       <> jsonb_array_length(NEW.payload->'suite_results') THEN
        RAISE EXCEPTION 'evidence bundle run links differ from payload'
            USING ERRCODE = '55000';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(NEW.payload->'suite_results') AS item
        WHERE NOT EXISTS (
            SELECT 1 FROM havre.evidence_bundle_runs AS link
            WHERE link.owner_id=NEW.owner_id
              AND link.evidence_bundle_id=NEW.evidence_bundle_id
              AND link.evaluation_run_id=(item->>'suite_result_id')::uuid
        )
    ) THEN
        RAISE EXCEPTION 'evidence bundle run payload is not durably linked'
            USING ERRCODE = '55000';
    END IF;
    expected_gate := CASE
        WHEN derived_critical > 0 THEN 'rejected'
        WHEN error_count > 0 THEN 'inconclusive'
        ELSE 'candidate_review'
    END;
    IF NEW.critical_failure_count <> derived_critical
       OR NEW.automated_gate <> expected_gate THEN
        RAISE EXCEPTION 'evidence bundle gate does not match durable case results'
            USING ERRCODE = '55000';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(NEW.payload->'judge_calibration_ids') AS item(id)
        WHERE NOT EXISTS (
            SELECT 1 FROM havre.evidence_bundle_calibrations AS link
            WHERE link.owner_id = NEW.owner_id
              AND link.evidence_bundle_id = NEW.evidence_bundle_id
              AND link.calibration_id = item.id::uuid
        )
    ) THEN
        RAISE EXCEPTION 'evidence bundle calibration payload is not durably linked'
            USING ERRCODE = '55000';
    END IF;
    IF (SELECT count(*) FROM havre.evidence_bundle_calibrations AS link
        WHERE link.owner_id = NEW.owner_id
          AND link.evidence_bundle_id = NEW.evidence_bundle_id)
       <> jsonb_array_length(NEW.payload->'judge_calibration_ids') THEN
        RAISE EXCEPTION 'evidence bundle calibration links differ from payload'
            USING ERRCODE = '55000';
    END IF;
    IF (SELECT count(*) FROM havre.evidence_bundle_traces AS link
        WHERE link.owner_id = NEW.owner_id
          AND link.evidence_bundle_id = NEW.evidence_bundle_id)
       <> jsonb_array_length(NEW.payload->'trace_ids') THEN
        RAISE EXCEPTION 'evidence bundle trace links differ from payload'
            USING ERRCODE = '55000';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(NEW.payload->'trace_ids') AS item(id)
        WHERE NOT EXISTS (
            SELECT 1 FROM havre.evidence_bundle_traces AS link
            WHERE link.owner_id=NEW.owner_id
              AND link.evidence_bundle_id=NEW.evidence_bundle_id
              AND trim(link.trace_id)=item.id
        )
    ) THEN
        RAISE EXCEPTION 'evidence bundle trace payload is not durably linked'
            USING ERRCODE = '55000';
    END IF;
    IF (SELECT count(*) FROM havre.evaluation_artifacts AS artifact
        WHERE artifact.owner_id = NEW.owner_id
          AND artifact.evidence_bundle_id = NEW.evidence_bundle_id)
       <> jsonb_array_length(NEW.payload->'artifact_ids') THEN
        RAISE EXCEPTION 'evidence bundle artifact links differ from payload'
            USING ERRCODE = '55000';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(NEW.payload->'artifact_ids') AS item(id)
        WHERE NOT EXISTS (
            SELECT 1 FROM havre.evaluation_artifacts AS artifact
            WHERE artifact.owner_id=NEW.owner_id
              AND artifact.evidence_bundle_id=NEW.evidence_bundle_id
              AND artifact.artifact_id=item.id::uuid
        )
    ) THEN
        RAISE EXCEPTION 'evidence bundle artifact payload is not durably linked'
            USING ERRCODE = '55000';
    END IF;
    IF (SELECT count(*) FROM havre.evidence_bundle_release_comparisons AS link
        WHERE link.owner_id=NEW.owner_id
          AND link.evidence_bundle_id=NEW.evidence_bundle_id)
       <> jsonb_array_length(NEW.payload->'release_comparison_ids')
       OR EXISTS (
           SELECT 1 FROM jsonb_array_elements_text(
               NEW.payload->'release_comparison_ids'
           ) AS item(id)
           WHERE NOT EXISTS (
               SELECT 1 FROM havre.evidence_bundle_release_comparisons AS link
               WHERE link.owner_id=NEW.owner_id
                 AND link.evidence_bundle_id=NEW.evidence_bundle_id
                 AND link.comparison_id=item.id::uuid
           )
       ) THEN
        RAISE EXCEPTION 'evidence bundle comparison links differ from payload'
            USING ERRCODE = '55000';
    END IF;
    IF (SELECT count(*) FROM havre.evidence_bundle_review_decisions AS link
        WHERE link.owner_id=NEW.owner_id
          AND link.evidence_bundle_id=NEW.evidence_bundle_id)
       <> jsonb_array_length(NEW.payload->'human_review_decision_ids')
       OR EXISTS (
           SELECT 1 FROM jsonb_array_elements_text(
               NEW.payload->'human_review_decision_ids'
           ) AS item(id)
           WHERE NOT EXISTS (
               SELECT 1 FROM havre.evidence_bundle_review_decisions AS link
               WHERE link.owner_id=NEW.owner_id
                 AND link.evidence_bundle_id=NEW.evidence_bundle_id
                 AND link.review_decision_id=item.id::uuid
           )
       ) THEN
        RAISE EXCEPTION 'evidence bundle review links differ from payload'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.explicit_decision = 'accepted_for_stage9_candidate_foundation' THEN
        IF jsonb_array_length(NEW.payload->'trace_ids') = 0
           OR NOT EXISTS (
               SELECT 1 FROM havre.evidence_bundle_release_comparisons AS link
               JOIN havre.release_comparisons AS comparison
                 ON comparison.owner_id = link.owner_id
                AND comparison.comparison_id = link.comparison_id
               JOIN havre.evidence_bundles AS reviewed_candidate
                 ON reviewed_candidate.owner_id = comparison.owner_id
                AND reviewed_candidate.evidence_bundle_id = comparison.candidate_bundle_id
               WHERE link.owner_id = NEW.owner_id
                 AND link.evidence_bundle_id = NEW.evidence_bundle_id
                 AND comparison.automated_recommendation = 'candidate_review'
                 AND comparison.critical_regression_count = 0
                 AND reviewed_candidate.candidate_release_id = NEW.candidate_release_id
           )
           OR NOT EXISTS (
               SELECT 1 FROM havre.evidence_bundle_review_decisions AS link
               JOIN havre.evaluation_review_decisions AS decision
                ON decision.owner_id = link.owner_id
                AND decision.review_decision_id = link.review_decision_id
               JOIN havre.evaluation_review_requests AS request
                 ON request.owner_id = decision.owner_id
                AND request.review_request_id = decision.review_request_id
               JOIN havre.evidence_bundle_release_comparisons AS comparison_link
                 ON comparison_link.owner_id = link.owner_id
                AND comparison_link.evidence_bundle_id = link.evidence_bundle_id
               JOIN havre.release_comparisons AS comparison
                 ON comparison.owner_id = comparison_link.owner_id
                AND comparison.comparison_id = comparison_link.comparison_id
               WHERE link.owner_id = NEW.owner_id
                 AND link.evidence_bundle_id = NEW.evidence_bundle_id
                 AND decision.decision = 'accepted_for_candidate_evidence'
                 AND decision.blocking_finding_count = 0
                 AND request.target_kind = 'evidence_bundle'
                 AND request.evidence_bundle_id = comparison.candidate_bundle_id
           ) THEN
            RAISE EXCEPTION 'accepted evidence lacks trace, comparison, or blocker-free review'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    RETURN NEW;
END
$$;
CREATE CONSTRAINT TRIGGER evidence_bundles_durable_guard
    AFTER INSERT ON havre.evidence_bundles
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION havre.guard_stage8_evidence_bundle();

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'evaluation_retention_policies', 'evaluation_runs',
        'evaluation_case_results', 'judge_calibration_runs', 'evidence_bundles',
        'evidence_bundle_runs', 'evidence_bundle_calibrations',
        'evidence_bundle_traces', 'evaluation_artifacts',
        'evaluation_retention_reviews',
        'evaluation_artifact_access_grants', 'evaluation_artifact_access_log',
        'release_comparisons', 'evaluation_review_requests',
        'evaluation_review_decisions', 'evidence_bundle_release_comparisons',
        'evidence_bundle_review_decisions'
    ] LOOP
        EXECUTE format(
            'CREATE TRIGGER %I_immutable BEFORE UPDATE OR DELETE ON havre.%I '
            'FOR EACH ROW EXECUTE FUNCTION havre.reject_mutation()',
            table_name, table_name
        );
    END LOOP;
END
$$;

CREATE VIEW havre.stage8_integrity_violations AS
SELECT bundle.evidence_bundle_id AS provenance_edge_id, bundle.owner_id,
       'stage8_evidence_bundle'::text AS source_kind,
       bundle.evidence_bundle_id AS source_id, NULL::integer AS source_revision,
       'missing_required_evaluation_domain'::text AS violation_code
FROM havre.evidence_bundles AS bundle
WHERE EXISTS (
    SELECT required.domain
    FROM unnest(ARRAY[
        'behavioral','retrieval','context','routing','inference','proactive',
        'memory_lifecycle','erasure_regeneration','source_health','regression'
    ]) AS required(domain)
    WHERE NOT EXISTS (
        SELECT 1
        FROM havre.evidence_bundle_runs AS link
        JOIN havre.evaluation_runs AS run
          ON run.owner_id = link.owner_id
         AND run.evaluation_run_id = link.evaluation_run_id
        WHERE link.owner_id = bundle.owner_id
          AND link.evidence_bundle_id = bundle.evidence_bundle_id
          AND run.domain = required.domain
    )
)
   OR (
       bundle.explicit_decision = 'accepted_for_stage9_candidate_foundation'
       AND (
           NOT EXISTS (
               SELECT 1 FROM havre.evidence_bundle_release_comparisons AS link
               WHERE link.owner_id = bundle.owner_id
                 AND link.evidence_bundle_id = bundle.evidence_bundle_id
           )
           OR NOT EXISTS (
               SELECT 1 FROM havre.evidence_bundle_review_decisions AS link
               JOIN havre.evaluation_review_decisions AS decision
                 ON decision.owner_id = link.owner_id
                AND decision.review_decision_id = link.review_decision_id
               WHERE link.owner_id = bundle.owner_id
                 AND link.evidence_bundle_id = bundle.evidence_bundle_id
                 AND decision.decision = 'accepted_for_candidate_evidence'
                 AND decision.blocking_finding_count = 0
           )
       )
   )
UNION ALL
SELECT artifact.artifact_id, artifact.owner_id,
       'stage8_evaluation_artifact', artifact.artifact_id, NULL::integer,
       'evaluation_artifact_policy_violation'
FROM havre.evaluation_artifacts AS artifact
WHERE artifact.privacy_class <> 'LOCAL_ONLY'
   OR artifact.memory_eligible
   OR artifact.training_eligible
   OR artifact.cloud_eligible
   OR artifact.external_transfer_allowed;
