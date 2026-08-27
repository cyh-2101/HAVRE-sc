\set ON_ERROR_STOP on

-- Run as the database owner after HAVRE migrations. These are NOLOGIN group
-- roles; create separate LOGIN roles with protected passwords outside this file.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_application') THEN
        CREATE ROLE havre_application NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_erasure_executor') THEN
        CREATE ROLE havre_erasure_executor NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_release_operator') THEN
        CREATE ROLE havre_release_operator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_restore_operator') THEN
        CREATE ROLE havre_restore_operator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='havre_context_operator') THEN
        CREATE ROLE havre_context_operator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END
$$;

REVOKE CONNECT ON DATABASE :DBNAME FROM PUBLIC;
GRANT CONNECT ON DATABASE :DBNAME TO havre_application, havre_erasure_executor,
    havre_release_operator, havre_restore_operator, havre_context_operator;
GRANT USAGE ON SCHEMA havre TO havre_application;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA havre TO havre_application;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA havre TO havre_application;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA havre TO havre_application;

GRANT havre_application TO havre_erasure_executor;
GRANT havre_privileged_erasure TO havre_erasure_executor;
GRANT havre_privileged_erasure TO havre_restore_operator;
GRANT DELETE ON ALL TABLES IN SCHEMA havre TO havre_erasure_executor;
GRANT USAGE ON SCHEMA havre TO havre_release_operator;
REVOKE SELECT ON ALL TABLES IN SCHEMA havre FROM havre_release_operator;
GRANT SELECT ON havre.component_promotion_authorizations,
    havre.release_manifests, havre.release_approval_records,
    havre.deployments, havre.backup_manifests, havre.restore_erasure_replays
    TO havre_release_operator;
GRANT INSERT ON havre.release_manifests, havre.release_approval_records,
    havre.deployments, havre.backup_manifests, havre.restore_erasure_replays,
    havre.component_promotion_authorizations
    TO havre_release_operator;

ALTER DEFAULT PRIVILEGES IN SCHEMA havre
    GRANT SELECT, INSERT, UPDATE ON TABLES TO havre_application;
ALTER DEFAULT PRIVILEGES IN SCHEMA havre
    GRANT USAGE, SELECT ON SEQUENCES TO havre_application;
ALTER DEFAULT PRIVILEGES IN SCHEMA havre
    GRANT EXECUTE ON FUNCTIONS TO havre_application;
ALTER DEFAULT PRIVILEGES IN SCHEMA havre
    GRANT DELETE ON TABLES TO havre_erasure_executor;

DO $$
BEGIN
    IF pg_has_role('havre_application', 'havre_privileged_erasure', 'MEMBER') THEN
        REVOKE havre_privileged_erasure FROM havre_application;
    END IF;
END
$$;
REVOKE DELETE ON ALL TABLES IN SCHEMA havre FROM havre_application;
REVOKE INSERT, UPDATE, DELETE ON havre.release_manifests,
    havre.release_approval_records, havre.deployments,
    havre.backup_manifests, havre.restore_erasure_replays,
    havre.component_promotion_authorizations
    FROM havre_application;

-- Stage 12 external-source enrollment and consent are owner-controlled
-- operations, not ordinary API writes. Device verification keys are never
-- readable by the application role. Signed observation/health inserts remain
-- available and are revalidated by database triggers.
DO $$
BEGIN
    IF to_regclass('havre.context_device_bindings') IS NOT NULL THEN
        REVOKE ALL ON havre.context_device_bindings FROM havre_application, PUBLIC;
        REVOKE INSERT, UPDATE, DELETE ON havre.context_sources,
            havre.context_source_erasure_tombstones,
            havre.context_source_state_revisions,
            havre.context_restore_quarantines,
            havre.context_source_capabilities,
            havre.context_capability_state_revisions,
            havre.context_consent_scope_revisions,
            havre.context_retention_expiry_intents,
            havre.context_retention_expiry_receipts FROM havre_application;
        GRANT SELECT ON havre.context_sources,
            havre.context_source_erasure_tombstones,
            havre.context_source_state_revisions,
            havre.context_source_capabilities,
            havre.context_capability_state_revisions,
            havre.context_consent_scope_revisions,
            havre.life_context_observations,
            havre.context_source_health_records,
            havre.context_retention_expiry_intents,
            havre.context_retention_expiry_receipts,
            havre.context_device_binding_metadata TO havre_application;
        GRANT INSERT ON havre.life_context_observations,
            havre.context_source_health_records TO havre_application;
        GRANT INSERT ON havre.context_retention_expiry_intents,
            havre.context_retention_expiry_receipts TO havre_privileged_erasure;
        GRANT INSERT, SELECT ON havre.context_restore_quarantines
            TO havre_privileged_erasure;
        GRANT INSERT, SELECT ON havre.context_source_erasure_tombstones
            TO havre_privileged_erasure;
        REVOKE UPDATE, DELETE ON havre.context_source_erasure_tombstones
            FROM havre_application, havre_erasure_executor,
                 havre_privileged_erasure, PUBLIC;
        GRANT USAGE ON SCHEMA havre TO havre_context_operator;
        GRANT SELECT ON havre.context_sources,
            havre.context_source_erasure_tombstones,
            havre.context_device_bindings,
            havre.context_source_state_revisions,
            havre.context_source_capabilities,
            havre.context_capability_state_revisions,
            havre.context_consent_scope_revisions,
            havre.context_restore_quarantines TO havre_context_operator;
        GRANT INSERT ON havre.sessions, havre.traces,
            havre.interaction_requests, havre.events,
            havre.context_sources, havre.context_device_bindings,
            havre.context_source_state_revisions,
            havre.context_source_capabilities,
            havre.context_capability_state_revisions,
            havre.context_consent_scope_revisions,
            havre.context_source_health_records TO havre_context_operator;
    END IF;
END
$$;
