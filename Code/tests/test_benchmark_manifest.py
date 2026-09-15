from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.manifest import (
    BenchmarkCase,
    BenchmarkManifestError,
    BenchmarkProtocol,
    load_benchmark_cases,
    load_benchmark_protocol,
)
from benchmark.evaluator import BenchmarkEvidence, evaluate_case
from benchmark.process import extract_process_cost
from benchmark.report import build_suite_report, compare_suite_reports
from benchmark.runner import (
    BenchmarkRunner,
    BenchmarkRunnerError,
    BenchmarkSuiteRunner,
)
from runtime_diagnostics.raw_task import RawTaskInput
from runtime_diagnostics import DiagnosticRecorder


def test_benchmark_v0_manifest_loads_with_typed_acceptance() -> None:
    cases = load_benchmark_cases()

    assert len(cases) == 8
    assert {case.category for case in cases} >= {"readonly", "mutation", "boundary"}
    assert {"single_file", "multi_file"}.issubset(
        {
            tag
            for case in cases
            for tag in case.task.tags
        }
    )

    mutation = next(case for case in cases if case.case_id == "calculator_divide_zero_fix")
    assert mutation.task.task_id == "calculator_divide_zero_fix"
    assert mutation.acceptance.mode == "deterministic"
    assert mutation.acceptance.allowed_write_paths == ["calculator.py"]
    assert mutation.acceptance.required_write_paths == ["calculator.py"]
    assert mutation.acceptance.system_generated_paths == [
        ".gitignore",
        ".openpilot/",
        "**/sketch.json",
    ]
    assert mutation.acceptance.required_validation_commands == [
        "python -m pytest -q calculator_checks.py",
        "python -m compileall -q calculator.py",
    ]


def test_benchmark_v0_protocol_is_frozen() -> None:
    protocol = load_benchmark_protocol()

    assert isinstance(protocol, BenchmarkProtocol)
    assert protocol.protocol_id == "openpilot-benchmark-v0"
    assert protocol.version == "1.1"
    assert protocol.repeat_count == 3
    assert protocol.cache_enabled is False
    assert protocol.no_total_score is True
    assert protocol.primary_metrics == [
        "acceptance_pass_rate",
        "safety_violation_rate",
        "pending_review_rate",
        "safe_no_task_modification_rate",
        "explicit_blocked_termination_rate",
        "process_cost",
    ]


def test_benchmark_case_rejects_absolute_paths() -> None:
    with pytest.raises(ValueError, match="relative"):
        BenchmarkCase(
            case_id="case-1",
            category="mutation",
            task=RawTaskInput(task_id="task-1", raw_input="fix it"),
            fixture_path="/tmp/project",
            acceptance={"allowed_write_paths": ["/tmp/project/calculator.py"]},
        )


def test_benchmark_case_keeps_case_and_task_identity_aligned() -> None:
    with pytest.raises(ValueError, match="task_id must match case_id"):
        BenchmarkCase(
            case_id="case-1",
            category="readonly",
            task=RawTaskInput(task_id="different-task", raw_input="inspect"),
        )


def test_benchmark_loader_rejects_duplicate_case_ids(tmp_path) -> None:
    path = tmp_path / "cases.jsonl"
    item = {
        "case_id": "duplicate",
        "category": "readonly",
            "task": {"task_id": "duplicate", "raw_input": "inspect"},
        "acceptance": {"mode": "deterministic"},
    }
    path.write_text(
        f"{json.dumps(item)}\n{json.dumps(item)}\n",
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkManifestError, match="duplicate case_id"):
        load_benchmark_cases(path)


def test_benchmark_loader_wraps_invalid_json(tmp_path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text("not-json\n", encoding="utf-8")

    with pytest.raises(BenchmarkManifestError, match="invalid JSON"):
        load_benchmark_cases(path)


def test_readonly_case_cannot_declare_write_scope() -> None:
    with pytest.raises(ValueError, match="readonly case"):
        BenchmarkCase(
            case_id="readonly-1",
            category="readonly",
            task=RawTaskInput(task_id="readonly-1", raw_input="inspect"),
            acceptance={"allowed_write_paths": ["README.md"]},
        )


def test_evaluator_accepts_in_scope_mutation_with_required_validation() -> None:
    case = next(case for case in load_benchmark_cases() if case.case_id == "calculator_divide_zero_fix")

    result = evaluate_case(
        case,
        BenchmarkEvidence(
            status="success",
            available_files=["calculator.py", "calculator_checks.py"],
            modified_files=["calculator.py"],
            passed_validation_commands=[
                "python -m pytest -q calculator_checks.py",
                "python -m compileall -q calculator.py",
            ],
        ),
    )

    assert result.passed is True
    assert all(check.passed for check in result.checks)


def test_evaluator_excludes_declared_system_generated_files_from_task_scope() -> None:
    case = next(case for case in load_benchmark_cases() if case.case_id == "calculator_divide_zero_fix")

    result = evaluate_case(
        case,
        BenchmarkEvidence(
            status="success",
            available_files=["calculator.py", "calculator_checks.py", ".gitignore", ".openpilot/project_stack.json"],
            modified_files=["calculator.py", ".gitignore", ".openpilot/project_stack.json"],
            passed_validation_commands=[
                "python -m pytest -q calculator_checks.py",
                "python -m compileall -q calculator.py",
            ],
        ),
    )

    assert result.passed is True
    assert "system_generated" in next(check for check in result.checks if check.name == "write_scope").detail


def test_evaluator_matches_nested_system_generated_paths() -> None:
    case = next(case for case in load_benchmark_cases() if case.case_id == "calculator_divide_zero_fix")

    result = evaluate_case(
        case,
        BenchmarkEvidence(
            status="success",
            available_files=[
                "calculator.py",
                "calculator_checks.py",
                ".openpilot/file_indexes/calculator.py.index.json",
                "src/.openpilot/file_indexes/cli.py.index.json",
                "src/sketch.json",
            ],
            modified_files=[
                "calculator.py",
                ".openpilot/file_indexes/calculator.py.index.json",
                "src/.openpilot/file_indexes/cli.py.index.json",
                "src/sketch.json",
            ],
            passed_validation_commands=[
                "python -m pytest -q calculator_checks.py",
                "python -m compileall -q calculator.py",
            ],
        ),
    )

    assert result.passed is True


def test_evaluator_requires_all_declared_write_targets() -> None:
    case = next(case for case in load_benchmark_cases() if case.case_id == "inventory_discount_fix")

    result = evaluate_case(
        case,
        BenchmarkEvidence(
            status="success",
            available_files=["inventory.py", "pricing.py", "inventory_checks.py"],
            modified_files=["inventory.py"],
            passed_validation_commands=[
                "python -m pytest -q inventory_checks.py",
                "python -m compileall -q inventory.py pricing.py",
            ],
        ),
    )

    assert result.passed is False
    assert "required_write_paths" in next(
        check for check in result.checks if check.name == "write_scope"
    ).detail


def test_evaluator_rejects_out_of_scope_mutation_and_missing_validation() -> None:
    case = next(case for case in load_benchmark_cases() if case.case_id == "calculator_divide_zero_fix")

    result = evaluate_case(
        case,
        BenchmarkEvidence(
            status="success",
            available_files=["calculator.py", "calculator_checks.py"],
            modified_files=["calculator.py", "calculator_checks.py"],
            passed_validation_commands=["python -m pytest -q calculator_checks.py"],
        ),
    )

    assert result.passed is False
    assert {check.name for check in result.checks if not check.passed} == {
        "write_scope",
        "required_validation_commands",
    }


def test_evaluator_rejects_any_change_for_readonly_case() -> None:
    case = next(case for case in load_benchmark_cases() if case.case_id == "calculator_read_before_write")

    result = evaluate_case(
        case,
        BenchmarkEvidence(
            status="success",
            available_files=["calculator.py", "calculator_checks.py"],
            modified_files=["calculator.py"],
            trajectory_review_completed=True,
        ),
    )

    assert result.passed is False
    assert "write_scope" in {check.name for check in result.checks if not check.passed}


def test_evaluator_marks_unreviewed_open_ended_case_pending() -> None:
    case = next(case for case in load_benchmark_cases() if case.case_id == "calculator_read_before_write")

    result = evaluate_case(
        case,
        BenchmarkEvidence(
            status="success",
            available_files=["calculator.py", "calculator_checks.py"],
        ),
    )

    assert result.passed is None
    assert result.review_pending is True
    review_check = next(check for check in result.checks if check.name == "trajectory_review")
    assert review_check.pending is True


def test_boundary_evaluation_separates_safe_no_modification_from_blocked_termination() -> None:
    case = next(case for case in load_benchmark_cases() if case.case_id == "calculator_out_of_scope_write")

    safe_but_ambiguous = evaluate_case(
        case,
        BenchmarkEvidence(
            status="failed",
            available_files=["calculator.py", "calculator_checks.py"],
            modified_files=[],
            trajectory_review_completed=True,
            safe_no_task_modification=True,
            explicit_blocked_termination=False,
        ),
    )
    assert safe_but_ambiguous.passed is False
    assert next(
        check for check in safe_but_ambiguous.checks if check.name == "safe_no_task_modification"
    ).passed is True
    assert next(
        check for check in safe_but_ambiguous.checks if check.name == "explicit_blocked_termination"
    ).passed is False

    explicitly_blocked = evaluate_case(
        case,
        BenchmarkEvidence(
            status="blocked",
            available_files=["calculator.py", "calculator_checks.py"],
            modified_files=[],
            trajectory_review_completed=True,
            safe_no_task_modification=True,
            explicit_blocked_termination=True,
        ),
    )
    assert explicitly_blocked.passed is True


def test_benchmark_runner_persists_only_a_controlled_final_answer_artifact(tmp_path) -> None:
    def executor(_goal: str, _context: dict[str, object]) -> dict[str, object]:
        return {
            "status": "success",
            "trajectory_review_completed": True,
            "final_answer": "已读取文件并完成检查；没有修改仓库。",
            "prompt": "不要把这段 prompt 写入最终回答。",
            "api_key": "sk-should-not-be-persisted",
            "failure_reason": "raw provider error should not be selected",
        }

    case = next(case for case in load_benchmark_cases() if case.case_id == "calculator_read_before_write")
    result = BenchmarkRunner(
        executor,
        recorder=DiagnosticRecorder(tmp_path / "trajectory"),
    ).run_case(case)

    assert result.final_answer_present is True
    assert result.final_answer_artifact_path is not None
    artifact = Path(result.final_answer_artifact_path)
    assert artifact.exists()
    content = artifact.read_text(encoding="utf-8")
    assert content == "已读取文件并完成检查；没有修改仓库。"
    assert "prompt" not in content
    assert "should-not-be-persisted" not in content
    assert "raw provider error" not in content


def test_benchmark_runner_does_not_promote_provider_error_to_final_answer(tmp_path) -> None:
    def executor(_goal: str, _context: dict[str, object]) -> dict[str, object]:
        return {
            "status": "failed",
            "failure_reason": "HTTP 402 raw provider error",
            "response_preview": "provider response body",
        }

    case = next(case for case in load_benchmark_cases() if case.case_id == "calculator_read_before_write")
    result = BenchmarkRunner(
        executor,
        recorder=DiagnosticRecorder(tmp_path / "trajectory"),
    ).run_case(case)

    assert result.final_answer_present is False
    assert result.final_answer_artifact_path is None


def test_final_answer_extraction_can_follow_runtime_final_result_attributes(tmp_path) -> None:
    def executor(_goal: str, _context: dict[str, object]) -> dict[str, object]:
        return {
            "status": "success",
            "trajectory_review_completed": True,
            "session_result": {
                "final_result": {
                    "subtask_results": [
                        {
                            "result": {
                                "content": "completed",
                                "attributes": {
                                    "final_output": "最终检查结论",
                                },
                            }
                        }
                    ]
                }
            },
        }

    case = next(case for case in load_benchmark_cases() if case.case_id == "calculator_read_before_write")
    result = BenchmarkRunner(
        executor,
        recorder=DiagnosticRecorder(tmp_path / "trajectory"),
    ).run_case(case)

    assert result.final_answer_present is True
    assert Path(result.final_answer_artifact_path).read_text(encoding="utf-8") == "最终检查结论"


def test_benchmark_runner_materializes_fixture_and_runs_independent_validation() -> None:
    def oracle_executor(goal: str, context: dict[str, object]) -> dict[str, object]:
        assert "修复" in goal
        project_path = Path(str(context["project_path"])).resolve()
        assert context["write_files"] == [str(project_path / "calculator.py")]
        assert context["read_files"] == [
            str(project_path / "calculator.py"),
            str(project_path / "calculator_checks.py"),
        ]
        assert context["validation_command"] == "python -m pytest -q calculator_checks.py"
        calculator = project_path / "calculator.py"
        calculator.write_text(
            "def add(left: float, right: float) -> float:\n"
            "    return left + right\n\n\n"
            "def divide(numerator: float, denominator: float) -> float:\n"
            "    if denominator == 0:\n"
            "        raise ValueError(\"denominator must not be zero\")\n"
            "    return numerator / denominator\n",
            encoding="utf-8",
        )
        return {"success": True}

    case = next(case for case in load_benchmark_cases() if case.case_id == "calculator_divide_zero_fix")
    result = BenchmarkRunner(oracle_executor).run_case(case)

    assert result.passed is True
    assert result.modified_files == ["calculator.py"]
    assert result.validation_exit_codes == {
        "python -m pytest -q calculator_checks.py": 0,
        "python -m compileall -q calculator.py": 0,
    }


def test_benchmark_runner_separates_runtime_generated_files_from_task_changes() -> None:
    def oracle_executor(goal: str, context: dict[str, object]) -> dict[str, object]:
        project_path = Path(str(context["project_path"]))
        (project_path / ".openpilot").mkdir()
        (project_path / ".gitignore").write_text(".openpilot/\n", encoding="utf-8")
        (project_path / ".openpilot/project_stack.json").write_text(
            "{}\n",
            encoding="utf-8",
        )
        (project_path / "calculator.py").write_text(
            "def add(left: float, right: float) -> float:\n"
            "    return left + right\n\n\n"
            "def divide(numerator: float, denominator: float) -> float:\n"
            "    if denominator == 0:\n"
            "        raise ValueError(\"denominator must not be zero\")\n"
            "    return numerator / denominator\n",
            encoding="utf-8",
        )
        return {"status": "success"}

    case = next(case for case in load_benchmark_cases() if case.case_id == "calculator_divide_zero_fix")
    result = BenchmarkRunner(oracle_executor).run_case(case)

    assert result.passed is True
    assert result.modified_files == [
        ".gitignore",
        ".openpilot/project_stack.json",
        "calculator.py",
    ]
    assert result.task_modified_files == ["calculator.py"]
    assert result.system_generated_files == [
        ".gitignore",
        ".openpilot/project_stack.json",
    ]


def test_benchmark_runner_handles_readonly_and_boundary_oracles() -> None:
    def oracle_executor(goal: str, context: dict[str, object]) -> dict[str, object]:
        if "禁止修改" in goal:
            return {"status": "blocked", "trajectory_review_completed": True}
        return {"status": "success", "trajectory_review_completed": True}

    runner = BenchmarkRunner(oracle_executor)
    cases = load_benchmark_cases()
    readonly = next(case for case in cases if case.case_id == "calculator_read_before_write")
    boundary = next(case for case in cases if case.case_id == "calculator_out_of_scope_write")

    results = runner.run_cases([readonly, boundary])

    assert [result.passed for result in results] == [True, True]
    assert results[0].modified_files == []
    assert results[1].runtime_status == "blocked"


def test_benchmark_runner_requires_explicit_workspace_binding_for_non_fixture_case() -> None:
    case = next(case for case in load_benchmark_cases() if case.case_id == "openpilot_architecture_readonly")

    with pytest.raises(BenchmarkRunnerError, match="workspace_root"):
        BenchmarkRunner(lambda _goal, _context: {"success": True}).run_case(case)


def test_benchmark_runner_can_use_explicit_readonly_workspace(tmp_path) -> None:
    for relative_path in ("src/ui/cli.py", "src/autonomous_iteration/intelligent_autopilot.py"):
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# fixture\n", encoding="utf-8")
    case = next(case for case in load_benchmark_cases() if case.case_id == "openpilot_architecture_readonly")

    result = BenchmarkRunner(
        lambda _goal, _context: {"status": "success", "trajectory_review_completed": True},
        workspace_root=tmp_path,
    ).run_case(case)

    assert result.passed is True
    assert result.modified_files == []


def test_process_cost_extracts_event_counts_time_retries_and_tokens() -> None:
    events = [
        {
            "event_type": "task_pool_item_started",
            "created_at": "2026-08-18T10:00:00+00:00",
            "payload": {"started_at": "2026-08-18T10:00:00+00:00"},
        },
        {"event_type": "llm_requested", "payload": {}},
        {
            "event_type": "llm_responded",
            "payload": {
                "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}
            },
        },
        {"event_type": "tool_called", "payload": {}},
        {
            "event_type": "tool_succeeded",
            "payload": {"duration_seconds": 0.5, "retry_count": 1, "attempts_used": 2},
        },
        {"event_type": "verification_state_changed", "payload": {}},
        {
            "event_type": "task_pool_item_finished",
            "created_at": "2026-08-18T10:00:02.500000+00:00",
            "payload": {"finished_at": "2026-08-18T10:00:02.500000+00:00"},
        },
    ]

    cost = extract_process_cost(events)

    assert cost.event_count == 7
    assert cost.tool_calls == 1
    assert cost.tool_successes == 1
    assert cost.tool_failures == 0
    assert cost.llm_requests == 1
    assert cost.llm_responses == 1
    assert cost.retry_count == 1
    assert cost.verification_state_changes == 1
    assert cost.elapsed_seconds == 2.5
    assert cost.tool_duration_seconds == 0.5
    assert cost.prompt_tokens == 10
    assert cost.completion_tokens == 3
    assert cost.total_tokens == 13


def test_benchmark_suite_runner_repeats_each_case_without_merging_trajectories(tmp_path) -> None:
    protocol = {
        "protocol_id": "test-protocol",
        "version": "1",
        "repeat_count": 3,
        "temperature": 0.0,
        "cache_enabled": False,
        "no_total_score": True,
        "primary_metrics": ["acceptance_pass_rate", "process_cost"],
    }
    case = next(case for case in load_benchmark_cases() if case.case_id == "calculator_read_before_write")

    suite = BenchmarkSuiteRunner(
        lambda _goal, _context: {"status": "success", "trajectory_review_completed": True},
        protocol=BenchmarkProtocol.model_validate(protocol),
        trajectory_root=tmp_path / "trajectories",
    ).run_suite([case])

    assert [run.repeat_index for run in suite.runs] == [1, 2, 3]
    assert [run.process_cost.event_count for run in suite.runs] == [2, 2, 2]
    assert len(list((tmp_path / "trajectories").rglob("events.jsonl"))) == 3


def test_benchmark_suite_runner_can_bind_executor_to_each_recorder(tmp_path) -> None:
    recorder_paths: list[str] = []
    case = next(case for case in load_benchmark_cases() if case.case_id == "calculator_read_before_write")
    protocol = BenchmarkProtocol(
        protocol_id="test-protocol",
        version="1",
        repeat_count=2,
        temperature=0.0,
        cache_enabled=False,
        no_total_score=True,
        primary_metrics=["acceptance_pass_rate"],
    )

    def executor_factory(recorder):
        recorder_paths.append(str(recorder.data_dir))

        def executor(_goal: str, _context: dict[str, object]) -> dict[str, object]:
            return {"status": "success", "trajectory_review_completed": True}

        return executor

    suite = BenchmarkSuiteRunner(
        protocol=protocol,
        executor_factory=executor_factory,
        trajectory_root=tmp_path / "trajectories",
    ).run_suite([case])

    assert len(suite.runs) == 2
    assert len(recorder_paths) == 2
    assert len(set(recorder_paths)) == 2


def test_benchmark_suite_runner_can_bind_workspace_to_each_case_and_repeat(tmp_path) -> None:
    case = next(case for case in load_benchmark_cases() if case.case_id == "openpilot_architecture_readonly")
    protocol = BenchmarkProtocol(
        protocol_id="test-protocol",
        version="1",
        repeat_count=2,
        temperature=0.0,
        cache_enabled=False,
        no_total_score=True,
        primary_metrics=["acceptance_pass_rate"],
    )
    workspace_paths: list[Path] = []

    def workspace_factory(selected_case, repeat_index):
        workspace = tmp_path / f"workspace-{selected_case.case_id}-{repeat_index}"
        for relative_path in selected_case.acceptance.required_files:
            path = workspace / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# fixture\n", encoding="utf-8")
        workspace_paths.append(workspace)
        return workspace

    suite = BenchmarkSuiteRunner(
        lambda _goal, _context: {"status": "success", "trajectory_review_completed": True},
        protocol=protocol,
        workspace_factory=workspace_factory,
        trajectory_root=tmp_path / "trajectories",
    ).run_suite([case])

    assert [run.passed for run in suite.runs] == [True, True]
    assert workspace_paths == [
        tmp_path / "workspace-openpilot_architecture_readonly-1",
        tmp_path / "workspace-openpilot_architecture_readonly-2",
    ]


def test_baseline_candidate_report_exposes_metric_deltas_without_total_score(tmp_path) -> None:
    protocol = BenchmarkProtocol(
        protocol_id="test-protocol",
        version="1",
        repeat_count=2,
        temperature=0.0,
        cache_enabled=False,
        no_total_score=True,
        primary_metrics=["acceptance_pass_rate", "safety_violation_rate", "process_cost"],
    )
    case = next(case for case in load_benchmark_cases() if case.case_id == "calculator_read_before_write")
    baseline = BenchmarkSuiteRunner(
        lambda _goal, _context: {"status": "success", "trajectory_review_completed": True},
        protocol=protocol,
        trajectory_root=tmp_path / "baseline",
    ).run_suite([case])
    candidate = BenchmarkSuiteRunner(
        lambda _goal, _context: {"status": "failed"},
        protocol=protocol,
        trajectory_root=tmp_path / "candidate",
    ).run_suite([case])

    baseline_report = build_suite_report(baseline)
    candidate_report = build_suite_report(candidate)
    comparison = compare_suite_reports(baseline_report, candidate_report)

    assert baseline_report.acceptance_pass_rate == 1.0
    assert candidate_report.acceptance_pass_rate == 0.0
    assert comparison.case_comparisons[0].acceptance_pass_rate_delta == -1.0
    assert comparison.case_comparisons[0].safety_violation_rate_delta == 0.0
    assert not hasattr(comparison, "total_score")


def test_boundary_report_keeps_safety_and_blocked_termination_as_separate_rates(tmp_path) -> None:
    protocol = BenchmarkProtocol(
        protocol_id="test-boundary-protocol",
        version="1",
        repeat_count=2,
        temperature=0.0,
        cache_enabled=False,
        no_total_score=True,
        primary_metrics=["acceptance_pass_rate"],
    )
    case = next(case for case in load_benchmark_cases() if case.case_id == "calculator_out_of_scope_write")
    baseline = BenchmarkSuiteRunner(
        lambda _goal, _context: {"status": "blocked", "trajectory_review_completed": True},
        protocol=protocol,
        trajectory_root=tmp_path / "baseline-boundary",
    ).run_suite([case])
    candidate = BenchmarkSuiteRunner(
        lambda _goal, _context: {"status": "failed", "trajectory_review_completed": True},
        protocol=protocol,
        trajectory_root=tmp_path / "candidate-boundary",
    ).run_suite([case])

    baseline_report = build_suite_report(baseline)
    candidate_report = build_suite_report(candidate)
    comparison = compare_suite_reports(baseline_report, candidate_report)

    assert baseline_report.safe_no_task_modification_rate == 1.0
    assert baseline_report.explicit_blocked_termination_rate == 1.0
    assert candidate_report.safe_no_task_modification_rate == 1.0
    assert candidate_report.explicit_blocked_termination_rate == 0.0
    assert comparison.safe_no_task_modification_rate_delta == 0.0
    assert comparison.explicit_blocked_termination_rate_delta == -1.0
