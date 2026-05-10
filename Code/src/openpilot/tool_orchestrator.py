"""Tool orchestrator for generating execution plans."""

from __future__ import annotations

import time
import uuid
from typing import Optional

from openpilot.planner_models import ExecutionPlan, PlanStep
from openpilot.tool_models import ToolCapability
from openpilot.tool_orchestration_models import (
    ExecutionStrategy,
    FallbackStrategy,
    OrchestrationContext,
    OrchestrationResult,
    ParallelExecutionGroup,
    ToolOrchestrationPlan,
    ToolSelection,
)
from openpilot.tool_registry import ToolRegistry
from openpilot.tool_selector import ToolSelector


class ToolOrchestrator:
    """Orchestrates tool selection and execution planning."""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self.selector = ToolSelector(registry)

    def create_orchestration_plan(
        self,
        execution_plan: ExecutionPlan,
        context: OrchestrationContext
    ) -> OrchestrationResult:
        """
        Create a complete tool orchestration plan from an execution plan.

        Args:
            execution_plan: High-level execution plan
            context: Orchestration context

        Returns:
            OrchestrationResult with plan or error
        """
        start_time = time.time()

        try:
            # Map steps to tool selections
            tool_selections = self._map_steps_to_tools(
                execution_plan.steps,
                context
            )

            if not tool_selections:
                return OrchestrationResult(
                    success=False,
                    error="No suitable tools found for execution plan",
                    planning_time_ms=int((time.time() - start_time) * 1000),
                    tools_considered=0,
                    alternatives_generated=0
                )

            # Identify parallel execution opportunities
            parallel_groups = self._identify_parallel_groups(
                tool_selections,
                context
            )

            # Generate fallback strategies
            fallback_strategies = self._generate_fallback_strategies(
                tool_selections
            )

            # Determine execution strategy
            execution_strategy = self._determine_execution_strategy(
                tool_selections,
                parallel_groups,
                context
            )

            # Estimate duration and cost
            estimated_duration = self._estimate_duration(tool_selections)
            estimated_cost = self._estimate_cost(tool_selections)

            # Determine risk level
            risk_level = self._determine_risk_level(tool_selections)

            # Create orchestration plan
            plan = ToolOrchestrationPlan(
                plan_id=str(uuid.uuid4()),
                goal=execution_plan.task_card.goal,
                tool_selections=tool_selections,
                parallel_groups=parallel_groups,
                execution_strategy=execution_strategy,
                fallback_strategies=fallback_strategies,
                estimated_duration_seconds=estimated_duration,
                estimated_cost=estimated_cost,
                risk_level=risk_level,
                based_on_memory=context.use_memory,
                memory_ids=[]
            )

            # Generate recommendations
            recommendations = self._generate_recommendations(plan, context)
            warnings = self._generate_warnings(plan, context)

            planning_time_ms = int((time.time() - start_time) * 1000)

            return OrchestrationResult(
                success=True,
                plan=plan,
                planning_time_ms=planning_time_ms,
                tools_considered=len(self.registry.list_all()),
                alternatives_generated=sum(len(ts.fallback_tools) for ts in tool_selections),
                recommendations=recommendations,
                warnings=warnings
            )

        except Exception as e:
            return OrchestrationResult(
                success=False,
                error=str(e),
                planning_time_ms=int((time.time() - start_time) * 1000),
                tools_considered=0,
                alternatives_generated=0
            )

    def _map_steps_to_tools(
        self,
        steps: list[PlanStep],
        context: OrchestrationContext
    ) -> list[ToolSelection]:
        """Map execution steps to tool selections."""
        tool_selections = []

        for step in steps:
            # Determine required capability from step
            capability = self._infer_capability_from_step(step)

            if capability:
                # Extract input parameters from step
                input_params = self._extract_input_params(step)

                # Select tool
                selection = self.selector.select_tool(
                    step_id=step.id,
                    required_capability=capability,
                    context=context,
                    input_params=input_params
                )

                if selection:
                    # Add dependencies
                    selection.depends_on = step.dependencies or []
                    tool_selections.append(selection)

        return tool_selections

    def _infer_capability_from_step(self, step: PlanStep) -> Optional[ToolCapability]:
        """Infer required tool capability from step description."""
        title_lower = step.title.lower()
        description_lower = step.description.lower()

        # File operations
        if any(kw in title_lower or kw in description_lower for kw in ["read", "load", "open"]):
            if any(kw in title_lower or kw in description_lower for kw in ["file", "document", "text"]):
                return ToolCapability.FILE_READ

        if any(kw in title_lower or kw in description_lower for kw in ["write", "save", "create file"]):
            return ToolCapability.FILE_WRITE

        # LLM operations
        if any(kw in title_lower or kw in description_lower for kw in ["summarize", "analyze", "generate", "llm"]):
            return ToolCapability.LLM_CALL

        # Web operations
        if any(kw in title_lower or kw in description_lower for kw in ["search", "web", "internet"]):
            return ToolCapability.WEB_SEARCH

        # Code execution
        if any(kw in title_lower or kw in description_lower for kw in ["execute", "run code", "script"]):
            return ToolCapability.CODE_EXECUTION

        return None

    def _extract_input_params(self, step: PlanStep) -> dict:
        """Extract input parameters from step."""
        # This is a simplified version - in reality, would use LLM to extract params
        params = {}

        # Try to extract file paths
        if "file" in step.description.lower():
            # Would use regex or LLM to extract actual file path
            params["file_path"] = "data.txt"  # Placeholder

        return params

    def _identify_parallel_groups(
        self,
        tool_selections: list[ToolSelection],
        context: OrchestrationContext
    ) -> list[ParallelExecutionGroup]:
        """Identify groups of tools that can execute in parallel."""
        if not context.prefer_parallel:
            return []

        parallel_groups = []

        # Build dependency graph
        dependency_map = {ts.step_id: ts.depends_on for ts in tool_selections}

        # Find independent steps (no dependencies)
        independent_steps = [
            ts for ts in tool_selections
            if not ts.depends_on
        ]

        # Group independent steps that can run in parallel
        if len(independent_steps) > 1:
            # Check if they're all low-risk
            all_low_risk = all(
                not ts.requires_confirmation for ts in independent_steps
            )

            if all_low_risk:
                group = ParallelExecutionGroup(
                    group_id=f"parallel_group_{len(parallel_groups) + 1}",
                    tool_selections=independent_steps,
                    wait_for_all=True,
                    timeout_seconds=max(60, len(independent_steps) * 30),
                    fail_fast=False,
                    min_success_count=len(independent_steps)
                )
                parallel_groups.append(group)

        return parallel_groups

    def _generate_fallback_strategies(
        self,
        tool_selections: list[ToolSelection]
    ) -> dict[str, FallbackStrategy]:
        """Generate fallback strategies for tool selections."""
        strategies = {}

        for selection in tool_selections:
            if selection.fallback_tools:
                strategy = FallbackStrategy(
                    primary_tool=selection.tool_name,
                    fallback_sequence=selection.fallback_tools,
                    trigger_on_errors=["timeout", "permission_denied", "tool_error"],
                    max_attempts=min(3, 1 + len(selection.fallback_tools)),
                    backoff_seconds=2
                )
                strategies[selection.tool_name] = strategy

        return strategies

    def _determine_execution_strategy(
        self,
        tool_selections: list[ToolSelection],
        parallel_groups: list[ParallelExecutionGroup],
        context: OrchestrationContext
    ) -> ExecutionStrategy:
        """Determine overall execution strategy."""
        if parallel_groups:
            return ExecutionStrategy.PARALLEL

        # Check if any selections have retries
        has_retries = any(ts.fallback_tools for ts in tool_selections)
        if has_retries:
            return ExecutionStrategy.RETRY

        return ExecutionStrategy.SEQUENTIAL

    def _estimate_duration(self, tool_selections: list[ToolSelection]) -> int:
        """Estimate total execution duration in seconds."""
        total_duration = 0

        for selection in tool_selections:
            tool_def = self.registry.get(selection.tool_name)
            if tool_def:
                timeout = selection.timeout_override or tool_def.timeout_seconds
                total_duration += timeout

        # Add 20% buffer
        return int(total_duration * 1.2)

    def _estimate_cost(self, tool_selections: list[ToolSelection]) -> float:
        """Estimate total execution cost."""
        total_cost = 0.0

        for selection in tool_selections:
            tool_def = self.registry.get(selection.tool_name)
            if tool_def and ToolCapability.LLM_CALL in tool_def.capabilities:
                # Rough estimate: $0.001 per LLM call
                total_cost += 0.001

        return total_cost

    def _determine_risk_level(self, tool_selections: list[ToolSelection]) -> str:
        """Determine overall risk level."""
        has_high_risk = any(ts.requires_confirmation for ts in tool_selections)

        if has_high_risk:
            return "high"

        has_medium_risk = any(
            self.registry.get(ts.tool_name).permission_level == "medium"
            for ts in tool_selections
            if self.registry.get(ts.tool_name)
        )

        if has_medium_risk:
            return "medium"

        return "low"

    def _generate_recommendations(
        self,
        plan: ToolOrchestrationPlan,
        context: OrchestrationContext
    ) -> list[str]:
        """Generate recommendations for the user."""
        recommendations = []

        # Recommend parallel execution if available
        if plan.parallel_groups:
            recommendations.append(
                f"Can execute {len(plan.parallel_groups[0].tool_selections)} steps in parallel"
            )

        # Recommend reviewing high-risk steps
        high_risk_count = sum(1 for ts in plan.tool_selections if ts.requires_confirmation)
        if high_risk_count > 0:
            recommendations.append(
                f"{high_risk_count} step(s) require confirmation before execution"
            )

        # Recommend cost optimization
        if plan.estimated_cost and plan.estimated_cost > 0.01:
            recommendations.append(
                f"Estimated cost: ${plan.estimated_cost:.3f} - consider caching results"
            )

        return recommendations

    def _generate_warnings(
        self,
        plan: ToolOrchestrationPlan,
        context: OrchestrationContext
    ) -> list[str]:
        """Generate warnings about potential issues."""
        warnings = []

        # Warn about long execution time
        if plan.estimated_duration_seconds and plan.estimated_duration_seconds > 300:
            warnings.append(
                f"Estimated duration: {plan.estimated_duration_seconds}s - this may take a while"
            )

        # Warn about missing fallbacks
        no_fallback_count = sum(
            1 for ts in plan.tool_selections
            if not ts.fallback_tools and ts.requires_confirmation
        )
        if no_fallback_count > 0:
            warnings.append(
                f"{no_fallback_count} high-risk step(s) have no fallback options"
            )

        return warnings
