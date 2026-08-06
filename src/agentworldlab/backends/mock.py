"""Deterministic backend for lifecycle and safety tests."""

from __future__ import annotations

import json
import threading
from typing import Any

from agentworldlab.backends.base import Backend, GenerationRequest
from agentworldlab.config import ModelConfig
from agentworldlab.errors import LifecycleError


class MockBackend(Backend):
    def __init__(self) -> None:
        self.model: ModelConfig | None = None
        self._cancel = threading.Event()

    def load(self, model: ModelConfig) -> dict[str, Any]:
        if self.model is not None:
            raise LifecycleError("a model is already loaded")
        self.model = model
        self._cancel.clear()
        return {"model_id": model.model_id, "revision": model.revision, "backend": "mock"}

    def generate(self, request: GenerationRequest) -> dict[str, Any]:
        if self.model is None:
            raise LifecycleError("no model is loaded")
        self._cancel.clear()
        # Test-only delay is part of the prompt contract and never executes anything.
        if "[MOCK:SLOW]" in request.prompt:
            for _ in range(200):
                if self._cancel.wait(0.01):
                    return {"raw_output": "", "input_tokens": 0, "output_tokens": 0, "cancelled": True}
        try:
            envelope = json.loads(request.prompt)
            action = str(envelope.get("proposed_action", "action"))
            facts = envelope.get("environment", {}).get("facts", [])
            fact_text = "; ".join(str(fact) for fact in facts)
        except (json.JSONDecodeError, AttributeError):
            action = "action"
            fact_text = ""
        observation = f"simulated: {action}: accepted"
        if fact_text:
            observation += f"; {fact_text}"
        observation += "; no host operation was performed"
        output = json.dumps({"observation": observation}, separators=(",", ":"))
        return {
            "raw_output": output,
            "input_tokens": min(len(request.prompt.split()), request.max_input_tokens),
            "output_tokens": min(len(output.split()), request.max_output_tokens),
            "cancelled": False,
            "preprocessing_seconds": 0.0,
            "prefill_seconds": 0.0,
            "decode_seconds": 0.0,
            "generation_seconds": 0.0,
        }

    def cancel(self) -> None:
        self._cancel.set()

    def unload(self) -> dict[str, Any]:
        was_loaded = self.model is not None
        self.model = None
        self._cancel.set()
        return {"unloaded": was_loaded}

    def health(self) -> dict[str, Any]:
        return {
            "backend": "mock",
            "loaded": self.model is not None,
            "model_id": self.model.model_id if self.model else None,
            "revision": self.model.revision if self.model else None,
        }
