"""
目标理解增强演示程序

展示OP-01的任务类型识别、资源推断和风险评估功能。
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from src.openpilot.goal_understanding import GoalUnderstandingEnhancer
from src.openpilot.planner import apply_task_type_fallback
from src.openpilot.planner_models import TaskCard, TaskType

console = Console()


def print_section(title: str):
    """打印章节标题"""
    console.print(f"\n[bold cyan]{'=' * 80}[/bold cyan]")
    console.print(f"[bold cyan]{title}[/bold cyan]")
    console.print(f"[bold cyan]{'=' * 80}[/bold cyan]\n")


def print_task_card(task_card: TaskCard, title: str = "任务卡片"):
    """打印任务卡片"""
    table = Table(title=title, box=box.ROUNDED, show_header=False)
    table.add_column("字段", style="cyan", width=20)
    table.add_column("值", style="white")

    table.add_row("目标", task_card.goal)
    table.add_row("任务类型", f"[green]{task_card.task_type.value}[/green]")
    table.add_row("优先级", task_card.priority)
    table.add_row("风险等级", f"[{'red' if task_card.risk_level.value == 'high' else 'yellow' if task_card.risk_level.value == 'medium' else 'green'}]{task_card.risk_level.value}[/]")

    if task_card.required_resources:
        table.add_row("所需资源", ", ".join(task_card.required_resources))

    if task_card.expected_deliverables:
        table.add_row("预期交付物", ", ".join(task_card.expected_deliverables))

    if task_card.constraints:
        table.add_row("约束条件", ", ".join(task_card.constraints))

    console.print(table)


def demo_1_task_type_recognition():
    """演示1: 任务类型识别"""
    print_section("演示 1: 任务类型识别（Phase 2 新增类型）")

    test_cases = [
        ("分析sales_data.csv文件，生成月度销售报告", "数据分析任务"),
        ("写个脚本批量重命名图片文件", "自动化任务"),
        ("研究Rust语言的内存管理机制", "研究任务"),
        ("修复登录页面的bug", "编程任务"),
        ("制定下季度的产品路线图", "规划任务"),
    ]

    for goal, description in test_cases:
        console.print(f"\n[bold]{description}[/bold]")
        console.print(f"输入: [italic]{goal}[/italic]")

        task_card = TaskCard(goal=goal, task_type=TaskType.UNKNOWN)
        result = apply_task_type_fallback(task_card, goal)

        console.print(f"识别类型: [green]{result.task_type.value}[/green]")


def demo_2_resource_inference():
    """演示2: 资源推断"""
    print_section("演示 2: 智能资源推断")

    enhancer = GoalUnderstandingEnhancer()

    test_cases = [
        ("分析用户行为数据", TaskType.DATA_ANALYSIS),
        ("批量转换文件格式", TaskType.AUTOMATION),
        ("研究竞品分析", TaskType.RESEARCH),
    ]

    for goal, task_type in test_cases:
        console.print(f"\n[bold]任务: {goal}[/bold]")
        console.print(f"类型: [cyan]{task_type.value}[/cyan]")

        task_card = TaskCard(goal=goal, task_type=task_type)
        result = enhancer.infer_resources_from_task_type(task_card)

        console.print(f"推断资源: [green]{', '.join(result.required_resources)}[/green]")


def demo_3_risk_assessment():
    """演示3: 风险评估"""
    print_section("演示 3: 智能风险评估")

    enhancer = GoalUnderstandingEnhancer()

    test_cases = [
        ("批量删除临时文件", TaskType.AUTOMATION, ["code_execution", "tool_orchestration"]),
        ("研究技术文档", TaskType.RESEARCH, ["web_search", "memory"]),
        ("发送项目报告邮件", TaskType.COMMUNICATION, ["email"]),
        ("分析数据并生成报告", TaskType.DATA_ANALYSIS, ["local_file", "code_execution"]),
    ]

    for goal, task_type, resources in test_cases:
        console.print(f"\n[bold]任务: {goal}[/bold]")

        task_card = TaskCard(
            goal=goal,
            task_type=task_type,
            required_resources=resources
        )
        result = enhancer.assess_risk_level(task_card)

        risk_color = {
            "low": "green",
            "medium": "yellow",
            "high": "red",
            "forbidden": "red bold"
        }.get(result.risk_level.value, "white")

        console.print(f"风险等级: [{risk_color}]{result.risk_level.value}[/{risk_color}]")
        console.print(f"原因: 任务类型={task_type.value}, 资源={', '.join(resources)}")


def demo_4_complete_enhancement():
    """演示4: 完整增强流程"""
    print_section("演示 4: 完整任务卡片增强")

    enhancer = GoalUnderstandingEnhancer()

    test_cases = [
        "分析sales_data.csv文件，生成月度销售趋势报告",
        "写个Python脚本批量处理Excel文件",
        "研究并总结最新的AI技术发展趋势",
    ]

    for goal in test_cases:
        console.print(f"\n[bold green]原始目标:[/bold green] {goal}\n")

        # 1. 创建初始任务卡片
        task_card = TaskCard(goal=goal, task_type=TaskType.UNKNOWN)
        print_task_card(task_card, "步骤1: 初始任务卡片")

        # 2. 识别任务类型
        task_card = apply_task_type_fallback(task_card, goal)
        console.print(f"\n[cyan]步骤2: 任务类型识别 → {task_card.task_type.value}[/cyan]")

        # 3. 完整增强
        task_card = enhancer.enhance_task_card(task_card)
        print_task_card(task_card, "步骤3: 增强后的任务卡片")

        # 4. 获取约束建议
        suggestions = enhancer.suggest_constraints(task_card)
        if suggestions:
            console.print(f"\n[yellow]步骤4: 约束建议:[/yellow]")
            for suggestion in suggestions:
                console.print(f"  • {suggestion}")


def demo_5_phase2_capabilities():
    """演示5: Phase 2 新能力展示"""
    print_section("演示 5: Phase 2 新增能力")

    enhancer = GoalUnderstandingEnhancer()

    console.print("[bold]Phase 2 新增了两种任务类型:[/bold]\n")

    # 数据分析任务
    console.print("[bold cyan]1. 数据分析任务 (DATA_ANALYSIS)[/bold cyan]")
    console.print("特点: 需要读取数据、执行代码、生成可视化\n")

    task_card = TaskCard(
        goal="分析用户行为数据，找出关键指标和趋势",
        task_type=TaskType.UNKNOWN
    )
    task_card = apply_task_type_fallback(task_card, task_card.goal)
    task_card = enhancer.enhance_task_card(task_card)

    print_task_card(task_card, "数据分析任务示例")

    # 自动化任务
    console.print("\n[bold cyan]2. 自动化任务 (AUTOMATION)[/bold cyan]")
    console.print("特点: 需要代码执行、工具编排、批量处理\n")

    task_card = TaskCard(
        goal="批量转换文档格式并上传到云存储",
        task_type=TaskType.UNKNOWN
    )
    task_card = apply_task_type_fallback(task_card, task_card.goal)
    task_card = enhancer.enhance_task_card(task_card)

    print_task_card(task_card, "自动化任务示例")


def demo_6_comparison():
    """演示6: Phase 1 vs Phase 2 对比"""
    print_section("演示 6: Phase 1 vs Phase 2 对比")

    table = Table(title="功能对比", box=box.ROUNDED)
    table.add_column("功能", style="cyan", width=25)
    table.add_column("Phase 1", style="yellow", width=25)
    table.add_column("Phase 2", style="green", width=25)

    table.add_row(
        "任务类型数量",
        "7种",
        "9种 (+2)"
    )
    table.add_row(
        "新增任务类型",
        "-",
        "data_analysis, automation"
    )
    table.add_row(
        "资源标签数量",
        "12种",
        "14种 (+2)"
    )
    table.add_row(
        "新增资源",
        "-",
        "code_execution, tool_orchestration"
    )
    table.add_row(
        "智能资源推断",
        "基础",
        "增强（基于任务类型）"
    )
    table.add_row(
        "风险评估",
        "基础",
        "多维度（类型+资源+关键词）"
    )
    table.add_row(
        "约束建议",
        "无",
        "有（基于任务类型）"
    )
    table.add_row(
        "交付物推断",
        "基础",
        "增强（更精确）"
    )

    console.print(table)


def main():
    """主函数"""
    console.print(Panel.fit(
        "[bold cyan]OpenPilot OP-01 目标理解增强演示[/bold cyan]\n"
        "展示Phase 2新增的任务类型识别和智能增强功能",
        border_style="cyan"
    ))

    try:
        # 演示1: 任务类型识别
        demo_1_task_type_recognition()

        # 演示2: 资源推断
        demo_2_resource_inference()

        # 演示3: 风险评估
        demo_3_risk_assessment()

        # 演示4: 完整增强流程
        demo_4_complete_enhancement()

        # 演示5: Phase 2 新能力
        demo_5_phase2_capabilities()

        # 演示6: 对比
        demo_6_comparison()

        # 总结
        print_section("演示完成")
        console.print("[bold green]✓ 所有演示已成功完成！[/bold green]\n")
        console.print("OP-01 目标理解增强主要功能:")
        console.print("  • 新增任务类型: data_analysis, automation")
        console.print("  • 智能资源推断: 基于任务类型自动推断所需资源")
        console.print("  • 多维度风险评估: 考虑任务类型、资源和关键词")
        console.print("  • 约束建议: 根据任务类型提供安全建议")
        console.print("  • 交付物推断: 自动推断预期交付物")

    except Exception as e:
        console.print(f"\n[bold red]错误: {e}[/bold red]")
        import traceback
        console.print(traceback.format_exc())


if __name__ == "__main__":
    main()
