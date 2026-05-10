"""
反思与优化演示程序

展示完整的反思分析、策略优化和持续学习流程。
"""

from datetime import datetime, timedelta
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from src.openpilot.code_models import CodeExecutionResult
from src.openpilot.executor_models import ExecutionResult, ExecutionError, ExecutionStatus
from src.openpilot.memory_store import MemoryStore
from src.openpilot.reflection_analyzer import ReflectionAnalyzer
from src.openpilot.reflection_models import PerformanceMetrics
from src.openpilot.strategy_optimizer import StrategyOptimizer
from src.openpilot.validation_models import QualityMetrics, QualityLevel

console = Console()


def print_section(title: str):
    """打印章节标题"""
    console.print(f"\n[bold cyan]{'=' * 80}[/bold cyan]")
    console.print(f"[bold cyan]{title}[/bold cyan]")
    console.print(f"[bold cyan]{'=' * 80}[/bold cyan]\n")


def demo_1_reflection_analysis():
    """演示1: 反思分析"""
    print_section("演示 1: 反思分析")

    analyzer = ReflectionAnalyzer()

    # 成功执行案例
    console.print("[bold green]1.1 分析成功执行[/bold green]\n")

    result = ExecutionResult(
        execution_id="exec_001",
        step_id="step_001",
        tool_name="file_reader",
        status=ExecutionStatus.SUCCESS,
        success=True,
        output={"content": "Sample data from file"},
        started_at=datetime.now(),
        duration_seconds=0.8,
    )

    quality_metrics = QualityMetrics(
        target_id="exec_001",
        correctness_score=0.95,
        completeness_score=0.9,
        efficiency_score=0.92,
        reliability_score=0.93,
        overall_score=0.925,
        quality_level=QualityLevel.EXCELLENT,
    )

    reflection = analyzer.analyze_execution_result(result, None, quality_metrics)

    console.print(f"反思ID: {reflection.reflection_id}")
    console.print(f"反思类型: [green]{reflection.reflection_type.value}[/green]")
    console.print(f"置信度: [cyan]{reflection.confidence:.2f}[/cyan]")
    console.print(f"观察: {reflection.observation}")
    console.print(f"分析: {reflection.analysis}")
    if reflection.insights:
        console.print(f"洞察: {', '.join(reflection.insights)}")

    # 失败执行案例
    console.print("\n[bold red]1.2 分析失败执行[/bold red]\n")

    result = ExecutionResult(
        execution_id="exec_002",
        step_id="step_002",
        tool_name="network_request",
        status=ExecutionStatus.FAILED,
        success=False,
        error=ExecutionError(
            error_type="TimeoutError",
            error_message="Request timeout after 30 seconds",
        ),
        started_at=datetime.now(),
        duration_seconds=30.0,
    )

    reflection = analyzer.analyze_execution_result(result)

    console.print(f"反思ID: {reflection.reflection_id}")
    console.print(f"反思类型: [red]{reflection.reflection_type.value}[/red]")
    console.print(f"置信度: [cyan]{reflection.confidence:.2f}[/cyan]")
    console.print(f"观察: {reflection.observation}")
    console.print(f"分析: {reflection.analysis}")
    if reflection.problems_identified:
        console.print(f"识别的问题: {', '.join(reflection.problems_identified)}")
    if reflection.recommended_actions:
        console.print(f"推荐行动: {', '.join(reflection.recommended_actions)}")

    # 代码执行案例
    console.print("\n[bold blue]1.3 分析代码执行[/bold blue]\n")

    code_result = CodeExecutionResult(
        execution_id="code_001",
        code_id="code_001",
        success=True,
        exit_code=0,
        stdout="Processing complete: 100 items processed",
        stderr="",
        execution_time_ms=150,
    )

    quality_metrics = QualityMetrics(
        target_id="code_001",
        correctness_score=0.9,
        completeness_score=0.95,
        efficiency_score=0.88,
        reliability_score=0.92,
        overall_score=0.91,
        quality_level=QualityLevel.EXCELLENT,
    )

    reflection = analyzer.analyze_code_execution_result(code_result, None, quality_metrics)

    console.print(f"反思ID: {reflection.reflection_id}")
    console.print(f"反思类型: [green]{reflection.reflection_type.value}[/green]")
    console.print(f"置信度: [cyan]{reflection.confidence:.2f}[/cyan]")
    console.print(f"观察: {reflection.observation}")
    console.print(f"分析: {reflection.analysis}")

    return analyzer


def demo_2_pattern_identification(analyzer: ReflectionAnalyzer):
    """演示2: 模式识别"""
    print_section("演示 2: 模式识别")

    console.print("[bold]创建多个相似的失败案例...[/bold]\n")

    # 创建多个相似的失败案例
    for i in range(5):
        result = ExecutionResult(
            execution_id=f"exec_pattern_{i}",
            step_id=f"step_{i}",
            tool_name="database_query",
            status=ExecutionStatus.FAILED,
            success=False,
            error=ExecutionError(
                error_type="ConnectionError",
                error_message="Database connection failed",
            ),
            started_at=datetime.now(),
            duration_seconds=5.0,
        )
        analyzer.analyze_execution_result(result)

    # 识别模式
    patterns = analyzer.identify_patterns(min_occurrences=3)

    console.print(f"[bold green]识别到 {len(patterns)} 个模式:[/bold green]\n")
    for pattern in patterns:
        console.print(f"  • {pattern}")

    # 统计信息
    stats = analyzer.get_stats()

    table = Table(title="反思统计", box=box.ROUNDED)
    table.add_column("指标", style="cyan")
    table.add_column("数值", style="green")

    table.add_row("总反思数", str(stats["total_reflections"]))
    table.add_row("成功反思数", str(stats["success_reflections"]))
    table.add_row("失败反思数", str(stats["failure_reflections"]))
    table.add_row("改进反思数", str(stats["improvement_reflections"]))

    console.print("\n")
    console.print(table)


def demo_3_strategy_optimization(analyzer: ReflectionAnalyzer):
    """演示3: 策略优化"""
    print_section("演示 3: 策略优化")

    optimizer = StrategyOptimizer()

    # 获取所有反思
    reflections = analyzer.get_reflections()

    console.print(f"[bold]基于 {len(reflections)} 个反思生成优化策略...[/bold]\n")

    # 生成优化策略
    strategies = optimizer.generate_optimization_strategies(reflections)

    console.print(f"[bold green]生成了 {len(strategies)} 个优化策略:[/bold green]\n")

    for i, strategy in enumerate(strategies, 1):
        panel = Panel(
            f"[cyan]类型:[/cyan] {strategy.strategy_type.value}\n"
            f"[cyan]目标:[/cyan] {strategy.optimization_target.value}\n"
            f"[cyan]描述:[/cyan] {strategy.description}\n"
            f"[cyan]预期影响:[/cyan] {strategy.expected_impact:.1%}\n"
            f"[cyan]优先级:[/cyan] {strategy.priority}/10\n"
            f"[cyan]工作量:[/cyan] {strategy.estimated_effort}",
            title=f"策略 {i}: {strategy.name}",
            border_style="green",
        )
        console.print(panel)

    return optimizer, strategies


def demo_4_strategy_application(optimizer: StrategyOptimizer, strategies):
    """演示4: 策略应用"""
    print_section("演示 4: 策略应用")

    if not strategies:
        console.print("[yellow]没有可用的策略[/yellow]")
        return

    strategy = strategies[0]

    console.print(f"[bold]策略详情: {strategy.name}[/bold]\n")
    console.print(f"类型: {strategy.strategy_type.value}")
    console.print(f"目标: {strategy.optimization_target.value}")
    console.print(f"预期影响: {strategy.expected_impact:.1%}")
    console.print(f"优先级: {strategy.priority}/10")

    console.print("\n[cyan]实施步骤:[/cyan]")
    for i, step in enumerate(strategy.implementation_steps, 1):
        console.print(f"  {i}. {step}")

    console.print("\n[cyan]验证标准:[/cyan]")
    for criterion in strategy.validation_criteria:
        console.print(f"  • {criterion}")

    console.print(f"\n[bold green]策略已准备就绪，可以应用到实际系统中[/bold green]")


def demo_5_memory_integration(analyzer: ReflectionAnalyzer):
    """演示5: 记忆系统集成"""
    print_section("演示 5: 记忆系统集成")

    memory_store = MemoryStore()
    optimizer = StrategyOptimizer(memory_store)

    # 获取成功反思
    success_reflections = analyzer.get_reflections(reflection_type="success", limit=3)

    console.print(f"[bold]从 {len(success_reflections)} 个成功反思创建学习记录...[/bold]\n")

    learning_records = []
    for reflection in success_reflections:
        record = analyzer.create_learning_record(
            reflection,
            topic="执行优化",
            category="performance",
        )
        record.effectiveness_score = 0.85
        learning_records.append(record)

    console.print(f"[green]创建了 {len(learning_records)} 个学习记录[/green]\n")

    # 更新记忆系统
    console.print("[bold]更新记忆系统...[/bold]\n")

    memory_records = optimizer.update_memory_from_reflections(
        success_reflections,
        learning_records,
    )

    console.print(f"[bold green]创建了 {len(memory_records)} 个记忆记录:[/bold green]\n")

    for memory in memory_records:
        console.print(f"  • [{memory.memory_type.value}] {memory.content[:60]}...")
        console.print(f"    标签: {', '.join(memory.tags)}")
        console.print(f"    置信度: {memory.confidence:.2f}\n")


def demo_6_reflection_report(analyzer: ReflectionAnalyzer):
    """演示6: 反思报告"""
    print_section("演示 6: 反思报告")

    optimizer = StrategyOptimizer()

    # 获取所有反思
    reflections = analyzer.get_reflections()

    # 创建学习记录
    learning_records = []
    for reflection in reflections[:3]:
        record = analyzer.create_learning_record(
            reflection,
            topic="系统优化",
            category="general",
        )
        learning_records.append(record)

    # 生成报告
    start_time = datetime.now() - timedelta(hours=1)
    end_time = datetime.now()

    report = optimizer.generate_reflection_report(
        reflections,
        learning_records,
        start_time,
        end_time,
    )

    console.print(f"[bold]反思报告 (ID: {report.report_id})[/bold]\n")

    # 统计信息
    table = Table(title="反思统计", box=box.ROUNDED)
    table.add_column("类型", style="cyan")
    table.add_column("数量", style="green")

    table.add_row("总反思数", str(report.total_reflections))
    table.add_row("成功反思", str(report.success_reflections))
    table.add_row("失败反思", str(report.failure_reflections))
    table.add_row("改进反思", str(report.improvement_reflections))
    table.add_row("学习记录", str(len(report.learning_records)))
    table.add_row("优化策略", str(len(report.optimization_strategies)))

    console.print(table)

    # 关键发现
    if report.key_findings:
        console.print("\n[bold cyan]关键发现:[/bold cyan]")
        for finding in report.key_findings:
            console.print(f"  • {finding}")

    # 常见模式
    if report.common_patterns:
        console.print("\n[bold cyan]常见模式:[/bold cyan]")
        for pattern in report.common_patterns:
            console.print(f"  • {pattern}")

    # 重复问题
    if report.recurring_issues:
        console.print("\n[bold yellow]重复问题:[/bold yellow]")
        for issue in report.recurring_issues:
            console.print(f"  • {issue}")

    # 优先行动
    if report.priority_actions:
        console.print("\n[bold green]优先行动:[/bold green]")
        for action in report.priority_actions:
            console.print(f"  • {action}")


def demo_7_optimization_statistics(optimizer: StrategyOptimizer):
    """演示7: 优化统计"""
    print_section("演示 7: 优化统计")

    console.print("[bold]优化统计功能已实现[/bold]\n")
    console.print("该模块可以跟踪:")
    console.print("  • 优化次数和成功率")
    console.print("  • 平均改进百分比")
    console.print("  • 策略使用情况")
    console.print("  • 性能趋势分析")

    console.print("\n[cyan]注意:[/cyan] 需要实际应用策略后才能生成统计数据")


def main():
    """主函数"""
    console.print(Panel.fit(
        "[bold cyan]OpenPilot 反思与优化演示[/bold cyan]\n"
        "展示完整的反思分析、策略优化和持续学习流程",
        border_style="cyan"
    ))

    try:
        # 演示1: 反思分析
        analyzer = demo_1_reflection_analysis()

        # 演示2: 模式识别
        demo_2_pattern_identification(analyzer)

        # 演示3: 策略优化
        optimizer, strategies = demo_3_strategy_optimization(analyzer)

        # 演示4: 策略应用
        demo_4_strategy_application(optimizer, strategies)

        # 演示5: 记忆系统集成
        demo_5_memory_integration(analyzer)

        # 演示6: 反思报告
        demo_6_reflection_report(analyzer)

        # 演示7: 优化统计
        demo_7_optimization_statistics(optimizer)

        # 总结
        print_section("演示完成")
        console.print("[bold green]✓ 所有演示已成功完成！[/bold green]\n")
        console.print("主要功能:")
        console.print("  • 反思分析 - 分析执行结果并提取洞察")
        console.print("  • 模式识别 - 识别重复问题和成功模式")
        console.print("  • 策略优化 - 生成和应用优化策略")
        console.print("  • 记忆集成 - 将经验保存到记忆系统")
        console.print("  • 持续学习 - 从每次执行中学习和改进")

    except Exception as e:
        console.print(f"\n[bold red]错误: {e}[/bold red]")
        import traceback
        console.print(traceback.format_exc())


if __name__ == "__main__":
    main()
