from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_stage28():
    path = ROOT / "experiments/full_architecture_context_observation/stage28_fully_scoped_task_repetition.py"
    spec = importlib.util.spec_from_file_location("phase28_fully_scoped_task_repetition", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fully_scoped_cli_task_contains_all_required_files_and_symbols():
    module = _load_stage28()
    task = module.TASKS[module.TASK_NAME]

    assert task["read_files"] == [
        ROOT / "Code/src/ui/cli.py",
        ROOT / "Code/src/ui/enhanced_cli.py",
    ]
    requirements = {option[0] for option in task["quality_requirements"]}
    assert {
        "build_parser",
        "_add_run_parser",
        "main",
        "_run_openpilot",
        "run_enhanced_cli",
        "_run_once_mode",
        "_execute_agent_generator",
    } <= requirements


def test_fully_scoped_cli_quality_gate_accepts_complete_answer():
    module = _load_stage28()
    answer = (
        "build_parser delegates to _add_run_parser, which defines --once; "
        "main calls _run_openpilot; _run_openpilot calls run_enhanced_cli; "
        "run_enhanced_cli sees args.once and calls _run_once_mode.\n"
        "The ordinary one-shot branch "
        "uses _run_once_mode and that function calls _execute_agent_generator "
        "only for the agent-generator route."
    )

    quality = module.run_task.__globals__["_quality_check"](
        module.TASK_NAME,
        answer,
        execution_passed=True,
    )

    assert quality["passed"] is True
    assert quality["classification"] == "semantic_quality"


def test_fully_scoped_cli_quality_gate_rejects_wrong_direct_once_handler():
    module = _load_stage28()
    answer = (
        "build_parser _add_run_parser --once; main calls _run_openpilot; "
        "_run_openpilot calls run_enhanced_cli. In the if hasattr(args, 'once') "
        "and args.once branch, the direct handler is _execute_agent_generator. "
        "_run_once_mode calls _execute_agent_generator for the agent-generator route."
    )

    quality = module.run_task.__globals__["_quality_check"](
        module.TASK_NAME,
        answer,
        execution_passed=True,
    )

    assert quality["passed"] is False
    assert quality["forbidden_relations"] == [
        ["if hasattr(args, 'once')", "_execute_agent_generator"],
        ["args.once", "_execute_agent_generator"],
    ]
