"""Strict development-only three-arm comparison and trajectory gates."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .contracts import BudgetLimits, ExperimentArm, ExperimentResult


_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_THREE_ARMS = {
    ExperimentArm.FIXED_ORDER,
    ExperimentArm.MODEL_DIRECTED,
    ExperimentArm.ACTIVE,
}


@dataclass(frozen=True)
class ThreeArmTrajectoryReceipt:
    """Arm-neutral evidence needed before outcome or cost comparison."""

    arm: ExperimentArm
    result: ExperimentResult
    provider_provenance_complete: bool
    budget_accounting_complete: bool
    tool_trace_complete: bool
    false_success: bool
    scope_violation: bool
    indeterminate_replay: bool
    diagnostic_decision_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.arm not in _THREE_ARMS:
            raise ValueError("trajectory receipt arm is outside the three-arm interface")
        if self.result.arm != self.arm:
            raise ValueError("trajectory receipt arm differs from its result")
        if len(set(self.diagnostic_decision_ids)) != len(
            self.diagnostic_decision_ids
        ):
            raise ValueError("diagnostic decision IDs must be unique")
        if self.arm == ExperimentArm.ACTIVE and not self.diagnostic_decision_ids:
            raise ValueError("active trajectory requires a diagnostic decision")

    @property
    def safety_clear(self) -> bool:
        return not (
            self.false_success
            or self.scope_violation
            or self.indeterminate_replay
        )

    @property
    def trajectory_complete(self) -> bool:
        return (
            self.provider_provenance_complete
            and self.budget_accounting_complete
            and self.tool_trace_complete
        )

    @property
    def verified_task_success(self) -> bool:
        return bool(self.result.evaluation.get("verified_task_success"))


@dataclass(frozen=True)
class ThreeArmComparison:
    """One matched fixed/model-directed/active development comparison."""

    task_id: str
    seed: int
    run_order: tuple[ExperimentArm, ...]
    model_fingerprint: str
    tool_surface_fingerprint: str
    evaluator_fingerprint: str
    budget: BudgetLimits
    receipts: dict[ExperimentArm, ThreeArmTrajectoryReceipt]

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("three-arm task ID must not be blank")
        if len(self.run_order) != 3 or set(self.run_order) != _THREE_ARMS:
            raise ValueError("three-arm run order must contain each arm exactly once")
        if set(self.receipts) != _THREE_ARMS:
            raise ValueError("three-arm receipts must contain each arm exactly once")
        for arm, receipt in self.receipts.items():
            if receipt.arm != arm:
                raise ValueError("three-arm receipt key differs from receipt identity")
        fingerprints = (
            self.model_fingerprint,
            self.tool_surface_fingerprint,
            self.evaluator_fingerprint,
        )
        if any(_SHA256_PATTERN.fullmatch(value) is None for value in fingerprints):
            raise ValueError("three-arm fingerprints must be canonical sha256 values")

    @property
    def primary_arms(self) -> tuple[ExperimentArm, ExperimentArm]:
        return (ExperimentArm.MODEL_DIRECTED, ExperimentArm.ACTIVE)

    @property
    def safety_gate_passed(self) -> bool:
        return all(receipt.safety_clear for receipt in self.receipts.values())

    @property
    def trajectory_gate_passed(self) -> bool:
        return all(receipt.trajectory_complete for receipt in self.receipts.values())

    @property
    def budget_gate_passed(self) -> bool:
        return all(
            not self.budget.exceeded_limits(receipt.result.total_usage)
            for receipt in self.receipts.values()
        )

    @property
    def paired_improvement(self) -> bool:
        model = self.receipts[ExperimentArm.MODEL_DIRECTED].verified_task_success
        active = self.receipts[ExperimentArm.ACTIVE].verified_task_success
        return active and not model

    @property
    def paired_regression(self) -> bool:
        model = self.receipts[ExperimentArm.MODEL_DIRECTED].verified_task_success
        active = self.receipts[ExperimentArm.ACTIVE].verified_task_success
        return model and not active

    @property
    def cost_comparison_admissible(self) -> bool:
        model = self.receipts[ExperimentArm.MODEL_DIRECTED].verified_task_success
        active = self.receipts[ExperimentArm.ACTIVE].verified_task_success
        return (
            model == active
            and self.safety_gate_passed
            and self.trajectory_gate_passed
            and self.budget_gate_passed
        )


__all__ = ["ThreeArmComparison", "ThreeArmTrajectoryReceipt"]
