-- Admit the curated owner-day Diary summarizer without rewriting any historical
-- revision.  v1/v2 remain readable and immutable; new revisions may use v3.

ALTER TABLE havre.daily_diary_entry_revisions
  DROP CONSTRAINT daily_diary_entry_revisions_summary_method_check;

ALTER TABLE havre.daily_diary_entry_revisions
  ADD CONSTRAINT daily_diary_entry_revisions_summary_method_check
  CHECK (summary_method IN (
    'evidence-extractive-diary-v1',
    'evidence-event-diary-v2',
    'curated-owner-day-diary-v3'
  ));
