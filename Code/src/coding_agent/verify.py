"""Verification policy for the standalone coding agent."""

from __future__ import annotations

from typing import Any, Literal, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field

from coding_agent.context import CodingContext
from coding_agent.contract import CodingActionKind, CodingActionResult, CodingTask


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["passed", "failed", "blocked", "pending"] = "pending"
    success: bool | None = None
    summary: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class Verifier(Protocol):
    def verify(
        self,
        task: CodingTask,
        context: CodingContext,
        action_result: CodingActionResult,
        history: Sequence[CodingActionResult],
    ) -> VerificationResult:
        ...


class SimpleVerifier:
    """Keep the verification rule small and explicit."""

    def verify(
        self,
        task: CodingTask,
        context: CodingContext,
        action_result: CodingActionResult,
        history: Sequence[CodingActionResult],
    ) -> VerificationResult:
        action_kind = action_result.action.kind
        if action_kind == CodingActionKind.RUN:
            passed = action_result.success and action_result.exit_code == 0
            return VerificationResult(
                status="passed" if passed else "failed",
                success=passed,
                summary=action_result.summary or ("validation passed" if passed else "validation failed"),
                details={"exit_code": action_result.exit_code},
            )
        if action_kind in {CodingActionKind.WRITE, CodingActionKind.PATCH}:
            if task.validation_command:
                return VerificationResult(
                    status="pending",
                    success=None,
                    summary="change applied; validation pending",
                    details={"next_step": "run_validation"},
                )
            return VerificationResult(
                status="passed",
                success=True,
                summary="change applied",
                details={"target_path": task.target_path},
            )
        if action_kind == CodingActionKind.READ:
            return VerificationResult(status="pending", success=None, summary="target inspected")
        if task.draft_text and context.current_text.strip() == task.draft_text.strip():
            return VerificationResult(status="passed", success=True, summary="target already matches draft")
        return VerificationResult(status="blocked", success=False, summary=action_result.summary or "no completion path")
