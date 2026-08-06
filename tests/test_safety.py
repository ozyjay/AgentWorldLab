from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from agentworldlab.config import RuntimeConfig, ThermalConfig
from agentworldlab.errors import InsufficientMemoryError
from agentworldlab.metrics import MemorySample
from agentworldlab.safety import ThermalMonitor, require_memory_headroom


def memory(available: int) -> MemorySample:
    return MemorySample(
        system_total_bytes=128 * 1024**3,
        system_available_bytes=available,
        swap_total_bytes=0,
        swap_free_bytes=0,
        process_rss_bytes=1,
        gpu_addressable_total_bytes=120 * 1024**3,
        gpu_addressable_available_bytes=available,
        gpu_addressable_used_bytes=1,
        gpu_vram_total_bytes=512 * 1024**2,
        gpu_vram_used_bytes=1,
        gpu_gtt_total_bytes=120 * 1024**3,
        gpu_gtt_used_bytes=1,
    )


THERMAL = ThermalConfig(0.01, 80, 85, 90, 75, 0, ("fake",))


class SafetyTests(unittest.TestCase):
    def test_insufficient_memory_fails_before_load(self) -> None:
        runtime = RuntimeConfig(1, 1, 1, 1, 1, 80, 24, 4, __import__("pathlib").Path("records"))
        with patch("agentworldlab.safety.memory_sample", return_value=memory(10 * 1024**3)):
            with self.assertRaises(InsufficientMemoryError):
                require_memory_headroom(runtime)

    def test_simulated_over_temperature_requests_cancellation(self) -> None:
        cancelled: list[bool] = []
        monitor = ThermalMonitor(
            THERMAL,
            lambda: cancelled.append(True),
            sample=lambda labels: (86.0, {"fake": 86.0}),
            hard_terminate=lambda: self.fail("hard termination should not run at 86°C"),
        )
        monitor.start()
        time.sleep(0.04)
        state = monitor.stop()
        self.assertTrue(cancelled)
        self.assertTrue(state.cancellation_requested)

    def test_simulated_critical_temperature_requests_hard_stop(self) -> None:
        hard: list[bool] = []
        monitor = ThermalMonitor(
            THERMAL,
            lambda: None,
            sample=lambda labels: (90.0, {"fake": 90.0}),
            hard_terminate=lambda: hard.append(True),
        )
        monitor.start()
        time.sleep(0.04)
        state = monitor.stop()
        self.assertTrue(hard)
        self.assertTrue(state.hard_termination_requested)


if __name__ == "__main__":
    unittest.main()

