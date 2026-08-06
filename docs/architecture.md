# Architecture

AgentWorldLab separates orchestration from inference so the control process can
remain responsive when model code hangs, crashes, exceeds limits, or encounters
a ROCm failure.

## Components

| Component | Responsibility | Must not do |
| --- | --- | --- |
| CLI | Validate operator input, select fixtures, coordinate lifecycle, write records | Execute model output or choose a fallback backend |
| Controller | Start one worker, correlate protocol replies, enforce timeouts, terminate failed workers | Host model objects or open a listening socket |
| Worker | Own one backend/model and process JSON Lines operations | Interpret generated text as an action |
| Backend | Load, generate, cancel, unload, and report health/metrics | Change model, precision, device, or offload policy silently |
| Safety monitor | Sample temperature and memory, request cancellation, enforce hard termination | Reconfigure host thermal or power services |
| Fixture/evaluator | Render synthetic state and deterministically assess observations | Touch the real environment represented by a fixture |
| Recorder | Preserve identity, settings, resources, output, parsing, and outcome | Hide failures or overwrite comparison settings |

## Process and data flow

```text
Operator
   |
   v
CLI/controller  -- bounded JSON Lines over pipes -->  isolated worker
   |                                                  |        |
   |                                                  |        +--> thermal/resource monitor
   |                                                  |
   |                                                  +--> explicit backend
   |                                                          |
   |                                                          +--> one pinned model
   |
   +--> JSON record + Markdown summary
```

There are no inbound network paths. The controller forces Hugging Face and
Transformers offline mode in the worker environment. Model downloads are a
separate, explicit operator action.

## Lifecycle

1. The controller rejects a live matching PID or removes a demonstrably stale
   PID record.
2. It starts a child process using the current Python interpreter and pipes.
3. `load` performs memory and temperature admission checks for real backends.
4. Load and generation run on a worker task thread so `health` and `cancel`
   remain available on the command loop.
5. The safety monitor samples throughout load and generation.
6. `run` returns raw output as data, resource/timing metrics, and cancellation
   state. The controller parses and evaluates it without executing it.
7. `unload` releases backend references and records memory recovery.
8. `stop` exits cleanly. A timeout, crash, or 90°C sample terminates the worker;
   the next controller can recover the stale PID record safely.

Only one task may load or generate at a time. Unload and stop are rejected while
a task remains active, requiring cancellation or process termination first.

## Backend boundary

All backends implement load, generation, cancellation, unload, and health.
Selection comes only from validated configuration.

- `mock` is deterministic and exercises lifecycle/safety code without ML
  dependencies.
- `transformers` is the first real validation path. It fixes BF16 and `cuda:0`
  (the PyTorch device name used by ROCm), rejects CPU/disk offload, and uses a
  stopping criterion for cancellation.
- `vllm` is present but configuration-gated. It uses one GPU, eager generation,
  tensor-parallel size one, language-model-only mode, no CPU offload, and a
  conservative context. Synchronous cancellation may require worker termination.

Backend failures are returned as structured errors. No adapter invokes another
adapter as a fallback.

## Trust boundaries

Trusted inputs are repository-controlled configuration and fixtures after
schema validation. Untrusted inputs include prompts, model files, tokenizer
templates, model output, and backend exceptions.

Remote model code is prohibited. The initial model configuration is pinned to a
commit, and all worker model access is offline. Generated text can only reach
recording, deterministic JSON parsing, and evaluation checks.

## Persistence

Records are append-only per experiment ID and consist of machine-readable JSON
plus a concise Markdown summary. The source tree retains only `records/.gitkeep`.
The PID record is runtime coordination data, not model state, and is removed
after clean shutdown.

