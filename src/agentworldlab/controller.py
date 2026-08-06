"""Responsive controller for the isolated worker process."""

from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
from typing import Any

from agentworldlab.config import AppConfig
from agentworldlab.errors import LifecycleError, ProtocolError, RequestTimeoutError, WorkerRemoteError
from agentworldlab.protocol import decode, encode, request


def _process_start_ticks(pid: int) -> str | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
        return fields[21]
    except (OSError, IndexError):
        return None


class WorkerClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.process: subprocess.Popen[str] | None = None
        self.pending: dict[str, queue.Queue[dict[str, Any]]] = {}
        self.pending_lock = threading.Lock()
        self.stderr_lines: deque[str] = deque(maxlen=100)
        self.reader: threading.Thread | None = None
        self.stderr_reader: threading.Thread | None = None
        self.pidfile = config.runtime.records_directory / ".worker.pid"

    def _check_stale_process(self) -> None:
        try:
            value = json.loads(self.pidfile.read_text(encoding="utf-8"))
            pid = int(value["pid"])
            ticks = str(value["start_ticks"])
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            self.pidfile.unlink(missing_ok=True)
            return
        if _process_start_ticks(pid) == ticks:
            try:
                command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            except OSError:
                command = ""
            if "agentworldlab.worker" in command:
                raise LifecycleError(f"worker process {pid} is already active")
        self.pidfile.unlink(missing_ok=True)

    def start(self) -> None:
        if self.process is not None:
            raise LifecycleError("worker has already been started")
        self.config.runtime.records_directory.mkdir(parents=True, exist_ok=True)
        self._check_stale_process()
        command = [sys.executable, "-m", "agentworldlab.worker", "--config", str(self.config.source)]
        environment = os.environ.copy()
        environment["HF_HUB_OFFLINE"] = "1"
        environment["TRANSFORMERS_OFFLINE"] = "1"
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            shell=False,
            close_fds=True,
            env=environment,
        )
        ticks = _process_start_ticks(self.process.pid)
        self.pidfile.write_text(
            json.dumps({"pid": self.process.pid, "start_ticks": ticks}) + "\n", encoding="utf-8"
        )
        self.reader = threading.Thread(target=self._read_stdout, name="worker-stdout", daemon=True)
        self.stderr_reader = threading.Thread(target=self._read_stderr, name="worker-stderr", daemon=True)
        self.reader.start()
        self.stderr_reader.start()

    def _read_stdout(self) -> None:
        assert self.process and self.process.stdout
        for line in self.process.stdout:
            try:
                value = decode(line)
                if not isinstance(value.get("ok"), bool):
                    raise ProtocolError("worker response is missing ok")
                request_id = value["id"]
                with self.pending_lock:
                    destination = self.pending.get(request_id)
                if destination:
                    destination.put(value)
            except ProtocolError as exc:
                self.stderr_lines.append(f"malformed worker response: {exc}")
        return_code = None
        if self.process:
            try:
                return_code = self.process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                return_code = self.process.poll()
        hard_thermal_stop = return_code == 90
        error = {
            "version": 1,
            "id": "worker-exit",
            "ok": False,
            "error": {
                "category": "thermal_hard_stop" if hard_thermal_stop else "worker_crash",
                "message": (
                    "worker terminated at the hard thermal threshold"
                    if hard_thermal_stop
                    else "worker stdout closed before the request completed"
                ),
            },
        }
        with self.pending_lock:
            destinations = list(self.pending.values())
        for destination in destinations:
            try:
                destination.put_nowait(error)
            except queue.Full:
                pass

    def _read_stderr(self) -> None:
        assert self.process and self.process.stderr
        for line in self.process.stderr:
            self.stderr_lines.append(line.rstrip())

    def request(self, operation: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
        if self.process is None or self.process.poll() is not None:
            details = "; ".join(self.stderr_lines)
            raise LifecycleError(f"worker is not running{': ' + details if details else ''}")
        message = request(operation, payload)
        destination: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self.pending_lock:
            self.pending[message["id"]] = destination
        try:
            assert self.process.stdin
            self.process.stdin.write(encode(message))
            self.process.stdin.flush()
            try:
                reply = destination.get(timeout=timeout)
            except queue.Empty as exc:
                raise RequestTimeoutError(f"{operation} exceeded {timeout:.1f} seconds") from exc
        finally:
            with self.pending_lock:
                self.pending.pop(message["id"], None)
        if not reply["ok"]:
            error = reply.get("error", {})
            raise WorkerRemoteError(
                str(error.get("category", "worker_error")),
                str(error.get("message", "unknown failure")),
            )
        result = reply.get("result")
        if not isinstance(result, dict):
            raise ProtocolError("worker result must be a JSON object")
        return result

    def cancel(self) -> dict[str, Any]:
        return self.request("cancel", {}, self.config.runtime.request_timeout_seconds)

    def terminate(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=self.config.runtime.stop_timeout_seconds)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=self.config.runtime.stop_timeout_seconds)
        self._cleanup()

    def stop(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            try:
                self.request("stop", {}, self.config.runtime.stop_timeout_seconds)
                self.process.wait(timeout=self.config.runtime.stop_timeout_seconds)
            except (LifecycleError, RequestTimeoutError, subprocess.TimeoutExpired):
                self.terminate()
                return
        self._cleanup()

    def _cleanup(self) -> None:
        if self.process:
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                if stream:
                    stream.close()
        self.pidfile.unlink(missing_ok=True)
        self.process = None

    def __enter__(self) -> "WorkerClient":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.stop()
