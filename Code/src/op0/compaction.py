"""Compaction: ledger -> model context projection under a token budget.

The ledger is the base table (append-only, never rewritten); the model
context is a materialized view; this module owns the projection rules and
the budget trigger. All transforms are deterministic and monotonic, so a
folded conversation re-materializes identically after any crash. Oversized
tool results live in .openpilot/observations/ (file system as overflow
memory); the context only carries a retrieval pointer.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from op0.response import assistant_text_from_payload

_OBS_INLINE_BYTES = 8_192   # E1: results above this never reach Pi memory
_OBS_MASK_BYTES = 4_096     # folded results above this gain a retrieval pointer
_SNIP_INLINE_BYTES = 1_024  # folded results above this stay inline, snipped
_SNIP_HEAD = 200
_SNIP_TAIL = 400
_REPLY_SNIP_CHARS = 2_048   # folded assistant replies above this get snipped
_OBS_FETCH_BYTES = 65_536   # openpilot_obs retrieval bound (matches sidecar)
_TRIGGER_RATIO = 0.70
_RECENT_TURNS = 2
_OBS_ID = re.compile(r"^[0-9a-f][0-9a-f-]{7,63}$")
_TOMBSTONE_TAIL = 400


def estimate_usage(events: list) -> int:
    """Real provider usage summed over turn-end records (usage lives in the
    message envelope as `input`, not on message_end); falls back to a rough
    character estimate when no usage was recorded."""
    real = fallback = 0
    for event in events:
        payload = event.payload or {}
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        usage = message.get("usage") or payload.get("usage") or {}
        real += int(
            usage.get("input") or usage.get("input_tokens") or usage.get("inputTokens")
            or usage.get("prompt_tokens") or usage.get("promptTokens") or 0
        )
        if event.event_type == "turn_started":
            fallback += len(str(payload.get("prompt") or "")) // 3
        elif event.event_type == "model_response":
            fallback += len(assistant_text_from_payload(payload)) // 3
    return real if real else fallback


def should_compact(usage: int, budget: int) -> bool:
    return budget > 0 and usage >= int(budget * _TRIGGER_RATIO)


def store_observation(
    observations_dir: str | None,
    call_id: str,
    tool: str,
    content: str,
    *,
    min_bytes: int = _OBS_INLINE_BYTES,
) -> dict[str, Any] | None:
    """Persist an oversized result outside the context; idempotent per call_id."""
    if observations_dir is None or not call_id:
        return None
    data = content.encode("utf-8", errors="replace")
    if len(data) < min_bytes:
        return None
    directory = Path(observations_dir)
    directory.mkdir(parents=True, exist_ok=True)
    full = directory / f"{call_id}.txt"
    if full.is_file():
        # idempotent, and the caller still needs the meta: a repeated store
        # must not fall through and leak the full text back into the context
        meta = json.loads((directory / f"{call_id}.json").read_text(encoding="utf-8"))
        meta["path"] = str(full)
        return meta
    full.write_bytes(data)
    meta = {"call_id": call_id, "tool": tool, "bytes": len(data), "path": str(full)}
    meta["sha256"] = hashlib.sha256(data).hexdigest()
    (directory / f"{call_id}.json").write_text(
        json.dumps({k: v for k, v in meta.items() if k != "path"}), encoding="utf-8"
    )
    return meta


def observation_tombstone(meta: dict[str, Any]) -> str:
    """Pointer injected where a full result used to sit, tail kept inline:
    errors and command verdicts live at the end of output."""
    tail = ""
    try:
        data = Path(meta["path"]).read_bytes()
        if len(data) > _TOMBSTONE_TAIL:
            tail = (
                f"\n[...last {_TOMBSTONE_TAIL} chars of {meta['bytes']}...]\n"
                + data[-_TOMBSTONE_TAIL:].decode("utf-8", errors="ignore")
            )
    except (OSError, KeyError):
        tail = "\n[observation file is no longer readable]"
    return (
        f"[observation {meta['call_id'][:8]} stored · {meta['bytes']} bytes · "
        f"tool={meta['tool']} · full text via openpilot_obs(\"{meta['call_id']}\")]"
        f"{tail}"
    )


def fetch_observation(observations_dir: str | None, obs_id: str) -> str:
    """openpilot_obs retrieval: exact pointer back to the full recorded text."""
    if observations_dir is None or not _OBS_ID.match(obs_id or ""):
        raise ValueError("invalid observation id")
    path = Path(observations_dir) / f"{obs_id}.txt"
    if not path.is_file():
        raise ValueError(f"unknown observation: {obs_id[:8]}")
    data = path.read_bytes()
    text = data[:_OBS_FETCH_BYTES].decode("utf-8", errors="replace")
    return text + ("\n[truncated at the retrieval bound]" if len(data) > _OBS_FETCH_BYTES else "")


def _observation_lines(observations_dir: str | None) -> list[str]:
    directory = Path(observations_dir) if observations_dir else None
    if directory is None or not directory.is_dir():
        return []
    lines = []
    for meta_path in sorted(directory.glob("*.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        lines.append(
            f"- obs {str(meta.get('call_id', ''))[:8]} · {meta.get('tool')} · "
            f"{meta.get('bytes')} bytes · openpilot_obs(\"{meta.get('call_id')}\")"
        )
    return lines


def _tool_result_text(payload: Any) -> str:
    """Defensive extraction; an unextractable result is left unmasked."""
    if not isinstance(payload, dict):
        return ""
    for key in ("content", "result", "text", "output"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, list):
            return "\n".join(str(i.get("text") or "") for i in value if isinstance(i, dict))
    return ""


def _snip(text: str, head: int, tail: int) -> str:
    """Tail-biased inline trim: errors and verdicts live at the end."""
    total = len(text)
    if total <= head + tail + 64:
        return text
    return text[:head] + f"\n[...snipped {total - head - tail} chars...]\n" + text[-tail:]


def _clean_text(text: str) -> str:
    """P5 whitespace pass: trailing blanks off, blank-line runs collapsed."""
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line.rstrip() for line in text.splitlines()))


def _turn_pairs(events: list) -> list[dict[str, Any]]:
    """Group the trajectory into turns. Only turn_started events carrying a
    prompt open a turn: the engine records one, Pi re-emits a mirror without
    a prompt, and the mirror must not fork the grouping."""
    turns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for event in events:
        if event.event_type == "turn_started":
            prompt = str((event.payload or {}).get("prompt") or "")
            if not prompt:
                continue
            current = {"prompt": prompt, "reply": "", "results": []}
            turns.append(current)
        elif current is None:
            continue
        elif event.event_type == "tool_result":
            if event.producer == "pi":
                current["results"].append((event.call_id, _tool_result_text(event.payload)))
        elif event.event_type == "model_response":
            reply = assistant_text_from_payload(event.payload)
            if reply:
                current["reply"] = reply
    return turns


def build_projection(events: list, observations_dir: str | None) -> str | None:
    """Materialize the folded projection; None if nothing is foldable."""
    turns = _turn_pairs(events)
    if len(turns) <= _RECENT_TURNS:
        return None
    recent_from = len(turns) - _RECENT_TURNS
    blocks: list[str] = []
    seen: set[str] = set()
    for number, turn in enumerate(turns, 1):
        is_recent = number > recent_from
        block = [f"### Turn {number}" + (" (recent, verbatim)" if is_recent else ""), f"user: {_clean_text(turn['prompt'])}"]
        reply = turn["reply"]
        if reply and not is_recent and len(reply) > _REPLY_SNIP_CHARS:
            reply = _snip(reply, 300, 500)  # P3: keep the verdict, drop the middle
        if reply:
            block.append(f"assistant: {_clean_text(reply)}")
        if not is_recent:
            for call_id, text in turn["results"]:
                text = _clean_text(text)
                size = len(text.encode("utf-8", errors="replace"))
                digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
                if digest in seen:
                    block.append(f"[duplicate of an earlier result · {size} chars]")  # P4
                    continue
                seen.add(digest)
                if size >= _OBS_MASK_BYTES:
                    # P1: retrieval pointer, indexed below
                    store_observation(observations_dir, call_id, "folded", text, min_bytes=_OBS_MASK_BYTES)
                elif size >= _SNIP_INLINE_BYTES:
                    block.append(_snip(text, _SNIP_HEAD, _SNIP_TAIL))  # P3: head+tail inline
                # else: too small to matter — rerunning is cheaper than a fetch
        blocks.append("\n".join(block))
    parts = [
        f"[op0 compact projection · {recent_from} folded turns · "
        f"{_RECENT_TURNS} recent turns verbatim · policy mask-v1]",
        "\n\n".join(blocks),
    ]
    index = _observation_lines(observations_dir)
    if index:
        parts.append("Masked observations (retrieve full text on demand):\n" + "\n".join(index))
    return "\n\n".join(parts)
