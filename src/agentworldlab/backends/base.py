"""Backend contract used by the isolated worker."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from agentworldlab.config import ModelConfig


@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    max_input_tokens: int
    max_output_tokens: int
    temperature: float = 0.0
    seed: int = 0

    @classmethod
    def from_payload(cls, payload: dict[str, Any], model: ModelConfig) -> "GenerationRequest":
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        max_input = payload.get("max_input_tokens", model.max_context_tokens)
        max_output = payload.get("max_output_tokens", model.max_output_tokens)
        temperature = payload.get("temperature", 0.0)
        seed = payload.get("seed", 0)
        if isinstance(max_input, bool) or not isinstance(max_input, int) or not 1 <= max_input <= model.max_context_tokens:
            raise ValueError(f"max_input_tokens must be between 1 and {model.max_context_tokens}")
        if isinstance(max_output, bool) or not isinstance(max_output, int) or not 1 <= max_output <= model.max_output_tokens:
            raise ValueError(f"max_output_tokens must be between 1 and {model.max_output_tokens}")
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer")
        return cls(prompt, max_input, max_output, float(temperature), seed)


class Backend(ABC):
    """One backend instance owns at most one loaded model."""

    @abstractmethod
    def load(self, model: ModelConfig) -> dict[str, Any]: ...

    @abstractmethod
    def generate(self, request: GenerationRequest) -> dict[str, Any]: ...

    @abstractmethod
    def cancel(self) -> None: ...

    @abstractmethod
    def unload(self) -> dict[str, Any]: ...

    @abstractmethod
    def health(self) -> dict[str, Any]: ...

