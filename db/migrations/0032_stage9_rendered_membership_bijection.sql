-- Close the rendered-training membership multiplicity bypass without rewriting 0030.
-- Trainer-visible artifacts must be a bijection over the durable canonical members.

CREATE FUNCTION havre.stage9_rendered_training_artifact_is_exact(
    artifact havre.rendered_training_artifacts
)
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
    SELECT COALESCE((
        SELECT
            NOT EXISTS (
                SELECT 1
                FROM havre.stage9_candidate_invalidations invalidation
                WHERE invalidation.owner_id=artifact.owner_id
                  AND invalidation.dataset_snapshot_id=artifact.dataset_snapshot_id
            )
            AND artifact.payload->>'rendered_artifact_id' = artifact.rendered_artifact_id::text
            AND artifact.payload->>'owner_id' = artifact.owner_id::text
            AND artifact.payload->>'dataset_snapshot_id' = artifact.dataset_snapshot_id::text
            AND artifact.payload->>'model_version_id' = artifact.model_version_id::text
            AND artifact.payload->>'renderer_version' = artifact.renderer_version
            AND artifact.payload->>'tokenizer_version' = artifact.tokenizer_version
            AND artifact.source_member_manifest_hash = snapshot.member_manifest_hash
            AND artifact.payload->>'source_member_manifest_hash' = snapshot.member_manifest_hash
            AND snapshot.member_manifest_hash = havre.stage5_content_hash((
                SELECT COALESCE(
                    jsonb_agg(
                        jsonb_build_object(
                            'example_id', member.example_id,
                            'content_hash', member.content_hash,
                            'split', member.split,
                            'source_ref', member.source_ref
                        ) ORDER BY member.example_id
                    ),
                    '[]'::jsonb
                )
                FROM havre.training_dataset_members member
                WHERE member.owner_id=artifact.owner_id
                  AND member.dataset_snapshot_id=artifact.dataset_snapshot_id
            ))
            AND jsonb_array_length(artifact.payload->'examples') = (
                SELECT count(*)
                FROM havre.training_dataset_members member
                WHERE member.owner_id=artifact.owner_id
                  AND member.dataset_snapshot_id=artifact.dataset_snapshot_id
            )
            AND jsonb_array_length(artifact.payload->'examples') = (
                SELECT count(DISTINCT item->>'example_id')
                FROM jsonb_array_elements(artifact.payload->'examples') item
            )
            AND NOT EXISTS (
                SELECT 1
                FROM jsonb_array_elements(artifact.payload->'examples') item
                WHERE item->>'example_id' IS NULL
                   OR NOT EXISTS (
                       SELECT 1
                       FROM havre.training_dataset_members member
                       WHERE member.owner_id=artifact.owner_id
                         AND member.dataset_snapshot_id=artifact.dataset_snapshot_id
                         AND member.example_id=item->>'example_id'
                         AND member.content_hash=item->>'source_content_hash'
                         AND item->>'rendered_text' =
                             '<user>' || (member.payload->>'input_text') ||
                             '</user><assistant>' || (member.payload->>'expected_text') ||
                             '</assistant>'
                   )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM havre.training_dataset_members member
                WHERE member.owner_id=artifact.owner_id
                  AND member.dataset_snapshot_id=artifact.dataset_snapshot_id
                  AND (
                      SELECT count(*)
                      FROM jsonb_array_elements(artifact.payload->'examples') item
                      WHERE item->>'example_id'=member.example_id
                        AND item->>'source_content_hash'=member.content_hash
                        AND item->>'rendered_text' =
                            '<user>' || (member.payload->>'input_text') ||
                            '</user><assistant>' || (member.payload->>'expected_text') ||
                            '</assistant>'
                  ) <> 1
            )
        FROM havre.training_dataset_snapshots snapshot
        WHERE snapshot.owner_id=artifact.owner_id
          AND snapshot.dataset_snapshot_id=artifact.dataset_snapshot_id
    ), false)
$$;

CREATE OR REPLACE FUNCTION havre.guard_stage9_rendered_training_artifact()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT havre.stage9_rendered_training_artifact_is_exact(NEW) THEN
        RAISE EXCEPTION 'rendered artifact is not an exact manifest-bound bijection over training members'
            USING ERRCODE='55000';
    END IF;
    RETURN NEW;
END $$;

-- Refuse to install the closure over a populated database that already contains
-- trainer-visible artifacts which do not satisfy the new durable invariant.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM havre.rendered_training_artifacts artifact
        WHERE NOT havre.stage9_rendered_training_artifact_is_exact(artifact)
    ) THEN
        RAISE EXCEPTION 'existing rendered training artifact violates exact membership bijection'
            USING ERRCODE='55000';
    END IF;
END $$;
