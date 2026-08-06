# AgentWorldLab

AgentWorldLab is a local, offline-first evaluation harness for
`Qwen/Qwen-AgentWorld-35B-A3B`. It treats the model as a world model that
predicts the next observation in a synthetic environment from interaction
history, environment state, and a proposed agent action.

It is **not** a chat application and model output is **not** permission to act.
Generated text is recorded and evaluated as untrusted observation data. It is
never passed to a shell, executed as code, sent to a live MCP server, or used to
modify the host.

## Current status

| Item | Status |
| --- | --- |
| Repository safety/lifecycle implementation | Implemented and mock-tested |
| Official model snapshot | Cached locally by HuggingFacePull |
| Pinned revision | `60d2b0434a53d2e62a7c00a489586815d94ebffb` |
| Snapshot inspection | Passed offline |
| Tokenizer and chat-template probe | Passed offline at 118 tokens |
| Official BF16 load on gfx1151 | Not yet verified |
| Minimal real generation | Not yet verified |
| vLLM ROCm backend | Implemented but gated until Transformers passes |

The cached checkpoint contains 21 complete BF16 shards, 693 indexed tensors,
and 69,321,314,576 bytes (64.561 GiB) of weight files. Offline inspection found
no missing indexed shard, broken snapshot link, or advertised remote-code
requirement. The configuration identifies `Qwen3_5MoeForConditionalGeneration`,
256 total experts, 8 experts selected per token, and language-model-only mode.

The official project describes AgentWorld as a 35B-total/3B-active MoE world
model covering terminal, MCP, software-engineering, search, Android, web, and OS
simulation. See the [official repository](https://github.com/QwenLM/Qwen-AgentWorld)
and [official model page](https://huggingface.co/Qwen/Qwen-AgentWorld-35B-A3B).

## Quick start: real model

These commands are for the target Framework Desktop. AgentWorldLab does not
depend on ModelDeck or any other application repository. Select the Python
interpreter from the ROCm environment you intend to validate, then run from the
repository root:

```powershell
cd /mnt/work/GitHubProjects/AgentWorldLab
$RocmPython = "/absolute/path/to/your/rocm-environment/bin/python"

& $RocmPython -c `
  "import torch, transformers; print(torch.__version__, torch.version.hip, transformers.__version__)"
```

The version command must report a ROCm-enabled torch build and a compatible
Transformers installation. A project-local environment such as
`AgentWorldLab/.venv-rocm72` is preferable because it keeps dependency changes
independent. Do not point this project at another application's environment as
a permanent setup, and do not install a second torch build over an environment
that already works.

First confirm that PyTorch can see exactly one gfx1151 device. This does not load
model weights:

```powershell
pwsh -NoProfile -File ./scripts/test.ps1 `
  -Hardware `
  -AcknowledgeHardwareRisk `
  -PythonPath $RocmPython
```

Then run one real terminal-simulation transition:

```powershell
pwsh -NoProfile -File ./scripts/run.ps1 `
  -Model agentworld `
  -AcknowledgeHardwareRisk `
  -PythonPath $RocmPython
```

That command performs one controlled lifecycle:

1. validates the pinned model and offline cache configuration;
2. starts an isolated worker process;
3. checks available memory and current temperature;
4. loads the official BF16 model with Transformers on `cuda:0` (ROCm's PyTorch
   device name), without CPU or disk offload;
5. renders the synthetic terminal fixture;
6. generates at most 64 tokens from at most 2,048 input tokens;
7. records output, timings, memory, temperature, and errors;
8. unloads the model and checks memory recovery;
9. stops the worker.

The first real run may fail during loading because gfx1151 kernel compatibility
has not yet been established. A precise failure record is the expected result
of an unsuccessful probe. AgentWorldLab will not silently switch to vLLM, CPU,
another dtype, quantisation, or a different checkpoint.

## What the default real experiment does

The default fixture describes an entirely synthetic POSIX-like terminal:

- simulated current directory: `/workspace`;
- simulated filesystem: initially empty;
- synthetic condition: `python` is unavailable and `python3` is installed;
- proposed action: `mkdir demo`.

The model is asked to predict only the next environment observation as a JSON
object. No real directory is created.

To propose another action in the same synthetic environment:

```powershell
pwsh -NoProfile -File ./scripts/run.ps1 `
  -Model agentworld `
  -Action "python --version" `
  -AcknowledgeHardwareRisk `
  -PythonPath $RocmPython
```

`-Action` changes prompt data only. It does not invoke the command.

To run the fixed five-turn synthetic filesystem trajectory:

```powershell
pwsh -NoProfile -File ./scripts/run.ps1 `
  -Model agentworld `
  -Trajectory `
  -AcknowledgeHardwareRisk `
  -PythonPath $RocmPython
```

The trajectory predicts observations for creating a simulated directory,
creating and listing a file, modifying it, and reading it. Each predicted
observation becomes history for the next turn. `-Action` and `-Trajectory`
cannot be used together.

## PowerShell run options

`scripts/run.ps1` is the recommended entry point on this machine.

| Option | Default | Meaning |
| --- | --- | --- |
| `-PythonPath` | `.venv`, then `python3`/`python` | Interpreter used by controller and worker |
| `-Config` | `configs/default.toml` | Model, limits, cache, and safety policy |
| `-Model` | `mock` | Allowlisted model name; use `agentworld` for BF16 |
| `-Fixture` | Default terminal fixture | Synthetic scenario JSON |
| `-Action` | Fixture action | Replacement action for a single transition |
| `-Trajectory` | Off | Run the fixture's five-to-ten-turn action list |
| `-MaxInputTokens` | Model configuration limit | Lower per-run input cap |
| `-MaxOutputTokens` | Model configuration limit | Lower per-run output cap |
| `-Temperature` | `0.0` | Decoding temperature between 0 and 2 |
| `-Seed` | `0` | Seed used when sampling |
| `-Warm` | Off | Label the record as warm; does not retain the worker |
| `-AcknowledgeHardwareRisk` | Off | Required for every non-mock backend |

Script arguments cannot raise token limits above the configured caps. The
default real configuration is deliberately limited to 2,048 input tokens and
64 output tokens with deterministic decoding and batch size one.

## Mock workflow

Use the mock backend to verify the complete controller/worker/record lifecycle
without ML packages or GPU access:

```powershell
pwsh -NoProfile -File ./scripts/run.ps1
pwsh -NoProfile -File ./scripts/run.ps1 -Trajectory
```

The mock uses the same JSON Lines protocol, fixture rendering, record writing,
evaluation, cancellation, unloading, and stale-process recovery paths as the
real backend. A mock pass proves the harness path works; it does not prove model
or ROCm compatibility.

## Available fixtures

| Fixture | Domain | Purpose |
| --- | --- | --- |
| `fixtures/terminal/single-transition-v1.json` | Terminal | One synthetic `mkdir` transition with a fixed Python perturbation |
| `fixtures/terminal/stateful-trajectory-v1.json` | Terminal | Five-turn synthetic filesystem consistency check |
| `fixtures/mcp/malformed-response-v1.json` | MCP | Predict handling of malformed synthetic tool JSON |
| `fixtures/swe/missing-dependency-v1.json` | SWE | Predict handling of an unavailable synthetic dependency |

Example controlled perturbation with the real model:

```powershell
pwsh -NoProfile -File ./scripts/run.ps1 `
  -Model agentworld `
  -Fixture fixtures/swe/missing-dependency-v1.json `
  -AcknowledgeHardwareRisk `
  -PythonPath $RocmPython
```

Fixtures describe conditions; they never reproduce those conditions on the
host. See [Experiment guide](docs/experiments.md) before creating or comparing
fixtures.

## Offline cache and revision

The target configuration is pinned to:

```text
Model:    Qwen/Qwen-AgentWorld-35B-A3B
Revision: 60d2b0434a53d2e62a7c00a489586815d94ebffb
Cache:    /mnt/work/models/huggingface/hub
```

HuggingFacePull has already downloaded this snapshot. AgentWorldLab passes the
cache path explicitly to Hugging Face, Transformers, and vLLM and forces the
worker into offline mode. It does not search for a newer revision.

To inspect the configured snapshot without loading weights:

```powershell
$Python = "/absolute/path/to/your/rocm-environment/bin/python"
$env:PYTHONPATH = (Join-Path $PWD "src")
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"

& $Python -m agentworldlab --config configs/default.toml `
  inspect-model --model agentworld

& $Python -m agentworldlab --config configs/default.toml `
  probe-tokenizer --model agentworld `
  --fixture fixtures/terminal/single-transition-v1.json
```

On another machine, copy `configs/default.toml` and change only
`cache_directory` to that machine's Hugging Face hub cache. Keep the revision
pinned. Downloading is deliberately outside AgentWorldLab:

```bash
hf download Qwen/Qwen-AgentWorld-35B-A3B \
  --revision 60d2b0434a53d2e62a7c00a489586815d94ebffb
```

## Safety policy

Thermal safety takes priority over completing a run.

| Condition | Behaviour |
| --- | --- |
| Temperature below 80°C | Continue with one-second sampling |
| 80–85°C | Record caution and continue close monitoring |
| Above 85°C | Cancel generation and unload when it returns |
| 90°C or above | Immediately terminate the isolated worker |
| No readable allowlisted sensor | Refuse a real model load |
| Pre-load temperature at least 85°C | Refuse a real model load |
| Available system memory below 104 GiB | Refuse a real model load |
| Load exceeds 900 seconds | Cancel or terminate worker |
| Generation exceeds 180 seconds | Cancel or terminate worker |
| Unload exceeds 120 seconds | Terminate worker |

The 104 GiB pre-load requirement combines an 80 GiB model/loading allowance
with 24 GiB headroom for Fedora, the controller, temporary copies, and other
workloads. CPU/disk offload is disabled; an unexpected device map fails visibly.

Press `Ctrl+C` to cancel an interactive run. The controller requests backend
cancellation, unloads when possible, terminates an unresponsive worker, and
writes a cancellation/failure record. After a thermal cancellation, wait for
the machine to cool before retrying.

Do not run sustained or unattended benchmarks until real automatic thermal
termination and memory recovery have been reviewed. Read
[Thermal and memory safety](docs/safety.md) for recovery procedures.

## Experiment records

Every `run` or `run-trajectory` command creates:

```text
records/<experiment-id>.json
records/<experiment-id>.md
```

The JSON record contains:

- host, Fedora, kernel, Python, ROCm, torch, Transformers, and vLLM identity;
- model ID, exact revision, cache, backend, precision, and quantisation;
- fixture ID/domain and cold/warm label;
- input, output, and context limits;
- load, preprocessing, prefill, decode, and total timings;
- generated token count and tokens per second;
- initial, peak, and post-unload system/GPU memory;
- peak temperature, cancellation, timeout, and hard-stop status;
- raw model output and the parsed synthetic observation;
- structured errors and automated evaluation checks;
- blank manual-review dimensions for operator assessment.

The CLI prints the exact record paths when it finishes. In PowerShell, inspect a
record with:

```powershell
Get-Content records/<experiment-id>.json | ConvertFrom-Json | Format-List
Get-Content records/<experiment-id>.md
```

Do not compare runs unless revision, backend, precision, fixture, limits,
decoding settings, and cold/warm classification match, or every difference is
documented.

## Build and test scripts

Create source and wheel distributions:

```powershell
pwsh -NoProfile -File ./scripts/build.ps1
```

This creates `.venv-build`, upgrades pip, installs the Python `build` frontend,
and writes artefacts under `dist/`. It may access the Python package index while
bootstrapping but never downloads model weights.

Run routine tests without hardware access:

```powershell
pwsh -NoProfile -File ./scripts/test.ps1
```

The routine path compiles Python sources and runs configuration, protocol,
lifecycle, cancellation, timeout, thermal, OOM, crash, stale-process, fixture,
record, no-execution, and PowerShell parser tests. The hardware test stays
skipped unless both `-Hardware` and `-AcknowledgeHardwareRisk` are supplied.

See [PowerShell scripts](docs/powershell.md) for every build/test/run parameter.

## Python CLI without PowerShell

Routine development needs no ML packages:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m unittest discover -s tests -v
agentworldlab inspect-host
agentworldlab run --model mock
agentworldlab run-trajectory --model mock
```

Do not install a second torch build over an existing ROCm environment. To use
the real backend, install AgentWorldLab without dependencies into the intended
ROCm environment or run from source with `PYTHONPATH=src`:

```bash
/path/to/rocm-env/bin/python -m pip install --upgrade pip
/path/to/rocm-env/bin/python -m pip install -e . --no-deps
/path/to/rocm-env/bin/python -c \
  'import torch, transformers; print(torch.__version__, torch.version.hip, transformers.__version__)'

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  /path/to/rocm-env/bin/python -m agentworldlab \
  --config configs/default.toml run --model agentworld \
  --fixture fixtures/terminal/single-transition-v1.json
```

The direct Python CLI enforces the same configuration and worker safety policy,
but the PowerShell wrapper adds an explicit hardware acknowledgement gate.

## Troubleshooting

| Symptom | Meaning and next action |
| --- | --- |
| `Hardware tests require ... AcknowledgeHardwareRisk` | Add the acknowledgement only after reading the safety guide |
| `Backend 'transformers' requires ...` | Real runs require `-AcknowledgeHardwareRisk`; mock runs do not |
| `torch.cuda.is_available()` is false | The selected environment cannot access ROCm; verify `/dev/kfd`, groups, and torch ROCm build |
| Hardware test does not report gfx1151 | Stop; do not attempt the model load with that interpreter/device |
| Pinned snapshot unavailable | Confirm the configured revision exists under the configured cache path |
| Available memory below 104 GiB | Close other workloads and retry later; do not weaken the gate merely to load |
| No temperature sensor is readable | Stop and restore telemetry; do not bypass the sensor admission check |
| Pre-load temperature is at least 85°C | Let the system cool below the threshold before retrying |
| `model_load_error` | Review the record for architecture, kernel, allocation, or device-map details |
| Worker exits with `thermal_hard_stop` | Cool down, inspect system state, and do not immediately reload |
| Memory recovery fails | Stop testing, retain the record, inspect system/GPU memory, and reboot only as an operator decision |
| vLLM import reports `libmpi_cxx.so.40` missing | The existing vLLM environment is not ready; continue with Transformers rather than patching during a run |
| Output is non-empty but automated evaluation fails | Review raw output and parsed observation; successful generation does not imply useful simulation |

Useful read-only checks before a first real run:

```bash
rocminfo | rg -n 'Name:|gfx1151'
rocm-smi --showproductname --showmeminfo vram --showtemp
amd-smi metric --mem-usage --temperature
sensors
```

Do not change services, kernel parameters, power profiles, FedoraUsage policy,
firmware, or BIOS settings as part of troubleshooting unless that separate
system change is explicitly reviewed and authorised.

## Architecture and protocol

The CLI/controller starts one child worker and communicates only through
versioned, bounded JSON Lines over stdin/stdout. Load and generation run on a
worker task thread so the command loop can answer `health` and `cancel` while a
backend is busy. The controller correlates replies, enforces timeouts, detects
crashes, and safely recovers stale PID records.

The worker operations are:

| Operation | Purpose |
| --- | --- |
| `health` | Report lifecycle, task, model identity, and current memory |
| `load` | Load one explicitly configured pinned model |
| `run` | Predict a synthetic observation |
| `cancel` | Request cancellation of the active task |
| `unload` | Release model resources and record memory recovery |
| `stop` | Shut down the worker cleanly |

There are no listening ports, HTTP services, browser interfaces, background
daemons, or live tool connections. See [Architecture](docs/architecture.md) and
[Worker protocol](docs/protocol.md) for implementation details.

## Project boundaries

- Model output is simulated observation data, not an action request.
- The first real validation backend is Transformers.
- Backend selection is explicit and has no silent fallback.
- Remote model code and unpinned revisions are rejected.
- One worker loads at most one model at a time.
- No CPU/disk offload, dtype fallback, quantisation fallback, or alternate
  checkpoint is enabled.
- Context progression stops at 32K until earlier stages pass; 128K and 256K are
  not initial targets.
- ModelDeck integration remains deferred until AgentWorldLab independently
  passes the official BF16 milestone.

## Documentation

- [Documentation index](docs/README.md)
- [Architecture](docs/architecture.md)
- [Development guide](docs/development.md)
- [Experiment guide](docs/experiments.md)
- [PowerShell scripts](docs/powershell.md)
- [Worker protocol](docs/protocol.md)
- [Thermal and memory safety](docs/safety.md)
- [System inspection](docs/system-inspection.md)
- [Validation and acceptance](docs/validation.md)
- [Experiment record schema](docs/experiment-record-schema.json)

Read the safety and validation documents before any hardware-dependent run.
