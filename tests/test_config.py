from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from agentworldlab.config import load_config
from agentworldlab.errors import ConfigurationError


VALID = """
[models.test]
model_id = "owner/model"
revision = "1111111111111111111111111111111111111111"
precision = "bfloat16"
backend = "mock"
local_files_only = true
trust_remote_code = false
max_context_tokens = 2048
max_output_tokens = 64
transformers_probe_passed = false

[runtime]
request_timeout_seconds = 1
load_timeout_seconds = 2
generation_timeout_seconds = 2
unload_timeout_seconds = 2
stop_timeout_seconds = 1
minimum_available_memory_gib = 1
minimum_memory_headroom_gib = 1
memory_recovery_tolerance_gib = 1
records_directory = "records"

[thermal]
sample_interval_seconds = 0.1
caution_celsius = 80
cancel_celsius = 85
terminate_celsius = 90
cooldown_celsius = 75
cooldown_seconds = 0
sensor_labels = ["Tctl"]
"""


class ConfigTests(unittest.TestCase):
    def load(self, text: str):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "configs" / "test.toml"
        path.parent.mkdir()
        path.write_text(text, encoding="utf-8")
        return load_config(path)

    def test_valid_config_and_allowlist(self) -> None:
        config = self.load(VALID)
        self.assertEqual(config.model("test").model_id, "owner/model")
        with self.assertRaisesRegex(ConfigurationError, "not allowlisted"):
            config.model("missing")

    def test_revision_must_be_pinned(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "40-character"):
            self.load(VALID.replace("1" * 40, "main"))

    def test_remote_code_is_prohibited(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "remote model code"):
            self.load(VALID.replace("trust_remote_code = false", "trust_remote_code = true"))

    def test_worker_model_access_is_offline(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "offline"):
            self.load(VALID.replace("local_files_only = true", "local_files_only = false"))

    def test_vllm_is_gated_by_transformers_probe(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "Transformers probe"):
            self.load(VALID.replace('backend = "mock"', 'backend = "vllm"'))

    def test_thermal_threshold_order_is_strict(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "thresholds"):
            self.load(VALID.replace("cancel_celsius = 85", "cancel_celsius = 79"))


if __name__ == "__main__":
    unittest.main()
