from __future__ import annotations

from pathlib import Path

from autonomous_iteration.models import EvaluationResult, ProjectStateSnapshot
from autonomous_iteration.project_diagnosis import ProjectDiagnoser
from metadata import (
    ProjectObjectiveMetadata,
    ReferenceInsightMetadata,
    SuccessMetricMetadata,
    ValidationIssueMetadata,
)


def _state(project: Path, goal: str, *, readme: str = "", memories: list[dict] | None = None) -> ProjectStateSnapshot:
    return ProjectStateSnapshot(
        project_path=str(project),
        goal=goal,
        written_files=[str(project / "app.py")],
        safe_target_files=[str(project / "app.py")],
        readme_summary=readme,
        file_summaries=[{"name": "app.py", "suffix": ".py", "preview": "def main(): pass"}],
        module_summaries=["app.py (.py, 24 chars)"],
        memory_records=memories or [],
    )


def _passing_evaluation() -> EvaluationResult:
    return EvaluationResult(
        validation_passed=True,
        runnable=True,
        has_blocking_bugs=False,
        summary="Project validation passed.",
        improvement_opportunities=["Add clearer workflow feedback."],
        recommended_actions=["Improve primary workflow feedback."],
    )


def test_project_diagnoser_infers_objectives_for_software_surfaces(tmp_path) -> None:
    diagnoses = {
        "web": ProjectDiagnoser(allow_reference_search=False).diagnose(
            project_state=_state(tmp_path, "Build a responsive web dashboard", readme="Run the browser app."),
            evaluation=_passing_evaluation(),
            iteration=0,
        ),
        "cli": ProjectDiagnoser(allow_reference_search=False).diagnose(
            project_state=_state(tmp_path, "Build a CLI CSV cleaner", readme="python app.py --input data.csv"),
            evaluation=_passing_evaluation(),
            iteration=0,
        ),
        "library": ProjectDiagnoser(allow_reference_search=False).diagnose(
            project_state=_state(tmp_path, "Create a Python library package API", readme="Import the package."),
            evaluation=_passing_evaluation(),
            iteration=0,
        ),
        "data": ProjectDiagnoser(allow_reference_search=False).diagnose(
            project_state=_state(tmp_path, "Create a CSV analysis script", readme="Generate the report."),
            evaluation=_passing_evaluation(),
            iteration=0,
        ),
    }

    assert diagnoses["web"].objective.delivery_surface == "browser"
    assert diagnoses["cli"].objective.project_type == "cli_tool"
    assert diagnoses["library"].objective.delivery_surface == "python_api"
    assert diagnoses["data"].objective.project_type == "data_tool"
    assert all(item.selected_candidate is not None for item in diagnoses.values())


def test_project_diagnoser_explicit_objective_and_metrics_override_inference(tmp_path) -> None:
    objective = ProjectObjectiveMetadata(
        goal="Ship the SDK",
        project_type="developer_sdk",
        delivery_surface="typed_api",
        target_users=["integrators"],
        core_value=["Stable integration API."],
        confidence=0.99,
    )
    metric = SuccessMetricMetadata(
        metric_id="typed_contract",
        name="Typed contract",
        dimension="user_value",
        target="Public API is typed.",
        required=True,
        satisfied=False,
        confidence=0.98,
    )
    diagnosis = ProjectDiagnoser(
        objective_override=objective,
        metric_overrides=[metric],
        allow_reference_search=False,
    ).diagnose(
        project_state=_state(tmp_path, "Generic project"),
        evaluation=_passing_evaluation(),
        iteration=1,
    )

    assert diagnosis.objective.project_type == "developer_sdk"
    assert [item.metric_id for item in diagnosis.success_metrics] == ["typed_contract"]


def test_project_diagnoser_prioritizes_blocking_validation_issue(tmp_path) -> None:
    evaluation = EvaluationResult(
        validation_passed=False,
        runnable=False,
        has_blocking_bugs=True,
        summary="Smoke validation failed.",
        validation_errors=["NameError during command"],
        validation_issues=[
            ValidationIssueMetadata(
                category="runtime_error",
                message="NameError during command",
                recommended_action="Fix the runtime failure.",
            )
        ],
    )
    diagnosis = ProjectDiagnoser(allow_reference_search=False).diagnose(
        project_state=_state(tmp_path, "Build an automation script"),
        evaluation=evaluation,
        iteration=0,
    )

    assert diagnosis.selected_candidate is not None
    assert diagnosis.selected_candidate.candidate_type == "repair"
    assert diagnosis.selected_candidate.dimension == "reliability"


def test_project_diagnoser_uses_reference_provider_only_for_low_evidence(tmp_path) -> None:
    calls: list[str] = []

    def provider(query, state, objective):
        calls.append(query)
        return [
            ReferenceInsightMetadata(
                query=query,
                summary="Reference practice",
                best_practices=["Expose a concrete primary workflow."],
                source_notes=["reference"],
                confidence=0.6,
            )
        ]

    diagnosis = ProjectDiagnoser(reference_provider=provider).diagnose(
        project_state=_state(tmp_path, "Project"),
        evaluation=EvaluationResult(
            validation_passed=True,
            runnable=True,
            has_blocking_bugs=False,
            summary="Project validation passed.",
        ),
        iteration=0,
    )
    confident = ProjectDiagnoser(reference_provider=provider).diagnose(
        project_state=_state(tmp_path, "Build a responsive web dashboard", readme="A browser dashboard for teams."),
        evaluation=_passing_evaluation(),
        iteration=1,
        analysis_seed={"recommended_actions": ["Add filter feedback.", "Add loading state."]},
    )

    assert diagnosis.reference_insights
    assert len(calls) == 1
    assert confident.reference_insights == []

