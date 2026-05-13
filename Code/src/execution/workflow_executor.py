"""
工作流执行器

整合Phase 2所有模块，提供完整的8阶段执行流程。
"""

from datetime import datetime
from typing import Any, Optional
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.table import Table
from rich import box

from models.executor_models import ExecutionError, ExecutionResult, ExecutionStatus
from planning.planner import TaskPlanner
from models.planner_models import TaskCard, ExecutionPlan
from core.semantic_analyzer import SemanticAnalyzer
from memory.memory_store import MemoryStore
from tools.tool_registry import ToolRegistry
from tools.tool_orchestrator import ToolOrchestrator
from tools.tool_executor import ToolExecutor
from validation.result_validator import ResultValidator
from validation.reflection_analyzer import ReflectionAnalyzer
from validation.strategy_optimizer import StrategyOptimizer
from core.openpilot_log import OpenPilotLogger


class WorkflowStage:
    """工作流阶段"""
    GOAL_UNDERSTANDING = "goal_understanding"
    MEMORY_RETRIEVAL = "memory_retrieval"
    PLAN_GENERATION = "plan_generation"
    TOOL_ORCHESTRATION = "tool_orchestration"
    EXECUTION = "execution"
    VALIDATION = "validation"
    REFLECTION = "reflection"
    LOGGING = "logging"


class StageConfig:
    """Stage configuration for flexible pipeline"""
    def __init__(self, name: str, handler: callable, display_name: str, icon: str = ""):
        self.name = name
        self.handler = handler
        self.display_name = display_name
        self.icon = icon


class WorkflowExecutor:
    """工作流执行器"""

    def __init__(
        self,
        llm_client,
        console: Optional[Console] = None,
        dry_run: bool = False,
        auto_approve: bool = False,
        save_report: Optional[str] = None,
        logger: OpenPilotLogger | None = None,
        log_file: str | Path | None = None,
    ):
        """
        初始化工作流执行器

        Args:
            llm_client: LLM客户端
            console: Rich控制台
            dry_run: 是否只规划不执行
            auto_approve: 是否自动批准低风险操作
            save_report: 报告保存路径
        """
        self.llm_client = llm_client
        self.console = console or Console()
        self.dry_run = dry_run
        self.auto_approve = auto_approve
        self.save_report = save_report

        # 初始化各个模块
        self.semantic_analyzer = SemanticAnalyzer(llm_client)
        self.planner = TaskPlanner(llm_client)
        self.memory_store = MemoryStore()
        self.tool_registry = ToolRegistry()

        # 注册内置工具
        from tools.builtin_tools import register_builtin_tools
        register_builtin_tools(self.tool_registry)

        self.orchestrator = ToolOrchestrator(self.tool_registry, semantic_analyzer=self.semantic_analyzer)
        self.executor = ToolExecutor(self.tool_registry)
        self.validator = ResultValidator()
        self.analyzer = ReflectionAnalyzer()
        self.optimizer = StrategyOptimizer(self.memory_store)

        # 初始化日志记录器（使用默认路径）
        default_log_file = Path(__file__).resolve().parents[2] / "logs" / "openpilot.jsonl"
        self.logger = logger or OpenPilotLogger(log_file or default_log_file)

        # 执行统计
        self.stats = {
            "start_time": None,
            "end_time": None,
            "stages_completed": 0,
            "total_stages": 8,
            "success": False,
        }
        self.workflow_session_id: str | None = None
        self._last_plan: ExecutionPlan | None = None
        self._last_orchestration_plan = None

        # Configure pipeline stages
        self._pipeline = self._build_default_pipeline()
        self.stats["total_stages"] = len(self._pipeline)

    def _build_default_pipeline(self) -> list[StageConfig]:
        """Build the default 8-stage pipeline"""
        return [
            StageConfig("goal_understanding", self._stage_goal_understanding, "理解目标", "📖"),
            StageConfig("memory_retrieval", self._stage_memory_retrieval, "检索记忆", "🧠"),
            StageConfig("plan_generation", self._stage_plan_generation, "生成计划", "📋"),
            StageConfig("tool_orchestration", self._stage_tool_orchestration, "编排工具", "🔧"),
            StageConfig("execution", self._stage_execution, "执行步骤", "⚡"),
            StageConfig("validation", self._stage_validation, "验证结果", "✅"),
            StageConfig("reflection", self._stage_reflection, "生成反思", "💭"),
            StageConfig("logging", self._stage_logging, "写入日志", "📝"),
        ]

    def execute(self, goal: str, constraints: Optional[list[str]] = None) -> dict:
        """
        执行完整的工作流

        Args:
            goal: 用户目标
            constraints: 约束条件

        Returns:
            dict: 执行结果
        """
        self.stats["start_time"] = datetime.now()
        constraints = constraints or []
        import uuid
        self.workflow_session_id = str(uuid.uuid4())

        try:
            # 显示开始面板
            self._show_start_panel(goal)

            # Execute pipeline stages dynamically
            context = {
                "goal": goal,
                "constraints": constraints,
                "task_card": None,
                "memories": [],
                "plan": None,
                "orchestration_plan": None,
                "execution_results": [],
                "validation_results": [],
                "reflections": [],
            }

            for i, stage in enumerate(self._pipeline, 1):
                stage_result = self._execute_stage(stage, i, context)
                # Update context with stage results
                if stage.name == "goal_understanding":
                    context["task_card"] = stage_result
                elif stage.name == "memory_retrieval":
                    context["memories"] = stage_result
                elif stage.name == "plan_generation":
                    context["plan"] = stage_result
                elif stage.name == "tool_orchestration":
                    context["orchestration_plan"] = stage_result
                elif stage.name == "execution":
                    context["execution_results"] = stage_result
                elif stage.name == "validation":
                    context["validation_results"] = stage_result
                elif stage.name == "reflection":
                    context["reflections"] = stage_result

            # 显示完成摘要
            self._show_completion_summary(
                context["task_card"],
                context["execution_results"],
                context["validation_results"]
            )

            final_success = self._workflow_success(
                context["execution_results"],
                context["validation_results"]
            )
            self.stats["success"] = final_success
            self.stats["end_time"] = datetime.now()

            return {
                "success": final_success,
                "task_card": context["task_card"],
                "plan": context["plan"],
                "execution_results": context["execution_results"],
                "validation_results": context["validation_results"],
                "reflections": context["reflections"],
                "stats": self.stats,
            }

        except Exception as e:
            self.console.print(f"\n[bold red]❌ 执行失败: {e}[/bold red]")
            self.stats["success"] = False
            self.stats["end_time"] = datetime.now()
            raise

    def _execute_stage(self, stage: StageConfig, stage_num: int, context: dict) -> Any:
        """Execute a single pipeline stage"""
        return stage.handler(stage_num, context)

    def _show_start_panel(self, goal: str):
        """显示开始面板"""
        panel = Panel(
            f"[bold cyan]目标:[/bold cyan] {goal}\n\n"
            f"[dim]模式: {'仅规划' if self.dry_run else '完整执行'}[/dim]\n"
            f"[dim]自动批准: {'是' if self.auto_approve else '否'}[/dim]",
            title="[bold green]🚀 OpenPilot 工作流启动[/bold green]",
            border_style="green",
        )
        self.console.print(panel)
        self.console.print()

    def _stage_goal_understanding(self, stage_num: int, context: dict) -> TaskCard:
        """阶段: 目标理解"""
        goal = context["goal"]
        constraints = context["constraints"]
        total = len(self._pipeline)

        with self.console.status(f"[bold cyan][{stage_num}/{total}] 📖 理解目标...[/bold cyan]"):
            # 创建初始任务卡片
            try:
                semantic = self.semantic_analyzer.analyze_goal(goal, constraints)
            except Exception as exc:
                self.logger.log_event(
                    "semantic_analysis_failed",
                    {
                        "scope": "goal",
                        "goal": goal,
                        "error": type(exc).__name__,
                        "message": str(exc),
                    },
                    session_id=self.workflow_session_id or "workflow",
                    turn_id=1,
                )
                raise

            # 应用类型识别
            self.logger.log_event(
                "semantic_goal_analysis",
                {"goal": goal, **semantic.log_payload()},
                session_id=self.workflow_session_id or "workflow",
                turn_id=1,
            )

            # 增强任务卡片
            task_card = TaskCard(
                goal=goal,
                task_type=semantic.task_type,
                risk_level=semantic.risk_level,
                required_resources=semantic.required_resources,
                expected_deliverables=semantic.expected_deliverables,
            )

            self.stats["stages_completed"] += 1

        # 显示结果
        self.console.print(f"[bold green]✓[/bold green] [{stage_num}/{len(self._pipeline)}] 目标理解完成")
        self.console.print(f"  • 任务类型: [cyan]{task_card.task_type.value}[/cyan]")
        self.console.print(f"  • 风险等级: [{'red' if task_card.risk_level.value == 'high' else 'yellow' if task_card.risk_level.value == 'medium' else 'green'}]{task_card.risk_level.value}[/]")
        self.console.print(f"  • 所需资源: {len(task_card.required_resources)}个")
        self.console.print()

        return task_card

    def _stage_memory_retrieval(self, stage_num: int, context: dict) -> list:
        """阶段: 记忆检索"""
        task_card = context["task_card"]
        total = len(self._pipeline)

        with self.console.status(f"[bold cyan][{stage_num}/{total}] 🧠 检索记忆...[/bold cyan]"):
            # 检索相关记忆
            memories = self.memory_store.query(task_card.goal, limit=5)
            self.stats["stages_completed"] += 1

        # 显示结果
        self.console.print(f"[bold green]✓[/bold green] [{stage_num}/{len(self._pipeline)}] 记忆检索完成")
        if memories.memories:
            self.console.print(f"  • 找到 {len(memories.memories)} 条相关记忆")
            for mem in memories.memories[:3]:
                self.console.print(f"    - [{mem.memory_type.value}] {mem.content[:50]}...")
        else:
            self.console.print("  • 未找到相关记忆")
        self.console.print()

        return memories.memories

    def _stage_plan_generation(self, stage_num: int, context: dict) -> ExecutionPlan:
        """阶段: 计划生成"""
        goal = context["goal"]
        constraints = context["constraints"]
        memories = context["memories"]
        total = len(self._pipeline)

        with self.console.status(f"[bold cyan][{stage_num}/{total}] 📋 生成计划...[/bold cyan]"):
            # 生成执行计划
            plan = self.planner.plan(goal, constraints=constraints)
            self._last_plan = plan
            self.logger.log_event(
                "workflow_plan_generated",
                {
                    "goal": plan.task_card.goal,
                    "task_type": plan.task_card.task_type.value,
                    "risk_level": plan.task_card.risk_level.value,
                    "planned_steps": self._planned_steps_payload(plan),
                    "success_criteria": plan.success_criteria,
                },
                session_id=self.workflow_session_id or "workflow",
                turn_id=1,
            )
            self.stats["stages_completed"] += 1

        # 显示结果
        self.console.print(f"[bold green]✓[/bold green] [{stage_num}/{len(self._pipeline)}] 计划生成完成")
        self.console.print(f"  • 执行步骤: {len(plan.steps)}个")
        for i, step in enumerate(plan.steps[:5], 1):
            self.console.print(f"    {i}. {step.title}")
        if len(plan.steps) > 5:
            self.console.print(f"    ... 还有 {len(plan.steps) - 5} 个步骤")
        self.console.print()

        return plan

    def _stage_tool_orchestration(self, stage_num: int, context: dict):
        """阶段: 工具编排"""
        plan = context["plan"]
        total = len(self._pipeline)

        with self.console.status(f"[bold cyan][{stage_num}/{total}] 🔧 编排工具...[/bold cyan]"):
            # 创建编排上下文
            from models.tool_orchestration_models import OrchestrationContext

            context = OrchestrationContext(
                task_type=plan.task_card.task_type.value,
                required_capabilities=[],
                max_parallel_tools=3,
                prefer_parallel=True,
                use_memory=True,
                auto_approve_low_risk=self.auto_approve,
            )

            # 为每个步骤选择工具
            result = self.orchestrator.create_orchestration_plan(plan, context)

            if not result.success:
                self.logger.log_event(
                    "semantic_analysis_failed",
                    {
                        "scope": "plan_step",
                        "goal": plan.task_card.goal,
                        "error": result.error,
                    },
                    session_id=self.workflow_session_id or "workflow",
                    turn_id=1,
                )
                raise Exception(f"工具编排失败: {result.error}")

            orchestration_plan = result.plan
            self._last_orchestration_plan = orchestration_plan
            for analysis in self.orchestrator.last_semantic_analyses:
                self.logger.log_event(
                    "semantic_step_analysis",
                    analysis,
                    session_id=self.workflow_session_id or "workflow",
                    turn_id=1,
                )
            self.logger.log_event(
                "tool_orchestration_planned",
                {
                    "goal": orchestration_plan.goal,
                    "tool_selections": self._tool_selections_payload(orchestration_plan),
                    "risk_level": orchestration_plan.risk_level,
                    "execution_strategy": orchestration_plan.execution_strategy,
                    "warnings": result.warnings,
                    "recommendations": result.recommendations,
                },
                session_id=self.workflow_session_id or "workflow",
                turn_id=1,
            )
            self.stats["stages_completed"] += 1

        # 显示结果
        self.console.print(f"[bold green]✓[/bold green] [{stage_num}/{len(self._pipeline)}] 工具编排完成")
        self.console.print(f"  • 工具调用: {len(orchestration_plan.tool_selections)}个")

        # 显示推荐和警告
        if result.recommendations:
            for rec in result.recommendations[:3]:
                self.console.print(f"  💡 {rec}")
        if result.warnings:
            for warn in result.warnings[:3]:
                self.console.print(f"  ⚠️  {warn}")

        self.console.print()

        return orchestration_plan

    def _stage_execution(self, stage_num: int, context: dict):
        """阶段: 执行步骤"""
        orchestration_plan = context["orchestration_plan"]
        total = len(self._pipeline)

        if self.dry_run:
            self.console.print(f"[bold yellow]⊘[/bold yellow] [{stage_num}/{total}] 执行步骤（跳过 - 仅规划模式）")
            self.console.print()
            self.stats["stages_completed"] += 1
            return []

        self.console.print(f"[bold cyan][{stage_num}/{total}] ⚡ 执行步骤...[/bold cyan]")

        execution_results = []
        step_outputs: dict[str, Any] = {}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=self.console,
        ) as progress:
            task = progress.add_task(
                "执行中...",
                total=len(orchestration_plan.tool_selections)
            )

            for i, selection in enumerate(orchestration_plan.tool_selections, 1):
                # 显示当前正在执行的工具和操作
                tool_display_name = self._get_tool_display_name(selection.tool_name)
                progress.update(task, description=f"步骤 {i}/{len(orchestration_plan.tool_selections)}: {tool_display_name}")

                # 执行工具
                resolved_selection, input_resolution = self._resolve_selection_with_diagnostics(selection, step_outputs)
                missing_inputs = input_resolution["missing_required_inputs"]
                if missing_inputs:
                    result = self._create_missing_input_result(resolved_selection, input_resolution)
                else:
                    # 显示详细状态
                    progress.update(task, description=f"步骤 {i}/{len(orchestration_plan.tool_selections)}: {tool_display_name} - 执行中...")
                    result = self.executor.execute_single(resolved_selection)
                    if self._is_empty_llm_output(result):
                        progress.update(task, description=f"步骤 {i}/{len(orchestration_plan.tool_selections)}: {tool_display_name} - 重试中...")
                        result = self._retry_empty_llm_output(resolved_selection, result)
                execution_results.append(result)
                result.metadata["input_keys"] = sorted(resolved_selection.input_params.keys())
                result.metadata["input_resolution"] = input_resolution
                if result.success:
                    step_outputs[result.step_id] = result.output
                self.logger.log_event(
                    "tool_execution_result",
                    self._execution_log_payload(result),
                    session_id=self.workflow_session_id or "workflow",
                    turn_id=1,
                )

                # 显示结果
                status = "✓" if result.success else "✗"
                color = "green" if result.success else "red"
                self.console.print(f"  [{color}]{status}[/{color}] 步骤 {i}: {selection.step_id} ({result.duration_seconds:.1f}s)")
                if result.error:
                    self.console.print(f"    [red]{result.error.error_type}: {result.error.error_message}[/red]")
                    if missing_inputs:
                        self.console.print(
                            f"    [red]missing inputs: {', '.join(missing_inputs)}; "
                            f"input keys: {', '.join(input_resolution['resolved_input_keys']) or '(none)'}[/red]"
                        )
                progress.advance(task)

        self.stats["stages_completed"] += 1
        self.console.print()

        return execution_results

    def _stage_validation(self, stage_num: int, context: dict):
        """阶段: 验证结果"""
        execution_results = context["execution_results"]
        total = len(self._pipeline)

        if self.dry_run:
            self.console.print(f"[bold yellow]⊘[/bold yellow] [{stage_num}/{total}] 验证结果（跳过 - 仅规划模式）")
            self.console.print()
            self.stats["stages_completed"] += 1
            return []

        with self.console.status(f"[bold cyan][{stage_num}/{total}] ✅ 验证结果...[/bold cyan]"):
            validation_results = []
            for result in execution_results:
                validation = self.validator.validate_execution_result(result)
                validation_results.append(validation)

            self.stats["stages_completed"] += 1

        # 显示结果
        self.console.print(f"[bold green]✓[/bold green] [{stage_num}/{len(self._pipeline)}] 结果验证完成")
        passed = sum(1 for v in validation_results if v.passed)
        self.console.print(f"  • 验证通过: {passed}/{len(validation_results)}")

        # 计算平均质量分数
        if validation_results:
            quality_scores = []
            for i, result in enumerate(execution_results):
                validation = validation_results[i] if i < len(validation_results) else None
                if validation:
                    metrics = self.validator.calculate_quality_metrics(result, validation)
                    quality_scores.append(metrics.overall_score)

            if quality_scores:
                avg_quality = sum(quality_scores) / len(quality_scores)
                self.console.print(f"  • 平均质量: {avg_quality:.2f}")

        self.console.print()

        return validation_results

    def _stage_reflection(self, stage_num: int, context: dict):
        """阶段: 生成反思"""
        execution_results = context["execution_results"]
        validation_results = context["validation_results"]
        total = len(self._pipeline)

        if self.dry_run:
            self.console.print(f"[bold yellow]⊘[/bold yellow] [{stage_num}/{total}] 生成反思（跳过 - 仅规划模式）")
            self.console.print()
            self.stats["stages_completed"] += 1
            return []

        with self.console.status(f"[bold cyan][{stage_num}/{total}] 💭 生成反思...[/bold cyan]"):
            reflections = []
            for i, result in enumerate(execution_results):
                validation = validation_results[i] if i < len(validation_results) else None

                # 只有在有验证结果时才计算质量指标
                if validation:
                    metrics = self.validator.calculate_quality_metrics(result, validation)
                else:
                    # 创建默认的质量指标
                    from models.validation_models import QualityMetrics, QualityLevel
                    metrics = QualityMetrics(
                        correctness_score=0.0,
                        completeness_score=0.0,
                        efficiency_score=0.0,
                        user_satisfaction_score=0.0,
                        overall_score=0.0,
                        quality_level=QualityLevel.POOR
                    )

                reflection = self.analyzer.analyze_execution_result(
                    result, validation, metrics
                )
                reflections.append(reflection)

            # 生成优化策略
            if reflections:
                strategies = self.optimizer.generate_optimization_strategies(reflections)

            self.stats["stages_completed"] += 1

        # 显示结果
        self.console.print(f"[bold green]✓[/bold green] [{stage_num}/{len(self._pipeline)}] 反思生成完成")
        success_count = sum(1 for r in reflections if r.reflection_type.value == "success")
        self.console.print(f"  • 成功反思: {success_count}/{len(reflections)}")
        if reflections:
            patterns = self.analyzer.identify_patterns(min_occurrences=2)
            if patterns:
                self.console.print(f"  • 识别模式: {len(patterns)}个")
        self.console.print()

        return reflections

    def _stage_logging(self, stage_num: int, context: dict):
        """阶段: 写入日志"""
        task_card = context["task_card"]
        plan = context["plan"]
        execution_results = context["execution_results"]
        validation_results = context["validation_results"]
        reflections = context["reflections"]
        total = len(self._pipeline)

        with self.console.status(f"[bold cyan][{stage_num}/{total}] 📝 写入日志...[/bold cyan]"):
            # 记录执行日志
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "goal": task_card.goal,
                "task_type": task_card.task_type.value,
                "risk_level": task_card.risk_level.value,
                "steps": len(plan.steps),
                "execution_results": len(execution_results),
                "reflections": len(reflections),
                "success": self._workflow_success(execution_results, validation_results),
                "planned_steps": self._planned_steps_payload(plan),
                "tool_selections": self._tool_selections_payload(self._last_orchestration_plan),
                "step_results": [
                    self._execution_log_payload(result)
                    for result in execution_results
                ],
            }

            self.logger.log_event(
                "workflow_execution",
                log_entry,
                session_id=self.workflow_session_id or "workflow",
                turn_id=1
            )
            self.stats["stages_completed"] += 1

        # 显示结果
        self.console.print(f"[bold green]✓[/bold green] [{stage_num}/{len(self._pipeline)}] 日志写入完成")
        self.console.print()

    def _planned_steps_payload(self, plan: ExecutionPlan) -> list[dict[str, Any]]:
        """Create log-safe planned step payloads."""
        return [
            {
                "id": step.id,
                "title": step.title,
                "description": step.description,
                "expected_output": step.expected_output,
                "dependencies": step.dependencies,
                "risk_level": step.risk_level.value if hasattr(step.risk_level, "value") else str(step.risk_level),
                "confirmation_required": step.confirmation_required,
            }
            for step in plan.steps
        ]

    def _tool_selections_payload(self, orchestration_plan) -> list[dict[str, Any]]:
        """Create log-safe tool selection payloads."""
        if orchestration_plan is None:
            return []
        return [
            {
                "step_id": selection.step_id,
                "tool": selection.tool_name,
                "input_keys": sorted(selection.input_params.keys()),
                "input_preview": self._input_preview(selection.input_params),
                "depends_on": selection.depends_on,
                "source_step_id": selection.input_params.get("source_step_id"),
                "reason": selection.reason.value if hasattr(selection.reason, "value") else str(selection.reason),
                "confidence": selection.confidence,
                "requires_confirmation": selection.requires_confirmation,
            }
            for selection in orchestration_plan.tool_selections
        ]

    def _input_preview(self, input_params: dict[str, Any]) -> dict[str, Any]:
        """Summarize inputs without logging large content."""
        preview: dict[str, Any] = {}
        for key, value in input_params.items():
            if isinstance(value, str):
                preview[key] = {
                    "type": "string",
                    "chars": len(value),
                    "sample": value[:120],
                }
            elif isinstance(value, list):
                preview[key] = {
                    "type": "list",
                    "count": len(value),
                    "sample": [str(item)[:120] for item in value[:3]],
                }
            elif isinstance(value, dict):
                preview[key] = {
                    "type": "object",
                    "keys": sorted(value.keys()),
                }
            else:
                preview[key] = value
        return preview

    def _resolve_selection_with_diagnostics(self, selection, step_outputs: dict[str, Any]):
        """Resolve chained inputs and return diagnostics for logs."""
        original_input_params = dict(selection.input_params)
        source_step_id = original_input_params.get("source_step_id")
        source_available = bool(source_step_id and source_step_id in step_outputs)
        source_output = step_outputs.get(source_step_id) if source_step_id else None
        resolved_selection = self._resolve_selection_inputs(selection, step_outputs)
        missing_required_inputs = self._missing_required_inputs(resolved_selection.tool_name, resolved_selection.input_params)
        source_text = self._coerce_output_to_text(source_output) if source_output is not None else ""
        input_resolution = {
            "original_input_keys": sorted(original_input_params.keys()),
            "resolved_input_keys": sorted(resolved_selection.input_params.keys()),
            "source_step_id": source_step_id,
            "source_available": source_available,
            "source_output_summary": self._summarize_output(source_output),
            "source_text_empty": bool(source_step_id and source_available and not source_text),
            "missing_required_inputs": missing_required_inputs,
            "unresolved_input_chain": (
                resolved_selection.tool_name == "llm_summarizer"
                and "text" in missing_required_inputs
                and not source_available
            ),
        }
        return resolved_selection, input_resolution

    def _resolve_selection_inputs(self, selection, step_outputs: dict[str, Any]):
        """Fill tool inputs from a previous step output when source_step_id is set."""
        input_params = dict(selection.input_params)
        source_step_id = input_params.pop("source_step_id", None)
        source_output = step_outputs.get(source_step_id) if source_step_id else None

        if source_output is not None:
            if selection.tool_name == "file_reader" and "file_path" not in input_params:
                # 从前一个步骤的输出中提取文件路径
                # 如果输出是字符串，直接使用；如果是字典，尝试提取 file_path 或 files
                if isinstance(source_output, str):
                    input_params["file_path"] = source_output
                elif isinstance(source_output, dict):
                    if "file_path" in source_output:
                        input_params["file_path"] = source_output["file_path"]
                    elif "files" in source_output and source_output["files"]:
                        # 如果有多个文件，取第一个
                        input_params["file_path"] = source_output["files"][0]
            elif selection.tool_name == "multi_file_reader" and "file_paths" not in input_params:
                files = self._extract_files(source_output)
                if files:
                    input_params["file_paths"] = files
            elif selection.tool_name == "llm_summarizer" and "text" not in input_params:
                # llm_summarizer 可以接收文本内容或文件列表
                text = self._coerce_output_to_text(source_output)
                if text:
                    input_params["text"] = text
                else:
                    # 如果无法转换为文本，可能是文件列表，尝试读取文件
                    files = self._extract_files(source_output)
                    if files:
                        # 读取所有文件并合并内容
                        combined_text = self._read_and_combine_files(files)
                        if combined_text:
                            input_params["text"] = combined_text
            elif selection.tool_name == "file_writer" and "content" not in input_params:
                # Check if source is code generation output
                if isinstance(source_output, dict) and "code" in source_output:
                    input_params["content"] = source_output["code"]
                else:
                    input_params["content"] = self._coerce_output_to_text(source_output)
            elif selection.tool_name == "code_reviewer":
                # Extract code and language from code_generator output
                if isinstance(source_output, dict):
                    if "code" in source_output:
                        input_params["code"] = source_output["code"]
                    if "language" in source_output:
                        input_params["language"] = source_output["language"]
            elif selection.tool_name == "code_executor":
                # Extract code and language from code_generator output
                if isinstance(source_output, dict):
                    if "code" in source_output:
                        input_params["code"] = source_output["code"]
                    if "language" in source_output:
                        input_params["language"] = source_output["language"]

        return selection.model_copy(update={"input_params": input_params})

    def _missing_required_inputs(self, tool_name: str, input_params: dict[str, Any]) -> list[str]:
        """Return missing required inputs before executing a built-in tool."""
        missing: list[str] = []
        if tool_name == "directory_lister":
            if not input_params.get("directory_path"):
                missing.append("directory_path")
        elif tool_name == "file_reader":
            if not input_params.get("file_path"):
                missing.append("file_path")
        elif tool_name == "file_writer":
            if not input_params.get("file_path"):
                missing.append("file_path")
            if not input_params.get("content"):
                missing.append("content")
        elif tool_name == "llm_summarizer":
            if not input_params.get("text"):
                missing.append("text")
        elif tool_name == "multi_file_reader":
            if not input_params.get("file_paths") and not input_params.get("directory_path"):
                missing.append("file_paths|directory_path")
        elif tool_name == "code_generator":
            if not input_params.get("task_description"):
                missing.append("task_description")
            if not input_params.get("language"):
                missing.append("language")
        elif tool_name == "code_reviewer":
            if not input_params.get("code"):
                missing.append("code")
            if not input_params.get("language"):
                missing.append("language")
        elif tool_name == "code_executor":
            if not input_params.get("code"):
                missing.append("code")
            if not input_params.get("language"):
                missing.append("language")
        return missing

    def _get_tool_display_name(self, tool_name: str) -> str:
        """Get a user-friendly display name for a tool."""
        display_names = {
            "directory_lister": "📁 列出目录",
            "file_reader": "📄 读取文件",
            "multi_file_reader": "📚 读取多个文件",
            "file_writer": "💾 写入文件",
            "llm_summarizer": "🤖 生成摘要",
            "code_generator": "💻 生成代码",
            "code_reviewer": "🔍 审查代码",
            "code_executor": "▶️ 执行代码",
        }
        return display_names.get(tool_name, tool_name)

    def _create_missing_input_result(self, selection, input_resolution: dict[str, Any]):
        """Create a failed execution result for missing required inputs."""
        result = ExecutionResult(
            execution_id=f"missing-input-{selection.step_id}",
            tool_name=selection.tool_name,
            step_id=selection.step_id,
            status=ExecutionStatus.FAILED,
            success=False,
            started_at=datetime.now(),
        )
        missing = input_resolution["missing_required_inputs"]
        source_step_id = input_resolution.get("source_step_id")
        source_note = (
            f"; source_step_id={source_step_id} available={input_resolution.get('source_available')}"
            if source_step_id
            else "; no source_step_id provided"
        )
        result.mark_failed(
            ExecutionError(
                error_type="MissingRequiredInput",
                error_message=(
                    f"{selection.tool_name} missing required input(s): {', '.join(missing)}"
                    f"{source_note}"
                ),
                recoverable=False,
                retry_recommended=False,
            )
        )
        return result

    def _is_empty_llm_output(self, result) -> bool:
        """Return true when an LLM tool succeeded without useful text."""
        if not result.success or result.tool_name != "llm_summarizer":
            return False
        if isinstance(result.output, dict):
            summary = result.output.get("summary")
            return not isinstance(summary, str) or not summary.strip()
        if isinstance(result.output, str):
            return not result.output.strip()
        return result.output is None

    def _retry_empty_llm_output(self, selection, first_result):
        """Retry an empty LLM output once with a shorter text payload."""
        self.logger.log_event(
            "empty_output_retry",
            {
                "step_id": selection.step_id,
                "tool": selection.tool_name,
                "first_output_summary": self._summarize_output(first_result.output),
            },
            session_id=self.workflow_session_id or "workflow",
            turn_id=1,
        )
        retry_params = dict(selection.input_params)
        text = retry_params.get("text")
        # 如果文本太长，大幅减少长度
        if isinstance(text, str) and len(text) > 8000:
            retry_params["text"] = text[:8000]
            self.console.print(f"    [yellow]⚠ 文本过长 ({len(text)} 字符)，截断到 8000 字符后重试[/yellow]")
        retry_params["instruction"] = (
            str(retry_params.get("instruction", "")).strip()
            + "\n\nIMPORTANT: Return a non-empty concise Chinese answer. If the source text is incomplete, summarize what is available."
        ).strip()
        retry_selection = selection.model_copy(update={"input_params": retry_params})
        retry_result = self.executor.execute_single(retry_selection)
        retry_result.metadata["empty_output_retry"] = True
        if self._is_empty_llm_output(retry_result):
            return self._create_empty_llm_result(selection, retry_result)
        return retry_result

    def _create_empty_llm_result(self, selection, last_result):
        """Create a clear failure for repeated empty LLM output."""
        result = ExecutionResult(
            execution_id=f"empty-llm-output-{selection.step_id}",
            tool_name=selection.tool_name,
            step_id=selection.step_id,
            status=ExecutionStatus.FAILED,
            success=False,
            started_at=last_result.started_at,
            output=last_result.output,
        )
        result.mark_failed(
            ExecutionError(
                error_type="EmptyLLMOutput",
                error_message="llm_summarizer returned an empty summary after one retry",
                recoverable=True,
                retry_recommended=True,
            )
        )
        result.metadata["empty_output_retry"] = True
        return result

    def _extract_files(self, output: Any) -> list[str]:
        """Extract file paths from tool output."""
        if isinstance(output, dict):
            files = output.get("files") or output.get("file_paths")
            if isinstance(files, list):
                return [str(item) for item in files]
        return []

    def _coerce_output_to_text(self, output: Any) -> str:
        """Convert a previous tool output into text for downstream tools."""
        if isinstance(output, dict):
            for key in ("content", "summary", "text"):
                value = output.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            return ""
        if isinstance(output, str):
            return output if output.strip() else ""
        return str(output)

    def _read_and_combine_files(self, file_paths: list[str]) -> str:
        """Read multiple files and combine their content."""
        from pathlib import Path

        combined_content = []
        for file_path in file_paths[:10]:  # 限制最多读取10个文件
            try:
                path = Path(file_path)
                if path.exists() and path.is_file():
                    content = path.read_text(encoding='utf-8', errors='ignore')
                    combined_content.append(f"=== {path.name} ===\n{content}\n")
            except Exception as e:
                combined_content.append(f"=== {file_path} (读取失败: {e}) ===\n")

        return "\n".join(combined_content)

    def _execution_log_payload(self, result) -> dict[str, Any]:
        """Create a compact, non-secret execution log payload."""
        return {
            "step_id": result.step_id,
            "tool": result.tool_name,
            "status": result.status.value if hasattr(result.status, "value") else str(result.status),
            "success": result.success,
            "error": None if result.error is None else {
                "type": result.error.error_type,
                "message": result.error.error_message,
            },
            "input_keys": sorted(result.metadata.get("input_keys", [])),
            "input_resolution": result.metadata.get("input_resolution"),
            "output_summary": self._summarize_output(result.output),
            "output_preview": self._preview_output(result.output),
            "duration_seconds": result.duration_seconds,
        }

    def _summarize_output(self, output: Any) -> dict[str, Any] | None:
        """Summarize output shape without logging full content."""
        if output is None:
            return None
        if isinstance(output, dict):
            summary: dict[str, Any] = {"type": "object", "keys": sorted(output.keys())}
            if "files" in output and isinstance(output["files"], list):
                summary["file_count"] = len(output["files"])
            if "content" in output and isinstance(output["content"], str):
                summary["content_chars"] = len(output["content"])
            if "summary" in output and isinstance(output["summary"], str):
                summary["summary_chars"] = len(output["summary"])
            return summary
        if isinstance(output, str):
            return {"type": "string", "chars": len(output)}
        return {"type": type(output).__name__}

    def _preview_output(self, output: Any, max_chars: int = 1500) -> dict[str, Any] | None:
        """Create a bounded text preview for diagnostics."""
        if output is None:
            return None
        if isinstance(output, dict):
            preview: dict[str, Any] = {"type": "object"}
            for key in ("summary", "content", "text"):
                value = output.get(key)
                if isinstance(value, str):
                    preview[key] = {
                        "chars": len(value),
                        "sample": value[:max_chars],
                        "truncated": len(value) > max_chars,
                    }
                    break
            files = output.get("files")
            if isinstance(files, list):
                preview["files"] = [str(item)[:240] for item in files[:10]]
                preview["file_count"] = len(files)
            return preview
        if isinstance(output, str):
            return {
                "type": "string",
                "chars": len(output),
                "sample": output[:max_chars],
                "truncated": len(output) > max_chars,
            }
        return {"type": type(output).__name__}

    def _workflow_success(self, execution_results, validation_results) -> bool:
        """Return true only when execution and validation actually pass."""
        if self.dry_run:
            return True
        if not execution_results:
            return False
        if not all(result.success for result in execution_results):
            return False
        if validation_results and not all(validation.passed for validation in validation_results):
            return False
        return True

    def _show_completion_summary(self, task_card, execution_results, validation_results):
        """显示完成摘要"""
        duration = (datetime.now() - self.stats["start_time"]).total_seconds()

        # 创建摘要表格
        table = Table(title="执行摘要", box=box.ROUNDED, show_header=False)
        table.add_column("项目", style="cyan", width=20)
        table.add_column("值", style="white")

        table.add_row("总耗时", f"{duration:.1f}秒")
        table.add_row("执行步骤", f"{len(execution_results)}个")

        if execution_results:
            success_rate = sum(1 for r in execution_results if r.success) / len(execution_results)
            table.add_row("成功率", f"{success_rate:.0%}")

        if validation_results:
            quality_scores = []
            for i, result in enumerate(execution_results):
                validation = validation_results[i] if i < len(validation_results) else None
                if validation:
                    metrics = self.validator.calculate_quality_metrics(result, validation)
                    quality_scores.append(metrics.overall_score)

            if quality_scores:
                avg_quality = sum(quality_scores) / len(quality_scores)
                table.add_row("平均质量", f"{avg_quality:.2f}")

        self.console.print()
        self.console.print("━" * 80)
        self.console.print("[bold green]✨ 任务完成！[/bold green]")
        self.console.print("━" * 80)
        self.console.print()
        self.console.print(table)

        # 保存报告
        if self.save_report:
            self._save_report(task_card, execution_results, validation_results)

    def _save_report(self, task_card, execution_results, validation_results):
        """保存执行报告"""
        report_path = Path(self.save_report)
        report_content = self._generate_report(task_card, execution_results, validation_results)

        report_path.write_text(report_content, encoding="utf-8")
        self.console.print(f"\n[green]📄 报告已保存到: {report_path}[/green]")

    def _generate_report(self, task_card, execution_results, validation_results) -> str:
        """生成执行报告"""
        duration = (self.stats["end_time"] - self.stats["start_time"]).total_seconds()

        report = f"""# OpenPilot 执行报告

## 任务信息

- **目标**: {task_card.goal}
- **任务类型**: {task_card.task_type.value}
- **风险等级**: {task_card.risk_level.value}
- **执行时间**: {self.stats["start_time"].strftime("%Y-%m-%d %H:%M:%S")}
- **总耗时**: {duration:.1f}秒

## 执行结果

- **执行步骤**: {len(execution_results)}个
- **成功步骤**: {sum(1 for r in execution_results if r.success)}个
- **失败步骤**: {sum(1 for r in execution_results if not r.success)}个

## 质量评估

"""
        if validation_results:
            passed = sum(1 for v in validation_results if v.passed)
            report += f"- **验证通过**: {passed}/{len(validation_results)}\n"

        report += f"\n---\n\n*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n"

        return report
