from __future__ import annotations

import importlib.util
from pathlib import Path

from core.provider_tool_roundtrip import ProviderToolRoundTripRunner


_SCRIPT = Path(__file__).resolve().parents[2] / "experiments" / "full_architecture_context_observation" / "stage25_budget_profile_task_matrix.py"
ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("phase25_task_matrix", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_quality_classifier_marks_scoped_refusal_without_calling_it_success() -> None:
    response = (
        "setup.py is not in the allowed read scope, so I cannot state whether it exists. "
        "The current CLI module is code/src/ui/cli.py and the runtime_controller evidence was read."
    )

    result = _MODULE._quality_check(
        "long_reproduction",
        response,
        execution_passed=True,
    )

    assert result["passed"] is False
    assert result["classification"] == "scope_limited_refusal"
    assert result["scope_limited"] is True
    assert result["scope_limited_safe"] is True
    assert "cannot state" in result["raw_negative_markers"]


def test_quality_classifier_keeps_ordinary_uncertainty_as_semantic_quality() -> None:
    response = (
        "setup.py code/src/ui/cli.py intelligent_autopilot runtime_controller are the requested "
        "evidence labels, but I cannot verify the relationship because the evidence is insufficient."
    )

    result = _MODULE._quality_check(
        "long_reproduction",
        response,
        execution_passed=True,
    )

    assert result["passed"] is False
    assert result["classification"] == "semantic_quality"
    assert result["scope_limited"] is False
    assert result["scope_limited_safe"] is False
    assert "cannot verify" in result["negative_markers"]


def test_long_source_projection_keeps_compact_local_call_edges() -> None:
    source = """\
def run_enhanced_cli():
    if args.once:
        return _run_once_mode()

def _run_once_mode():
    return _execute_agent_generator()

def _execute_agent_generator():
    return True
""" + "\n".join(
        f"def helper_{index}():\n    return {index}" for index in range(120)
    )

    excerpt = ProviderToolRoundTripRunner._bounded_source_excerpt(source, 1200)

    assert "[local call index]" in excerpt
    assert "run_enhanced_cli -> _run_once_mode" in excerpt
    assert "_run_once_mode -> _execute_agent_generator" in excerpt


def test_long_cli_projection_keeps_once_guard_and_inner_branch_calls() -> None:
    source = (ROOT / "Code/src/ui/enhanced_cli.py").read_text(encoding="utf-8")
    excerpt = ProviderToolRoundTripRunner._bounded_source_excerpt(source, 1792)

    assert "if hasattr(args, 'once')" in excerpt
    assert "return _run_once_mode(" in excerpt
    assert "if classification.route == \"agent_generator\":" in excerpt
    assert "_execute_agent_generator(" in excerpt
