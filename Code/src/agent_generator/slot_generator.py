"""Slot generation for user-defined agents."""

from __future__ import annotations

from typing import Any

from agent_generator.models import Slot, SlotKind
from core.llm import LLMClient, LLMMessage, LLMRequest
from ui.environment_guard import agent_generator_llm_error_message, is_socks_dependency_error


def generate_slots(task: str, *, llm_client: Any | None = None) -> list[Slot]:
    """Generate reusable slots from a natural-language task with an LLM."""
    cleaned_task = " ".join(task.strip().split())
    if not cleaned_task:
        raise ValueError("task must not be empty")

    client = llm_client or LLMClient()
    try:
        response = client.complete(
            LLMRequest(
                response_format="json_object",
                temperature=0.2,
                messages=[
                    LLMMessage(
                        role="system",
                        content=(
                            "You generate dynamic slots for reusable user-defined agents. "
                            "A slot is a variable requirement, constraint, data source, "
                            "processing choice, output preference, or interaction preference "
                            "that should remain configurable when the agent is reused. "
                            "Do not use a fixed template. Do not invent generic slots unless "
                            "the user's task actually needs them. Return only JSON."
                        ),
                    ),
                    LLMMessage(
                        role="user",
                        content=(
                            "Create task-specific slots for this agent-building request.\n\n"
                            f"Task: {cleaned_task}\n\n"
                            "Return this JSON shape:\n"
                            "{\n"
                            '  "slots": [\n'
                            "    {\n"
                            '      "name": "snake_case_ascii_identifier",\n'
                            '      "kind": "task | constraint | data_source | format | processing | interaction",\n'
                            '      "description": "what this slot controls",\n'
                            '      "value": "initial value inferred from the task or null",\n'
                            '      "required": true,\n'
                            '      "revision_notes": []\n'
                            "    }\n"
                            "  ]\n"
                            "}\n\n"
                            "Prefer precise slots that reflect the user's actual wording, "
                            "language, ambiguity, and likely follow-up choices."
                        ),
                    ),
                ],
            )
        )
    except Exception as exc:
        if is_socks_dependency_error(exc):
            raise RuntimeError(agent_generator_llm_error_message(exc)) from exc
        raise

    parsed = response.parsed_json
    if not isinstance(parsed, dict):
        raise ValueError("slot generator LLM response must be a JSON object")
    raw_slots = parsed.get("slots")
    if not isinstance(raw_slots, list) or not raw_slots:
        raise ValueError("slot generator LLM response must include a non-empty slots array")

    slots: list[Slot] = []
    for index, raw_slot in enumerate(raw_slots, start=1):
        if not isinstance(raw_slot, dict):
            continue
        slot = _coerce_slot(raw_slot, index)
        slots.append(slot)

    if not slots:
        raise ValueError("slot generator LLM response did not contain valid slots")
    return slots


def _coerce_slot(raw_slot: dict[str, Any], index: int) -> Slot:
    kind = _coerce_kind(raw_slot.get("kind"))
    name = str(raw_slot.get("name") or f"slot_{index}").strip() or f"slot_{index}"
    description = str(raw_slot.get("description") or name).strip()
    revision_notes = raw_slot.get("revision_notes")
    if not isinstance(revision_notes, list):
        revision_notes = []

    return Slot(
        name=name,
        kind=kind,
        description=description,
        value=raw_slot.get("value"),
        required=bool(raw_slot.get("required", True)),
        revision_notes=[str(note) for note in revision_notes],
    )


def _coerce_kind(raw_kind: Any) -> SlotKind:
    try:
        return SlotKind(str(raw_kind))
    except ValueError:
        return SlotKind.CONSTRAINT
