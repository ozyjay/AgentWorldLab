"""Strict TOML configuration loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib
from typing import Any

from agentworldlab.errors import ConfigurationError


REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SUPPORTED_BACKENDS = {"mock", "transformers", "vllm"}


def _number(data: dict[str, Any], name: str, *, minimum: float) -> float:
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
        raise ConfigurationError(f"{name} must be a number greater than or equal to {minimum}")
    return float(value)


def _integer(data: dict[str, Any], name: str, *, minimum: int) -> int:
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigurationError(f"{name} must be an integer greater than or equal to {minimum}")
    return value


@dataclass(frozen=True)
class ModelConfig:
    name: str
    model_id: str
    revision: str
    precision: str
    backend: str
    local_files_only: bool
    trust_remote_code: bool
    max_context_tokens: int
    max_output_tokens: int
    transformers_probe_passed: bool
    cache_directory: Path | None = None

    @classmethod
    def from_mapping(cls, name: str, data: dict[str, Any], base: Path | None = None) -> "ModelConfig":
        model_id = data.get("model_id")
        revision = data.get("revision")
        backend = data.get("backend")
        precision = data.get("precision")
        if not isinstance(model_id, str) or "/" not in model_id:
            raise ConfigurationError(f"models.{name}.model_id must be an allowlisted owner/name")
        if not isinstance(revision, str) or not REVISION_RE.fullmatch(revision):
            raise ConfigurationError(f"models.{name}.revision must be a pinned 40-character commit hash")
        if backend not in SUPPORTED_BACKENDS:
            raise ConfigurationError(f"models.{name}.backend must be one of {sorted(SUPPORTED_BACKENDS)}")
        if precision not in {"bfloat16", "float16", "float32"}:
            raise ConfigurationError(f"models.{name}.precision is unsupported")
        local_files_only = data.get("local_files_only", True)
        trust_remote_code = data.get("trust_remote_code", False)
        probe_passed = data.get("transformers_probe_passed", False)
        cache_value = data.get("cache_directory")
        if not all(isinstance(value, bool) for value in (local_files_only, trust_remote_code, probe_passed)):
            raise ConfigurationError(f"models.{name} boolean settings must be true or false")
        if not local_files_only:
            raise ConfigurationError("worker model access must remain offline (local_files_only = true)")
        if trust_remote_code:
            raise ConfigurationError("remote model code is prohibited by the initial safety policy")
        if backend == "vllm" and not probe_passed:
            raise ConfigurationError("vLLM requires an explicitly recorded successful Transformers probe")
        cache_directory: Path | None = None
        if cache_value is not None:
            if not isinstance(cache_value, str) or not cache_value.strip():
                raise ConfigurationError(f"models.{name}.cache_directory must be a non-empty path")
            cache_directory = Path(cache_value)
            if not cache_directory.is_absolute():
                cache_directory = ((base or Path.cwd()) / cache_directory).resolve()
        return cls(
            name=name,
            model_id=model_id,
            revision=revision,
            precision=precision,
            backend=backend,
            local_files_only=local_files_only,
            trust_remote_code=trust_remote_code,
            max_context_tokens=_integer(data, "max_context_tokens", minimum=128),
            max_output_tokens=_integer(data, "max_output_tokens", minimum=1),
            transformers_probe_passed=probe_passed,
            cache_directory=cache_directory,
        )


@dataclass(frozen=True)
class RuntimeConfig:
    request_timeout_seconds: float
    load_timeout_seconds: float
    generation_timeout_seconds: float
    unload_timeout_seconds: float
    stop_timeout_seconds: float
    minimum_available_memory_gib: float
    minimum_memory_headroom_gib: float
    memory_recovery_tolerance_gib: float
    records_directory: Path

    @classmethod
    def from_mapping(cls, data: dict[str, Any], base: Path) -> "RuntimeConfig":
        records = data.get("records_directory", "records")
        if not isinstance(records, str) or not records:
            raise ConfigurationError("runtime.records_directory must be a path")
        records_path = Path(records)
        if not records_path.is_absolute():
            records_path = (base / records_path).resolve()
        return cls(
            request_timeout_seconds=_number(data, "request_timeout_seconds", minimum=0.1),
            load_timeout_seconds=_number(data, "load_timeout_seconds", minimum=1),
            generation_timeout_seconds=_number(data, "generation_timeout_seconds", minimum=1),
            unload_timeout_seconds=_number(data, "unload_timeout_seconds", minimum=1),
            stop_timeout_seconds=_number(data, "stop_timeout_seconds", minimum=0.1),
            minimum_available_memory_gib=_number(data, "minimum_available_memory_gib", minimum=1),
            minimum_memory_headroom_gib=_number(data, "minimum_memory_headroom_gib", minimum=1),
            memory_recovery_tolerance_gib=_number(data, "memory_recovery_tolerance_gib", minimum=0),
            records_directory=records_path,
        )


@dataclass(frozen=True)
class ThermalConfig:
    sample_interval_seconds: float
    caution_celsius: float
    cancel_celsius: float
    terminate_celsius: float
    cooldown_celsius: float
    cooldown_seconds: float
    sensor_labels: tuple[str, ...]

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "ThermalConfig":
        caution = _number(data, "caution_celsius", minimum=1)
        cancel = _number(data, "cancel_celsius", minimum=1)
        terminate = _number(data, "terminate_celsius", minimum=1)
        cooldown = _number(data, "cooldown_celsius", minimum=1)
        if not cooldown < caution < cancel < terminate:
            raise ConfigurationError("thermal thresholds must satisfy cooldown < caution < cancel < terminate")
        labels = data.get("sensor_labels", ["Tctl", "cpu@4c", "edge"])
        if not isinstance(labels, list) or not labels or not all(isinstance(item, str) and item for item in labels):
            raise ConfigurationError("thermal.sensor_labels must be a non-empty list of names")
        return cls(
            sample_interval_seconds=_number(data, "sample_interval_seconds", minimum=0.1),
            caution_celsius=caution,
            cancel_celsius=cancel,
            terminate_celsius=terminate,
            cooldown_celsius=cooldown,
            cooldown_seconds=_number(data, "cooldown_seconds", minimum=0),
            sensor_labels=tuple(labels),
        )


@dataclass(frozen=True)
class AppConfig:
    models: dict[str, ModelConfig]
    runtime: RuntimeConfig
    thermal: ThermalConfig
    source: Path

    def model(self, name: str) -> ModelConfig:
        try:
            return self.models[name]
        except KeyError as exc:
            raise ConfigurationError(f"model {name!r} is not allowlisted") from exc


def load_config(path: str | Path) -> AppConfig:
    source = Path(path).resolve()
    try:
        data = tomllib.loads(source.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationError(f"cannot read configuration {source}: {exc}") from exc
    model_data = data.get("models")
    if not isinstance(model_data, dict) or not model_data:
        raise ConfigurationError("at least one model must be allowlisted")
    models = {
        name: ModelConfig.from_mapping(name, values, source.parent.parent)
        for name, values in model_data.items()
        if isinstance(name, str) and isinstance(values, dict)
    }
    if len(models) != len(model_data):
        raise ConfigurationError("every models entry must be a table")
    runtime_data = data.get("runtime")
    thermal_data = data.get("thermal")
    if not isinstance(runtime_data, dict) or not isinstance(thermal_data, dict):
        raise ConfigurationError("runtime and thermal tables are required")
    return AppConfig(
        models=models,
        runtime=RuntimeConfig.from_mapping(runtime_data, source.parent.parent),
        thermal=ThermalConfig.from_mapping(thermal_data),
        source=source,
    )
