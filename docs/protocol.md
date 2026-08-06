# Worker protocol

The protocol is UTF-8 JSON Lines, version 1, with a 2 MiB message cap. Only
stdin and stdout are used; diagnostics go to stderr. There are no sockets.

Requests contain `version`, a caller-selected `id`, `operation`, and an object
`payload`. Responses contain the same `id`, `ok`, and either `result` or a
structured `error` with `category` and `message`.

| Operation | Payload | Result |
| --- | --- | --- |
| `health` | `{}` | lifecycle state, task, model identity, memory |
| `load` | `{"model":"allowlist-name"}` | pinned identity, timing, memory, temperature |
| `run` | prompt and bounded decoding fields | raw observation, tokens, timings, resources |
| `cancel` | `{}` | whether an active task received cancellation |
| `unload` | `{}` | unload state and before/after memory |
| `stop` | `{}` | clean worker shutdown acknowledgement |

`load` and `run` responses are asynchronous with respect to later requests:
the command loop stays available for `health` and `cancel`. A busy worker
rejects another load/run task. Unload and stop require the task to finish after
cancellation. If it cannot, the controller terminates the entire worker.

Unknown versions, operations, model names, non-object payloads, oversized lines,
and malformed JSON fail visibly. Backend failures remain explicit and never
trigger a fallback.

