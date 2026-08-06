"""Offline host and model metadata inspection."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any

from agentworldlab.config import ModelConfig, ThermalConfig
from agentworldlab.errors import BackendUnavailableError, ConfigurationError
from agentworldlab.metrics import host_identity, memory_sample, package_version, peak_temperature


def inspect_host(thermal: ThermalConfig) -> dict[str, Any]:
    peak, readings = peak_temperature(thermal.sensor_labels)
    return {
        "host": host_identity(),
        "memory": memory_sample().to_dict(),
        "temperature": {"control_celsius": peak, "readings": readings},
        "tools": {
            name: shutil.which(name)
            for name in ("rocminfo", "rocm-smi", "amd-smi", "sensors", "tuned-adm", "powerprofilesctl")
        },
        "packages": {
            "torch": package_version("torch"),
            "transformers": package_version("transformers"),
            "vllm": package_version("vllm"),
            "huggingface_hub": package_version("huggingface-hub"),
        },
        "notes": [
            "Tool presence does not prove that the current process can access /dev/kfd.",
            "ROCm runtime and PyTorch build compatibility require an opt-in hardware probe.",
        ],
    }


def resolve_local_snapshot(model: ModelConfig) -> Path:
    direct = Path(model.model_id)
    if direct.is_dir():
        return direct.resolve()
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise BackendUnavailableError("huggingface-hub is required to resolve a cached model snapshot") from exc
    try:
        return Path(
            snapshot_download(
                repo_id=model.model_id,
                revision=model.revision,
                local_files_only=True,
                cache_dir=str(model.cache_directory) if model.cache_directory else None,
            )
        )
    except Exception as exc:
        raise ConfigurationError(
            f"pinned snapshot is not available locally; download it explicitly before offline inspection: {exc}"
        ) from exc


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def inspect_model_metadata(model: ModelConfig) -> dict[str, Any]:
    root = resolve_local_snapshot(model)
    config = _read_json(root / "config.json") or {}
    generation = _read_json(root / "generation_config.json")
    tokenizer = _read_json(root / "tokenizer_config.json") or {}
    indexes = sorted(root.glob("*.safetensors.index.json"))
    index = _read_json(indexes[0]) if indexes else None
    files = [path for path in root.rglob("*") if path.is_file()]
    tensors = index.get("weight_map", {}) if isinstance(index, dict) else {}
    shards = sorted(set(tensors.values())) if isinstance(tensors, dict) else []
    text_config = config.get("text_config", {}) if isinstance(config.get("text_config"), dict) else {}
    return {
        "model_id": model.model_id,
        "revision": model.revision,
        "cache_directory": str(model.cache_directory) if model.cache_directory else None,
        "snapshot_path": str(root),
        "snapshot_bytes": sum(path.stat().st_size for path in files),
        "architectures": config.get("architectures"),
        "model_type": config.get("model_type"),
        "language_model_only": config.get("language_model_only"),
        "dtype": text_config.get("dtype", config.get("dtype")),
        "max_position_embeddings": text_config.get("max_position_embeddings"),
        "num_experts": text_config.get("num_experts"),
        "num_experts_per_token": text_config.get("num_experts_per_tok"),
        "tensor_count": len(tensors),
        "weight_shards": shards,
        "generation_config_present": generation is not None,
        "tokenizer_class": tokenizer.get("tokenizer_class"),
        "chat_template_present": isinstance(tokenizer.get("chat_template"), str),
        "remote_code_required_or_advertised": bool(config.get("auto_map") or tokenizer.get("auto_map")),
    }


def tokenizer_probe(model: ModelConfig, prompt: str) -> dict[str, Any]:
    try:
        from transformers import AutoProcessor
    except ImportError as exc:
        raise BackendUnavailableError("transformers is required for the tokenizer probe") from exc
    try:
        processor = AutoProcessor.from_pretrained(
            model.model_id,
            revision=model.revision,
            local_files_only=True,
            trust_remote_code=False,
            cache_dir=str(model.cache_directory) if model.cache_directory else None,
        )
        rendered = processor.apply_chat_template(
            [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            add_generation_prompt=True,
            tokenize=False,
        )
        encoded = processor(text=rendered, return_tensors=None)
    except Exception as exc:
        raise ConfigurationError(f"tokenizer-only probe failed: {type(exc).__name__}: {exc}") from exc
    input_ids = encoded.get("input_ids", [])
    if input_ids and isinstance(input_ids[0], list):
        token_count = len(input_ids[0])
    else:
        token_count = len(input_ids)
    tokenizer = getattr(processor, "tokenizer", None)
    return {
        "model_id": model.model_id,
        "revision": model.revision,
        "token_count": token_count,
        "rendered_prompt": rendered,
        "special_tokens": (
            getattr(processor, "special_tokens_map", None)
            or getattr(tokenizer, "special_tokens_map", None)
        ),
    }
