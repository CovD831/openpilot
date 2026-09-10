"""Contract registry: the metadata layer made explicit (Domain Contract layer).

The old architecture's lesson, kept small: every ledger event type
declares its payload schema, its producer, and its consumers;
Session.record enforces strict contracts at write time (fail-closed).
Four honesty rules keep this from becoming the 6,390-line past:

  - the registry only records facts extracted from real record() call
    sites, not speculative designs;
  - Pi-passed-through payloads are declared but not strictly enforced -
    we do not pretend to validate a third party's wire format;
  - the Pi passthrough twins of engine-built names (agent_start/
    turn_start/turn_end) are split via a pi_ prefix, so the engine-built
    events keep strict contracts;
  - a new event type must be registered before its first record: the
    registry is the admission gate for metadata itself.
"""

from __future__ import annotations

_CONTRACT: dict[str, dict] = {}
# event -> {producer, consumers, required, optional, strict}


def _contract(
    event: str,
    *,
    producer: str,
    consumers: tuple[str, ...],
    required: dict[str, type] | None = None,
    optional: dict[str, type] | None = None,
    strict: bool = True,
) -> None:
    _CONTRACT[event] = {
        "producer": producer,
        "consumers": consumers,
        "required": required or {},
        "optional": optional or {},
        "strict": strict,
    }


def _register() -> None:
    # -- engine lifecycle (engine-built) --------------------------------
    _contract("engine_started", producer="engine", consumers=("tui",),
              required={"pid": int})
    _contract("engine_stopped", producer="engine", consumers=("tui",))
    _contract("engine_crashed", producer="engine", consumers=("tui", "recovery"),
              required={"error_type": str, "message": str})
    _contract("model_request", producer="engine", consumers=("recovery",),
              required={"accepted": bool})
    _contract("turn_started", producer="engine", consumers=("compaction", "tui", "recovery"),
              required={"prompt": str, "turn_id": str})
    _contract("compaction", producer="engine", consumers=("recovery", "audit"),
              required={"policy": str, "usage_estimate": int, "budget_tokens": int})

    # -- Pi wire passthrough (declared, not enforced) -------------------
    for event, consumers in (
        ("model_response_started", ("tui",)),
        ("model_response_delta", ("tui",)),
        ("model_response", ("compaction", "tui", "recovery")),
        ("tool_call", ("tui", "admission")),
        ("tool_result", ("compaction", "tui")),
        ("agent_end", ("engine",)),
        # passthrough twins of engine-built names, split via the pi_ prefix
        ("pi_engine_started", ("audit",)),
        ("pi_turn_started", ("audit",)),
        ("pi_turn_finished", ("compaction",)),
        ("pi_agent_end", ("engine",)),
    ):
        _contract(event, producer="pi", consumers=consumers, strict=False)

    # -- admission family (shape varies per mode; declared, not enforced)
    for event in ("consent_bound", "patch_authorized", "patch_proposed",
                  "command_authorized", "command_proposed", "proposal_denied",
                  "approval_timeout"):
        _contract(event, producer="admission", consumers=("audit",), strict=False)

    # -- receipts & cli lifecycle ---------------------------------------
    _contract("task_received", producer="cli", consumers=("audit",),
              required={"goal": str}, optional={"project_root": str})
    _contract("session_started", producer="cli", consumers=("audit",),
              required={"project_root": str})
    _contract("conversation_reset", producer="cli", consumers=("audit",))
    _contract("approval_mode_changed", producer="cli", consumers=("audit",),
              required={"mode": str})
    _contract("receipt_dismissed", producer="cli", consumers=("recovery",),
              required={"receipt_id": str, "path": str})
    _contract("patch_receipt_written", producer="bridge", consumers=("audit",),
              required={"receipt_id": str, "path": str, "hash_before": str,
                        "hash_after": str, "validation_status": str})
    _contract("bash_receipt_written", producer="bridge", consumers=("audit",),
              required={"receipt_id": str, "command": str, "exit_code": int,
                        "validation_status": str})
    _contract("validation_completed", producer="cli", consumers=("audit",),
              required={"receipt_id": str, "returncode": int, "status": str},
              optional={"command": str})
    _contract("run_finished", producer="tui", consumers=("audit",),
              required={"response_chars": int}, optional={"crashed": bool})

    # -- subagent: the first domain contract born inside the registry ---
    _contract("task_spawned", producer="task", consumers=("audit", "recovery"),
              required={"task_run_id": str, "task": str, "depth": int})
    _contract("task_finished", producer="task", consumers=("audit", "recovery", "parent model"),
              required={"task_run_id": str, "status": str, "summary": str, "receipts": int})


_register()


def violation(event_type: str, payload: dict) -> str:
    """Contract check for one record; empty string means it passes.
    Unregistered types fail closed: metadata cannot enter the ledger
    without a contract."""
    spec = _CONTRACT.get(event_type)
    if spec is None:
        return f"unregistered event type: {event_type}"
    if not isinstance(payload, dict):
        return f"{event_type}: payload must be a dict"
    if not spec["strict"]:
        return ""
    for name, kind in spec["required"].items():
        if name not in payload:
            return f"{event_type}: missing required field {name!r}"
        value = payload[name]
        if kind is int and isinstance(value, bool):
            return f"{event_type}: field {name!r} must be int (got bool)"
        if not isinstance(value, kind):
            return f"{event_type}: field {name!r} must be {kind.__name__}"
    for name, kind in spec["optional"].items():
        if name in payload and not isinstance(payload[name], kind):
            return f"{event_type}: field {name!r} must be {kind.__name__}"
    return ""


def contract_of(event_type: str) -> dict | None:
    return _CONTRACT.get(event_type)


def registered() -> tuple[str, ...]:
    return tuple(sorted(_CONTRACT))
