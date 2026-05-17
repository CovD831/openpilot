"""Combine approved pipelines into a reusable Python agent file."""

from __future__ import annotations

import json
import re
from pathlib import Path

from agent_generator.models import GeneratedAgentSpec, PipelineSpec, Slot


def combine_pipelines(
    pipelines: list[PipelineSpec],
    *,
    output_dir: str | Path | None = None,
    agent_name: str | None = None,
) -> GeneratedAgentSpec:
    """Combine pipelines and write a reusable Python agent module."""
    if not pipelines:
        raise ValueError("pipelines must contain at least one pipeline")
    unapproved = [pipeline.id for pipeline in pipelines if not pipeline.approved]
    if unapproved:
        raise ValueError(f"pipelines must be approved before combination: {', '.join(unapproved)}")

    task_summary = next((pipeline.task_summary for pipeline in pipelines if pipeline.task_summary), "Generated agent")
    slots = _merge_slots(pipelines)
    module_name = _safe_module_name(agent_name or task_summary)
    target_dir = Path(output_dir) if output_dir is not None else Path.cwd() / "generated_agents"
    target_dir.mkdir(parents=True, exist_ok=True)
    agent_file = target_dir / f"{module_name}.py"

    spec = GeneratedAgentSpec(
        name=module_name,
        task_summary=task_summary,
        slots=slots,
        pipelines=pipelines,
        entry_function="run",
        dependencies=[],
        agent_file=str(agent_file),
    )
    agent_file.write_text(_render_agent_module(spec), encoding="utf-8")
    return spec


def _merge_slots(pipelines: list[PipelineSpec]) -> list[Slot]:
    slots_by_name: dict[str, Slot] = {}
    for pipeline in pipelines:
        for slot in pipeline.slots:
            slots_by_name.setdefault(slot.name, slot)
    return list(slots_by_name.values())


def _safe_module_name(value: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_")
    if not stem:
        stem = "generated_agent"
    if stem[0].isdigit():
        stem = f"agent_{stem}"
    return stem[:60]


def _render_agent_module(spec: GeneratedAgentSpec) -> str:
    payload = spec.model_dump(mode="json")
    payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
    return f'''"""Generated OpenPilot agent.

This file was produced by Agent Generator. Slot values are configurable at
runtime so private or one-off data does not need to be hardcoded.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


AGENT_SPEC = {payload_json}


def run(**slot_overrides: Any) -> dict[str, Any]:
    """Return a replay-ready agent execution plan with applied slot overrides."""
    spec = deepcopy(AGENT_SPEC)
    slots = spec.get("slots", [])
    for slot in slots:
        name = slot.get("name")
        if name in slot_overrides:
            slot["value"] = slot_overrides[name]

    return {{
        "agent": spec.get("name"),
        "task_summary": spec.get("task_summary"),
        "slots": slots,
        "pipelines": spec.get("pipelines", []),
        "entry_function": spec.get("entry_function", "run"),
    }}
'''
