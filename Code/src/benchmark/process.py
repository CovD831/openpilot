"""Evidence-only process-cost extraction from persisted benchmark trajectories."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field


class BenchmarkProcessCost(BaseModel):
    """Observed process quantities for one benchmark run.

    These are descriptive measurements, not a quality score. Missing provider
    usage remains ``None`` instead of being converted into zero.
    """

    model_config = ConfigDict(extra="forbid")

    event_count: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    tool_successes: int = Field(default=0, ge=0)
    tool_failures: int = Field(default=0, ge=0)
    llm_requests: int = Field(default=0, ge=0)
    llm_responses: int = Field(default=0, ge=0)
    llm_failures: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    verification_state_changes: int = Field(default=0, ge=0)
    phase_changes: int = Field(default=0, ge=0)
    tool_duration_seconds: float = Field(default=0.0, ge=0.0)
    elapsed_seconds: float | None = Field(default=None, ge=0.0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)


def extract_process_cost(
    events: Sequence[Mapping[str, Any]],
    run: Mapping[str, Any] | None = None,
) -> BenchmarkProcessCost:
    """Extract stable counters and known usage from trajectory events."""

    starts: list[datetime] = []
    finishes: list[datetime] = []
    prompt_tokens: list[int] = []
    completion_tokens: list[int] = []
    total_tokens: list[int] = []
    reasoning_tokens: list[int] = []
    tool_duration_seconds = 0.0
    retry_count = 0
    tool_calls = tool_successes = tool_failures = 0
    llm_requests = llm_responses = llm_failures = 0
    verification_state_changes = phase_changes = 0

    if run:
        _append_timestamp(starts, run.get("started_at"))
        _append_timestamp(finishes, run.get("finished_at"))

    for event in events:
        event_type = str(event.get("event_type") or event.get("event") or "")
        payload = event.get("payload")
        payload = payload if isinstance(payload, Mapping) else {}
        _append_timestamp(starts, payload.get("started_at"))
        _append_timestamp(finishes, payload.get("finished_at"))

        if event_type == "tool_called":
            tool_calls += 1
        elif event_type == "tool_succeeded":
            tool_successes += 1
            tool_calls = max(tool_calls, tool_successes + tool_failures)
            tool_duration_seconds += _duration_seconds(payload)
            retry_count += _retry_count(payload)
        elif event_type == "tool_failed":
            tool_failures += 1
            tool_calls = max(tool_calls, tool_successes + tool_failures)
            tool_duration_seconds += _duration_seconds(payload)
            retry_count += _retry_count(payload)
        elif event_type == "llm_requested":
            llm_requests += 1
        elif event_type == "llm_responded":
            llm_responses += 1
            usage = payload.get("usage")
            if isinstance(usage, Mapping):
                _append_number(prompt_tokens, usage.get("prompt_tokens"))
                _append_number(completion_tokens, usage.get("completion_tokens"))
                _append_number(total_tokens, usage.get("total_tokens"))
                reasoning = _first_number(
                    usage.get("reasoning_tokens"),
                    _nested_value(usage, "completion_tokens_details", "reasoning_tokens"),
                    _nested_value(usage, "output_tokens_details", "thinking_tokens"),
                )
                if reasoning is not None:
                    reasoning_tokens.append(reasoning)
        elif event_type == "llm_failed":
            llm_failures += 1
        elif event_type == "verification_state_changed":
            verification_state_changes += 1
        elif event_type == "runtime_phase_changed":
            phase_changes += 1

        _append_timestamp(starts, event.get("created_at"))
        _append_timestamp(finishes, event.get("created_at"))

    elapsed_seconds = None
    if starts and finishes:
        elapsed_seconds = max(0.0, (max(finishes) - min(starts)).total_seconds())

    return BenchmarkProcessCost(
        event_count=len(events),
        tool_calls=tool_calls,
        tool_successes=tool_successes,
        tool_failures=tool_failures,
        llm_requests=llm_requests,
        llm_responses=llm_responses,
        llm_failures=llm_failures,
        retry_count=retry_count,
        verification_state_changes=verification_state_changes,
        phase_changes=phase_changes,
        tool_duration_seconds=tool_duration_seconds,
        elapsed_seconds=elapsed_seconds,
        prompt_tokens=sum(prompt_tokens) if prompt_tokens else None,
        completion_tokens=sum(completion_tokens) if completion_tokens else None,
        total_tokens=sum(total_tokens) if total_tokens else None,
        reasoning_tokens=sum(reasoning_tokens) if reasoning_tokens else None,
    )


def _append_timestamp(target: list[datetime], value: Any) -> None:
    if not value:
        return
    try:
        text = str(value).replace("Z", "+00:00")
        target.append(datetime.fromisoformat(text))
    except (TypeError, ValueError):
        return


def _append_number(target: list[int], value: Any) -> None:
    number = _as_int(value)
    if number is not None:
        target.append(number)


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _duration_seconds(payload: Mapping[str, Any]) -> float:
    seconds = _as_float(payload.get("duration_seconds"))
    if seconds is not None:
        return seconds
    milliseconds = _as_float(payload.get("duration_ms"))
    return milliseconds / 1000.0 if milliseconds is not None else 0.0


def _retry_count(payload: Mapping[str, Any]) -> int:
    explicit = _as_int(payload.get("retry_count"))
    attempts = _as_int(payload.get("attempts_used"))
    inferred = max(0, attempts - 1) if attempts is not None else 0
    return max(explicit or 0, inferred)


def _nested_value(payload: Mapping[str, Any], *keys: str) -> Any:
    value: Any = payload
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _first_number(*values: Any) -> int | None:
    for value in values:
        number = _as_int(value)
        if number is not None:
            return number
    return None
