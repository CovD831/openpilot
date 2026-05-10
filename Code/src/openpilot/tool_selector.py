"""Tool selector for intelligent tool matching."""

from __future__ import annotations

from typing import Optional

from openpilot.tool_models import ToolCapability, PermissionLevel
from openpilot.tool_orchestration_models import (
    OrchestrationContext,
    SelectionReason,
    ToolMatchScore,
    ToolSelection,
)
from openpilot.tool_registry import ToolRegistry


class ToolSelector:
    """Intelligent tool selector based on requirements and context."""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def select_tool(
        self,
        step_id: str,
        required_capability: ToolCapability,
        context: OrchestrationContext,
        input_params: Optional[dict] = None
    ) -> Optional[ToolSelection]:
        """
        Select the best tool for a given capability and context.

        Args:
            step_id: Unique step identifier
            required_capability: Required tool capability
            context: Orchestration context with constraints
            input_params: Optional input parameters for the tool

        Returns:
            ToolSelection or None if no suitable tool found
        """
        # Find candidate tools
        candidates = self.registry.find_by_capability(required_capability)

        if not candidates:
            return None

        # Filter by permission level if specified
        if context.max_permission_level:
            max_perm = PermissionLevel(context.max_permission_level)
            permission_order = [
                PermissionLevel.AUTO,
                PermissionLevel.LOW,
                PermissionLevel.MEDIUM,
                PermissionLevel.HIGH,
                PermissionLevel.FORBIDDEN
            ]
            max_index = permission_order.index(max_perm)
            candidates = [
                tool for tool in candidates
                if permission_order.index(PermissionLevel(tool.permission_level)) <= max_index
            ]

        if not candidates:
            return None

        # Score each candidate
        scores = [self._score_tool(tool, context) for tool in candidates]

        # Sort by total score (descending)
        scored_tools = sorted(
            zip(candidates, scores),
            key=lambda x: x[1].total_score,
            reverse=True
        )

        # Select best tool
        best_tool, best_score = scored_tools[0]

        # Determine selection reason
        reason = self._determine_reason(best_score, len(candidates), context)

        # Determine if confirmation required
        requires_confirmation = self._requires_confirmation(
            best_tool,
            best_score,
            context
        )

        # Generate fallback options
        fallback_tools = [
            tool.name for tool, score in scored_tools[1:4]  # Top 3 alternatives
            if score.total_score > 0.3  # Only reasonable alternatives
        ]

        return ToolSelection(
            step_id=step_id,
            tool_name=best_tool.name,
            reason=reason,
            confidence=best_score.total_score,
            input_params=input_params or {},
            requires_confirmation=requires_confirmation,
            fallback_tools=fallback_tools
        )

    def _score_tool(
        self,
        tool,
        context: OrchestrationContext
    ) -> ToolMatchScore:
        """
        Score how well a tool matches the requirements.

        Args:
            tool: Tool definition
            context: Orchestration context

        Returns:
            ToolMatchScore with detailed scoring
        """
        reasons = []
        warnings = []

        # 1. Capability score (always 1.0 since we filtered by capability)
        capability_score = 1.0

        # 2. Permission score (prefer lower permission levels)
        permission_order = {
            "auto": 1.0,
            "low": 0.9,
            "medium": 0.7,
            "high": 0.4,
            "forbidden": 0.0
        }
        permission_score = permission_order.get(tool.permission_level, 0.5)

        if tool.permission_level == "auto":
            reasons.append("Can run automatically")
        elif tool.permission_level == "high":
            warnings.append("Requires user confirmation")

        # 3. Performance score (based on historical data if available)
        performance_score = 0.7  # Default neutral score

        if context.use_memory and context.memory_query_results:
            # Check if we have historical data for this tool
            tool_history = context.memory_query_results.get(tool.name, {})
            success_rate = tool_history.get("success_rate", 0.7)
            performance_score = success_rate

            if success_rate > 0.8:
                reasons.append(f"High success rate ({success_rate:.0%})")
            elif success_rate < 0.5:
                warnings.append(f"Low success rate ({success_rate:.0%})")

        # 4. Cost score (prefer lower cost)
        cost_score = 0.8  # Default

        # LLM calls are more expensive
        if ToolCapability.LLM_CALL in tool.capabilities:
            cost_score = 0.6
            if context.max_cost and context.max_cost < 0.01:
                warnings.append("LLM calls may exceed cost budget")

        # 5. Calculate weighted total score
        weights = {
            "capability": 0.4,
            "permission": 0.2,
            "performance": 0.25,
            "cost": 0.15
        }

        total_score = (
            capability_score * weights["capability"] +
            permission_score * weights["permission"] +
            performance_score * weights["performance"] +
            cost_score * weights["cost"]
        )

        return ToolMatchScore(
            tool_name=tool.name,
            capability_score=capability_score,
            permission_score=permission_score,
            performance_score=performance_score,
            cost_score=cost_score,
            total_score=total_score,
            reasons=reasons,
            warnings=warnings
        )

    def _determine_reason(
        self,
        score: ToolMatchScore,
        num_candidates: int,
        context: OrchestrationContext
    ) -> SelectionReason:
        """Determine the reason for tool selection."""
        if num_candidates == 1:
            return SelectionReason.ONLY_OPTION

        if score.performance_score > 0.8 and context.use_memory:
            return SelectionReason.BEST_PERFORMANCE

        if score.cost_score > 0.8:
            return SelectionReason.COST_OPTIMIZED

        return SelectionReason.CAPABILITY_MATCH

    def _requires_confirmation(
        self,
        tool,
        score: ToolMatchScore,
        context: OrchestrationContext
    ) -> bool:
        """
        Determine if user confirmation is required.

        Args:
            tool: Tool definition
            score: Match score
            context: Orchestration context

        Returns:
            True if confirmation required
        """
        # High/forbidden permission always requires confirmation
        if tool.permission_level in ["high", "forbidden"]:
            return True

        # Medium permission requires confirmation if confidence is low
        if tool.permission_level == "medium":
            if score.total_score < context.confidence_threshold:
                return True

            # Check autonomy level
            if context.autonomy_level in ["manual_required", "confirm_each_time"]:
                return True

        # Low confidence always requires confirmation
        if score.total_score < 0.5:
            return True

        return False

    def select_multiple_tools(
        self,
        steps: list[tuple[str, ToolCapability, dict]],
        context: OrchestrationContext
    ) -> list[ToolSelection]:
        """
        Select tools for multiple steps.

        Args:
            steps: List of (step_id, capability, input_params) tuples
            context: Orchestration context

        Returns:
            List of tool selections
        """
        selections = []

        for step_id, capability, input_params in steps:
            selection = self.select_tool(step_id, capability, context, input_params)
            if selection:
                selections.append(selection)

        return selections
