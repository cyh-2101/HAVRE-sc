-- A disposable local search index over preserved Events, not a second history.
-- No remote encoder, policy relaxation, or new source collection is involved.
CREATE FUNCTION havre.event_context_search_terms(payload jsonb)
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
      LATERAL regexp_matches(lower(value), '[a-z0-9]{3,}|[㐀-鿿]+', 'g') match
  ), terms AS (
    SELECT value AS term FROM spans WHERE value ~ '^[a-z0-9]'
    UNION
    SELECT substr(value,position,2) FROM spans,
      LATERAL generate_series(1,char_length(value)-1) position
    WHERE value ~ '^[㐀-鿿]'
  )
  SELECT COALESCE(array_agg(term ORDER BY term), ARRAY[]::text[]) FROM terms;
$function$;

CREATE INDEX events_personal_context_terms_gin_idx
ON havre.events USING gin (havre.event_context_search_terms(payload))
WHERE event_type='USER_MESSAGE'
  AND privacy_class IN ('PUBLIC','NORMAL') AND cloud_eligible AND memory_eligible;

COMMENT ON INDEX havre.events_personal_context_terms_gin_idx IS
'Rebuildable lexical candidates only; runtime independently requires exact owner, as-of, completed GPT route, and non-revoked source.';
