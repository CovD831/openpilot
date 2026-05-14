"""Autonomy decision tool."""

from __future__ import annotations

from typing import Any

from models.autonomy_models import AutonomyDecision, AutonomyLevel, ConfidenceFactors
from models.tool_models import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolFailureMode,
    ToolInputSchema,
    ToolOutputSchema,
)


AUTONOMY_TOOL_DEFINITION = ToolDefinition(
    name="autonomy_tool",
    display_name="Autonomy Decision Tool",
    description="Decide whether a task step can run autonomously based on risk, task type, and confidence context.",
    version="1.0.0",
    capabilities=[],
    permission_level=PermissionLevel.LOW,
    input_schema=[
        ToolInputSchema(
            name="step_id",
            type="string",
            description="Identifier of the step being evaluated",
            required=False,
            default="unknown",
        ),
        ToolInputSchema(
            name="risk_level",
            type="string",
            description="Risk level: low, medium, high, or forbidden",
            required=True,
        ),
        ToolInputSchema(
            name="task_type",
            type="string",
            description="Task type such as coding, research, file_workflow, or unknown",
            required=False,
            default="unknown",
        ),
        ToolInputSchema(
            name="requires_user_input",
            type="boolean",
            description="Whether the step explicitly needs user-provided information",
            required=False,
            default=False,
        ),
        ToolInputSchema(
            name="memory_context",
            type="object",
            description="Optional confidence context from memory or prior executions",
            required=False,
            default={},
        ),
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="Autonomy decision and confidence factors",
        properties={
            "step_id": {"type": "string"},
            "should_ask_user": {"type": "boolean"},
            "autonomy_level": {"type": "string"},
            "confidence": {"type": "number"},
            "decision_reason": {"type": "string"},
            "intervention_reason": {"type": ["string", "null"]},
            "confidence_factors": {"type": "object"},
        },
    ),
    timeout_seconds=10,
    max_retries=0,
    failure_modes=[
        ToolFailureMode(
            error_type="invalid_input",
            description="Risk level or confidence context cannot be interpreted",
            recovery_strategy="Use one of: low, medium, high, forbidden",
        )
    ],
    tags=["autonomy", "risk", "confidence", "decision"],
    audit_required=True,
)


def autonomy_tool_executor(params: dict[str, Any]) -> dict[str, Any]:
    """Execute deterministic autonomy decision logic."""
    step_id = str(params.get("step_id") or "unknown")
    risk_level = str(params.get("risk_level") or "medium").lower()
    task_type = str(params.get("task_type") or "unknown").lower()
    requires_user_input = bool(params.get("requires_user_input", False))
    memory_context = params.get("memory_context") or {}
    if not isinstance(memory_context, dict):
        memory_context = {}

    historical_success = _bounded_float(memory_context.get("historical_success_rate"), 0.5)
    preference_match = _bounded_float(memory_context.get("preference_match_score"), 0.5)
    recency_bonus = min(0.1, _bounded_float(memory_context.get("recency_bonus"), 0.0))
    usage_frequency_bonus = min(0.1, _bounded_float(memory_context.get("usage_frequency_bonus"), 0.0))
    risk_penalty = _risk_penalty(risk_level)

    base_confidence = historical_success * 0.6 + preference_match * 0.4
    final_confidence = min(1.0, max(0.0, base_confidence * (1.0 - risk_penalty) + recency_bonus + usage_frequency_bonus))
    base_level = _base_autonomy_level(risk_level, task_type)
    autonomy_level, should_ask = _adjust_autonomy(base_level, final_confidence, risk_level)

    if requires_user_input:
        should_ask = True
        if autonomy_level == AutonomyLevel.AUTO_RUN_LOW_RISK:
            autonomy_level = AutonomyLevel.CONFIRM_EACH_TIME

    decision_reason = (
        f"Risk={risk_level}, task_type={task_type}, confidence={final_confidence:.2f}; "
        f"selected {autonomy_level.value}"
    )
    intervention_reason = None
    if should_ask:
        intervention_reason = _intervention_reason(risk_level, final_confidence, requires_user_input)

    factors = ConfidenceFactors(
        historical_success_rate=historical_success,
        preference_match_score=preference_match,
        risk_penalty=risk_penalty,
        recency_bonus=recency_bonus,
        usage_frequency_bonus=usage_frequency_bonus,
        final_confidence=final_confidence,
    )
    decision = AutonomyDecision(
        step_id=step_id,
        should_ask_user=should_ask,
        autonomy_level=autonomy_level,
        confidence=final_confidence,
        preference_basis=[str(item) for item in memory_context.get("preference_basis", [])]
        if isinstance(memory_context.get("preference_basis"), list)
        else [],
        decision_reason=decision_reason,
        intervention_reason=intervention_reason,
        requires_user_input=requires_user_input,
    )

    return {
        **decision.model_dump(mode="json"),
        "confidence_factors": factors.model_dump(mode="json"),
    }


def _bounded_float(value: Any, default: float) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return default


def _risk_penalty(risk_level: str) -> float:
    return {
        "low": 0.0,
        "medium": 0.2,
        "high": 0.5,
        "forbidden": 1.0,
    }.get(risk_level, 0.5)


def _base_autonomy_level(risk_level: str, task_type: str) -> AutonomyLevel:
    if risk_level == "forbidden":
        return AutonomyLevel.MANUAL_REQUIRED
    if risk_level == "high":
        return AutonomyLevel.CONFIRM_EACH_TIME
    if task_type in {"research", "document_summary"}:
        return AutonomyLevel.NOTIFY_THEN_RUN
    if task_type in {"communication", "unknown"}:
        return AutonomyLevel.MANUAL_REQUIRED
    if risk_level == "low":
        return AutonomyLevel.AUTO_RUN_LOW_RISK
    if risk_level == "medium":
        return AutonomyLevel.NOTIFY_THEN_RUN
    return AutonomyLevel.CONFIRM_EACH_TIME


def _adjust_autonomy(
    base_level: AutonomyLevel,
    confidence: float,
    risk_level: str,
) -> tuple[AutonomyLevel, bool]:
    if risk_level in {"high", "forbidden"}:
        return base_level, True
    if confidence >= 0.7:
        if base_level in {AutonomyLevel.CONFIRM_EACH_TIME, AutonomyLevel.NOTIFY_THEN_RUN}:
            return AutonomyLevel.AUTO_RUN_LOW_RISK, False
    if confidence < 0.5:
        if base_level == AutonomyLevel.AUTO_RUN_LOW_RISK:
            return AutonomyLevel.NOTIFY_THEN_RUN, True
        if base_level == AutonomyLevel.NOTIFY_THEN_RUN:
            return AutonomyLevel.CONFIRM_EACH_TIME, True
    return base_level, base_level in {AutonomyLevel.MANUAL_REQUIRED, AutonomyLevel.CONFIRM_EACH_TIME}


def _intervention_reason(risk_level: str, confidence: float, requires_user_input: bool) -> str:
    if requires_user_input:
        return "Step requires user-provided information"
    if risk_level in {"high", "forbidden"}:
        return f"Risk level {risk_level} requires confirmation"
    if confidence < 0.5:
        return f"Low confidence ({confidence:.2f}) requires confirmation"
    return "User confirmation required"
