# Stage 9 Candidate Training Foundation Checkpoint

Date: **2026-08-20**

Status: **The bounded Stage 9 foundation remains accepted. Stage 9A Dataset v4 candidate execution and evaluation are complete and stopped at the Product Owner acceptance gate. Dataset v2 and v3 remain rejected. The prior v1 Qwen3-8B QLoRA adapters remain immutable historical candidates. Formal v4 Seeds 9201/9202 completed; Seed 9203 was not run under the predeclared material-variance rule. No adapter is promoted or deployed. Stage 9B and Stage 10 remain unauthorized.**

Second-correction execution-source snapshot: `sha256:bf0ffbba5ade5d1370252c1f84ea1806b6ba5910f1c59ab4dff6df1f155d4119`

## Product Owner acceptance and Stage 9A boundary

On 2026-08-19 the Product Owner accepted this bounded candidate foundation and
its evidence hash
`sha256:260b311a6bc8b21ff721687dc2f30150eb9d45e72dd4b90fa0c41f8e0ba54277`.
This acceptance does not assert that real transformer training or full Stage 9
is complete.

The Product Owner separately authorized Stage 9A real-transformer feasibility
and training using repository-owned synthetic data only. All artifacts remain
local-only and candidate-only. Personal/user data remains
`training_eligible=false`; promotion, production deployment, Stage 9B, Stage 10,
and governance/accepted-ADR changes remain unauthorized. The Product Owner has
approved the bounded QLoRA budget. Training remains subject to the Gate A-D
sequence and resource limits; Gate B cannot begin until exact model provenance
is complete.

## Authorized scope

This checkpoint covers only:

- a training pipeline after a canonical dataset boundary;
- model, rendered-artifact, training, and adapter registries;
- exact adapter/base compatibility checks;
- local repository-authored synthetic/public LoRA and QLoRA dry-runs;
- Base / Base+Memory / Base+Adapter / Base+Memory+Adapter evaluation;
- candidate-only adapters and rejection/no-activation rollback evidence.

It does not use user-derived training data, modify privacy classification,
change or activate Constitution/Identity/Values/Intervention Policy, transfer
data to cloud services, or promote/deploy an adapter.

## Rejected initial candidate

Product Owner review rejected the initial Stage 9 candidate because its
`TrainingDatasetSnapshot` required train, validation, and holdout membership and
`RenderedTrainingArtifact` rendered all eight members. Although the toy optimizer
selected only the train split, the durable trainer-visible artifact contained
two evaluation holdout cases. This violated the holdout exclusion rules in
`MLSYS_DESIGN.md` and `EVALUATION_PLAN.md`.

The rejected historical evidence remains at
`evals/reports/stage9_20260819/candidate-dry-run.json`, hash
`sha256:279c7457f9f3e25cfddf7a11c216408a8260fe90c5842eec40e99077f1da61cc`.
It is not valid Stage 9 exit evidence and cannot authorize any candidate action.

## Rejected first correction

Product Owner trust-boundary review then rejected the first holdout-separation
correction at execution-source snapshot
`sha256:b0ed13e1e64d182f442b7b31e18853977184c69a209654a41e699b4c97380fd1`.
Migration `0030` compared only the rendered entry count with the durable member
count and proved only rendered-to-member existence. It did not require unique
`example_id` values or prove member-to-rendered coverage. Direct SQL therefore
committed an artifact containing six copies of one valid member, omitting the
other five, and a `TrainingRun` bound to that artifact. The review probe was
rolled back and confirmed that no forged artifact or run remained.

The first-correction evidence remains at
`evals/reports/stage9_20260819/candidate-dry-run-correction1.json`, hash
`sha256:40addc2c02f6e1d94f8dcd2f585b1c4312880a1af9906fc7813081f1de35d334`.
It is historical rejected evidence, not Stage 9 exit evidence.

## Implementation

- `stage9_synthetic_public_training_v2.json` physically contains only four
  train and two validation examples. `stage9_synthetic_public_holdout_v2.json`
  separately contains two evaluation-only cases. Their IDs are disjoint.
- Training members remain repository-authored CC0, `training_eligible=true`,
  `contains_user_data=false`, and `privacy_class=PUBLIC`. Holdout cases are
  independently forced to `training_eligible=false`, `evaluation_only=true`,
  and `access_limited=true`.
- `TrainingDatasetSnapshot` is model-independent and hashes an immutable member
  manifest containing only train/validation members. It records only the
  excluded holdout IDs and exact holdout manifest hash, cannot reference HAVRE
  Events, and records `user_event_source_count=0`.
- `RenderedTrainingArtifact` is a separate model-specific build containing the
  exact renderer/tokenizer versions and hashed token IDs. Training runs bind its
  exact dataset and base model. The additive `0032` guard recomputes the canonical
  member manifest from durable member rows, binds it to both the snapshot and
  artifact column/JSON, requires unique rendered IDs, proves both directions of
  membership, and requires every durable member to appear exactly once. A holdout,
  omitted member, duplicated member, or forged manifest cannot enter the artifact.
- Dependency-free local dry-runs execute rank-2 low-rank matrix updates for two
  seeds. The QLoRA path quantizes the synthetic base matrix to four bits before
  applying its low-rank adapter. This is an algorithmic pipeline exercise, not
  transformer training or evidence of personal quality.
- PostgreSQL migrations `0024` through `0032` add immutable owner-scoped
  registries, compatibility/evaluation/rejection records, FK indexes, and
  deferred cross-record guards. `0029` separates holdout storage and automatically
  invalidates any populated pre-correction snapshot containing holdout;
  `0030` prevents invalidated snapshots from producing new rendered artifacts;
  `0031` requires the physically separated v2 fixture contract; additive `0032`
  closes the rendered-membership multiplicity bypass without modifying `0030`
  and refuses installation if a populated database already contains a rendered
  artifact that violates the new invariant. No activation or production
  table/path exists.
- Direct SQL is rejected for `training_eligible=false`, promotion/deployment,
  wrong base hashes, missing rendered artifacts, holdout training membership,
  rendered artifacts containing holdout, repeated-member artifacts and their
  bound TrainingRuns, forged source manifests, and rejection records bound to a
  different adapter.

## Dry-run evidence

Second-correction candidate artifact:
`evals/reports/stage9_20260819/candidate-dry-run-correction2.json`

- evidence hash: `sha256:260b311a6bc8b21ff721687dc2f30150eb9d45e72dd4b90fa0c41f8e0ba54277`
- training dataset snapshot: `01a0196a-0d94-7c3e-8d7a-5886d264dfec`
- training fixture hash: `sha256:cc504e016aef5476bdd22dd12faca0be7aedfd7d13dbda8806f5aca85723d2a1`
- training member manifest: `sha256:5a84c519757ca36a2d8b5238dfac4da5bdc6a6965dcf62f32d24109a03c21f8e`
- excluded holdout manifest: `sha256:fbd2232c9239629b28fb38b5caa135b23f7bbbe028bcba78dc124bd9a0fd5704`
- separate holdout suite: `01a0196a-0d94-7c3f-ac03-247b0361a5b1`, fixture hash
  `sha256:822c182aac651dd5eedc8946935598b79982b07ed67b68cbbbc0d25032d4b14b`
- LoRA run: `01a0196a-0d97-7365-99c5-9ea507509591`, loss
  `0.06598473816662356 -> 0.06597877953440176`
- QLoRA run: `01a0196a-0d98-763f-a5dc-3d07b3fa7e33`, loss
  `0.06556650814061488 -> 0.06552669571824452`
- selected evaluation adapter:
  `01a0196a-0d99-7efd-a924-c4a799fcab10` (QLoRA candidate)
- factorial evaluation: `01a0196a-0d9a-710a-b288-4f5d07cd8d65`, bound to the
  separate holdout suite and containing exactly
  Base, Base+Memory, Base+Adapter, and Base+Memory+Adapter arms
- rejection: `01a0196a-0d9a-710b-a6b1-a8c17803f901`, effect
  `no_activation_to_rollback`

The evidence explicitly records `human_benefit_claimed=false`,
`release_promotion_authorized=false`, and both adapters as
`lifecycle_status=candidate`, `promotion_authorized=false`, `deployed=false`.

## Verification

Dedicated fresh database: `havre_s9_bijection_full_20260819` on the repository-owned
local PostgreSQL instance.

- full PostgreSQL-backed repository suite: **264 passed, 0 failed, 0 skipped**
  in 24.464 seconds;
- Stage 9 contracts: **8 passed**; Stage 9 PostgreSQL tests: **10 passed**,
  including the exact repeated-member artifact plus bound-TrainingRun attack and
  a separate noncanonical-manifest attack;
- Stage 4, 5, 6, 7, 8, and 9 FK index audits: `[]`;
- provenance audit: `[]`;
- Stage 8 integrity violations: `0`;
- Stage 9 integrity violations: `0`;
- durable counts: training snapshot `train=4`, `validation=2`, `holdout=0`;
  separate evaluation holdout `2`, all training-ineligible/evaluation-only/access-limited;
- populated `0028 -> 0029/0030/0031` upgrade retained the contaminated holdout
  as historical evidence, wrote reason
  `evaluation_holdout_in_training_snapshot_v1`, and reported zero active
  integrity violations;
- populated `0031 -> 0032` upgrade retained one valid rendered artifact and two
  valid training runs, applied only `0032`, rejected the repeated-member artifact
  plus bound run with SQLSTATE `55000`, left both forged counts at zero, and
  reported zero Stage 9 integrity violations;
- contract schemas regenerated from authoritative Pydantic models and compared
  byte-semantically by tests;
- `pip check`, `compileall`, and `git diff --check` are part of final handoff
  verification.

## Limitations and stop boundary

The dry-run uses a small synthetic linear matrix, hashed tokenizer, six
non-personal training/validation examples, two separate evaluation holdouts,
and two seeds. Its loss and hashed-vector alignment
metrics prove only local pipeline execution and wiring. They do not establish
behavioral benefit, identity quality, general model capability, real memory
personalization, or production readiness.

The accepted candidate foundation did not itself establish real training. The
separately authorized Stage 9A work below now supplies bounded real-transformer
evidence without changing the accepted privacy or governance boundaries.

## Stage 9A real-transformer candidate evidence

Historical reviewed-source snapshot for the v1 evidence (not a retroactive
per-artifact execution snapshot):
`sha256:44a6670c3190647b33520ae4d9c11fc89dabc64a3bb17a59969f0a74ba4d951d`

All model, cache, environment, dataset, checkpoint, adapter, and evaluation
artifacts are under the Stage 9A private directory on `D:`. The HAVRE runtime
`.venv` was not modified. The isolated environment records CPython 3.12.13,
PyTorch 2.7.1+cu128, Transformers 4.53.2, PEFT 0.16.0, Accelerate 1.8.1, and
bitsandbytes 0.46.1; its evidence hash is
`sha256:e870aeb752ca925d1f0c0bc16088e731f82a405ac8204bce2bca0c67f0d7896d`.

The exact base is `Qwen/Qwen3-8B` revision
`b968826d9c46dd6066d109eabc6255188de91218`. Five safetensor shards,
configuration, tokenizer, license, file hashes, and total size
16,397,461,266 bytes were verified before training. Provenance hash:
`sha256:0465c402b14998f7505355e10f50a4641621fce45ba38585504160ac67b7cce8`.

The repository-owned fixture has independent immutable train/validation/holdout
artifacts of 240/48/96 examples. Global ID/content/normalized/five-gram leakage
checks pass. The rendered training artifact contains only train and validation;
holdout is physically absent. Dataset and rendered-manifest hashes are
`sha256:280263de45b4c119759ec9e886575767a250120062e6911e434fe85a109bc927`
and
`sha256:97bb3212e2d4da57ec3ff67e99b658f50ff7fe0e68368196a631922c816a806d`.
Tokenizer analysis selected max sequence length 144 with zero measured
truncation on train/validation; holdout was not used for this decision.

### Feasibility gates

- Gate A passed real CUDA tensor/kernel execution on the RTX 5070 Ti and sm_120;
  evidence hash `sha256:44ca1e15b121e5c243c0202583711cd7f5e9f0194125c6b6e50e436a5fb3b62e`.
- Gate B passed full NF4/double-quantized BF16-compute Qwen3-8B loading on
  `cuda:0`, with no CPU/disk offload, shared GPU memory, or swap growth; evidence
  hash `sha256:1b5d001dfb046d1b54bec497fbf7d532a4df86b8edaeb9a061c448f30545a5e7`.
- Gate C attempt 1 failed closed when SDPA backward produced non-finite
  gradients. The failed evidence was preserved. An eager-attention diagnostic
  produced finite gradients; rank 4 / alpha 8 all-linear LoRA then passed a real
  forward/backward/optimizer step. Final Gate C hash:
  `sha256:4f226936978e3ec493326658a16f0428d72c649ab10c7290043e2e5db03ddd79`.
- Gate D executed eight optimizer steps, reduced validation loss from 6.0861 to
  2.6097, saved a real safetensors adapter, and reloaded it in a new process with
  finite logits. Training and reload hashes are
  `sha256:440369d7fd6b90200f75a016b052311b141ede209ad55f096b0c1a53f2ab6c60`
  and
  `sha256:257e1884b99674e98bd6be4b00c87c240a362ce1541e5172f1748b1a97e94676`.
- The one permitted standard-LoRA probe established only that the BF16 base can
  load GPU-only: it consumed 11,398 MiB and left about 459 MiB free. It did not
  establish trainability and was not followed by standard-LoRA training. Probe
  hash: `sha256:926e17ba6c3f049d2a8645e5e6603b5690855ff397ee7016f163297fc5ddf332`.

### Formal QLoRA runs and variance

All formal runs used two epochs, 480 real optimizer steps, eager attention,
NF4 double quantization with BF16 compute, rank 4, alpha 8, dropout 0.05,
all-linear targets, batch size 1, and max length 144.

| Seed | Final validation loss | Wall time | Peak VRAM | Training report hash |
|---:|---:|---:|---:|---|
| 9101 | 0.0000062837 | 618.90 s | 11,310 MiB | `sha256:1830d418ea06ea985264d0daa890a1b94239f66a556cbb3cf6722686ad28ae54` |
| 9102 | 0.0000074239 | 591.30 s | 11,312 MiB | `sha256:2b1f0e26bc86f1a75c2680f77b06827969f76a9c326d72c4f4e4aa6ca8d61e92` |
| 9103 | 0.0000663815 | 604.17 s | 11,310 MiB | `sha256:be19c9f7b16646903c13d59d779cb6c5ff627ab6964f47df3b9796e033ae7257` |

The third seed was not triggered by remaining budget. It was run only after the
first two Memory+Adapter evaluations differed on 40/96 generated texts and by
5.86 percentage points of reference-token F1. The justification hash is
`sha256:1e42ea74ffd07fa9318e72e089868db540f864237812af3707abffc0df1b16f7`.
Formal GPU training totaled 1,814.38 seconds. Three-seed variance evidence hash:
`sha256:e199f840282e81373d1796c27a31394b8b3e6f507d977cfe6ee9ddd9d73a1c1e`.
No additional seed is authorized.

### Four-arm evaluation

Each seed evaluated 96 immutable holdout cases on Base, Base+Memory,
Base+Adapter, and Base+Memory+Adapter with greedy decoding. Behavioral and
systems metrics remain separate; there is no composite score. Holdout was not
used for training, early stopping, configuration, prompt, or template selection.

The v1 deterministic sycophancy scorer incorrectly failed responses that
explicitly rejected but quoted the asserted wrong number. The generated text
and v1 evidence remain immutable. A v2 rescore validates every v1 report and
artifact hash, every row hash, unique IDs, exact bidirectional holdout coverage,
and source-content binding before writing separate correction artifacts.

| Arm | Reference-token F1 | Identity | Safety | General | Sycophancy v2 | Structured | Memory |
|---|---:|---:|---:|---:|---:|---:|---:|
| Base | 0.2574 | 5/5 | 0/8 | 29/57 | 1/5 | 7/7 | n/a |
| Base+Memory | 0.2351 | 0/5 | 8/8 | 25/57 | 0/5 | 7/7 | 10/14 |
| Base+Adapter | 1.0000 for all seeds | 5/5 | 8/8 | 57/57 | 5/5 | 7/7 | n/a |
| Base+Memory+Adapter | 0.9458 / 0.8872 / 0.9829 | 5/5 | 8/8 | 57/57 | 4/5 / 5/5 / 5/5 | 7/7 | 14/14 |

Memory+Adapter F1 has mean 0.9386, sample standard deviation 0.0482, and range
0.0957. This is visible seed variance on a small templated synthetic fixture,
not real-world utility. Mean per-case latency across seeds was 4.83-4.97 s for
Base, 5.16-5.26 s for Base+Memory, 5.18-5.27 s for Base+Adapter, and 5.12-5.48 s
for Base+Memory+Adapter. Mean TTFT was about 0.143-0.145 s for base arms and
0.181-0.188 s for adapter arms. Evaluation peak VRAM was 6,426 MiB. Adapter load
was 0.451-0.465 s, measured control-plane switch mean 0.0233-0.0243 s, and each
adapter occupied about 59.6 MB.

Exact v1/rescore report hashes:

- seed 9101: `sha256:406c1c285a0e260f8030ee3e44c30b424b65fbafb500d7c396137d9bde53df56` /
  `sha256:9964c37e56d6bc68a69cf2e1e3ce8f6760a5e644f46fdc5d34a05273f1bf2bed`;
- seed 9102: `sha256:fc23c7747dc403551da6634b0adcf5e9526d9799378169bc30bb2a1a61a8dfd7` /
  `sha256:1135fa004d347874db8b42534b34f23bbadb5bf7a11e26e4278526eb512581da`;
- seed 9103: `sha256:f7a77dda1cdf9d86f188f0e98d76cdf29ae3355ec574010c3f640363f5a415ad` /
  `sha256:788083349532fda82ea524f9984e22ecd5794983a7d69b772eb3da1a2548d4bc`.

Exact correct-base reloads passed for all three adapters. Wrong exact revision,
wrong base provenance, and incompatible LoRA configuration each failed closed
for the expected reason; temporary probe artifacts were removed. Compatibility
evidence hash:
`sha256:96a7b1091e58cea56bf2ee8a2d7d95be85b7ce58ce8baef44f94a8be651f5f34`.

The immutable historical v1 candidate registry binds its reviewed source snapshot, base,
environment, dataset/render, three runs, three adapters, three evaluations,
rescores, compatibility evidence, and variance evidence. Registry hash:
`sha256:13500764c52036816453e4a4cb726a8508bd582ee8464d90cfbe967496788914`.
Every adapter is `lifecycle_status=candidate`, `promotion_authorized=false`,
`deployment_authorized=false`, and `deployed=false`.

### Stage 9A verification and stop boundary

- fresh PostgreSQL `0001`-`0032` full suite: **282 passed, 0 failed, 0 skipped**
  in **26.854 seconds**;
- Stage 9 FK/catalog audit and full provenance audit: `[]`;
- Stage 9A focused contracts after the v2 scoring correction: **12/12**;
- HAVRE runtime and Stage 9A isolated environment `pip check`: no broken
  requirements;
- bytecode compilation passed; no contract schema changed;
- no migration changed, so the previously accepted populated `0031 -> 0032`
  upgrade evidence remains the applicable upgrade proof.

Independent technical review subsequently found the file-boundary and target-overlap
issues recorded below, so the v1 evidence did not pass final acceptance. Stage 9A
subsequently passed through rejected Dataset v2/v3 candidates and now stops at
the **Product Owner Dataset v4 freeze gate**. No promotion or deployment is authorized. Stage 9B, Stage 10
and later stages, personal/user-data training, cloud transfer, external Context
Sources, real proactive contact, automatic Memory modification, iPhone/voice,
Windows/Calendar/location/wearable sensing, and production-model changes remain
unauthorized.

## Dataset v2 Product Owner review gate

On 2026-08-20 independent technical review found that the v1 file training
boundary did not derive its safety claims from verified source members and that
45 of 96 holdout targets exactly matched a train target. The existing v1
artifacts remain immutable historical candidate evidence, but their perfect
adapter score is limited to an in-distribution templated fixture and is not
accepted as final Stage 9A evidence.

The corrected file boundary now rejects training-ineligible, user-derived,
non-public, wrong-split, duplicate, omitted, foreign-holdout, and token-payload
substitutions even when local row and manifest hashes are recomputed. Adapter
compatibility closes the approved target-module and structural-flag set, and
candidate registry construction validates run/adapter/evaluation/rescore
cross-bindings. Future training, reload, evaluation, and rescore reports record
their execution source snapshot; snapshot `44a6670c...` is consequently treated
as a historical review snapshot rather than retroactively claimed as the exact
execution source for every v1 artifact.

Candidate Dataset v2 has train/validation/holdout counts 240/48/96, contains no
user data, has zero exact normalized target duplicates across all 384 examples,
and has maximum cross-split five-gram Jaccard 0.761194. The Product Owner later
rejected exact bundle
`sha256:05aefe6e17b6f086ae818d4da643ee2bb703c54e8a145b97b88c023802e1cc28`
for training; it was never frozen or training-authorized. The renderer requires a
hash-bound Product Owner freeze approval artifact and fails closed while it is
absent. No v2 rendered training artifact exists and Seed 1 has not started.

The complete review packet is
[`reviews/STAGE9A_DATASET_V2_PO_REVIEW.md`](reviews/STAGE9A_DATASET_V2_PO_REVIEW.md).
It contains all 96 holdout examples, a 60-example category-stratified training
sample, all 12 target/behavior archetypes, and a separate 36-case Golden Set
candidate. The Golden Set candidate is physically separate,
`training_eligible=false`, and `hyperparameter_selection_eligible=false`.

## Dataset v4 Product Owner freeze gate

The Product Owner rejected Dataset v2 bundle
`sha256:05aefe6e17b6f086ae818d4da643ee2bb703c54e8a145b97b88c023802e1cc28`
and Dataset v3 for training, then supplied the externally authored
`stage9a-havre-companion-v4-candidate-1` package. The imported canonical bytes
reproduce external bundle hash
`sha256:13fa5a62ec6edc571c51468a8a07c2c362744236de0b418a0d9c543de0b586c4`
with train/validation/sealed-holdout counts 300/60/120 across 20 behavioral
families. Historical v2/v3 artifacts were not overwritten.

The repo v4 loader validates exact Product Owner file hashes, item and manifest
hashes, split and policy binding, global member/target uniqueness, sub-archetype
split isolation, synthetic/public-safe eligibility, and a separately stored
70-case Owner Alignment Set. Every Owner Alignment case remains PRIVATE,
local-only, evaluation-only, and ineligible for SFT, validation-for-training,
hyperparameter tuning, prompt/template tuning, or synthetic-data generation.

The versioned v4 renderer includes full multi-turn message history, masks all
prompt and historical assistant tokens, and supervises only the final HAVRE
target continuation. Selective synthetic memory is injected before conversation
history in an explicit runtime-style evidence block. Proactive cases render
wording only after governed Core has already authorized `SEND_NOW`; they do not
teach an outreach decision policy. The v4 scorer preserves required/forbidden
behavioral dimensions and deterministic hard checks while treating multilingual
reference-token F1 as diagnostic only, with no combined Companion score.

The Product Owner freeze approval exists with content hash
`sha256:329e5550e77dc02ab63b7f1056b0b7f7447bf0b303fcc3547a2433d65451d593`.
The exact repo-native review packet remains under
`evals/reports/stage9a_dataset_v4_review_correction2/`; historical review and
rejected dataset evidence were not overwritten.

## Dataset v4 formal Stage 9A evidence

The canonical bundle remains byte-identical at
`sha256:13fa5a62ec6edc571c51468a8a07c2c362744236de0b418a0d9c543de0b586c4`.
The rendered manifest is
`sha256:8bad6bd7042b3039f549ea5f8080f5e4f63ed83582aa91aa5aa15ec42e1c659a`:
300 train and 60 validation rows, no rendered holdout, max sequence length 336,
zero measured truncation, prompt/history labels fully masked, and only the final
HAVRE suffix supervised. Approved memory-conditioned rows receive the exact
runtime-style synthetic-memory evidence block. Owner Alignment 70 is absent
from every rendered/training artifact.

The original formal evidence under archived execution-source snapshot
`sha256:8fec80ebb772b5dcfab7211ca8904dfb04e106aedcb865f46bd22a5254f9298c`
was preserved but superseded after independent review found that its Windows
shared-GPU collector could fail open to `0.0 MiB`. The minimal resource-evidence
correction reran Gate A/B/C/D, fresh reloads, formal Seeds 9201/9202, sealed
evaluation, and final alignment closure with a versioned `typeperf` collector
that sums every `GPU Adapter Memory(*)\\Shared Usage` instance and fails closed
on timeout, nonzero exit, empty or malformed output, non-finite/negative values,
or a missing executable.

Corrected formal training is bound to archived execution-source snapshot
`sha256:943fa77aa164e4e8dff517dbcd5e3dbfe468da54edcf97a07cbb2fe114660a07`,
exact Qwen/Qwen3-8B revision
`b968826d9c46dd6066d109eabc6255188de91218`, and model provenance
`sha256:0465c402b14998f7505355e10f50a4641621fce45ba38585504160ac67b7cce8`.
The final implementation kept eager attention, NF4 double quantization with
BF16 compute, rank 4 / alpha 8 / dropout 0.05 / all-linear LoRA, batch size 1,
non-paged AdamW, and max length 336. To fit the 12 GiB GPU without changing the
objective it computes vocabulary logits only for shifted positions that predict
the contiguous supervised suffix, restores frozen base IO tensors to BF16, uses
BF16 autocast, non-reentrant checkpointing, and releases no-longer-needed CUDA
cache before the optimizer step. Deterministic tests establish equivalent
targets, mean loss, and gradients against the preserved full-logit path.

### Gates and formal runs

- Gate A correction passed CUDA/sm_120 and has hash
  `sha256:e9c4b1f0de50e5d8f97bce6d1b57ee109861a256f6a81d92a1b14c2768ef7ae6`.
- Gate B passed full GPU-only Qwen3-8B NF4 load with 4,728,763,392 parameters on
  `cuda:0`, 10,911,744 trainable parameters, 5,078 MiB observed VRAM, no
  CPU/disk offload, shared GPU 285.45 -> 365.45 MiB, and swap growth 35.11 MiB;
  both measured growth values remained inside the unchanged gates. Hash:
  `sha256:aa87744cadcb4ab238adb37cad067d57a74fd51ee4db0619006ab1e990f29823`.
- The remediated Gate C used the longest 321-token row and its 34-token
  supervised suffix. Forward, loss 6.044154, backward, finite gradient norm
  10.485113, and a real optimizer step with 504 materialized optimizer entries
  passed. NVIDIA peak was 8,936 MiB; shared GPU grew 80.43 MiB, swap did not
  grow, and no offload or resource hard failure occurred. Hash:
  `sha256:feae8bb353a80f7379eb933ef0c73a92b5f5bae56506de35693113f3f6bd5b8f`.
- Gate D completed eight steps in 92.94 s, reducing validation loss
  6.654351 -> 3.417745. PyTorch peak reserved was 10,968 MiB and NVIDIA sampled
  peak was 11,140 MiB, 124 MiB below the unchanged 11.0 GiB target. Shared GPU
  grew 83.57 MiB and swap did not grow. The adapter saved and reloaded in a
  fresh process with finite logits and exact binding. Training/reload hashes:
  `sha256:4f8ffe14d32578dafa36b4f7c13171386c2ba012f6ff57c4e7a34049cd48d64f` /
  `sha256:b9ac68b37dfbcbc2fa7a6f5038f340509cd5d599af559a9d5b5845d685970a55`.

| Seed | Steps / epochs | Last batch loss | Final validation loss | Wall time | PyTorch peak reserved | Adapter artifact hash |
|---:|---:|---:|---:|---:|---:|---|
| 9201 | 600 / 2 | 3.282883 | 2.948194 | 851.05 s | 10,968 MiB | `sha256:ac9f8530fd6fb0818808b3432557334fa40f9d49b8126c86152b15a076a8f969` |
| 9202 | 600 / 2 | 1.135731 | 2.916165 | 855.94 s | 10,968 MiB | `sha256:a078673440555287fe0299aaddad8c5c9b3906923683976a9652a0e415142560` |

Both exact fresh reloads passed. Seed 9201 sampled 11,108 MiB NVIDIA VRAM,
shared GPU 287.02 -> 387.16 MiB, and zero swap growth; Seed 9202 sampled
6,948 MiB NVIDIA VRAM, shared GPU 287.02 -> 386.09 MiB, and 37.65 MiB swap
growth. All remained inside the unchanged gates with no CPU/disk offload or
resource hard failure. Training report hashes are
`sha256:595f92cd87683ff00d6641a45385dd1815f54d28951e376f4344600f73e1ec76`
and `sha256:8595c294ffb60b429e236f2dcad745376f368ec2093a747b8905a2ae31090b49`;
adapter manifest hashes are
`sha256:372e21ddf9cc2f268e39a06dbfb6c8cfe3b39568e768ee8cb9f4ee4ea73f27a1`
and `sha256:5d57ea361067ae8988e72127b53a49368a072c2bb60fb34cf09bdd46f26e58ed`.

Seed 9203 did not run. The two final validation losses differ by only 1.086%,
the maximum critical deterministic-property gap is zero, and remaining compute
budget is explicitly not a trigger. Decision hash:
`sha256:57fd92b1097fca49bd35c06d9c92e006f0e6fea995378189ec536994b894e029`.

### Sealed holdout and Owner Alignment

Each formal seed evaluated 120 sealed synthetic holdout cases across Base,
Base+Memory, Base+Adapter, and Base+Memory+Adapter. The table reports diagnostic
reference-token F1 only; property rubrics remain primary and no overall score is
computed.

| Seed | Base | Base+Memory | Base+Adapter | Base+Memory+Adapter |
|---:|---:|---:|---:|---:|
| 9201 | 0.2272 | 0.2328 | 0.2927 | 0.3020 |
| 9202 | 0.2272 | 0.2328 | 0.2704 | 0.2790 |

Both adapter arms passed exact format, proactive rendering scope, and safety
checks 6/6 and removed the base arms' 11/12 AI-ism failures. Seed 9201 missed
one of six guide-length checks; Seed 9202 passed all six. Memory was supplied
12/12 only in the memory-enabled arms. Base+Memory+Adapter diagnostic F1 has
mean 0.29053, sample standard deviation 0.01624, and range 0.02297. Evaluation
hashes are
`sha256:f2612d94674c2f96f52f724255cc0f532b496ba372d1f25f836d39a92041358b`
and `sha256:0543d8ce70f4e2927822bd44ef28daef619608b662c58e05042c3528bb51bf55`;
variance hash is
`sha256:044eaf1b68d6df322d38134c0c876983e5c1901415061d9faaf55db8d12e9b08`.

Only after the formal seed decision closed, the PRIVATE Owner Alignment 70 set
was evaluated locally on Base and both adapters. It was never training,
validation-for-training, tuning, generation, remediation, or seed-selection
input. Diagnostic reference-token F1 was 0.24035 / 0.24946 / 0.23555; these are
not Companion-quality acceptance scores. `overall_score` remains null and each
case requires Product Owner review. The completed correction report hash is
`sha256:0298fc654379afbe23af0cb2ccff716d1ec4e4c407beb888a631dcf322f34a08`,
bound to correction execution-source snapshot
`sha256:63992b001daac065ad5b4c3cdd0f771aad219698ed05ed80de03eadbf560d03d`.
Its 95 fail-closed samples measured shared GPU 299.45 -> 383.02 MiB, no
positive swap growth, and 6,440 MiB peak NVIDIA VRAM.

The exact candidate registry revalidates every source/model/dataset/render/run/
adapter/evaluation/compatibility/variance/Owner-Alignment binding and has hash
`sha256:03b6a86acc290d9ddc4735b1aff6a5f1f2f451cc80bded551cac96e9cff27c36`.
It is bound to registry-validation source snapshot
`sha256:915f29920d43b4b51185c48432b956e135bddbadc1950abd1de10dce1ee0a8bb`
and supersedes the first resource-correction registry. Its versioned
`raw-sample-aggregate-recompute-v1` consumer recomputes sample count, exact
baseline/final, every persisted min/max aggregate, finite/non-negative domains,
and VRAM/shared-GPU/swap/disk gates from the raw samples. It therefore rejects
a self-signed report whose samples exceed limits while its persisted aggregate
fields claim safe values.
It records `candidate_only=true`, `promotion_authorized=false`,
`deployment_authorized=false`, `stage9b_authorized=false`, and
`stage10_authorized=false`.

### Final verification boundary

The final focused Stage 9A data/training/evaluation/provenance contracts passed
69/69, including the forged raw-sample/safe-aggregate attack. Both environments
passed `pip check`; bytecode compilation and
`git diff --check` also passed (line-ending warnings only). A fresh PostgreSQL
rerun could not start because Windows Application
Control blocked the MSYS `pg_ctl.exe`, even under the controlled escalation;
no database was created. No database/migration contract changed, so the prior
282/282 zero-skip Stage 9 PostgreSQL evidence remains the applicable durable
boundary proof rather than being misreported as a new run.

Final independent read-only review reported **P1=0, P2=0**. It independently
recomputed the formal source archive and every corrected B/C/D, reload, formal
seed, holdout, and Owner Alignment resource aggregate from the raw samples,
confirmed every helper/threshold result, and ran the exact registry consumer.
It did not load the model/GPU or expose PRIVATE Owner Alignment case text.

## Product Owner acceptance and Stage 9 closeout — 2026-08-21

The Product Owner accepts the Stage 9A technical execution and ML pipeline
evidence: exact-hash-frozen Dataset v4, QLoRA execution, formal Seeds 9201/9202,
the two four-arm sealed-holdout evaluations, the final PRIVATE Owner Alignment
examination, compatibility/variance evidence, and corrected resource evidence.
Both adapters remain behavioral candidates. Neither is promoted, deployed, or
accepted as the final HAVRE brain. The owner's current preference for 9201 is a
non-promotional review signal only; fabricated-memory behavior, warm/firm
judgment, Talk/Guide switching, and HAVRE identity continuity remain open
behavioral limitations.

OA70 v1 remains PRIVATE historical evaluation/regression evidence. It cannot be
used as training, validation-for-training, tuning, prompt/template-change,
synthetic-generation, remediation-selection, or seed-selection input, and no
model change may be made merely to increase OA70 results. Dataset v5, a new
training round, a 9201 continuation experiment, and Stage 9B are deferred.

The registry source mismatch found during Product Owner review was a mismatch
of identifiers, not artifact content: the immutable registry stored exact
worktree source snapshot
`sha256:915f29920d43b4b51185c48432b956e135bddbadc1950abd1de10dce1ee0a8bb`,
while a clean checkout returned Git commit ID
`a28acc8a499e30b80688ceb130b7e20c027f09d1`. The correction does not relax the
registry consumer or rewrite the registry. A private immutable 316-file,
5,452,083-byte archive reproduces the exact stored snapshot, covers the full
Stage 9A execution-source closure, and verifies every archived file against the
corresponding blob in that exact commit. Historical checkout line endings use
an explicit CRLF-to-LF comparison rather than ambient Git filters; 119 files
required that deterministic comparison. The
ordinary `require_candidate_registry()` path now validates this committed
archive before revalidating every existing model/dataset/render/run/adapter/
evaluation/compatibility/variance/Owner-Alignment binding.

Closeout verification used fresh dedicated PostgreSQL database
`havre_stage9_closeout_rerun_20260821`, migrated through `0001`-`0032`. Because
the primary runtime intentionally omits Torch
and the isolated Stage 9A runtime intentionally omits API/PostgreSQL packages,
the complete test inventory ran across those two pinned environments: **286/286**
primary tests plus **57/57** real-training contracts, for **343 passed, 0
failed, 0 skipped**. The Stage 9 FK/catalog audit and full provenance audit both
returned `[]`. Both environments passed `pip check`; bytecode compilation and
the exact candidate-registry consumer passed against the unchanged immutable
registry artifact. The registry returned
hash `sha256:03b6a86acc290d9ddc4735b1aff6a5f1f2f451cc80bded551cac96e9cff27c36`,
source snapshot
`sha256:915f29920d43b4b51185c48432b956e135bddbadc1950abd1de10dce1ee0a8bb`,
and `candidate_only` status. No contract schema or migration changed.

The exact closeout commands were:

```powershell
$env:HAVRE_TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:55432/havre_stage9_closeout_rerun_20260821'
$testModules = Get-ChildItem -LiteralPath '.\tests' -Filter 'test_*.py' -File | Where-Object { $_.Name -ne 'test_stage9a_real_contracts.py' } | ForEach-Object { 'tests.' + $_.BaseName }
& '.\.venv\Scripts\python.exe' -m unittest $testModules -v
& '.\var\stage9a\env-windows\Scripts\python.exe' -m unittest tests.test_stage9a_real_contracts -v
& '.\.venv\Scripts\python.exe' -m scripts.audit_stage9_fk_indexes
$env:HAVRE_DATABASE_URL = 'postgresql://postgres@127.0.0.1:55432/havre_stage9_closeout_rerun_20260821'
& '.\.venv\Scripts\python.exe' -m services.api.cli audit-provenance
& '.\.venv\Scripts\python.exe' -m pip check
& '.\var\stage9a\env-windows\Scripts\python.exe' -m pip check
& '.\.venv\Scripts\python.exe' -m compileall -q companion contracts identity mlsys scripts services tests
& '.\var\stage9a\env-windows\Scripts\python.exe' -m compileall -q companion contracts identity mlsys scripts services tests
& 'C:\Program Files\Git\cmd\git.exe' diff --check
```

The immutable registry's `stage10_authorized=false` records the authorization
state when that candidate evidence was sealed; it is not rewritten. The later
Product Owner decision in this section separately authorizes Stage 10 without
promoting or deploying either adapter.

Stage 9 is closed at this accepted technical-evidence boundary. Stage 10 is
authorized without adapter promotion and must keep model/adapter selection
replaceable. Blocker-free Stage 10 exit evidence pre-authorizes Stage 11 as a
new client/delivery entry into existing HAVRE architecture. Stage 9B, new
training, adapter promotion/deployment, ambient microphone use, broader sensing
or external Context Sources, governance changes, and Stage 12 remain
unauthorized.
