-- Keep historical vectors; bind each vector to its registered dimension.
ALTER TABLE havre.embedding_versions DROP CONSTRAINT embedding_versions_dimension_check;
ALTER TABLE havre.embedding_versions ADD CONSTRAINT embedding_versions_dimension_check
    CHECK (dimension IN (64,384));
ALTER TABLE havre.memory_embeddings ALTER COLUMN embedding TYPE vector;

CREATE FUNCTION havre.guard_embedding_dimension() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected_dimension integer; expected_hash text;
BEGIN
    SELECT dimension INTO expected_dimension FROM havre.embedding_versions
      WHERE embedding_version_id=NEW.embedding_version_id;
    SELECT content_hash INTO expected_hash FROM havre.memory_revisions
      WHERE owner_id=NEW.owner_id AND memory_id=NEW.memory_id AND revision=NEW.memory_revision;
    IF expected_dimension IS NULL OR vector_dims(NEW.embedding)<>expected_dimension
       OR expected_hash IS NULL OR NEW.content_hash<>expected_hash THEN
        RAISE EXCEPTION 'embedding must match registered dimension and exact memory revision';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER memory_embeddings_dimension_guard BEFORE INSERT ON havre.memory_embeddings
    FOR EACH ROW EXECUTE FUNCTION havre.guard_embedding_dimension();

ALTER TABLE havre.retrieval_results DROP CONSTRAINT retrieval_results_selection_policy_check;
ALTER TABLE havre.retrieval_results ADD CONSTRAINT retrieval_results_selection_policy_check CHECK (
    (selection_policy_version='retrieval-selection-legacy-ungated-v1'
      AND minimum_semantic_similarity IS NULL AND duplicate_similarity_threshold IS NULL
      AND duplicate_token_overlap_threshold IS NULL)
    OR (selection_policy_version='retrieval-selection-context-safe-v1'
      AND minimum_semantic_similarity IS NOT NULL AND duplicate_similarity_threshold IS NOT NULL
      AND duplicate_token_overlap_threshold IS NOT NULL)
    OR (selection_policy_version='retrieval-selection-hybrid-v1'
      AND algorithm_version='retrieval-r2-hybrid-v1'
      AND embedding_version_id='embedding-minilm-multilingual-int8-v1'
      AND minimum_semantic_similarity=0.20 AND duplicate_similarity_threshold=0.92
      AND duplicate_token_overlap_threshold=0.8)
);
