# Stage 9A Dataset v4 Product Owner Freeze Review

Status: **PENDING PRODUCT OWNER FREEZE — TRAINING NOT AUTHORIZED**

- Dataset: `stage9a-havre-companion-v4-candidate-1`
- External candidate bundle: `sha256:13fa5a62ec6edc571c51468a8a07c2c362744236de0b418a0d9c543de0b586c4`
- Repo-native bundle: `sha256:13fa5a62ec6edc571c51468a8a07c2c362744236de0b418a0d9c543de0b586c4`
- Review manifest content hash: `sha256:a2c5739bebbc7745546cd80ec8eb8ba9d512e3e1f0bdf70ae9c3c9056ef0f179`
- Train / validation / sealed holdout: `300 / 60 / 120`
- Owner Alignment Set: 70 PRIVATE, local-only, permanently evaluation-only cases; excluded from every training and tuning input.
- Renderer: `qwen3-v4-multiturn-final-target-no-thinking-v1`; full multi-turn context, historical assistant turns masked, final HAVRE target only supervised; every rendered consumer revalidates the exact Product Owner freeze approval.
- Memory: supplied synthetic memory only, selective by canonical flags, current conversation wins on conflict.
- Proactive: message wording only after governed Core has already authorized `SEND_NOW`.
- Evaluation: `havre-behavioral-rubric-v4` property dimensions are primary; reference-token F1 is diagnostic only.

The complete Product Owner-authored review remains byte-preserved at:
`<repo>\var\stage9a\imports\HAVRE_STAGE9A_V4_CANDIDATE_1\PO_REVIEW_v4.md`

Its SHA-256 is `sha256:f8d5cc123da099e7a87e7904727817523ce23db13731ab1ece685271d09ce49e`.

## Product Owner decision

- [ ] ACCEPT exact v4 bundle for freeze and later formal rendering/training
- [ ] EDIT (requires a new externally authored immutable candidate)
- [ ] REJECT

Decision: __________

Product Owner: __________

Recorded at: __________

No approval file was created by this review builder. Seed 9201/9202 remain blocked until a separate exact-hash Product Owner freeze decision is recorded.
