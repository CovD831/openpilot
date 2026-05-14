"""Tool orchestrator for generating execution plans."""

from __future__ import annotations

import time
import uuid
import re
from typing import Optional

from core.semantic_types import ExecutionPlan, PlanStep
from tools.tool_models import ToolCapability
from tools.tool_orchestration_models import (
    ExecutionStrategy,
    FallbackStrategy,
    OrchestrationContext,
    OrchestrationResult,
    ParallelExecutionGroup,
    SelectionReason,
    ToolOrchestrationPlan,
    ToolSelection,
)
from tools.tool_registry import ToolRegistry
from tools.tool_selector import ToolSelector
from core.semantic_analyzer import SemanticAnalyzer, StepSemanticAnalysis


class ToolOrchestrator:
    """Orchestrates tool selection and execution planning."""

    def __init__(self, registry: ToolRegistry, semantic_analyzer: SemanticAnalyzer | None = None):
        self.registry = registry
        self.selector = ToolSelector(registry)
        self.semantic_analyzer = semantic_analyzer
        self.last_semantic_analyses: list[dict] = []
        self._semantic_warnings: list[str] = []

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
                execution_plan,
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
            warnings = self._semantic_warnings + self._generate_warnings(plan, context)

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
        execution_plan: ExecutionPlan,
        context: OrchestrationContext
    ) -> list[ToolSelection]:
        """Map execution steps to tool selections."""
        if self.semantic_analyzer is None:
            raise ValueError("LLM semantic analyzer is required for tool orchestration")

        self.last_semantic_analyses = []
        self._semantic_warnings = []
        tool_selections = []
        known_directory = self._extract_path_from_text(execution_plan.task_card.goal)
        directory_step_id: str | None = None
        content_step_id: str | None = None
        code_generation_step_id: str | None = None  # 跟踪代码生成步骤
        available_tools = [tool.name for tool in self.registry.list_all()]

        for step in execution_plan.steps:
            semantic = self.semantic_analyzer.analyze_plan_step(
                execution_plan.task_card.goal,
                step,
                available_tools,
            )
            self.last_semantic_analyses.append(
                {
                    "goal": execution_plan.task_card.goal,
                    "step": {
                        "id": step.id,
                        "title": step.title,
                        "description": step.description,
                        "expected_output": step.expected_output,
                    },
                    **semantic.log_payload(),
                }
            )

            input_params = self._extract_semantic_input_params(step, semantic, known_directory)
            preferred_tool = self._preferred_tool_from_semantics(semantic)
            if preferred_tool == "unsupported_file_mutation":
                self._semantic_warnings.append(
                    f"{step.id}: file mutation requested but no safe move/rename tool is available"
                )
                continue

            selection = self._select_preferred_tool(
                step=step,
                required_capability=semantic.capability,
                context=context,
                input_params=input_params,
                preferred_tool=preferred_tool,
            )

            if selection:
                selection.depends_on = step.dependencies or []
                if selection.tool_name == "directory_lister":
                    directory_step_id = selection.step_id
                elif selection.tool_name == "multi_file_reader":
                    if directory_step_id:
                        selection.input_params.setdefault("source_step_id", directory_step_id)
                        if directory_step_id not in selection.depends_on:
                            selection.depends_on.append(directory_step_id)
                    content_step_id = selection.step_id
                elif selection.tool_name == "llm_summarizer":
                    # llm_summarizer 可以从 content_step_id 或 directory_step_id 获取输入
                    if content_step_id:
                        selection.input_params.setdefault("source_step_id", content_step_id)
                        if content_step_id not in selection.depends_on:
                            selection.depends_on.append(content_step_id)
                    elif directory_step_id:
                        # 如果没有 content_step_id，但有 directory_step_id，
                        # 说明需要先读取文件内容，这里暂时使用 directory_step_id
                        selection.input_params.setdefault("source_step_id", directory_step_id)
                        if directory_step_id not in selection.depends_on:
                            selection.depends_on.append(directory_step_id)
                    content_step_id = selection.step_id
                elif selection.tool_name == "code_generator":
                    # 代码生成步骤
                    code_generation_step_id = selection.step_id
                    content_step_id = selection.step_id  # 代码也是内容
                elif selection.tool_name == "code_reviewer":
                    # 代码审查需要从代码生成步骤获取代码
                    if code_generation_step_id:
                        selection.input_params.setdefault("source_step_id", code_generation_step_id)
                        if code_generation_step_id not in selection.depends_on:
                            selection.depends_on.append(code_generation_step_id)
                elif selection.tool_name == "code_executor":
                    # 代码执行需要从代码生成步骤获取代码
                    if code_generation_step_id:
                        selection.input_params.setdefault("source_step_id", code_generation_step_id)
                        if code_generation_step_id not in selection.depends_on:
                            selection.depends_on.append(code_generation_step_id)
                elif selection.tool_name == "file_writer":
                    # file_writer 可以从代码生成或其他内容步骤获取内容
                    if code_generation_step_id and "content" not in selection.input_params:
                        # 优先使用代码生成的输出
                        selection.input_params.setdefault("source_step_id", code_generation_step_id)
                        if code_generation_step_id not in selection.depends_on:
                            selection.depends_on.append(code_generation_step_id)
                    elif content_step_id and "content" not in selection.input_params:
                        selection.input_params.setdefault("source_step_id", content_step_id)
                        if content_step_id not in selection.depends_on:
                            selection.depends_on.append(content_step_id)
                tool_selections.append(selection)

        return tool_selections

    def _extract_semantic_input_params(
        self,
        step: PlanStep,
        semantic: StepSemanticAnalysis,
        known_directory: str | None = None,
    ) -> dict:
        """Create tool inputs from LLM semantics plus deterministic path extraction."""
        params: dict = {}
        raw_text = self._step_raw_text(step)
        directory_path = self._extract_path_from_text(raw_text) or known_directory

        if semantic.preferred_tool == "directory_lister" and directory_path:
            params["directory_path"] = directory_path
            params["pattern"] = "*\u5b8c\u6210\u62a5\u544a*.md"
            params["recursive"] = False
        elif semantic.preferred_tool == "multi_file_reader" and directory_path:
            params["directory_path"] = directory_path
            params["pattern"] = "*\u5b8c\u6210\u62a5\u544a*.md"
            params["max_total_chars"] = 20000  # \u51cf\u5c11\u5230 20000 \u5b57\u7b26\uff0c\u907f\u514d LLM \u8d85\u8f7d
        elif semantic.preferred_tool == "file_writer":
            output_path = self._extract_output_path_from_text(raw_text)
            if output_path:
                params["file_path"] = output_path
            else:
                # 如果无法提取输出路径，生成一个默认路径
                # 基于操作类型和目录路径生成合理的文件名
                if directory_path:
                    # 在同一目录下生成输出文件
                    import os
                    base_dir = os.path.dirname(directory_path) if os.path.isfile(directory_path) else directory_path
                    if semantic.operation_type in ["generate_final_report", "summarize", "organize"]:
                        params["file_path"] = os.path.join(base_dir, "整理报告.md")
                    else:
                        params["file_path"] = os.path.join(base_dir, "输出文件.md")
                else:
                    # 使用当前目录
                    params["file_path"] = "输出文件.md"
        elif semantic.preferred_tool == "llm_summarizer":
            params["instruction"] = self._instruction_for_operation(semantic.operation_type)
            params["max_tokens"] = 1200
        elif semantic.preferred_tool == "code_generator":
            # Extract task description from step description
            params["task_description"] = step.description
            # Detect language from step text (default to Python)
            language = "python"
            if "shell" in raw_text.lower() or "bash" in raw_text.lower():
                language = "bash"
            params["language"] = language
            # Add context if available
            if step.expected_output:
                params["context"] = f"Expected output: {step.expected_output}"
        elif semantic.preferred_tool == "code_reviewer":
            # code and language will be resolved from source_step_id
            pass
        elif semantic.preferred_tool == "code_executor":
            # code and language will be resolved from source_step_id
            params["timeout"] = 30

        return params

    def _preferred_tool_from_semantics(self, semantic: StepSemanticAnalysis) -> str | None:
        """Use the LLM-selected tool without keyword reinterpretation."""
        if semantic.preferred_tool == "unsupported_file_mutation":
            return "unsupported_file_mutation"
        if self.registry.get(semantic.preferred_tool):
            return semantic.preferred_tool
        return None

    def _instruction_for_operation(self, operation_type: str) -> str:
        """Return stable instructions for a semantically selected LLM operation."""
        if operation_type in {"move_files", "archive_files", "rename_files", "unsupported_file_mutation"}:
            return (
                "\u8bf7\u4e0d\u8981\u79fb\u52a8\u3001\u91cd\u547d\u540d\u6216\u4fee\u6539\u539f\u59cb\u6587\u4ef6\u3002"
                "\u8bf7\u57fa\u4e8e\u5df2\u8bfb\u53d6\u7684\u5b8c\u6210\u62a5\u544a\u5185\u5bb9\uff0c"
                "\u751f\u6210\u6587\u4ef6\u5f52\u6863\u5efa\u8bae\u548c\u6574\u7406\u8bf4\u660e\u3002"
            )
        if operation_type == "generate_final_report":
            return (
                "\u8bf7\u57fa\u4e8e\u4e0a\u4e00\u6b65\u6458\u8981\u751f\u6210\u6700\u7ec8\u4e2d\u6587\u6574\u7406\u62a5\u544a\uff0c"
                "\u5305\u542b\u603b\u4f53\u5b8c\u6210\u60c5\u51b5\u3001\u5206\u9879\u6210\u679c\u3001\u98ce\u9669\u4e0e\u540e\u7eed\u5efa\u8bae\u3002"
            )
        return (
            "\u8bf7\u57fa\u4e8e\u4e0b\u5217\u5b8c\u6210\u62a5\u544a\u751f\u6210\u7b80\u6d01\u7684\u4e2d\u6587\u603b\u7ed3\uff0c"
            "\u5305\u542b\u5df2\u5b8c\u6210\u5185\u5bb9\u3001\u5173\u952e\u6210\u679c\u548c\u540e\u7eed\u5efa\u8bae\u3002"
        )

    # Removed: _infer_capability_from_step
    # Now using SemanticAnalyzer for all capability inference

    # Removed: _extract_input_params (keyword-based)
    # Now using _extract_semantic_input_params which relies on SemanticAnalyzer

    # Removed: _preferred_tool_for_step (keyword-based)
    # Now using SemanticAnalyzer.analyze_plan_step() which provides preferred_tool

    def _select_preferred_tool(
        self,
        step: PlanStep,
        required_capability: ToolCapability,
        context: OrchestrationContext,
        input_params: dict,
        preferred_tool: str | None,
    ) -> ToolSelection | None:
        """Select a specific preferred tool when the step semantics are clear."""
        if preferred_tool:
            tool_def = self.registry.get(preferred_tool)
            if tool_def and required_capability in tool_def.capabilities:
                permission_level = str(tool_def.permission_level)
                return ToolSelection(
                    step_id=step.id,
                    tool_name=tool_def.name,
                    reason=SelectionReason.CAPABILITY_MATCH,
                    confidence=0.9,
                    input_params=input_params,
                    requires_confirmation=permission_level in {"high", "forbidden"},
                    fallback_tools=[],
                )

        return self.selector.select_tool(
            step_id=step.id,
            required_capability=required_capability,
            context=context,
            input_params=input_params,
        )

    def _step_text(self, step: PlanStep) -> str:
        """Return searchable text for a plan step."""
        return self._step_raw_text(step).lower()

    def _step_raw_text(self, step: PlanStep) -> str:
        """Return original-casing text for a plan step."""
        return " ".join(
            str(part)
            for part in [
                step.title,
                step.description,
                step.expected_output,
            ]
            if part
        )

    # Removed: _is_directory_listing_step, _is_multi_file_read_step,
    # _is_summary_step, _is_file_write_step
    # Now using SemanticAnalyzer.analyze_plan_step() for all step classification

    def _extract_output_path_from_text(self, text: str) -> str | None:
        """Extract an explicit output file path or filename from free text."""
        path = self._extract_path_from_text(text)
        if path and re.search(r"\.(md|txt|json|csv|docx|pdf)$", path, re.IGNORECASE):
            return path
        file_match = re.search(r"([^\s'\"，。；;\\/]+\.(?:md|txt|json|csv|docx|pdf))", text, re.IGNORECASE)
        if file_match:
            return self._clean_path_candidate(file_match.group(1))
        return None

    def _extract_path_from_text(self, text: str) -> str | None:
        """Extract a Windows or WSL path from free text."""
        path_pattern = r"(/[^\s'\"，。；;]+|[A-Za-z]:[\\/][^\s'\"，。；;]+)"
        for match in re.finditer(path_pattern, text):
            candidate = self._clean_path_candidate(match.group(1))
            if candidate:
                return candidate
        return None

    def _clean_path_candidate(self, candidate: str) -> str:
        """Trim common natural-language suffixes around extracted paths."""
        candidate = candidate.strip().strip("'\"`.,;:，。；：")
        suffixes = [
            "\u4e0b", "\u4e2d", "\u91cc", "\u5185",
            "\u76ee\u5f55", "\u6587\u4ef6\u5939",
        ]
        changed = True
        while changed:
            changed = False
            for suffix in suffixes:
                if candidate.endswith(suffix):
                    candidate = candidate[: -len(suffix)]
                    changed = True
        return candidate.strip().strip("'\"`.,;:，。；：")

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
