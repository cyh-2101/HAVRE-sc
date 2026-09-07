-- State is append-oriented, so publication needs an owner-scoped lock rather
-- than a mutable head row. Delayed delivery takes the same transaction lock.
-- Enforce it for direct SQL INSERT as well as the repository writer.
CREATE FUNCTION havre.lock_current_state_publication()
RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
  PERFORM pg_advisory_xact_lock(
    hashtext('havre-current-state-v1'), hashtext(NEW.owner_id::text)
  );
  RETURN NEW;
END;
$function$;

CREATE TRIGGER a_current_state_delivery_freshness_lock
BEFORE INSERT ON havre.current_state_snapshots
FOR EACH ROW EXECUTE FUNCTION havre.lock_current_state_publication();
