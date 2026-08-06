from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import time
import unittest

from agentworldlab.config import load_config
from agentworldlab.controller import WorkerClient
from agentworldlab.errors import AgentWorldLabError, RequestTimeoutError, WorkerRemoteError
from agentworldlab.fixtures import load_fixture, render_prompt


ROOT = Path(__file__).resolve().parents[1]


class WorkerLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        source = (ROOT / "configs/default.toml").read_text(encoding="utf-8")
        source = source.replace('records_directory = "records"', f'records_directory = "{self.temporary.name}"')
        path = Path(self.temporary.name) / "config.toml"
        path.write_text(source, encoding="utf-8")
        self.config = load_config(path)
        self.client = WorkerClient(self.config)
        self.client.start()
        self.addCleanup(self.client.terminate)

    def test_load_run_unload_stop(self) -> None:
        loaded = self.client.request("load", {"model": "mock"}, 2)
        self.assertEqual(loaded["backend"], "mock")
        result = self.client.request("run", {"prompt": "synthetic action"}, 2)
        self.assertIn("observation", result["raw_output"])
        self.assertTrue(self.client.request("unload", {}, 2)["unloaded"])
        self.client.stop()
        self.assertIsNone(self.client.process)

    def test_second_model_load_is_rejected(self) -> None:
        self.client.request("load", {"model": "mock"}, 2)
        with self.assertRaisesRegex(WorkerRemoteError, "already loaded"):
            self.client.request("load", {"model": "mock"}, 2)

    def test_cancel_keeps_worker_recoverable(self) -> None:
        self.client.request("load", {"model": "mock"}, 2)
        result: dict = {}

        def generate() -> None:
            result.update(self.client.request("run", {"prompt": "[MOCK:SLOW]"}, 3))

        thread = threading.Thread(target=generate)
        thread.start()
        time.sleep(0.05)
        self.assertTrue(self.client.cancel()["cancellation_requested"])
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(result["cancelled"])
        self.assertEqual(self.client.request("health", {}, 1)["state"], "loaded")

    def test_timeout_can_be_cancelled(self) -> None:
        self.client.request("load", {"model": "mock"}, 2)
        with self.assertRaises(RequestTimeoutError):
            self.client.request("run", {"prompt": "[MOCK:SLOW]"}, 0.01)
        self.client.cancel()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if self.client.request("health", {}, 1)["state"] != "busy":
                break
            time.sleep(0.01)
        self.assertEqual(self.client.request("health", {}, 1)["state"], "loaded")

    def test_model_text_is_never_executed(self) -> None:
        marker = Path(self.temporary.name) / "must-not-exist"
        self.client.request("load", {"model": "mock"}, 2)
        fixture = load_fixture(ROOT / "fixtures/terminal/single-transition-v1.json")
        hostile = render_prompt(fixture, f"touch {marker}; $(touch {marker})")
        self.client.request("run", {"prompt": hostile}, 2)
        self.assertFalse(marker.exists())

    def test_stale_pid_record_is_recovered_without_killing_a_process(self) -> None:
        self.client.stop()
        self.client.pidfile.write_text(
            '{"pid":99999999,"start_ticks":"1"}\n', encoding="utf-8"
        )
        self.client.start()
        self.assertEqual(self.client.request("health", {}, 1)["state"], "ready")

    def test_worker_crash_unblocks_pending_request(self) -> None:
        self.client.request("load", {"model": "mock"}, 2)
        failures: list[AgentWorldLabError] = []

        def generate() -> None:
            try:
                self.client.request("run", {"prompt": "[MOCK:SLOW]"}, 5)
            except AgentWorldLabError as exc:
                failures.append(exc)

        thread = threading.Thread(target=generate)
        thread.start()
        time.sleep(0.05)
        assert self.client.process is not None
        self.client.process.terminate()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(failures)
        self.assertEqual(failures[0].details()["category"], "worker_crash")


if __name__ == "__main__":
    unittest.main()
