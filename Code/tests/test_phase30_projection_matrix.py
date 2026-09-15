from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_matrix():
    path = ROOT / "experiments/full_architecture_context_observation/stage30_fully_scoped_projection_matrix.py"
    spec = importlib.util.spec_from_file_location("phase30_projection_matrix", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase30_matrix_has_five_fully_scoped_read_only_arms():
    module = _load_matrix()

    assert set(module.TASK_SPECS) == {
        "single_file_symbol",
        "two_file_linkage",
        "long_file_middle",
        "guarded_branch",
        "adaptive_window_evidence",
    }
    for task in module.TASK_SPECS.values():
        assert task["read_files"]
        assert all(not str(path).endswith("/") for path in task["read_files"])
        assert "modify files" in task["description"]


def test_phase30_guarded_branch_quality_rejects_direct_generator_claim():
    module = _load_matrix()
    task_name = "guarded_branch"
    quality_check = module.run_task.__globals__["_quality_check"]

    wrong = (
        "args.once directly calls _execute_agent_generator, while classification.route "
        "also uses _execute_agent_generator. _run_once_mode is present."
    )
    result = quality_check(task_name, wrong, execution_passed=True)

    assert result["passed"] is False
    assert result["forbidden_relations"] == [["args.once", "_execute_agent_generator"]]


def test_phase30_two_file_quality_accepts_flag_or_source_symbol_equivalence():
    module = _load_matrix()
    quality_check = module.run_task.__globals__["_quality_check"]

    response = (
        "main calls _run_openpilot, which delegates to run_enhanced_cli. "
        "The args.once branch returns _run_once_mode."
    )
    result = quality_check("two_file_linkage", response, execution_passed=True)

    assert result["passed"] is True
    assert result["missing_requirements"] == []

    missing = quality_check(
        "two_file_linkage",
        "main calls _run_openpilot and run_enhanced_cli, but the once handler is not shown.",
        execution_passed=True,
    )
    assert missing["passed"] is False
    assert ["--once", "args.once"] in missing["missing_requirements"]
    assert ["_run_once_mode"] in missing["missing_requirements"]


def test_phase30_adaptive_quality_uses_public_contract_not_internal_names():
    module = _load_matrix()
    quality_check = module.run_task.__globals__["_quality_check"]

    response = (
        "Adaptive read_mode uses full-read defaults for code/config files when no window is "
        "provided. An explicit offset or max_lines requests a bounded window, and the result "
        "reports lines_read, total_lines, and truncated. ToolInputMetadata carries read_mode, "
        "file_path, offset, and max_lines."
    )
    result = quality_check("adaptive_window_evidence", response, execution_passed=True)

    assert result["passed"] is True
    assert result["missing_requirements"] == []
    assert result["negative_markers"] == []
