# AgentWorldLab documentation

Start with the safety boundary and current compatibility status before running
anything against real hardware.

## Guides

| Document | Purpose |
| --- | --- |
| [Architecture](architecture.md) | Process boundaries, data flow, backends, and failure containment |
| [Development](development.md) | Local setup, checks, contribution workflow, and documentation maintenance |
| [Experiments](experiments.md) | Fixture authoring, single and trajectory runs, comparisons, and record review |
| [PowerShell scripts](powershell.md) | Cross-platform build, test, and safe-run commands |
| [Worker protocol](protocol.md) | Versioned JSON Lines requests, responses, and lifecycle rules |
| [Thermal and memory safety](safety.md) | Thresholds, resource policy, and recovery procedure |
| [System inspection](system-inspection.md) | Verified host observations, upstream facts, estimates, and open questions |
| [Validation and acceptance](validation.md) | Progressive hardware stages and milestone criteria |
| [Experiment record schema](experiment-record-schema.json) | Machine-readable version 1 record shape |

## Recommended reading order

For routine development:

1. [Architecture](architecture.md)
2. [Development](development.md)
3. [Worker protocol](protocol.md)

Before an explicitly authorised hardware probe:

1. [System inspection](system-inspection.md)
2. [Thermal and memory safety](safety.md)
3. [Validation and acceptance](validation.md)
4. [Experiments](experiments.md)

The root [README](../README.md) contains the shortest safe-start path. Repository
automation and coding agents must also follow [AGENTS.md](../AGENTS.md).
