# AgentWorldLab

AgentWorldLab is a local, offline-first evaluation harness for treating
`Qwen/Qwen-AgentWorld-35B-A3B` as an environment simulator. It does not treat
model output as instructions: generated actions are never executed, no port is
opened, and the first real backend is direct Hugging Face Transformers.

The repository currently implements the safe investigation and minimal
compatibility milestone. It does **not** claim that the BF16 checkpoint works
on gfx1151; no weights were downloaded or loaded while building the harness.

## What is implemented

- A standard-library CLI and strict TOML configuration.
- A pinned official model revision and explicit model allowlist.
- An isolated worker with a versioned JSON Lines stdin/stdout protocol.
- `health`, `load`, `run`, `cancel`, `unload`, and `stop` operations.
- One model per worker, no backend fallback, no listening sockets, and no UI.
- Mock, Transformers, and gated vLLM adapters.
- Offline snapshot inspection and tokenizer-only probes.
- Pre-load memory and temperature checks, continuous sampling, cancellation
  above 85°C, and worker termination at 90°C or above.
- Generation/load/unload timeouts, stale-worker detection, and crash recovery.
- Versioned terminal, MCP, and software-engineering fixtures.
- JSON experiment records, Markdown summaries, and deterministic local checks.
- Mock-based tests for routine safety and lifecycle behaviour.

The official project describes AgentWorld as a 35B-total/3B-active MoE world
model with terminal, MCP, and SWE among its simulation domains. The pinned
configuration reports `Qwen3_5MoeForConditionalGeneration`, BF16, 256 experts
with 8 selected per token, and language-model-only mode. See the
[official repository](https://github.com/QwenLM/Qwen-AgentWorld) and
[official model page](https://huggingface.co/Qwen/Qwen-AgentWorld-35B-A3B).

## Safe start

Routine validation needs no ML packages:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m unittest discover -s tests -v
agentworldlab inspect-host
agentworldlab run --model mock
agentworldlab run-trajectory --model mock
```

PowerShell 7 equivalents are available for routine workflows:

```powershell
pwsh -NoProfile -File scripts/build.ps1
pwsh -NoProfile -File scripts/test.ps1
pwsh -NoProfile -File scripts/run.ps1
pwsh -NoProfile -File scripts/run.ps1 -Trajectory
```

See [PowerShell scripts](docs/powershell.md) for parameters and the explicit
acknowledgement required by hardware-dependent test or run paths.

The mock command creates one JSON record and one Markdown summary in `records/`.
It exercises the same controller and worker protocol as a hardware run.

`run` covers a single transition. `run-trajectory` carries each synthetic
action and prior simulated observation into a fixed five-to-ten-turn run.
Controlled perturbation fixtures live under `fixtures/mcp` and `fixtures/swe`;
the same fixture can be selected with another allowlisted model for a local
baseline comparison.

Do not install a second PyTorch build over an existing ROCm environment. For a
real probe, install AgentWorldLab without dependencies into the intended ROCm
environment and confirm its existing packages first:

```bash
/path/to/rocm-env/bin/python -m pip install --upgrade pip
/path/to/rocm-env/bin/python -m pip install -e . --no-deps
/path/to/rocm-env/bin/python -c 'import torch, transformers; print(torch.__version__, torch.version.hip, transformers.__version__)'
```

## Offline model progression

Downloading is deliberately separate from evaluation and requires an explicit
network-enabled operator action. The configured revision is immutable:

```bash
hf download Qwen/Qwen-AgentWorld-35B-A3B \
  --revision 60d2b0434a53d2e62a7c00a489586815d94ebffb
```

After the snapshot is present, force offline operation and progress one stage
at a time:

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

agentworldlab inspect-model --model agentworld
agentworldlab probe-tokenizer --model agentworld
agentworldlab run --model agentworld \
  --fixture fixtures/terminal/single-transition-v1.json
```

The target-machine configuration points `cache_directory` at
`/mnt/work/models/huggingface/hub`, matching HuggingFacePull's cache. Override
that path in a local configuration when using another machine; model access
remains offline and revision-pinned.

The default real-model limits are 2,048 input tokens, 64 output tokens, batch
size one, BF16, and deterministic decoding. Do not increase them until the load
and unload record passes review. The initial 104 GiB available-memory gate
(80 GiB allowance plus 24 GiB headroom) is an engineering estimate; replace it
only after recording the exact snapshot size and peak temporary-copy behaviour.

## Protocol

`agentworldlab worker` exposes JSON Lines only on stdin/stdout. A controller can
send, for example:

```json
{"version":1,"id":"1","operation":"load","payload":{"model":"mock"}}
{"version":1,"id":"2","operation":"run","payload":{"prompt":"Predict a synthetic observation"}}
{"version":1,"id":"3","operation":"cancel","payload":{}}
{"version":1,"id":"4","operation":"unload","payload":{}}
{"version":1,"id":"5","operation":"stop","payload":{}}
```

Each request receives a response with the same ID. `run` and `load` occur on a
worker task thread, keeping the command loop responsive. A 90°C sample exits
the worker immediately; the controller treats that as a visible crash and
cleans the stale PID record. Details are in [protocol.md](docs/protocol.md).

## Project boundaries

- Outputs are simulated observations, not permission to act.
- Model output has no code path to `subprocess`, a shell, a host filesystem
  mutation, a network request, or an MCP server.
- Remote model code and unpinned revisions are rejected.
- vLLM configuration is rejected until `transformers_probe_passed = true` is
  deliberately recorded after the official BF16 Transformers probe.
- There is no silent backend, dtype, quantisation, device, or CPU fallback.
- ModelDeck integration remains deferred until the independent acceptance
  milestone passes.

See the [documentation index](docs/README.md) for architecture, development,
experiments, PowerShell workflows, protocol, safety, system inspection, and
validation guidance.
Read [safety.md](docs/safety.md) and [validation.md](docs/validation.md) before
any hardware-dependent run.
