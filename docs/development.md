# Development guide

## Environment

AgentWorldLab supports Python 3.11 and newer. Routine development uses only the
standard library; real backends use optional dependencies.

Create an isolated environment and upgrade pip before installing packages:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[test]'
```

When using an existing ROCm environment, do not install another torch build over
it. Install this repository without dependencies and inspect versions first:

```bash
/path/to/rocm-env/bin/python -m pip install --upgrade pip
/path/to/rocm-env/bin/python -m pip install -e . --no-deps
/path/to/rocm-env/bin/python -c \
  'import torch, transformers; print(torch.__version__, torch.version.hip, transformers.__version__)'
```

## Routine checks

From an editable install:

```bash
.venv/bin/python -m compileall -q src tests
.venv/bin/python -m unittest discover -s tests -v
agentworldlab inspect-host
agentworldlab run --model mock
agentworldlab run-trajectory --model mock
```

Without installing the project:

```bash
PYTHONPATH=src python3 -m compileall -q src tests
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m agentworldlab run --model mock
```

The hardware smoke check is deliberately excluded from routine runs:

```bash
AGENTWORLDLAB_HARDWARE_TESTS=1 \
  /path/to/rocm-env/bin/python -m unittest discover \
    -s tests -p 'test_hardware.py' -v
```

Run it only after explicit authorisation and the read-only checks in
[system-inspection.md](system-inspection.md).

## Change checklist

For Python behaviour changes:

1. Follow the existing typed, standard-library-first patterns.
2. Add a focused test for the changed behaviour and failure path.
3. Run the focused test, then the complete routine suite.
4. Run a mock transition when controller, worker, backend, protocol, records,
   fixtures, evaluation, or safety code changes.
5. Remove only records created by your verification run.

Additional paired updates:

| Change | Also update |
| --- | --- |
| Protocol shape or lifecycle | `docs/protocol.md`, protocol/lifecycle tests, version if incompatible |
| Configuration field or limit | example TOML, config tests, README or safety guidance |
| Record field | `docs/experiment-record-schema.json`, record tests, experiment guide |
| Fixture semantics | fixture ID/schema, fixture tests, expected evaluation facts |
| Thermal/memory policy | safety tests, `docs/safety.md`, validation acceptance |
| Backend capability | architecture, validation status, explicit dependency guidance |
| CLI command | root README, docs index destination, command-level tests |

## Code review priorities

Review in this order:

1. Could model-controlled text reach an execution or external-action path?
2. Could a change weaken thermal, memory, timeout, isolation, or offline policy?
3. Does the controller remain responsive during backend work?
4. Are failures structured, visible, and free of silent fallback?
5. Are experiments still reproducible and comparable?
6. Are tests and nearby documentation aligned with behaviour?

Treat safety regressions as blocking even when the happy-path output is correct.

## Documentation style

Use Australian English and plain language. Keep observed system state separate
from upstream facts, estimates, and hypotheses. Do not copy transient benchmark
values into general guidance without a dated record and matching configuration.

`docs/README.md` is the documentation index. Add new operator or contributor
guides there and link important entry points from the root README.
