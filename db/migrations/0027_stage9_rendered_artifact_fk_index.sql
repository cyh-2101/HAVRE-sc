-- Complete the left-prefix index for the rendered-artifact composite foreign key.

CREATE INDEX training_runs_owner_rendered_artifact_idx
    ON havre.training_runs(
        owner_id, rendered_artifact_id, dataset_snapshot_id, model_version_id
    );
