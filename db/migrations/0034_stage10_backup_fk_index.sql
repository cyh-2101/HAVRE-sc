BEGIN;

CREATE INDEX backup_manifests_owner_release_hash_idx
    ON havre.backup_manifests(
        owner_id,
        release_manifest_id,
        release_manifest_hash
    );

COMMIT;
