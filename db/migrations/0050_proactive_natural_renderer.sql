-- Admit the natural proactive renderer while retaining historical v1 rows.

BEGIN;

ALTER TABLE havre.rendered_proactive_messages
  DROP CONSTRAINT rendered_proactive_messages_renderer_version_check,
  ADD CONSTRAINT rendered_proactive_messages_renderer_version_check CHECK (
    renderer_version IN ('proactive-template-v1','proactive-natural-template-v2')
  );

COMMIT;
