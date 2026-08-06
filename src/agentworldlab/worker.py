"""Isolated JSON Lines inference worker.

The worker accepts only structured requests on stdin and writes only structured
responses on stdout. Model output is data and is never passed to subprocesses,
shells, files, networks, or host tools.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from typing import Any, TextIO

from agentworldlab.backends.base import Backend, GenerationRequest
from agentworldlab.backends.vllm import create_backend
from agentworldlab.config import AppConfig, ModelConfig, load_config
from agentworldlab.errors import AgentWorldLabError, LifecycleError, ProtocolError
from agentworldlab.metrics import memory_sample
from agentworldlab.protocol import decode, encode, response, validate_request
from agentworldlab.safety import ThermalMonitor, require_memory_headroom, require_safe_start


class WorkerRuntime:
    def __init__(self, config: AppConfig, output: TextIO) -> None:
        self.config = config
        self.output = output
        self.output_lock = threading.Lock()
        self.state_lock = threading.RLock()
        self.backend: Backend | None = None
        self.model: ModelConfig | None = None
        self.task: threading.Thread | None = None
        self.task_operation: str | None = None
        self.stopping = False

    def send(self, message: dict[str, Any]) -> None:
        with self.output_lock:
            self.output.write(encode(message))
            self.output.flush()

    def failure(self, request_id: str, exc: BaseException) -> None:
        if isinstance(exc, AgentWorldLabError):
            details = exc.details()
        else:
            details = {"category": "internal_error", "message": f"{type(exc).__name__}: {exc}"}
        self.send(response(request_id, ok=False, error=details))

    def _task_finished(self) -> None:
        with self.state_lock:
            self.task = None
            self.task_operation = None

    def _run_task(self, request_id: str, operation: str, function: Any) -> None:
        with self.state_lock:
            if self.task is not None:
                raise LifecycleError(f"worker is busy with {self.task_operation}")

            def target() -> None:
                try:
                    result = function()
                except BaseException as exc:
                    self._task_finished()
                    self.failure(request_id, exc)
                else:
                    self._task_finished()
                    self.send(response(request_id, ok=True, result=result))

            self.task_operation = operation
            self.task = threading.Thread(target=target, name=f"worker-{operation}", daemon=False)
            self.task.start()

    def handle(self, request_id: str, operation: str, payload: dict[str, Any]) -> None:
        if operation == "health":
            with self.state_lock:
                result = {
                    "state": "busy" if self.task else ("loaded" if self.model else "ready"),
                    "task": self.task_operation,
                    "model": self.backend.health() if self.backend else None,
                    "memory": memory_sample().to_dict(),
                }
            self.send(response(request_id, ok=True, result=result))
            return
        if operation == "load":
            model_name = payload.get("model")
            if not isinstance(model_name, str):
                raise ProtocolError("load requires a model name")
            model = self.config.model(model_name)
            with self.state_lock:
                if self.model is not None or self.backend is not None:
                    raise LifecycleError("one model is already loaded")

            def load_model() -> dict[str, Any]:
                before = memory_sample()
                monitor: ThermalMonitor | None = None
                backend = create_backend(model.backend)
                if model.backend != "mock":
                    require_memory_headroom(self.config.runtime)
                    require_safe_start(self.config.thermal)
                    monitor = ThermalMonitor(self.config.thermal, backend.cancel)
                    monitor.start()
                started = time.monotonic()
                try:
                    loaded = backend.load(model)
                    if monitor and monitor.state.cancellation_requested:
                        backend.unload()
                        raise LifecycleError("model load completed after thermal cancellation; model was unloaded")
                    with self.state_lock:
                        self.backend = backend
                        self.model = model
                    return {
                        **loaded,
                        "total_load_seconds": time.monotonic() - started,
                        "memory_before": before.to_dict(),
                        "memory_after": memory_sample().to_dict(),
                        "thermal": monitor.stop().to_dict() if monitor else {},
                    }
                finally:
                    if monitor:
                        monitor.stop()

            self._run_task(request_id, operation, load_model)
            return
        if operation == "run":
            with self.state_lock:
                if self.backend is None or self.model is None:
                    raise LifecycleError("load a model before running inference")
                backend = self.backend
                model = self.model
            try:
                generation = GenerationRequest.from_payload(payload, model)
            except ValueError as exc:
                raise ProtocolError(str(exc)) from exc

            def run_generation() -> dict[str, Any]:
                monitor = ThermalMonitor(self.config.thermal, backend.cancel)
                monitor.start()
                before = memory_sample()
                started = time.monotonic()
                try:
                    result = backend.generate(generation)
                    result["total_seconds"] = time.monotonic() - started
                    result["memory_before"] = before.to_dict()
                    result["memory_after"] = memory_sample().to_dict()
                    result["thermal"] = monitor.stop().to_dict()
                    if result["thermal"].get("cancellation_requested"):
                        backend.unload()
                        with self.state_lock:
                            if self.backend is backend:
                                self.backend = None
                                self.model = None
                        result["thermal_unloaded"] = True
                        result["memory_after_thermal_unload"] = memory_sample().to_dict()
                    if result.get("cancelled") and not result["thermal"].get("cancellation_requested"):
                        result["cancel_reason"] = "user_or_timeout"
                    elif result.get("cancelled"):
                        result["cancel_reason"] = "thermal"
                    return result
                finally:
                    monitor.stop()

            self._run_task(request_id, operation, run_generation)
            return
        if operation == "cancel":
            with self.state_lock:
                if self.backend:
                    self.backend.cancel()
                cancelled = self.task is not None
            self.send(response(request_id, ok=True, result={"cancellation_requested": cancelled}))
            return
        if operation == "unload":
            with self.state_lock:
                if self.task is not None:
                    raise LifecycleError(f"cannot unload while {self.task_operation} is active; cancel it first")
                backend = self.backend
                self.backend = None
                self.model = None
            before = memory_sample()
            result = backend.unload() if backend else {"unloaded": False}
            result["memory_before"] = before.to_dict()
            result["memory_after"] = memory_sample().to_dict()
            self.send(response(request_id, ok=True, result=result))
            return
        if operation == "stop":
            with self.state_lock:
                if self.task is not None:
                    raise LifecycleError(f"cannot stop while {self.task_operation} is active; cancel it first")
                backend = self.backend
                self.backend = None
                self.model = None
                self.stopping = True
            if backend:
                backend.unload()
            self.send(response(request_id, ok=True, result={"stopped": True}))
            return
        raise ProtocolError(f"unsupported operation: {operation}")


def serve(config: AppConfig, input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout) -> int:
    runtime = WorkerRuntime(config, output_stream)
    for line in input_stream:
        if not line.strip():
            continue
        request_id = "invalid"
        try:
            value = decode(line)
            request_id = value["id"]
            request_id, operation, payload = validate_request(value)
            runtime.handle(request_id, operation, payload)
        except BaseException as exc:
            runtime.failure(request_id, exc)
        if runtime.stopping:
            return 0
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AgentWorldLab isolated worker")
    parser.add_argument("--config", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        return serve(config)
    except Exception as exc:
        print(f"worker_startup_error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
