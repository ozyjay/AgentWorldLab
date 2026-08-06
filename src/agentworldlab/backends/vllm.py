"""Explicit vLLM ROCm backend, gated on a recorded Transformers probe."""

from __future__ import annotations

import gc
import threading
import time
from typing import Any

from agentworldlab.backends.base import Backend, GenerationRequest
from agentworldlab.config import ModelConfig
from agentworldlab.errors import BackendUnavailableError, GenerationError, LifecycleError, ModelLoadError


class VllmBackend(Backend):
    def __init__(self) -> None:
        self.engine: Any = None
        self.model_config: ModelConfig | None = None
        self._cancel = threading.Event()

    def load(self, model: ModelConfig) -> dict[str, Any]:
        if not model.transformers_probe_passed:
            raise ModelLoadError("vLLM is gated until the Transformers compatibility probe passes")
        if self.engine is not None:
            raise LifecycleError("a model is already loaded")
        try:
            from vllm import LLM
        except ImportError as exc:
            raise BackendUnavailableError("vLLM is not installed in the worker environment") from exc
        started = time.monotonic()
        try:
            # These flags are deliberately conservative and must be verified against
            # the installed vLLM version before a hardware run.
            self.engine = LLM(
                model=model.model_id,
                revision=model.revision,
                runner="generate",
                dtype=model.precision,
                max_model_len=model.max_context_tokens,
                tensor_parallel_size=1,
                enforce_eager=True,
                trust_remote_code=False,
                cpu_offload_gb=0,
                language_model_only=True,
                download_dir=str(model.cache_directory) if model.cache_directory else None,
            )
        except Exception as exc:
            self.engine = None
            raise ModelLoadError(f"vLLM checkpoint load failed: {type(exc).__name__}: {exc}") from exc
        self.model_config = model
        return {
            "model_id": model.model_id,
            "revision": model.revision,
            "backend": "vllm",
            "load_seconds": time.monotonic() - started,
        }

    def generate(self, request: GenerationRequest) -> dict[str, Any]:
        if self.engine is None:
            raise LifecycleError("no model is loaded")
        try:
            from vllm import SamplingParams

            started = time.monotonic()
            params = SamplingParams(
                max_tokens=request.max_output_tokens,
                temperature=request.temperature,
                seed=request.seed,
            )
            outputs = self.engine.generate([request.prompt], params, use_tqdm=False)
            text = outputs[0].outputs[0].text
            token_ids = outputs[0].outputs[0].token_ids
            return {
                "raw_output": text,
                "input_tokens": len(outputs[0].prompt_token_ids),
                "output_tokens": len(token_ids),
                "cancelled": self._cancel.is_set(),
                "preprocessing_seconds": None,
                "prefill_seconds": None,
                "decode_seconds": None,
                "generation_seconds": time.monotonic() - started,
            }
        except Exception as exc:
            raise GenerationError(f"vLLM generation failed: {type(exc).__name__}: {exc}") from exc

    def cancel(self) -> None:
        # The synchronous vLLM API cannot guarantee in-process cancellation.
        # The controller timeout therefore terminates the isolated worker.
        self._cancel.set()

    def unload(self) -> dict[str, Any]:
        was_loaded = self.engine is not None
        self.engine = None
        self.model_config = None
        self._cancel.set()
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        return {"unloaded": was_loaded}

    def health(self) -> dict[str, Any]:
        return {
            "backend": "vllm",
            "loaded": self.engine is not None,
            "model_id": self.model_config.model_id if self.model_config else None,
            "revision": self.model_config.revision if self.model_config else None,
            "cancellation_mode": "worker_termination",
        }


def create_backend(name: str) -> Backend:
    if name == "mock":
        from agentworldlab.backends.mock import MockBackend

        return MockBackend()
    if name == "transformers":
        from agentworldlab.backends.transformers import TransformersBackend

        return TransformersBackend()
    if name == "vllm":
        return VllmBackend()
    raise BackendUnavailableError(f"unsupported backend: {name}")
