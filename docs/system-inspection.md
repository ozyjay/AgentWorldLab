# System inspection — 6 August 2026

Labels distinguish measurements from upstream facts and untested expectations.

## Verified repository or system observations

- The workspace began empty and was not an initialised Git worktree.
- The host reports Fedora 44, kernel `7.1.5-201.fc44.x86_64`, an AMD Ryzen AI
  Max+ 395 with Radeon 8060S, 32 logical CPUs, and 125 GiB total system memory.
- At inspection time, about 115 GiB system memory and 411 GiB on the workspace
  NVMe filesystem were available. These values are transient, not benchmarks.
- `/proc/cmdline` contains `amdgpu.gttsize=120000` and
  `ttm.pages_limit=30720000`; the readable TTM module value also reports
  `30720000` pages.
- AMD sysfs exposed a 125,829,120,000-byte GTT allocation plus a 512 MiB VRAM
  aperture. AgentWorldLab records system memory, VRAM, and GTT separately.
- `sensors` exposed `k10temp/Tctl`, `cros_ec/cpu@4c`, and `amdgpu/edge`.
  Readings during inspection were well below 80°C; this is not evidence about
  model-load temperatures.
- Fedora ROCm RPMs are predominantly 7.1.x (`rocm-core` 7.1.1). Existing local
  environments contain PyTorch `2.9.1+rocm7.2.1` and `2.11.0+rocm7.2` builds.
  That split must be tested rather than assumed compatible.
- A pre-existing ROCm 7.2 environment outside this repository was inspected
  read-only. It contains Transformers 5.13.0 and exposes both
  `AutoModelForMultimodalLM` and `Qwen3_5MoeForConditionalGeneration`. This was
  a compatibility observation, not an AgentWorldLab dependency or integration.
  Symbol presence does not prove that all gfx1151 kernels work.
- A local vLLM 0.24.0+rocm723 environment exists. Its installed source registers
  `Qwen3_5MoeForConditionalGeneration` and exposes the conservative settings
  used here: generate runner, tensor-parallel size one, BF16, eager mode,
  maximum model length, zero CPU offload, and language-model-only mode. Importing
  that environment still failed because `libmpi_cxx.so.40` was unavailable, so
  the runtime path and ROCm kernels remain unresolved.
- The constrained build environment could not open `/dev/kfd`; no ROCm kernel,
  allocation, weight load, or generation was attempted.
- HuggingFacePull subsequently cached the official snapshot at revision
  `60d2b0434a53d2e62a7c00a489586815d94ebffb` under
  `/mnt/work/models/huggingface/hub`. Offline inspection found 21 complete BF16
  shards, 693 indexed tensors, no broken links or missing indexed shards, and
  69,321,314,576 bytes (64.561 GiB) of weight shard files.
- The FedoraUsage repository contains an automatic thermal policy with default
  82°C entry and 72°C recovery thresholds, five-second sampling, and TuneD
  integration. The sandbox could not query the system D-Bus, so installed,
  enabled, and active service state remains unverified.

## Official upstream facts

- AMD's ROCm 7.2.1 Ryzen support matrix lists gfx1151, Ryzen AI Max+ 395,
  PyTorch 2.9.1, and Python 3.12. Its native Linux table lists Ubuntu 24.04.4,
  not Fedora 44, and marks only FP16 as officially validated for the listed
  Ryzen GPUs. AgentWorldLab's Fedora BF16 path therefore still requires direct
  validation.
- The official model configuration identifies
  `Qwen3_5MoeForConditionalGeneration`, `qwen3_5_moe`, BF16,
  `language_model_only: true`, 256 experts, 8 experts per token, 40 text layers,
  and a 262,144-token maximum position setting.
- The upstream project describes the release as 35B total and 3B active
  parameters and supports environment simulation across seven domains.

Sources: [AMD Ryzen compatibility matrix](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityryz/native_linux/native_linux_compatibility.html),
[official model configuration](https://huggingface.co/Qwen/Qwen-AgentWorld-35B-A3B/blob/main/config.json),
and [official AgentWorld repository](https://github.com/QwenLM/Qwen-AgentWorld).

## Engineering estimates

- BF16 weights are likely around 70 GB before metadata, allocator overhead,
  buffers, KV cache, and temporary loading copies. The exact pinned snapshot
  size must replace this estimate in Stage A.
- Requiring 104 GiB currently available system memory (80 GiB allowance plus
  24 GiB headroom) is a conservative initial gate, but may still be insufficient
  if loading creates substantial temporary copies. Fitting does not imply useful
  latency.

## Hypotheses requiring testing

- The Transformers architecture may load on gfx1151 without CUDA-only linear
  attention or MoE kernels.
- PyTorch's ROCm build may allocate the BF16 checkpoint through GTT without
  unexpected CPU fallback or host offload.
- Transformers cancellation may return promptly at a generation token boundary.
- vLLM 0.24.0+rocm723 may instantiate its registered model after the missing MPI
  runtime is resolved, but its gfx1151 ROCm kernels remain unverified.
- Most memory may be recoverable after unload without rebooting Fedora.
- Load, prefill, and decode speed may or may not be practically useful.

## Remaining read-only operator checks

Run these outside the constrained build environment before model loading:

```bash
rocminfo | rg -n 'Name:|gfx1151'
rocm-smi --showproductname --showmeminfo vram --showtemp
amd-smi metric --mem-usage --temperature
systemctl status fedorausage-auto-powersaver.service tuned.service tuned-ppd.service
systemctl status framework-thermal-policy.service power-profiles-daemon.service tlp.service
tuned-adm active
fedorausage auto-powersaver status | jq .
fedorausage auto-powersaver conflicts | jq .
```

Do not change a profile, service, firmware setting, kernel parameter, or BIOS
allocation as part of inspection.
