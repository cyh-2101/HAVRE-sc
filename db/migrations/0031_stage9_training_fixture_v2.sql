-- New candidates must use physically separated training-v2 and holdout-v2 fixtures.

ALTER TABLE havre.training_dataset_snapshots
    DROP CONSTRAINT training_dataset_snapshots_name_check,
    DROP CONSTRAINT training_dataset_snapshots_semantic_version_check,
    DROP CONSTRAINT training_dataset_snapshots_builder_version_check,
    DROP CONSTRAINT training_dataset_snapshots_split_policy_version_check;

ALTER TABLE havre.training_dataset_snapshots
    ADD CONSTRAINT training_dataset_snapshots_name_v2_check
        CHECK (name='stage9-synthetic-public-training-v2') NOT VALID,
    ADD CONSTRAINT training_dataset_snapshots_semantic_version_v2_check
        CHECK (semantic_version='2.0.0') NOT VALID,
    ADD CONSTRAINT training_dataset_snapshots_builder_version_v2_check
        CHECK (builder_version='stage9-canonical-fixture-builder-v2') NOT VALID,
    ADD CONSTRAINT training_dataset_snapshots_split_policy_version_v2_check
        CHECK (split_policy_version='fixed-train-validation-holdout-exclusion-v2') NOT VALID;
