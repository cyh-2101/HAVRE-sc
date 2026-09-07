BEGIN;

-- Stage 12A permits up to 512 availability-only intervals. The original
-- 16 KiB signing-material bound rejected valid semester projections well
-- before that typed limit. This remains bounded and changes no semantics,
-- privacy class, retained fields, or provider-content prohibition.
ALTER TABLE havre.life_context_observations
    DROP CONSTRAINT life_context_observations_draft_signing_material_check,
    ADD CONSTRAINT life_context_observations_draft_signing_material_check
        CHECK (length(draft_signing_material) BETWEEN 2 AND 131072);

COMMIT;
