"""JSON-safe helpers for host-neutral evidence payloads."""

from __future__ import annotations

import inspect
import json
import os
import re
from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel


MAX_EVENT_PAYLOAD_BYTES = 16_384
MAX_TEXT_FIELD_LENGTH = 4_096
MAX_ARTIFACT_BYTES = 1_048_576
_SENSITIVE_KEYS = {
    "authorization", "api_key", "apikey", "access_token", "refresh_token",
    "token", "secret", "password", "client_secret", "private_key",
}
_BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|private[_-]?key|password|secret|token)\b"
    r"(\s*[:=]\s*)([^\s,;]+)"
)


def sanitize_payload(value: Any, *, max_bytes: int = MAX_EVENT_PAYLOAD_BYTES) -> Any:
    """Redact secrets and bound event payloads before durable serialization."""
    sanitized = _sanitize(value, set())
    encoded = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) <= max_bytes:
        return sanitized
    if isinstance(sanitized, dict):
        bounded = dict(sanitized)
        bounded["_evidence_truncated"] = True
        for key in sorted(bounded, key=lambda item: len(str(bounded[item])), reverse=True):
            if key == "_evidence_truncated":
                continue
            bounded[key] = "<truncated>"
            encoded = json.dumps(bounded, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if len(encoded.encode("utf-8")) <= max_bytes:
                return bounded
    return {"value": "<payload-redacted>", "_evidence_truncated": True}


def sanitize_text(value: str, *, max_bytes: int = MAX_TEXT_FIELD_LENGTH) -> str:
    """Redact credential-shaped text and enforce a UTF-8 byte bound."""

    redacted = _BEARER_TOKEN_RE.sub("Bearer <redacted>", str(value))
    redacted = _SENSITIVE_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>",
        redacted,
    )
    encoded = redacted.encode("utf-8")
    if len(encoded) <= max_bytes:
        return redacted
    marker = "<truncated>"
    budget = max(0, max_bytes - len(marker.encode("utf-8")))
    return encoded[:budget].decode("utf-8", errors="ignore") + marker


def _sanitize(value: Any, seen: set[int]) -> Any:
    if isinstance(value, BaseModel):
        return _sanitize(value.model_dump(mode="python"), seen)
    if isinstance(value, Mapping):
        marker = id(value)
        if marker in seen:
            return "<recursive:dict>"
        seen.add(marker)
        try:
            result = {}
            for key, item in value.items():
                name = str(key)
                result[name] = "<redacted>" if name.lower() in _SENSITIVE_KEYS else _sanitize(item, seen)
            return result
        finally:
            seen.discard(marker)
    if isinstance(value, (list, tuple)):
        marker = id(value)
        if marker in seen:
            return "<recursive:list>"
        seen.add(marker)
        try:
            return [_sanitize(item, seen) for item in value]
        finally:
            seen.discard(marker)
    if isinstance(value, Enum):
        return json_safe(value)
    if isinstance(value, str):
        return sanitize_text(value)
    return json_safe(value)


def json_safe(value: Any) -> Any:
    return _json_safe(value, set())


def dump_json(value: Any, *, indent: int = 2) -> str:
    return json.dumps(json_safe(value), ensure_ascii=False, indent=indent, sort_keys=True)


def _callable_summary(value: Any) -> str:
    name = getattr(value, "__name__", type(value).__name__)
    return f"<callable:{name}>"


def _json_safe(value: Any, seen: set[int]) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if inspect.ismethod(value) or inspect.isfunction(value) or callable(value):
        return _callable_summary(value)
    if isinstance(value, Enum):
        return _json_safe(value.value, seen)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    if isinstance(value, BaseModel):
        object_id = id(value)
        if object_id in seen:
            return f"<recursive:{type(value).__name__}>"
        seen.add(object_id)
        try:
            return _json_safe(value.model_dump(mode="python"), seen)
        finally:
            seen.discard(object_id)
    if isinstance(value, Mapping):
        object_id = id(value)
        if object_id in seen:
            return "<recursive:dict>"
        seen.add(object_id)
        try:
            return {str(key): _json_safe(item, seen) for key, item in value.items()}
        finally:
            seen.discard(object_id)
    if isinstance(value, (list, tuple)):
        object_id = id(value)
        if object_id in seen:
            return f"<recursive:{type(value).__name__}>"
        seen.add(object_id)
        try:
            return [_json_safe(item, seen) for item in value]
        finally:
            seen.discard(object_id)
    if isinstance(value, (set, frozenset)):
        object_id = id(value)
        if object_id in seen:
            return f"<recursive:{type(value).__name__}>"
        seen.add(object_id)
        try:
            return [_json_safe(item, seen) for item in sorted(value, key=str)]
        finally:
            seen.discard(object_id)
    return str(value)
