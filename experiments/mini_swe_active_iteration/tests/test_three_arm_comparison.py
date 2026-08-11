from __future__ import annotations

import pytest

from mini_swe_active_iteration.contracts import (
    BudgetLimits,
    ExperimentArm,
    ExperimentResult,
    Usage,
)
from mini_swe_active_iteration.three_arm import (
    ThreeArmComparison,
    ThreeArmTrajectoryReceipt,
)


def _result(arm: ExperimentArm, *, success: bool = True) -> ExperimentResult:
    return ExperimentResult(
        arm=arm,
        messages=(),
        commands=(),
        submission="done",
        agent_usage=Usage(provider_calls=1),
        controller_usage=Usage(),
        total_usage=Usage(provider_calls=1),
        evaluation={"verified_task_success": success},
        trajectory={"trajectory_format": "mini-swe-agent-1.1"},
    )


def _receipt(
    arm: ExperimentArm,
    *,
    success: bool = True,
    false_success: bool = False,
) -> ThreeArmTrajectoryReceipt:
    return ThreeArmTrajectoryReceipt(
        arm=arm,
        result=_result(arm, success=success),
        provider_provenance_complete=True,
        budget_accounting_complete=True,
        tool_trace_complete=True,
        false_success=false_success,
        scope_violation=False,
        indeterminate_replay=False,
        diagnostic_decision_ids=("decision-1",)
        if arm == ExperimentArm.ACTIVE
        else (),
    )


def _comparison(*, active_success: bool = True, model_success: bool = True):
    receipts = {
        ExperimentArm.FIXED_ORDER: _receipt(ExperimentArm.FIXED_ORDER),
        ExperimentArm.MODEL_DIRECTED: _receipt(
            ExperimentArm.MODEL_DIRECTED,
            success=model_success,
        ),
        ExperimentArm.ACTIVE: _receipt(
            ExperimentArm.ACTIVE,
            success=active_success,
        ),
    }
    return ThreeArmComparison(
        task_id="task-1",
        seed=7,
        run_order=(
            ExperimentArm.MODEL_DIRECTED,
            ExperimentArm.ACTIVE,
            ExperimentArm.FIXED_ORDER,
        ),
        model_fingerprint="sha256:" + "a" * 64,
        tool_surface_fingerprint="sha256:" + "b" * 64,
        evaluator_fingerprint="sha256:" + "c" * 64,
        budget=BudgetLimits(
            max_provider_calls=20,
            max_total_tokens=20_000,
            max_tool_calls=30,
            max_iterations=20,
        ),
        receipts=receipts,
    )


def test_three_arm_interface_binds_exact_primary_and_mechanism_arms() -> None:
    comparison = _comparison()

    assert set(comparison.receipts) == {
        ExperimentArm.FIXED_ORDER,
        ExperimentArm.MODEL_DIRECTED,
        ExperimentArm.ACTIVE,
    }
    assert comparison.primary_arms == (
        ExperimentArm.MODEL_DIRECTED,
        ExperimentArm.ACTIVE,
    )
    assert comparison.safety_gate_passed is True
    assert comparison.cost_comparison_admissible is True
    assert comparison.paired_improvement is False
    assert comparison.paired_regression is False


def test_three_arm_interface_rejects_missing_arm_and_unexplained_active_trace() -> None:
    comparison = _comparison()
    receipts = dict(comparison.receipts)
    receipts.pop(ExperimentArm.FIXED_ORDER)
    with pytest.raises(ValueError, match="exactly once"):
        ThreeArmComparison(
            task_id=comparison.task_id,
            seed=comparison.seed,
            run_order=comparison.run_order,
            model_fingerprint=comparison.model_fingerprint,
            tool_surface_fingerprint=comparison.tool_surface_fingerprint,
            evaluator_fingerprint=comparison.evaluator_fingerprint,
            budget=comparison.budget,
            receipts=receipts,
        )

    with pytest.raises(ValueError, match="diagnostic decision"):
        ThreeArmTrajectoryReceipt(
            arm=ExperimentArm.ACTIVE,
            result=_result(ExperimentArm.ACTIVE),
            provider_provenance_complete=True,
            budget_accounting_complete=True,
            tool_trace_complete=True,
            false_success=False,
            scope_violation=False,
            indeterminate_replay=False,
        )


def test_three_arm_cost_gate_is_non_compensatory() -> None:
    success_mismatch = _comparison(active_success=False, model_success=True)
    assert success_mismatch.paired_regression is True
    assert success_mismatch.cost_comparison_admissible is False

    comparison = _comparison()
    unsafe_receipts = dict(comparison.receipts)
    unsafe_receipts[ExperimentArm.ACTIVE] = _receipt(
        ExperimentArm.ACTIVE,
        false_success=True,
    )
    unsafe = ThreeArmComparison(
        task_id=comparison.task_id,
        seed=comparison.seed,
        run_order=comparison.run_order,
        model_fingerprint=comparison.model_fingerprint,
        tool_surface_fingerprint=comparison.tool_surface_fingerprint,
        evaluator_fingerprint=comparison.evaluator_fingerprint,
        budget=comparison.budget,
        receipts=unsafe_receipts,
    )
    assert unsafe.safety_gate_passed is False
    assert unsafe.cost_comparison_admissible is False
