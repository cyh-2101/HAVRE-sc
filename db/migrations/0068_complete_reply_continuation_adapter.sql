-- Same authorized GPT/model/no-tools boundary, a versioned parser that preserves
-- every completed answer item. Historical v2 receipts remain valid and unchanged.
ALTER TABLE havre.owner_conversation_continuation_runs
 DROP CONSTRAINT owner_conversation_continuation_terminal_provider_check;
ALTER TABLE havre.owner_conversation_continuation_runs
 ADD CONSTRAINT owner_conversation_continuation_terminal_provider_check
 CHECK (COALESCE(status NOT IN ('completed','no_action') OR (
   inference_request_id IS NOT NULL AND request_binding_hash IS NOT NULL
   AND model_version_id IS NOT NULL AND provider_adapter_version_id IS NOT NULL
   AND serving_config_version IS NOT NULL AND result IS NOT NULL
   AND response_content_hash IS NOT NULL AND error_code IS NULL
   AND (
     (authorization_ref IN (
       'product-owner/local-conversation-continuation-2026-09-04',
       'product-owner/two-beat-friend-conversation-2026-09-04')
       AND provider_id='self-hosted-openai-compatible' AND reasoning_effort IS NULL)
     OR
     (authorization_ref='product-owner/gpt-two-beat-friend-conversation-2026-09-04'
       AND provider_id='openai-codex-chatgpt' AND model_version_id='gpt-5.6-sol'
       AND provider_adapter_version_id IN (
         'codex-cli-provider-v2-owner-automatic',
         'codex-cli-provider-v3-complete-reply')
       AND serving_config_version='codex-cli-reply-only-no-tools-v2-high'
       AND reasoning_effort='high')
   )
 ),false));
