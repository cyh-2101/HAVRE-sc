# Stage 13 Model and Runtime Feasibility

Status: candidate investigation; no model promotion, runtime installation, or default-route change is authorized by this document

## Decision

Do not retrain the 8B model yet. The current evidence contains failures that prompt wording and a 14B base-model increase did not fix reliably. The next high-information experiment is a stronger untuned local foundation-model replay, followed by the same full HAVRE path only if the raw arm passes the hard utility gate.

The preferred first 35B experiment is the `ggml-org/Qwen3.6-35B-A3B-GGUF`
Q4_K_M artifact through the existing isolated llama.cpp candidate server. This
reuses HAVRE's OpenAI-compatible local-provider boundary and avoids making a new
experimental runtime part of the architecture. The checked-in candidate manifest
pins repository revision `baec3ebee244827cda0f4557eafa8b28f7545fa6`, exact
size `20,419,565,568` bytes, and SHA-256
`671e47e0ec53c665d048b98c3ecbfd5236b5ca9c3e02ed19fc8f81f7b85140c7`.

FreeToken remains a second runtime candidate, not the first dependency to add.

## Why 35B-A3B is materially different

`Qwen3.6-35B-A3B` is a mixture-of-experts model with about 35B total parameters and about 3B activated per token. A larger stored model can therefore expose broader learned capacity without paying dense-35B compute on every token. This does not guarantee good HAVRE conversation quality; only replay and owner use can establish that.

## FreeToken assessment

The FreeToken design is relevant to HAVRE because it keeps MoE experts in host memory, caches selected experts on the GPU, and exposes OpenAI-compatible endpoints. The official project lists Qwen3.6-35B-A3B and the NVIDIA NVFP4 checkpoint as supported.

However, the current official CLI installation document names Linux x86_64, an NVIDIA GPU, driver R580 or newer, CUDA 13, and a CUDA 13 toolkit with `nvcc`. Windows is distributed through the desktop application instead of the documented pip path. The NVIDIA NVFP4 artifact is approximately 23.5 GB before any FreeToken conversion or cache overhead.

Open issue reports in the upstream repository describe native-Windows failures on consumer RTX 50-series systems, including Qwen3.6-35B-A3B-NVFP4 load failures and broken Chinese tokenization. These reports are not proof that every machine fails, but they are sufficient to reject a blind native-Windows installation as the first experiment. WSL2/Linux may avoid those exact paths, but it adds driver, toolkit, RAM, and operational requirements that must be verified locally.

## Required local feasibility checks

Before any 20+ GB download:

- record Windows version, CPU, physical RAM, GPU model, VRAM, NVIDIA driver, and free disk space;
- record the existing llama.cpp build and confirm Qwen3.6 MoE architecture support;
- verify that the daily 8B service can be stopped and restored without changing its registered model or adapter;
- estimate system-RAM headroom for weights, KV cache, application services, and Windows;
- select a bounded context length for the candidate test rather than advertising the model's maximum context;
- pin model repository revision and SHA-256;
- use a separate candidate directory, port, logs, and process lifecycle;
- run public/synthetic raw replays before any full HAVRE or private conversation test.

## Verified workstation snapshot

The read-only 2026-09-02 snapshot records:

- AMD Ryzen 9 7945HX, 16 cores / 32 logical processors;
- 31.2 GB physical RAM;
- NVIDIA GeForce RTX 5070 Ti Laptop GPU with 12,227 MiB VRAM;
- NVIDIA driver 573.22;
- 82.0 GB free on C: and 126.6 GB free on D:;
- pinned llama.cpp build 10405, commit `e79e4bf66`, whose help exposes
  `--cpu-moe`, `--n-gpu-layers auto`, fit controls, and quantized KV-cache types.

This is sufficient to justify a bounded Q4_K_M load experiment, not to claim it
will be fast or stable. The candidate profile uses one slot, a 4,096-token
context, automatic GPU fitting, CPU-resident MoE experts, and q8_0 KV caches.
The current 573.22 driver is below FreeToken's documented R580 minimum, so
FreeToken cannot be evaluated without crossing the explicit driver/system gate.

The Product Owner authorized the exact pinned 35B download. A resumable transfer
was started on 2026-09-03, but bandwidth remained roughly 0.6–0.7 MiB/s during
the observed interval. The partial is not an artifact: it remains ignored,
candidate-local, and cannot be launched or cited as verified until the exact
20,419,565,568-byte size and SHA-256 pass. This transfer does not change the
daily model route.

## Runtime comparison order

1. Existing isolated llama.cpp candidate path with Q4_K_M.
2. If quality passes but speed is unacceptable, evaluate FreeToken under an isolated WSL2/Linux environment.
3. Native Windows FreeToken only after the upstream RTX 50 and Chinese-tokenization paths are verified fixed on a pinned release.
4. Training only after a stronger untuned base-model control and the architecture arms show what remains model-specific.

## Stop gates

Stop for owner approval before:

- downloading the selected 20+ GB artifact if current free space or bandwidth makes the cost material;
- installing or upgrading GPU drivers, CUDA, WSL, system packages, or a desktop application;
- disclosing LOCAL_ONLY conversations to any external reviewer;
- changing the default model or provider route;
- starting training or producing a personalized release candidate.

## Success evidence

A successful feasibility run records exact artifact identity, load success, peak RAM/VRAM, first-token latency, decode rate, context length, three repeated public/synthetic replays, restoration of the daily service, and a semantic review under `STAGE13_PRACTICAL_UTILITY_GATE.md`. It proves only candidate feasibility until the full delivery path and owner shadow-use gates pass.
