"""Response extraction and terminal sanitization (pure functions)."""

from __future__ import annotations

import re
from typing import Any

_ANSI_ESCAPE = re.compile(r"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~])")
_BIDI_OR_INVISIBLE = frozenset(
    {
        "\u061c", "\u200b", "\u200c", "\u200d", "\u200e", "\u200f",
        "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
        "\u2066", "\u2067", "\u2068", "\u2069", "\ufeff",
    }
)
_MAX_RESPONSE_CHARS = 6000


def response_text_from_payload(value: Any, *, depth: int = 0) -> str:
    """Extract the first bounded textual leaf from a Pi model-response record."""
    if depth > 5:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "content", "message"):
            if key in value:
                text = response_text_from_payload(value[key], depth=depth + 1)
                if text:
                    return text
        for item in value.values():
            text = response_text_from_payload(item, depth=depth + 1)
            if text:
                return text
    if isinstance(value, list):
        for item in value:
            text = response_text_from_payload(item, depth=depth + 1)
            if text:
                return text
    return ""


def assistant_text_from_payload(payload: Any) -> str:
    """Extract the assistant's visible text from one Pi message_end record.

    Pi emits message_end for user and assistant messages alike; only an
    assistant message with a non-error stopReason carries a model response.
    """
    if not isinstance(payload, dict):
        return ""
    message = payload.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return ""
    if str(message.get("stopReason") or "") == "error":
        return ""
    parts: list[str] = []
    content = message.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                parts.append(str(item["text"]))
    elif isinstance(content, str) and content.strip():
        parts.append(content)
    return "\n".join(parts).strip()


def sanitize_terminal_text(value: str) -> str:
    """Strip ANSI escapes and bidi/invisible characters; bound the length."""
    without_ansi = _ANSI_ESCAPE.sub("", str(value))
    cleaned = "".join(
        character
        for character in without_ansi
        if character not in _BIDI_OR_INVISIBLE
        and (character in {"\n", "\t"} or ord(character) >= 32)
    )
    return cleaned[:_MAX_RESPONSE_CHARS]
