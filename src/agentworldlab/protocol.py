"""Versioned JSON Lines protocol with bounded messages."""

from __future__ import annotations

import json
from typing import Any
import uuid

from agentworldlab.errors import ProtocolError


PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 2 * 1024 * 1024
OPERATIONS = {"health", "load", "run", "cancel", "unload", "stop"}


def request(operation: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if operation not in OPERATIONS:
        raise ProtocolError(f"unsupported operation: {operation}")
    return {
        "version": PROTOCOL_VERSION,
        "id": uuid.uuid4().hex,
        "operation": operation,
        "payload": payload or {},
    }


def response(
    request_id: str,
    *,
    ok: bool,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "version": PROTOCOL_VERSION,
        "id": request_id,
        "ok": ok,
    }
    if ok:
        value["result"] = result or {}
    else:
        value["error"] = error or {"category": "unknown_error", "message": "unknown failure"}
    return value


def encode(message: dict[str, Any]) -> str:
    try:
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"message is not JSON serialisable: {exc}") from exc
    if len(line.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ProtocolError("message exceeds the protocol size limit")
    return line + "\n"


def decode(line: str) -> dict[str, Any]:
    if len(line.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ProtocolError("message exceeds the protocol size limit")
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"malformed JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ProtocolError("message must be a JSON object")
    if value.get("version") != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol version: {value.get('version')!r}")
    request_id = value.get("id")
    if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
        raise ProtocolError("message id must be a non-empty string of at most 128 characters")
    return value


def validate_request(value: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    request_id = value["id"]
    operation = value.get("operation")
    payload = value.get("payload", {})
    if operation not in OPERATIONS:
        raise ProtocolError(f"unsupported operation: {operation!r}")
    if not isinstance(payload, dict):
        raise ProtocolError("payload must be a JSON object")
    return request_id, operation, payload

