"""Versioned fixture loading and prompt rendering."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentworldlab.errors import ConfigurationError


ALLOWED_DOMAINS = {"terminal", "mcp", "swe"}


def load_fixture(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"cannot load fixture {source}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ConfigurationError("fixture must be a schema version 1 JSON object")
    if value.get("domain") not in ALLOWED_DOMAINS:
        raise ConfigurationError(f"fixture domain must be one of {sorted(ALLOWED_DOMAINS)}")
    if not isinstance(value.get("fixture_id"), str) or not value["fixture_id"]:
        raise ConfigurationError("fixture_id is required")
    if not isinstance(value.get("environment"), dict):
        raise ConfigurationError("fixture environment must be an object")
    return value


def render_prompt(fixture: dict[str, Any], action: str | None = None) -> str:
    selected_action = action if action is not None else fixture.get("action")
    if not isinstance(selected_action, str) or not selected_action.strip():
        raise ConfigurationError("a non-empty synthetic action is required")
    envelope = {
        "instruction": (
            "Predict only the next observation in this synthetic environment. "
            "Do not perform, request, or claim any host action. Return one JSON object "
            "with a string field named observation."
        ),
        "domain": fixture["domain"],
        "environment": fixture["environment"],
        "history": fixture.get("history", []),
        "proposed_action": selected_action,
    }
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True)

