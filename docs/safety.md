# Thermal and memory safety

Thermal safety overrides benchmark completion.

## Policy

| Control temperature | Worker behaviour |
| --- | --- |
| Below 80°C | Continue and sample every second |
| 80–85°C | Record caution state and continue close monitoring |
| Above 85°C | Request generation cancellation and automatically unload when the task returns |
| 90°C or above | Request cancellation and immediately terminate the worker |

The control value is the maximum readable allowlisted sensor value. A real
model load is refused if no allowlisted sensor is readable or if the initial
value is 85°C or higher. The worker samples during loading and generation.
Hard termination uses process isolation because a hung GPU call cannot be
reliably interrupted in Python.

After any thermal cancellation, allow the machine to reach at most 75°C for the
configured cooldown before another run. Do not run sustained or unattended
benchmarks until a simulated hard stop, an operator-observed cancellation, and
a real worker crash recovery have all passed.

## Memory policy

- System available memory and GPU-addressable GTT/VRAM are recorded separately.
- The default load gate requires 104 GiB system memory available: an 80 GiB
  model/load allowance plus a stated 24 GiB headroom policy.
- Swap totals, process RSS, minimum system availability, and maximum GPU use are
  recorded throughout the task.
- No automatic CPU offload, disk offload, dtype change, quantisation, or smaller
  checkpoint fallback is configured.
- One model is allowed per worker. Concurrent loads are rejected.
- Unload drops model and processor references, collects Python objects, clears
  the torch device cache, synchronises, and records memory again.
- A run passes recovery only when available memory returns within the configured
  4 GiB tolerance. Review both system and GPU counters; one number is not enough.

## Failure recovery

1. Above 85°C, cancel and wait for the active task to return.
2. At 90°C, on a timeout, or on an unresponsive backend, terminate the worker.
3. Never kill a PID based only on a stale file. The controller verifies both
   Linux process start ticks and the worker command line.
4. Start a fresh worker and run `health`; do not immediately reload weights.
5. Confirm temperature, memory, swap use, and `/dev/kfd` health.
6. If memory does not recover, stop testing and capture the record and kernel
   logs. Reboot only as an operator decision, not an automatic rollback.

FedoraUsage and firmware protection are independent layers. AgentWorldLab does
not enable, disable, or reconfigure them.
