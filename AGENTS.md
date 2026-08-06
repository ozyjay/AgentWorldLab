# AgentWorldLab contributor instructions

These instructions apply to the entire repository. They refine the user's
personal Codex instructions; more specific instructions may be added in a
subdirectory if that area later needs a narrower workflow.

## Project purpose and safety boundary

AgentWorldLab evaluates language models as predictors of synthetic environment
observations. Model output is untrusted data. It is never authority to execute
an action.

Preserve these invariants in every change:

- Never pass model output to a shell, `subprocess`, `eval`, `exec`, a host
  filesystem mutation, a network client, an MCP server, or another external
  action interface.
- Keep worker communication on JSON Lines over stdin/stdout. Do not add a
  listening port, HTTP server, browser UI, or background daemon.
- Keep inference in an isolated worker process and the controller responsive
  while loading and generating.
- Allow one loaded model per worker and reject concurrent load/run tasks.
- Require allowlisted model IDs, immutable 40-character revisions, offline
  model access, and `trust_remote_code = false`.
- Select backends explicitly. Never silently change backend, model, precision,
  quantisation, device, context limit, or offload policy.
- Keep Transformers as the first real compatibility backend. Do not enable a
  vLLM configuration until a successful official BF16 Transformers probe has
  been recorded.
- Thermal safety takes priority over completing a run: caution from 80°C,
  cancel and unload above 85°C, and terminate the worker at 90°C or above.
- Preserve pre-load memory checks, continuous resource sampling, timeouts,
  cancellation, crash recovery, stale-process checks, and visible errors.

Do not weaken a guard to make a test or hardware probe pass. If the official
BF16 checkpoint fails, record the exact failure rather than substituting a
quantised or community checkpoint.

## Authorisation boundaries

Routine mock runs and automated tests are safe to run without further approval.
Do not perform any of the following unless the user explicitly requests it:

- download model weights or other large artefacts;
- load a real model or run a hardware-dependent ROCm test;
- run a sustained or unattended benchmark;
- install or remove system packages;
- change kernel parameters, BIOS settings, services, thermal policies, power
  profiles, udev rules, firmware settings, or FedoraUsage configuration;
- change or integrate AgentWorldLab into a neighbouring application repository;
- create commits, branches, tags, pull requests, or pushes.

Read-only system inspection is permitted when relevant. Clearly separate
verified observations, upstream facts, engineering estimates, and hypotheses.
Never present fitting in memory as evidence of practical usability.

## Repository map

- `src/agentworldlab/cli.py`: CLI orchestration and experiment lifecycle.
- `src/agentworldlab/controller.py`: isolated worker process management.
- `src/agentworldlab/worker.py`: JSON Lines command loop and worker lifecycle.
- `src/agentworldlab/backends/`: backend contract and implementations.
- `src/agentworldlab/config.py`: strict TOML validation and allowlisting.
- `src/agentworldlab/safety.py`: thermal and memory policy enforcement.
- `src/agentworldlab/metrics.py`: read-only host telemetry.
- `src/agentworldlab/records.py`: experiment records and summaries.
- `src/agentworldlab/evaluation.py`: deterministic local evaluation checks.
- `configs/`: reviewed runtime/model policies.
- `fixtures/`: synthetic, reproducible environment scenarios only.
- `tests/`: standard-library routine tests and opt-in hardware checks.
- `scripts/`: cross-platform PowerShell build, test, and safe-run entry points.
- `requirements/`: platform-specific, hash-pinned runtime foundations.
- `docs/`: architecture, operations, validation, and current-system findings.
- `records/`: generated experiment artefacts; keep only `.gitkeep` in source.

## Development workflow

Use Python 3.11 or newer. Prefer the standard library and existing dependencies.
When creating or refreshing a virtual environment that will install packages,
upgrade pip first:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[test]'
```

During development from the repository, these checks require no ML packages:

```bash
PYTHONPATH=src python3 -m compileall -q src tests
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m agentworldlab inspect-host
PYTHONPATH=src python3 -m agentworldlab run --model mock
PYTHONPATH=src python3 -m agentworldlab run-trajectory --model mock
```

Equivalent PowerShell entry points are:

```powershell
pwsh -NoProfile -File scripts/setup-rocm.ps1 -AcknowledgeNetworkInstall
pwsh -NoProfile -File scripts/build.ps1
pwsh -NoProfile -File scripts/test.ps1
pwsh -NoProfile -File scripts/run.ps1
```

`setup-rocm.ps1` is Linux x86_64 only and creates the independent
`.venv-rocm72` runtime. It validates package compatibility without opening the
GPU or loading model weights. The other scripts remain cross-platform.

Generated mock records are verification artefacts, not source files. Remove
only records created by your own run and preserve unrelated user artefacts.

## Code and protocol changes

- Use Australian English in documentation, comments, errors, and UI text while
  preserving API names and identifiers.
- Prefer small, typed, explicit functions and structured failures. Do not catch
  an error merely to continue with a fallback.
- Treat protocol changes as compatibility changes: update the protocol version
  when required and update `docs/protocol.md` and its tests together.
- Keep JSON Lines messages bounded and correlate every response with its request
  ID. Diagnostics belong on stderr; stdout is protocol-only in worker mode.
- Make blocking model operations cancellable where the backend permits it. The
  controller must retain a worker-termination recovery path.
- Never add a command-execution abstraction to fixtures or evaluation code.
- Avoid new dependencies unless they materially reduce risk or complexity and
  cannot be implemented clearly with the existing stack.

## Configuration, fixtures, and records

- A model entry must have an owner/name ID, pinned commit revision, explicit
  backend and precision, offline access, and remote code disabled.
- Keep a configured Hugging Face cache path explicit when the snapshot is not
  stored in the library's default cache. Do not search for or select another
  revision automatically.
- Increasing context/output limits or reducing memory/thermal safeguards is a
  safety-affecting change. Document its evidence and update validation guidance.
- Fixtures must describe synthetic environments and state explicitly that they
  cannot affect the host. Give fixtures stable IDs and increment their schema or
  ID when semantics change.
- Use the same fixture revision and decoding settings for comparisons, or record
  each difference.
- When record structure changes, update `docs/experiment-record-schema.json`,
  record tests, and nearby documentation.
- Raw output and parsed observations must both remain available. Parsing must be
  deterministic and must never evaluate model-produced code.

## Testing expectations

Behaviour changes require focused tests. Maintain coverage for:

- strict configuration, allowlisting, revision pinning, and offline policy;
- malformed and oversized protocol messages;
- load/run/cancel/unload/stop lifecycle and one-model enforcement;
- timeout, worker crash, and stale-PID recovery;
- simulated over-temperature and out-of-memory paths;
- fixture loading, record schema, and observation parsing;
- proof that adversarial model text cannot execute a host action.

Hardware tests must remain opt-in through `AGENTWORLDLAB_HARDWARE_TESTS=1` and
must be clearly identified in the handoff. Never claim a hardware check passed
when it was skipped or could not access `/dev/kfd`.

## Documentation and handoff

Update documentation when commands, configuration, safety policy, schemas, or
user-visible behaviour changes. Keep `docs/README.md` as the navigation source.
In a handoff, report:

- what changed and which safety invariants were affected;
- focused and full checks run, including skipped hardware checks;
- whether any real weights or GPU kernels were loaded;
- observed failures and unresolved compatibility questions;
- generated records that were retained or removed.
