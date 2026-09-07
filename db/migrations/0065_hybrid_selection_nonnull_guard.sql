-- Additive correction: SQL CHECK's unknown result must not admit null gates.
ALTER TABLE havre.retrieval_results ADD CONSTRAINT retrieval_results_hybrid_binding_check
CHECK ((algorithm_version <> 'retrieval-r2-hybrid-v1'
        AND selection_policy_version <> 'retrieval-selection-hybrid-v1') OR (
    algorithm_version = 'retrieval-r2-hybrid-v1'
    AND selection_policy_version = 'retrieval-selection-hybrid-v1'
    AND embedding_version_id = 'embedding-minilm-multilingual-int8-v1'
    AND minimum_semantic_similarity IS NOT NULL AND minimum_semantic_similarity=0.20
    AND duplicate_similarity_threshold IS NOT NULL AND duplicate_similarity_threshold=0.92
    AND duplicate_token_overlap_threshold IS NOT NULL AND duplicate_token_overlap_threshold=0.8
));
