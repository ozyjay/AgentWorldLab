"""Machine-readable experiment records and concise Markdown summaries."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import uuid

from agentworldlab.config import ModelConfig
from agentworldlab.metrics import host_identity, package_version


SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_observation(raw: str) -> dict[str, Any] | None:
    if not isinstance(raw, str):
        return None
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for index, character in enumerate(raw):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("observation"), str):
            candidates.append(value)
    if candidates:
        return candidates[-1]
    return None


def new_record(
    *,
    model: ModelConfig,
    fixture: dict[str, Any],
    cold_run: bool,
) -> dict[str, Any]:
    identity = host_identity()
    return {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": uuid.uuid4().hex,
        "started_at": utc_now(),
        "finished_at": None,
        "host": identity,
        "software": {
            "torch_version": package_version("torch"),
            "transformers_version": package_version("transformers"),
            "vllm_version": package_version("vllm"),
        },
        "model": {
            "backend": model.backend,
            "model_id": model.model_id,
            "revision": model.revision,
            "precision": model.precision,
            "quantisation": None,
        },
        "fixture": {
            "fixture_id": fixture["fixture_id"],
            "schema_version": fixture["schema_version"],
            "domain": fixture["domain"],
        },
        "run": {
            "cold_run": cold_run,
            "context_limit": model.max_context_tokens,
            "output_token_limit": model.max_output_tokens,
            "input_tokens": None,
            "generated_tokens": None,
            "load_seconds": None,
            "tokenizer_preprocessing_seconds": None,
            "prompt_prefill_seconds": None,
            "text_generation_seconds": None,
            "total_seconds": None,
            "tokens_per_second": None,
        },
        "memory": {
            "initial": None,
            "peak": None,
            "after_unload": None,
            "recovered_within_tolerance": None,
        },
        "thermal": {
            "peak_celsius": None,
            "caution_observed": False,
            "cancelled": False,
            "hard_termination": False,
            "telemetry_available": False,
        },
        "outcome": {
            "completion_status": "running",
            "timeout": False,
            "error_category": None,
            "error_message": None,
            "raw_output": None,
            "parsed_observation": None,
        },
        "evaluation": {
            "automated_checks": {},
            "automated_pass": None,
            "manual_review": {},
        },
    }


def write_record(record: dict[str, Any], directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    record["finished_at"] = record.get("finished_at") or utc_now()
    identifier = record["experiment_id"]
    json_path = directory / f"{identifier}.json"
    markdown_path = directory / f"{identifier}.md"
    json_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    outcome = record["outcome"]
    run = record["run"]
    thermal = record["thermal"]
    summary = (
        f"# Experiment {identifier}\n\n"
        f"- Status: {outcome['completion_status']}\n"
        f"- Model: `{record['model']['model_id']}` at `{record['model']['revision']}`\n"
        f"- Backend: `{record['model']['backend']}`\n"
        f"- Fixture: `{record['fixture']['fixture_id']}`\n"
        f"- Input/output tokens: {run['input_tokens']} / {run['generated_tokens']}\n"
        f"- Total time: {run['total_seconds']} seconds\n"
        f"- Peak temperature: {thermal['peak_celsius']}°C\n"
        f"- Error: {outcome['error_category'] or 'none'}\n"
    )
    markdown_path.write_text(summary, encoding="utf-8")
    return json_path, markdown_path
