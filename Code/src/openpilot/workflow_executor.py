"""
工作流执行器

整合Phase 2所有模块，提供完整的8阶段执行流程。
"""

from datetime import datetime
from typing import Optional
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.table import Table
from rich import box

from openpilot.goal_understanding import GoalUnderstandingEnhancer
from openpilot.planner import TaskPlanner, apply_task_type_fallback
from openpilot.planner_models import TaskCard, TaskType, ExecutionPlan
from openpilot.memory_store import MemoryStore
from openpilot.tool_registry import ToolRegistry
from openpilot.tool_orchestrator import ToolOrchestrator
from openpilot.tool_executor import ToolExecutor
from openpilot.result_validator import ResultValidator
from openpilot.reflection_analyzer import ReflectionAnalyzer
from openpilot.strategy_optimizer import StrategyOptimizer
from openpilot.openpilot_log import OpenPilotLogger


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


class WorkflowExecutor:
    """工作流执行器"""

    def __init__(
        self,
        llm_client,
        console: Optional[Console] = None,
        dry_run: bool = False,
        auto_approve: bool = False,
        save_report: Optional[str] = None,
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
        self.goal_enhancer = GoalUnderstandingEnhancer()
        self.planner = TaskPlanner(llm_client)
        self.memory_store = MemoryStore()
        self.tool_registry = ToolRegistry()
        self.orchestrator = ToolOrchestrator(self.tool_registry)
        self.executor = ToolExecutor(self.tool_registry)
        self.validator = ResultValidator()
        self.analyzer = ReflectionAnalyzer()
        self.optimizer = StrategyOptimizer(self.memory_store)

        # 初始化日志记录器（使用默认路径）
        default_log_file = Path(__file__).resolve().parents[2] / "logs" / "workflow.jsonl"
        self.logger = OpenPilotLogger(default_log_file)

        # 执行统计
        self.stats = {
            "start_time": None,
            "end_time": None,
            "stages_completed": 0,
            "total_stages": 8,
            "success": False,
        }

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

        try:
            # 显示开始面板
            self._show_start_panel(goal)

            # 阶段1: 目标理解
            task_card = self._stage_1_goal_understanding(goal)

            # 阶段2: 记忆检索
            memories = self._stage_2_memory_retrieval(task_card)

            # 阶段3: 计划生成
            plan = self._stage_3_plan_generation(goal, constraints, memories)

            # 阶段4: 工具编排
            orchestration_plan = self._stage_4_tool_orchestration(plan)

            # 阶段5: 执行步骤
            execution_results = self._stage_5_execution(orchestration_plan)

            # 阶段6: 验证结果
            validation_results = self._stage_6_validation(execution_results)

            # 阶段7: 生成反思
            reflections = self._stage_7_reflection(execution_results, validation_results)

            # 阶段8: 写入日志
            self._stage_8_logging(task_card, plan, execution_results, reflections)

            # 显示完成摘要
            self._show_completion_summary(task_card, execution_results, validation_results)

            self.stats["success"] = True
            self.stats["end_time"] = datetime.now()

            return {
                "success": True,
                "task_card": task_card,
                "plan": plan,
                "execution_results": execution_results,
                "validation_results": validation_results,
                "reflections": reflections,
                "stats": self.stats,
            }

        except Exception as e:
            self.console.print(f"\n[bold red]❌ 执行失败: {e}[/bold red]")
            self.stats["success"] = False
            self.stats["end_time"] = datetime.now()
            raise

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

    def _stage_1_goal_understanding(self, goal: str) -> TaskCard:
        """阶段1: 目标理解"""
        with self.console.status("[bold cyan][1/8] 📖 理解目标...[/bold cyan]"):
            # 创建初始任务卡片
            task_card = TaskCard(goal=goal, task_type=TaskType.UNKNOWN)

            # 应用类型识别
            task_card = apply_task_type_fallback(task_card, goal)

            # 增强任务卡片
            task_card = self.goal_enhancer.enhance_task_card(task_card)

            self.stats["stages_completed"] += 1

        # 显示结果
        self.console.print("[bold green]✓[/bold green] [1/8] 目标理解完成")
        self.console.print(f"  • 任务类型: [cyan]{task_card.task_type.value}[/cyan]")
        self.console.print(f"  • 风险等级: [{'red' if task_card.risk_level.value == 'high' else 'yellow' if task_card.risk_level.value == 'medium' else 'green'}]{task_card.risk_level.value}[/]")
        self.console.print(f"  • 所需资源: {len(task_card.required_resources)}个")
        self.console.print()

        return task_card

    def _stage_2_memory_retrieval(self, task_card: TaskCard) -> list:
        """阶段2: 记忆检索"""
        with self.console.status("[bold cyan][2/8] 🧠 检索记忆...[/bold cyan]"):
            # 检索相关记忆
            memories = self.memory_store.query(task_card.goal, limit=5)
            self.stats["stages_completed"] += 1

        # 显示结果
        self.console.print("[bold green]✓[/bold green] [2/8] 记忆检索完成")
        if memories.memories:
            self.console.print(f"  • 找到 {len(memories.memories)} 条相关记忆")
            for mem in memories.memories[:3]:
                self.console.print(f"    - [{mem.memory_type.value}] {mem.content[:50]}...")
        else:
            self.console.print("  • 未找到相关记忆")
        self.console.print()

        return memories.memories

    def _stage_3_plan_generation(
        self, goal: str, constraints: list[str], memories: list
    ) -> ExecutionPlan:
        """阶段3: 计划生成"""
        with self.console.status("[bold cyan][3/8] 📋 生成计划...[/bold cyan]"):
            # 生成执行计划
            plan = self.planner.plan(goal, constraints=constraints)
            self.stats["stages_completed"] += 1

        # 显示结果
        self.console.print("[bold green]✓[/bold green] [3/8] 计划生成完成")
        self.console.print(f"  • 执行步骤: {len(plan.steps)}个")
        for i, step in enumerate(plan.steps[:5], 1):
            self.console.print(f"    {i}. {step.title}")
        if len(plan.steps) > 5:
            self.console.print(f"    ... 还有 {len(plan.steps) - 5} 个步骤")
        self.console.print()

        return plan

    def _stage_4_tool_orchestration(self, plan: ExecutionPlan):
        """阶段4: 工具编排"""
        with self.console.status("[bold cyan][4/8] 🔧 编排工具...[/bold cyan]"):
            # 为每个步骤选择工具
            orchestration_plan = self.orchestrator.orchestrate(plan)
            self.stats["stages_completed"] += 1

        # 显示结果
        self.console.print("[bold green]✓[/bold green] [4/8] 工具编排完成")
        self.console.print(f"  • 工具调用: {len(orchestration_plan.tool_selections)}个")
        self.console.print()

        return orchestration_plan

    def _stage_5_execution(self, orchestration_plan):
        """阶段5: 执行步骤"""
        if self.dry_run:
            self.console.print("[bold yellow]⊘[/bold yellow] [5/8] 执行步骤（跳过 - 仅规划模式）")
            self.console.print()
            self.stats["stages_completed"] += 1
            return []

        self.console.print("[bold cyan][5/8] ⚡ 执行步骤...[/bold cyan]")

        execution_results = []

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
                progress.update(task, description=f"步骤 {i}/{len(orchestration_plan.tool_selections)}: {selection.step_id}")

                # 执行工具
                result = self.executor.execute(selection)
                execution_results.append(result)

                # 显示结果
                status = "✓" if result.success else "✗"
                color = "green" if result.success else "red"
                self.console.print(f"  [{color}]{status}[/{color}] 步骤 {i}: {selection.step_id} ({result.duration_seconds:.1f}s)")

                progress.advance(task)

        self.stats["stages_completed"] += 1
        self.console.print()

        return execution_results

    def _stage_6_validation(self, execution_results):
        """阶段6: 验证结果"""
        if self.dry_run:
            self.console.print("[bold yellow]⊘[/bold yellow] [6/8] 验证结果（跳过 - 仅规划模式）")
            self.console.print()
            self.stats["stages_completed"] += 1
            return []

        with self.console.status("[bold cyan][6/8] ✅ 验证结果...[/bold cyan]"):
            validation_results = []
            for result in execution_results:
                validation = self.validator.validate_execution_result(result)
                validation_results.append(validation)

            self.stats["stages_completed"] += 1

        # 显示结果
        self.console.print("[bold green]✓[/bold green] [6/8] 结果验证完成")
        passed = sum(1 for v in validation_results if v.passed)
        self.console.print(f"  • 验证通过: {passed}/{len(validation_results)}")

        # 计算平均质量分数
        if validation_results:
            quality_scores = []
            for result in execution_results:
                metrics = self.validator.calculate_quality_metrics(result)
                quality_scores.append(metrics.overall_score)

            avg_quality = sum(quality_scores) / len(quality_scores)
            self.console.print(f"  • 平均质量: {avg_quality:.2f}")

        self.console.print()

        return validation_results

    def _stage_7_reflection(self, execution_results, validation_results):
        """阶段7: 生成反思"""
        if self.dry_run:
            self.console.print("[bold yellow]⊘[/bold yellow] [7/8] 生成反思（跳过 - 仅规划模式）")
            self.console.print()
            self.stats["stages_completed"] += 1
            return []

        with self.console.status("[bold cyan][7/8] 💭 生成反思...[/bold cyan]"):
            reflections = []
            for i, result in enumerate(execution_results):
                validation = validation_results[i] if i < len(validation_results) else None
                metrics = self.validator.calculate_quality_metrics(result)

                reflection = self.analyzer.analyze_execution_result(
                    result, validation, metrics
                )
                reflections.append(reflection)

            # 生成优化策略
            if reflections:
                strategies = self.optimizer.generate_optimization_strategies(reflections)

            self.stats["stages_completed"] += 1

        # 显示结果
        self.console.print("[bold green]✓[/bold green] [7/8] 反思生成完成")
        success_count = sum(1 for r in reflections if r.reflection_type.value == "success")
        self.console.print(f"  • 成功反思: {success_count}/{len(reflections)}")
        if reflections:
            patterns = self.analyzer.identify_patterns(min_occurrences=2)
            if patterns:
                self.console.print(f"  • 识别模式: {len(patterns)}个")
        self.console.print()

        return reflections

    def _stage_8_logging(self, task_card, plan, execution_results, reflections):
        """阶段8: 写入日志"""
        with self.console.status("[bold cyan][8/8] 📝 写入日志...[/bold cyan]"):
            # 记录执行日志
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "goal": task_card.goal,
                "task_type": task_card.task_type.value,
                "risk_level": task_card.risk_level.value,
                "steps": len(plan.steps),
                "execution_results": len(execution_results),
                "reflections": len(reflections),
                "success": all(r.success for r in execution_results) if execution_results else True,
            }

            # 生成会话ID（使用时间戳）
            import uuid
            session_id = str(uuid.uuid4())

            self.logger.log_event(
                "workflow_execution",
                log_entry,
                session_id=session_id,
                turn_id=1
            )
            self.stats["stages_completed"] += 1

        # 显示结果
        self.console.print("[bold green]✓[/bold green] [8/8] 日志写入完成")
        self.console.print()

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
            for result in execution_results:
                metrics = self.validator.calculate_quality_metrics(result)
                quality_scores.append(metrics.overall_score)
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

        report += f"\n---\n\n*报告生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*\n"

        return report
