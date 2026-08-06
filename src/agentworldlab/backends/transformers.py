"""Direct Transformers backend for the first real compatibility probe."""

from __future__ import annotations

import gc
import threading
import time
from typing import Any

from agentworldlab.backends.base import Backend, GenerationRequest
from agentworldlab.config import ModelConfig
from agentworldlab.errors import BackendUnavailableError, GenerationError, LifecycleError, ModelLoadError


class TransformersBackend(Backend):
    def __init__(self) -> None:
        self.model_config: ModelConfig | None = None
        self.model: Any = None
        self.processor: Any = None
        self._cancel = threading.Event()
        self._torch: Any = None

    def _imports(self) -> tuple[Any, Any, Any]:
        try:
            import torch
            from transformers import AutoModelForMultimodalLM, AutoProcessor
        except (ImportError, AttributeError) as exc:
            raise BackendUnavailableError(
                "Transformers backend requires compatible torch and transformers packages"
            ) from exc
        return torch, AutoModelForMultimodalLM, AutoProcessor

    def load(self, model: ModelConfig) -> dict[str, Any]:
        if self.model is not None:
            raise LifecycleError("a model is already loaded")
        torch, model_class, processor_class = self._imports()
        if not torch.cuda.is_available():
            raise BackendUnavailableError("PyTorch does not expose the ROCm device through torch.cuda")
        dtype = getattr(torch, model.precision, None)
        if dtype is None:
            raise ModelLoadError(f"torch does not provide dtype {model.precision}")
        started = time.monotonic()
        try:
            self.processor = processor_class.from_pretrained(
                model.model_id,
                revision=model.revision,
                local_files_only=model.local_files_only,
                trust_remote_code=False,
            )
            self.model = model_class.from_pretrained(
                model.model_id,
                revision=model.revision,
                local_files_only=model.local_files_only,
                trust_remote_code=False,
                dtype=dtype,
                device_map={"": "cuda:0"},
                low_cpu_mem_usage=True,
            )
            self.model.eval()
            device_map = getattr(self.model, "hf_device_map", None)
            if isinstance(device_map, dict):
                unexpected = {
                    str(device) for device in device_map.values()
                    if device not in {0, "cuda", "cuda:0"}
                }
                if unexpected:
                    raise ModelLoadError(
                        f"unexpected CPU/disk/device offload detected in device map: {sorted(unexpected)}"
                    )
            else:
                first_device = next(self.model.parameters()).device
                if first_device.type != "cuda":
                    raise ModelLoadError(f"model loaded on unexpected device {first_device}")
        except Exception as exc:
            self.model = None
            self.processor = None
            gc.collect()
            raise ModelLoadError(f"official checkpoint load failed: {type(exc).__name__}: {exc}") from exc
        self._torch = torch
        self.model_config = model
        self._cancel.clear()
        return {
            "model_id": model.model_id,
            "revision": model.revision,
            "backend": "transformers",
            "load_seconds": time.monotonic() - started,
            "device_name": torch.cuda.get_device_name(0),
            "torch_rocm_version": getattr(torch.version, "hip", None),
            "allocated_bytes": torch.cuda.memory_allocated(0),
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(0),
        }

    def generate(self, request: GenerationRequest) -> dict[str, Any]:
        if self.model is None or self.processor is None or self.model_config is None:
            raise LifecycleError("no model is loaded")
        torch = self._torch
        self._cancel.clear()
        started = time.monotonic()
        messages = [
            {"role": "user", "content": [{"type": "text", "text": request.prompt}]}
        ]
        try:
            inputs = self.processor.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
                truncation=True,
                max_length=request.max_input_tokens,
            )
            inputs = {name: value.to("cuda:0") for name, value in inputs.items()}
            input_tokens = int(inputs["input_ids"].shape[-1])
            preprocessing_done = time.monotonic()

            cancel_event = self._cancel
            from transformers import StoppingCriteria, StoppingCriteriaList

            class Cancelled(StoppingCriteria):
                def __call__(self, input_ids: Any, scores: Any, **kwargs: Any) -> bool:
                    return cancel_event.is_set()

            class TimingStreamer:
                def __init__(self) -> None:
                    self.prompt_seen = False
                    self.first_token_at: float | None = None

                def put(self, value: Any) -> None:
                    if not self.prompt_seen:
                        self.prompt_seen = True
                    elif self.first_token_at is None:
                        self.first_token_at = time.monotonic()

                def end(self) -> None:
                    return None

            timing_streamer = TimingStreamer()

            generation_args: dict[str, Any] = {
                "max_new_tokens": request.max_output_tokens,
                "do_sample": request.temperature > 0,
                "stopping_criteria": StoppingCriteriaList([Cancelled()]),
                "use_cache": True,
                "streamer": timing_streamer,
            }
            if request.temperature > 0:
                generation_args["temperature"] = request.temperature
                generator = torch.Generator(device="cuda").manual_seed(request.seed)
                generation_args["generator"] = generator
            with torch.inference_mode():
                output_ids = self.model.generate(**inputs, **generation_args)
            generated_ids = output_ids[0, input_tokens:]
            raw_output = self.processor.decode(generated_ids, skip_special_tokens=False)
            done = time.monotonic()
            first_token = timing_streamer.first_token_at
            return {
                "raw_output": raw_output,
                "input_tokens": input_tokens,
                "output_tokens": int(generated_ids.shape[-1]),
                "cancelled": self._cancel.is_set(),
                "preprocessing_seconds": preprocessing_done - started,
                "prefill_seconds": first_token - preprocessing_done if first_token else None,
                "decode_seconds": done - first_token if first_token else None,
                "generation_seconds": done - preprocessing_done,
                "allocated_bytes": torch.cuda.memory_allocated(0),
                "peak_allocated_bytes": torch.cuda.max_memory_allocated(0),
            }
        except Exception as exc:
            raise GenerationError(f"generation failed: {type(exc).__name__}: {exc}") from exc

    def cancel(self) -> None:
        self._cancel.set()

    def unload(self) -> dict[str, Any]:
        was_loaded = self.model is not None
        self._cancel.set()
        self.model = None
        self.processor = None
        self.model_config = None
        gc.collect()
        if self._torch is not None and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()
            self._torch.cuda.synchronize()
        return {"unloaded": was_loaded}

    def health(self) -> dict[str, Any]:
        return {
            "backend": "transformers",
            "loaded": self.model is not None,
            "model_id": self.model_config.model_id if self.model_config else None,
            "revision": self.model_config.revision if self.model_config else None,
        }
