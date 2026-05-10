"""
Autonomy controller for OP-19.

Implements confidence calculation, autonomy level decision-making,
and feedback-driven learning.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from openpilot.autonomy_models import (
    AutonomyDecision,
    AutonomyLevel,
    AutonomyProfile,
    ConfidenceFactors,
    PreferenceSignal,
    UserFeedback,
)
from openpilot.memory_models import MemoryType
from openpilot.planner_models import RiskLevel, TaskType

if TYPE_CHECKING:
    from openpilot.memory_store import MemoryStore
    from openpilot.planner_models import PlanStep, TaskCard


class AutonomyController:
    """Controls autonomy decisions based on confidence and user preferences."""

    def __init__(
        self,
        memory_store: "MemoryStore | None" = None,
        autonomy_profile: AutonomyProfile | None = None,
    ):
        self.memory_store = memory_store
        self.profile = autonomy_profile or self._default_profile()

    def _default_profile(self) -> AutonomyProfile:
        """Create default autonomy profile with conservative settings."""
        return AutonomyProfile(
            task_type_autonomy={
                TaskType.RESEARCH.value: AutonomyLevel.NOTIFY_THEN_RUN,
                TaskType.DOCUMENT_SUMMARY.value: AutonomyLevel.NOTIFY_THEN_RUN,
                TaskType.PLANNING.value: AutonomyLevel.CONFIRM_EACH_TIME,
                TaskType.FILE_WORKFLOW.value: AutonomyLevel.CONFIRM_EACH_TIME,
                TaskType.CALENDAR_RELATED.value: AutonomyLevel.CONFIRM_EACH_TIME,
                TaskType.COMMUNICATION.value: AutonomyLevel.MANUAL_REQUIRED,
                TaskType.CODING.value: AutonomyLevel.CONFIRM_EACH_TIME,
                TaskType.UNKNOWN.value: AutonomyLevel.MANUAL_REQUIRED,
            },
            risk_level_autonomy={
                RiskLevel.LOW.value: AutonomyLevel.AUTO_RUN_LOW_RISK,
                RiskLevel.MEDIUM.value: AutonomyLevel.NOTIFY_THEN_RUN,
                RiskLevel.HIGH.value: AutonomyLevel.CONFIRM_EACH_TIME,
                RiskLevel.FORBIDDEN.value: AutonomyLevel.MANUAL_REQUIRED,
            },
            global_confidence_threshold=0.7,
        )

    def decide_autonomy(
        self,
        step: "PlanStep",
        task_card: "TaskCard",
        goal: str,
    ) -> AutonomyDecision:
        """
        Decide autonomy level for a step.

        Args:
            step: The plan step to evaluate
            task_card: The task card containing task type and risk level
            goal: The user's goal text

        Returns:
            AutonomyDecision with confidence and autonomy level
        """
        # Calculate confidence factors
        factors = self._calculate_confidence_factors(step, task_card, goal)

        # Determine base autonomy level from risk
        base_level = self._get_base_autonomy_level(step.risk_level, task_card.task_type)

        # Adjust based on confidence
        final_level, should_ask = self._adjust_autonomy_by_confidence(
            base_level, factors.final_confidence, step.risk_level
        )

        # Build decision
        decision_reason = self._build_decision_reason(base_level, final_level, factors)
        intervention_reason = None
        if should_ask:
            intervention_reason = self._build_intervention_reason(
                step.risk_level, factors.final_confidence
            )

        return AutonomyDecision(
            step_id=step.id,
            should_ask_user=should_ask,
            autonomy_level=final_level,
            confidence=factors.final_confidence,
            preference_basis=[],  # TODO: populate from memory retrieval
            decision_reason=decision_reason,
            intervention_reason=intervention_reason,
            requires_user_input=step.confirmation_required,
        )

    def _calculate_confidence_factors(
        self,
        step: "PlanStep",
        task_card: "TaskCard",
        goal: str,
    ) -> ConfidenceFactors:
        """Calculate confidence based on multiple factors."""
        # Historical success rate (from memory)
        historical_success = self._get_historical_success_rate(
            task_card.task_type, step.risk_level
        )

        # Preference match score (from memory)
        preference_match = self._get_preference_match_score(task_card, goal)

        # Risk penalty (higher risk = lower confidence)
        risk_penalty = self._calculate_risk_penalty(step.risk_level)

        # Recency bonus (recent successes boost confidence)
        recency_bonus = self._calculate_recency_bonus(task_card.task_type)

        # Usage frequency bonus (frequently used patterns boost confidence)
        frequency_bonus = self._calculate_frequency_bonus(task_card.task_type)

        # Calculate final confidence
        # Base confidence from historical success and preference match
        base_confidence = (historical_success * 0.6 + preference_match * 0.4)

        # Apply risk penalty (multiplicative)
        confidence_after_risk = base_confidence * (1.0 - risk_penalty)

        # Add bonuses (additive, capped)
        final_confidence = min(
            1.0, confidence_after_risk + recency_bonus + frequency_bonus
        )

        return ConfidenceFactors(
            historical_success_rate=historical_success,
            preference_match_score=preference_match,
            risk_penalty=risk_penalty,
            recency_bonus=recency_bonus,
            usage_frequency_bonus=frequency_bonus,
            final_confidence=final_confidence,
        )

    def _get_historical_success_rate(
        self, task_type: TaskType, risk_level: RiskLevel
    ) -> float:
        """Get historical success rate for similar tasks from memory."""
        if not self.memory_store:
            return 0.5  # Default neutral confidence

        # Query task memory for similar tasks
        query_result = self.memory_store.query(
            query=f"{task_type.value} {risk_level.value}",
            memory_types=[MemoryType.TASK],
            limit=10,
        )

        if not query_result.memories:
            return 0.5  # No history, neutral confidence

        # Calculate success rate from memories
        # Memories with high confidence indicate past successes
        total_confidence = sum(m.confidence for m in query_result.memories)
        avg_confidence = total_confidence / len(query_result.memories)

        return avg_confidence

    def _get_preference_match_score(self, task_card: "TaskCard", goal: str) -> float:
        """Get preference match score from long-term memory."""
        if not self.memory_store:
            return 0.5  # Default neutral

        # Query long-term preferences
        query_result = self.memory_store.query(
            query=f"{task_card.task_type.value} {goal}",
            memory_types=[MemoryType.LONG_TERM],
            limit=5,
        )

        if not query_result.memories:
            return 0.5  # No preferences, neutral

        # High-confidence preferences indicate strong match
        total_confidence = sum(m.confidence for m in query_result.memories)
        avg_confidence = total_confidence / len(query_result.memories)

        return avg_confidence

    def _calculate_risk_penalty(self, risk_level: RiskLevel) -> float:
        """Calculate confidence penalty based on risk level."""
        risk_penalties = {
            RiskLevel.LOW: 0.0,
            RiskLevel.MEDIUM: 0.2,
            RiskLevel.HIGH: 0.5,
            RiskLevel.FORBIDDEN: 1.0,  # Complete penalty
        }
        return risk_penalties.get(risk_level, 0.5)

    def _calculate_recency_bonus(self, task_type: TaskType) -> float:
        """Calculate bonus for recent similar successes."""
        if not self.memory_store:
            return 0.0

        # Query recent task memories (last 7 days)
        query_result = self.memory_store.query(
            query=task_type.value,
            memory_types=[MemoryType.TASK],
            limit=5,
        )

        if not query_result.memories:
            return 0.0

        # Check if any recent memories (within 7 days)
        now = datetime.now(timezone.utc)
        recent_count = 0
        for memory in query_result.memories:
            if memory.last_used:
                try:
                    last_used = datetime.fromisoformat(memory.last_used)
                    # Make naive datetime timezone-aware (assume UTC)
                    if last_used.tzinfo is None:
                        last_used = last_used.replace(tzinfo=timezone.utc)
                    if (now - last_used) < timedelta(days=7):
                        recent_count += 1
                except ValueError:
                    pass

        # Bonus scales with recent usage
        return min(0.1, recent_count * 0.02)

    def _calculate_frequency_bonus(self, task_type: TaskType) -> float:
        """Calculate bonus for frequently used patterns."""
        if not self.memory_store:
            return 0.0

        # Query task memories
        query_result = self.memory_store.query(
            query=task_type.value,
            memory_types=[MemoryType.TASK],
            limit=10,
        )

        if not query_result.memories:
            return 0.0

        # Bonus based on usage count
        total_usage = sum(m.usage_count for m in query_result.memories)
        avg_usage = total_usage / len(query_result.memories)

        # Cap bonus at 0.1
        return min(0.1, avg_usage * 0.01)

    def _get_base_autonomy_level(
        self, risk_level: RiskLevel, task_type: TaskType
    ) -> AutonomyLevel:
        """Get base autonomy level from profile."""
        # Risk level takes precedence for safety
        if risk_level == RiskLevel.FORBIDDEN:
            return AutonomyLevel.MANUAL_REQUIRED
        if risk_level == RiskLevel.HIGH:
            return AutonomyLevel.CONFIRM_EACH_TIME

        # Check task type autonomy
        task_autonomy = self.profile.task_type_autonomy.get(task_type.value)
        if task_autonomy:
            return AutonomyLevel(task_autonomy)

        # Fall back to risk-based autonomy
        risk_autonomy = self.profile.risk_level_autonomy.get(risk_level.value)
        if risk_autonomy:
            return AutonomyLevel(risk_autonomy)

        # Default to confirm each time
        return AutonomyLevel.CONFIRM_EACH_TIME

    def _adjust_autonomy_by_confidence(
        self,
        base_level: AutonomyLevel,
        confidence: float,
        risk_level: RiskLevel,
    ) -> tuple[AutonomyLevel, bool]:
        """
        Adjust autonomy level based on confidence.

        Returns:
            Tuple of (final_autonomy_level, should_ask_user)
        """
        # CRITICAL: High risk and forbidden always require confirmation
        if risk_level in [RiskLevel.HIGH, RiskLevel.FORBIDDEN]:
            return base_level, True

        # High confidence can upgrade autonomy for low/medium risk
        if confidence >= self.profile.global_confidence_threshold:
            if base_level == AutonomyLevel.CONFIRM_EACH_TIME and risk_level == RiskLevel.LOW:
                return AutonomyLevel.AUTO_RUN_LOW_RISK, False
            if base_level == AutonomyLevel.CONFIRM_EACH_TIME and risk_level == RiskLevel.MEDIUM:
                return AutonomyLevel.NOTIFY_THEN_RUN, False
            if base_level == AutonomyLevel.NOTIFY_THEN_RUN:
                return AutonomyLevel.AUTO_RUN_LOW_RISK, False

        # Low confidence downgrades autonomy
        if confidence < 0.5:
            if base_level == AutonomyLevel.AUTO_RUN_LOW_RISK:
                return AutonomyLevel.NOTIFY_THEN_RUN, True
            if base_level == AutonomyLevel.NOTIFY_THEN_RUN:
                return AutonomyLevel.CONFIRM_EACH_TIME, True

        # Determine if user input is needed
        should_ask = base_level in [
            AutonomyLevel.MANUAL_REQUIRED,
            AutonomyLevel.CONFIRM_EACH_TIME,
        ]

        return base_level, should_ask

    def _build_decision_reason(
        self,
        base_level: AutonomyLevel,
        final_level: AutonomyLevel,
        factors: ConfidenceFactors,
    ) -> str:
        """Build human-readable decision reason."""
        if base_level == final_level:
            return f"Base autonomy level ({base_level.value}) with confidence {factors.final_confidence:.2f}"

        return (
            f"Adjusted from {base_level.value} to {final_level.value} "
            f"based on confidence {factors.final_confidence:.2f}"
        )

    def _build_intervention_reason(
        self, risk_level: RiskLevel, confidence: float
    ) -> str:
        """Build human-readable intervention reason."""
        if risk_level in [RiskLevel.HIGH, RiskLevel.FORBIDDEN]:
            return f"High risk ({risk_level.value}) requires confirmation"

        if confidence < 0.5:
            return f"Low confidence ({confidence:.2f}) requires confirmation"

        return "User confirmation required"

    def record_feedback(
        self,
        feedback: UserFeedback,
        step: "PlanStep",
        task_card: "TaskCard",
    ) -> None:
        """
        Record user feedback and update confidence.

        This method updates the autonomy profile based on user feedback,
        adjusting confidence for future similar tasks.
        """
        if not self.memory_store:
            return

        # Determine if feedback is positive or negative
        is_positive = feedback.feedback_type in ["accepted", "success"]
        is_negative = feedback.feedback_type in ["rejected", "modified", "failed", "blocked"]

        # Update task memory
        memory_content = (
            f"Task type {task_card.task_type.value} with risk {step.risk_level.value}: "
            f"{feedback.feedback_type}"
        )

        # Adjust confidence based on feedback
        new_confidence = 0.7 if is_positive else 0.3

        from openpilot.memory_models import MemoryRecord

        memory = MemoryRecord(
            id="",  # Will be generated
            memory_type=MemoryType.TASK,
            content=memory_content,
            tags=[task_card.task_type.value, step.risk_level.value, feedback.feedback_type],
            confidence=new_confidence,
            usage_count=1,
            metadata={"feedback": feedback.model_dump()},
        )

        self.memory_store.save(memory)

        # Update profile last_updated timestamp
        self.profile.last_updated = datetime.now(timezone.utc).isoformat()
