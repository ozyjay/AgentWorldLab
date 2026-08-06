from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from agentworldlab.config import ModelConfig
from agentworldlab.fixtures import load_fixture, render_prompt
from agentworldlab.evaluation import evaluate_transition
from agentworldlab.records import new_record, parse_observation, write_record


ROOT = Path(__file__).resolve().parents[1]


class FixtureAndRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = load_fixture(ROOT / "fixtures/terminal/single-transition-v1.json")
        self.model = ModelConfig(
            name="mock",
            model_id="local/mock",
            revision="0" * 40,
            precision="bfloat16",
            backend="mock",
            local_files_only=True,
            trust_remote_code=False,
            max_context_tokens=2048,
            max_output_tokens=64,
            transformers_probe_passed=False,
        )

    def test_rendered_prompt_is_explicitly_synthetic(self) -> None:
        prompt = render_prompt(self.fixture)
        self.assertIn("synthetic", prompt)
        self.assertIn("Do not perform", prompt)

    def test_observation_parser_requires_expected_shape(self) -> None:
        self.assertEqual(parse_observation('{"observation":"ok"}'), {"observation": "ok"})
        self.assertEqual(
            parse_observation('<think>synthetic reasoning</think>\n{"observation":"ok"}<|im_end|>'),
            {"observation": "ok"},
        )
        self.assertIsNone(parse_observation('{"answer":"ok"}'))
        self.assertIsNone(parse_observation("not json"))

    def test_automated_evaluation_reports_missing_fixture_fact(self) -> None:
        result = evaluate_transition(self.fixture, '{"observation":"directory created"}')
        self.assertFalse(result["automated_pass"])
        self.assertFalse(result["automated_checks"]["required_facts_preserved"])

    def test_record_writes_json_and_human_summary(self) -> None:
        record = new_record(model=self.model, fixture=self.fixture, cold_run=True)
        record["outcome"]["completion_status"] = "completed"
        with tempfile.TemporaryDirectory() as directory:
            json_path, markdown_path = write_record(record, Path(directory))
            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["schema_version"], 1)
            self.assertIn("Status: completed", markdown_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
