# Validation and acceptance

## Routine checks

```bash
PYTHONPATH=src python3 -m compileall -q src tests
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m agentworldlab inspect-host
PYTHONPATH=src python3 -m agentworldlab run --model mock
```

Success means configuration, protocol, fixture, record, safety, cancellation,
timeout, lifecycle, stale-state, and no-execution tests pass. A mock result is
not evidence of model compatibility.

## Progressive hardware stages

| Stage | Command or action | Acceptance signal | Failure and rollback |
| --- | --- | --- | --- |
| A — metadata | `agentworldlab inspect-model --model agentworld` | Exact revision, snapshot bytes, shards, architecture, BF16 and MoE fields recorded; no weights loaded | Keep the cached snapshot, report missing/corrupt metadata, do not load |
| B — tokenizer | `agentworldlab probe-tokenizer --model agentworld` | Template renders, special tokens are inspectable, fixture stays under 2K | Record processor/template error; do not load weights |
| C — load only | Use the worker protocol: `load`, `health`, `unload`, `stop` | BF16 loads on one gfx1151 device, peak below 85°C, no host offload, memory recovers within tolerance | Cancel; terminate worker if needed; produce compatibility record, no quantised substitution |
| D — minimal generation | `agentworldlab run --model agentworld` | One coherent JSON terminal observation, at most 2,048 input and 64 output tokens, cancellable, no host action, full record | Unload or terminate, cool down, retain failure record |
| E1 — 8K | Explicit reviewed config capped at 8K/512 | Stable transition and trajectory results with practical recorded latency | Return to Stage D limits |
| E2 — 16K | Explicit reviewed config capped at 16K/1,024 | Stable memory, temperature, cancellation and state consistency | Return to last passing context |
| E3 — 32K | Only after E2 acceptance | Same safety and evaluation criteria remain satisfied | Stop progression; do not test 128K/256K |

Cold and warm runs must be labelled. Compare runs only when model revision,
backend, precision, fixture version, context/output limits, and decoding settings
match, or document each difference.

## Initial milestone

The milestone passes only when all are true:

- The official pinned BF16 checkpoint loads through Transformers on gfx1151.
- One terminal observation is coherent and structurally valid.
- Input/output caps remain near 2K/64 and batch size remains one.
- No generated command is executed.
- Peak control temperature remains below 85°C.
- Cancellation returns and leaves the worker usable.
- Unload recovers most memory within the documented tolerance.
- Timings, software versions, memory, temperature, raw output, parsed
  observation, and any errors appear in a structured record.

If BF16 fails, publish the exact compatibility report. Do not enable vLLM,
switch dtype, or choose a community quantisation as an automatic workaround.

## Later evaluation

Use the versioned fixtures for single transitions, fixed five-step trajectories,
controlled failures, and identical baseline-model comparisons. Automated checks
cover non-empty output, JSON observation shape, required facts, prohibited
claims, and the no-host-execution harness invariant. Complete the manual review
fields for factual consistency, trajectory consistency, realism, formatting,
failure handling, synthetic constraints, and usefulness.

Host-application integration is accepted only after this milestone passes
independently.
Its boundary should be an environment-simulator provider carrying the same
pinned identity, cancellation, health, unloading, and safety semantics.
