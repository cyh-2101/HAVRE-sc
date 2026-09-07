-- Preserve already-applied 0069; two-character project/name anchors (AI, VR,
-- Li) must be indexed exactly as runtime query terms. Rebuild the derived index
-- atomically after changing its immutable expression function.
CREATE OR REPLACE FUNCTION havre.event_context_search_terms(payload jsonb)
RETURNS text[] LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $function$
  WITH parts AS (
    SELECT item->>'text' AS value
    FROM jsonb_array_elements(
      CASE WHEN jsonb_typeof(payload->'content_parts')='array'
        THEN payload->'content_parts' ELSE '[]'::jsonb END
    ) item
    WHERE item->>'type'='text'
  ), spans AS (
    SELECT match[1] AS value FROM parts,
      LATERAL regexp_matches(lower(value), '[a-z0-9]{2,}|[㐀-鿿]+', 'g') match
  ), terms AS (
    SELECT value AS term FROM spans WHERE value ~ '^[a-z0-9]'
    UNION
    SELECT substr(value,position,2) FROM spans,
      LATERAL generate_series(1,char_length(value)-1) position
    WHERE value ~ '^[㐀-鿿]'
  )
  SELECT COALESCE(array_agg(term ORDER BY term), ARRAY[]::text[]) FROM terms;
$function$;

REINDEX INDEX havre.events_personal_context_terms_gin_idx;
