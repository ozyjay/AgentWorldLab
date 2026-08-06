"""Structured errors shared across the controller and worker."""

from __future__ import annotations


class AgentWorldLabError(Exception):
    category = "internal_error"

    def details(self) -> dict[str, str]:
        return {"category": self.category, "message": str(self)}


class ConfigurationError(AgentWorldLabError):
    category = "configuration_error"


class ProtocolError(AgentWorldLabError):
    category = "protocol_error"


class LifecycleError(AgentWorldLabError):
    category = "lifecycle_error"


class BackendUnavailableError(AgentWorldLabError):
    category = "backend_unavailable"


class ModelLoadError(AgentWorldLabError):
    category = "model_load_error"


class GenerationError(AgentWorldLabError):
    category = "generation_error"


class SafetyError(AgentWorldLabError):
    category = "safety_error"


class InsufficientMemoryError(SafetyError):
    category = "insufficient_memory"


class ThermalLimitError(SafetyError):
    category = "thermal_limit"


class RequestTimeoutError(AgentWorldLabError):
    category = "timeout"


class WorkerRemoteError(AgentWorldLabError):
    category = "worker_error"

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.remote_category = category

    def details(self) -> dict[str, str]:
        return {"category": self.remote_category, "message": str(self)}
