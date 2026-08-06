"""Pre-load memory checks and continuous thermal policy enforcement."""

from __future__ import annotations

from dataclasses import dataclass
import os
import threading
import time
from typing import Callable

from agentworldlab.config import RuntimeConfig, ThermalConfig
from agentworldlab.errors import InsufficientMemoryError, ThermalLimitError
from agentworldlab.metrics import GIB, MemorySample, memory_sample, peak_temperature


def require_memory_headroom(runtime: RuntimeConfig) -> MemorySample:
    sample = memory_sample()
    available = sample.system_available_bytes
    if available is None:
        raise InsufficientMemoryError("system available memory could not be measured")
    required_gib = runtime.minimum_available_memory_gib + runtime.minimum_memory_headroom_gib
    if available < required_gib * GIB:
        raise InsufficientMemoryError(
            f"available memory is {available / GIB:.1f} GiB; at least {required_gib:.1f} GiB is required"
        )
    return sample


@dataclass
class ThermalState:
    peak_celsius: float | None = None
    cancellation_requested: bool = False
    hard_termination_requested: bool = False
    telemetry_available: bool = False
    caution_observed: bool = False
    last_readings: dict[str, float] | None = None
    minimum_system_available_bytes: int | None = None
    maximum_gpu_used_bytes: int | None = None
    maximum_process_rss_bytes: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "peak_celsius": self.peak_celsius,
            "cancellation_requested": self.cancellation_requested,
            "hard_termination_requested": self.hard_termination_requested,
            "telemetry_available": self.telemetry_available,
            "caution_observed": self.caution_observed,
            "last_readings": self.last_readings or {},
            "minimum_system_available_bytes": self.minimum_system_available_bytes,
            "maximum_gpu_used_bytes": self.maximum_gpu_used_bytes,
            "maximum_process_rss_bytes": self.maximum_process_rss_bytes,
        }


class ThermalMonitor:
    def __init__(
        self,
        config: ThermalConfig,
        cancel: Callable[[], None],
        *,
        sample: Callable[[tuple[str, ...]], tuple[float | None, dict[str, float]]] = peak_temperature,
        hard_terminate: Callable[[], None] | None = None,
    ) -> None:
        self.config = config
        self.cancel = cancel
        self.sample = sample
        self.hard_terminate = hard_terminate or (lambda: os._exit(90))
        self.state = ThermalState()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="thermal-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> ThermalState:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=max(1.0, self.config.sample_interval_seconds * 2))
        return self.state

    def _loop(self) -> None:
        while not self._stop.is_set():
            value, readings = self.sample(self.config.sensor_labels)
            memory = memory_sample()
            if memory.system_available_bytes is not None:
                current = self.state.minimum_system_available_bytes
                self.state.minimum_system_available_bytes = (
                    memory.system_available_bytes if current is None else min(current, memory.system_available_bytes)
                )
            if memory.gpu_addressable_used_bytes is not None:
                current = self.state.maximum_gpu_used_bytes
                self.state.maximum_gpu_used_bytes = (
                    memory.gpu_addressable_used_bytes
                    if current is None
                    else max(current, memory.gpu_addressable_used_bytes)
                )
            if memory.process_rss_bytes is not None:
                current = self.state.maximum_process_rss_bytes
                self.state.maximum_process_rss_bytes = (
                    memory.process_rss_bytes if current is None else max(current, memory.process_rss_bytes)
                )
            self.state.last_readings = readings
            if value is not None:
                self.state.telemetry_available = True
                if self.state.peak_celsius is None or value > self.state.peak_celsius:
                    self.state.peak_celsius = value
                if value >= self.config.caution_celsius:
                    self.state.caution_observed = True
                if value >= self.config.terminate_celsius:
                    self.state.hard_termination_requested = True
                    self.cancel()
                    self.hard_terminate()
                    return
                if value > self.config.cancel_celsius:
                    self.state.cancellation_requested = True
                    self.cancel()
            self._stop.wait(self.config.sample_interval_seconds)


def require_safe_start(thermal: ThermalConfig) -> float:
    value, _ = peak_temperature(thermal.sensor_labels)
    if value is None:
        raise ThermalLimitError("no allowlisted temperature sensor is readable")
    if value >= thermal.cancel_celsius:
        raise ThermalLimitError(f"pre-load temperature {value:.1f}°C is not below {thermal.cancel_celsius:.1f}°C")
    return value


def wait_for_cooldown(thermal: ThermalConfig) -> bool:
    if thermal.cooldown_seconds <= 0:
        return True
    deadline = time.monotonic() + thermal.cooldown_seconds
    while time.monotonic() < deadline:
        value, _ = peak_temperature(thermal.sensor_labels)
        if value is None or value > thermal.cooldown_celsius:
            return False
        time.sleep(min(thermal.sample_interval_seconds, max(0.0, deadline - time.monotonic())))
    return True
