from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from mini_swe_active_iteration.usability_canary import (
    CanaryImplementation,
    CanaryPath,
    CanaryRunReceipt,
    CanaryTaskCategory,
    evaluate_usability_canary,
)


_PATHS = {
    CanaryTaskCategory.RUNTIME_CONFIGURATION: CanaryPath.RESPONSE_ONLY,
    CanaryTaskCategory.ORDINARY_AMBIGUOUS: CanaryPath.RESPONSE_ONLY,
    CanaryTaskCategory.READ_ONLY_REPOSITORY: CanaryPath.EVIDENCE_SEEKING,
    CanaryTaskCategory.SINGLE_FILE_REPAIR: CanaryPath.SINGLE_TASK,
    CanaryTaskCategory.MULTI_FILE_DEPENDENCY: CanaryPath.DECOMPOSED,
    CanaryTaskCategory.VALIDATION_FAILURE_REPAIR: CanaryPath.SINGLE_TASK,
    CanaryTaskCategory.SCHEMA_UNKNOWN_TOOL: CanaryPath.SINGLE_TASK,
    CanaryTaskCategory.CONFIRM_REJECT: CanaryPath.EVIDENCE_SEEKING,
    CanaryTaskCategory.INTERRUPT: CanaryPath.SINGLE_TASK,
    CanaryTaskCategory.CHECKPOINT_RESUME: CanaryPath.SINGLE_TASK,
    CanaryTaskCategory.OPTIONAL_ENHANCEMENT: CanaryPath.SINGLE_TASK,
    CanaryTaskCategory.REQUIRED_ENHANCEMENT: CanaryPath.SINGLE_TASK,
}


def _receipt(
    category: CanaryTaskCategory,
    implementation: CanaryImplementation,
    *,
    scenario_passed: bool = True,
    core_success: bool | None = True,
) -> CanaryRunReceipt:
    return CanaryRunReceipt(
        run_id=f"{implementation.value}-{category.value}",
        category=category,
        path=_PATHS[category],
        implementation=implementation,
        scenario_passed=scenario_passed,
        core_success=core_success,
        traceback_leakage_count=0,
        false_success_count=0,
        scope_violation_count=0,
        duplicate_mutation_count=0,
        indeterminate_replay_count=0,
        credential_leakage_count=0,
        provider_calls=1,
        total_tokens=100,
        wall_time_ms=10,
        evidence_ids=(f"pytest:{category.value}",),
        evidence_hash="sha256:" + "a" * 64,
    )


def _matrix() -> tuple[CanaryRunReceipt, ...]:
    return tuple(
        _receipt(category, implementation)
        for category in CanaryTaskCategory
        for implementation in CanaryImplementation
    )


def test_exact_twelve_category_matrix_passes_hard_gates_before_cost() -> None:
    verdict = evaluate_usability_canary(
        _matrix(),
        post_core_consumer_available=False,
        protocol_repair_negative_gate_passed=True,
    )

    assert verdict.category_coverage_passed is True
    assert verdict.path_coverage_passed is True
    assert verdict.hard_gate_passed is True
    assert verdict.core_non_regression_passed is True
    assert verdict.cost_comparison_admissible is True
    assert verdict.unified_entry_default_on is True
    assert verdict.governed_decomposition_default_on is True
    assert verdict.protocol_repair_default_on is True
    assert verdict.core_post_core_integration_default_on is False
    assert verdict.legacy_pipeline_decision == "default_off_rollback_only"


def test_missing_category_or_lane_fails_closed() -> None:
    matrix = _matrix()

    with pytest.raises(ValueError, match="exactly one legacy and candidate"):
        evaluate_usability_canary(
            matrix[:-1],
            post_core_consumer_available=False,
            protocol_repair_negative_gate_passed=True,
        )


@pytest.mark.parametrize(
    "field",
    (
        "traceback_leakage_count",
        "false_success_count",
        "scope_violation_count",
        "duplicate_mutation_count",
        "indeterminate_replay_count",
        "credential_leakage_count",
    ),
)
def test_each_candidate_safety_metric_is_a_non_compensating_hard_gate(field: str) -> None:
    matrix = list(_matrix())
    candidate_index = next(
        index
        for index, receipt in enumerate(matrix)
        if receipt.implementation == CanaryImplementation.CANDIDATE
    )
    matrix[candidate_index] = replace(matrix[candidate_index], **{field: 1})

    verdict = evaluate_usability_canary(
        matrix,
        post_core_consumer_available=True,
        protocol_repair_negative_gate_passed=True,
    )

    assert verdict.hard_gate_passed is False
    assert verdict.cost_comparison_admissible is False
    assert verdict.unified_entry_default_on is False
    assert verdict.governed_decomposition_default_on is False
    assert verdict.protocol_repair_default_on is False
    assert verdict.core_post_core_integration_default_on is False
    assert verdict.legacy_pipeline_decision == "retain_default"


def test_core_regression_or_quality_failure_blocks_cost_and_rollout() -> None:
    matrix = list(_matrix())
    index = next(
        index
        for index, receipt in enumerate(matrix)
        if receipt.category == CanaryTaskCategory.SINGLE_FILE_REPAIR
        and receipt.implementation == CanaryImplementation.CANDIDATE
    )
    matrix[index] = replace(
        matrix[index],
        scenario_passed=False,
        core_success=False,
        provider_calls=0,
        total_tokens=0,
        wall_time_ms=1,
    )

    verdict = evaluate_usability_canary(
        matrix,
        post_core_consumer_available=True,
        protocol_repair_negative_gate_passed=True,
    )

    assert verdict.core_non_regression_passed is False
    assert verdict.hard_gate_passed is False
    assert verdict.cost_comparison_admissible is False


def test_protocol_and_post_core_switches_require_their_separate_gates() -> None:
    no_protocol = evaluate_usability_canary(
        _matrix(),
        post_core_consumer_available=True,
        protocol_repair_negative_gate_passed=False,
    )
    no_consumer = evaluate_usability_canary(
        _matrix(),
        post_core_consumer_available=False,
        protocol_repair_negative_gate_passed=True,
    )

    assert no_protocol.protocol_repair_default_on is False
    assert no_protocol.core_post_core_integration_default_on is True
    assert no_consumer.protocol_repair_default_on is True
    assert no_consumer.core_post_core_integration_default_on is False


def test_receipt_rejects_self_attested_or_unbounded_evidence() -> None:
    receipt = _receipt(
        CanaryTaskCategory.RUNTIME_CONFIGURATION,
        CanaryImplementation.CANDIDATE,
    )
    with pytest.raises(ValueError, match="evidence hash"):
        replace(receipt, evidence_hash="not-a-hash")
    with pytest.raises(ValueError, match="evidence IDs"):
        replace(receipt, evidence_ids=())
    with pytest.raises(ValueError, match="literal non-negative integers"):
        replace(receipt, false_success_count=True)


def test_committed_result_is_bound_to_protocol_and_non_compensating_verdict() -> None:
    package_root = Path(__file__).resolve().parents[1]
    protocol_path = package_root / "CRU_7_USABILITY_CANARY_PROTOCOL_V1.json"
    result_path = package_root / "CRU_7_USABILITY_CANARY_RESULT_V1.json"
    protocol_bytes = protocol_path.read_bytes()
    protocol = json.loads(protocol_bytes)
    result = json.loads(result_path.read_text(encoding="utf-8"))

    assert len(protocol["tasks"]) == 12
    assert {task["path"] for task in protocol["tasks"]} == {
        path.value for path in CanaryPath
    }
    assert result["protocol"]["sha256"] == (
        "sha256:" + hashlib.sha256(protocol_bytes).hexdigest()
    )
    assert result["task_matrix"]["passed_categories"] == 12
    assert result["task_matrix"]["covered_paths"] == 4
    assert all(value == 0 for key, value in result["hard_metrics"].items() if key.endswith("_count"))
    assert result["hard_metrics"]["core_non_regression_passed"] is True
    assert result["cost_metrics"]["admissible"] is True
    assert result["cost_metrics"]["comparison_claimed"] is False
    assert result["rollout"]["model_visible_protocol_repair"] == "canary_only"
    assert result["rollout"]["core_post_core_integration"] == "canary_only"
