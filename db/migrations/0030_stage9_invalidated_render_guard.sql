-- An invalidated pre-correction snapshot cannot produce any new trainer-visible artifact.

CREATE OR REPLACE FUNCTION havre.guard_stage9_rendered_training_artifact()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE linked_count integer; rendered_count integer;
BEGIN
    IF EXISTS (
        SELECT 1 FROM havre.stage9_candidate_invalidations invalidation
        WHERE invalidation.owner_id=NEW.owner_id
          AND invalidation.dataset_snapshot_id=NEW.dataset_snapshot_id
    ) THEN
        RAISE EXCEPTION 'invalidated Stage 9 snapshot cannot produce rendered artifacts'
            USING ERRCODE='55000';
    END IF;
    SELECT count(*) INTO linked_count FROM havre.training_dataset_members
    WHERE owner_id=NEW.owner_id AND dataset_snapshot_id=NEW.dataset_snapshot_id;
    rendered_count := jsonb_array_length(NEW.payload->'examples');
    IF rendered_count IS NULL OR rendered_count <> linked_count OR EXISTS (
        SELECT 1 FROM jsonb_array_elements(NEW.payload->'examples') item
        WHERE NOT EXISTS (
            SELECT 1 FROM havre.training_dataset_members member
            WHERE member.owner_id=NEW.owner_id
              AND member.dataset_snapshot_id=NEW.dataset_snapshot_id
              AND member.example_id=item->>'example_id'
              AND member.content_hash=item->>'source_content_hash'
              AND item->>'rendered_text' =
                  '<user>' || (member.payload->>'input_text') ||
                  '</user><assistant>' || (member.payload->>'expected_text') || '</assistant>'
        )
    ) THEN
        RAISE EXCEPTION 'rendered artifact is not exact training-only membership'
            USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END $$;
