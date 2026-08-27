\set ON_ERROR_STOP on

-- Run as the target database administrator after backup-restore and before
-- bootstrap_roles.sql. The restore LOGIN temporarily owns objects because
-- pg_restore intentionally uses --no-owner. Cutover must remove that implicit
-- owner privilege before ordinary traffic is allowed.
-- Each fail-closed assertion deliberately divides by zero on mismatch so the
-- psql ON_ERROR_STOP contract aborts before any ownership changes.
SELECT 1 / CASE WHEN current_database() = :'DBNAME' THEN 1 ELSE 0 END;
SELECT 1 / CASE WHEN current_user <> :'RESTORE_LOGIN' THEN 1 ELSE 0 END;
SELECT 1 / CASE WHEN EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = :'RESTORE_LOGIN'
      AND rolcanlogin
      AND NOT rolsuper
) THEN 1 ELSE 0 END;
SELECT 1 / CASE WHEN pg_has_role(
    :'RESTORE_LOGIN', 'havre_restore_operator', 'MEMBER'
) THEN 1 ELSE 0 END;

REASSIGN OWNED BY :"RESTORE_LOGIN" TO CURRENT_USER;
ALTER DATABASE :"DBNAME" OWNER TO CURRENT_USER;

SELECT 1 / CASE WHEN NOT EXISTS (
    SELECT 1
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_roles r ON r.oid = c.relowner
    WHERE n.nspname = 'havre'
      AND r.rolname = :'RESTORE_LOGIN'
) THEN 1 ELSE 0 END;
