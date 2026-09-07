BEGIN;

-- The canonical observation material contains the same bounded, minimized
-- availability projection as its signed draft. Keep the database bound
-- consistent with the typed 512-interval Stage 12A contract.
ALTER TABLE havre.life_context_observations
    DROP CONSTRAINT life_context_observations_canonical_content_material_check,
    ADD CONSTRAINT life_context_observations_canonical_content_material_check
        CHECK (length(canonical_content_material) BETWEEN 2 AND 131072);

COMMIT;
