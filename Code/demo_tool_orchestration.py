"""Demo script for tool orchestration functionality."""

from openpilot.builtin_tools import register_builtin_tools
from openpilot.planner_models import ExecutionPlan, PlanStep, TaskCard
from openpilot.tool_orchestration_models import OrchestrationContext
from openpilot.tool_orchestrator import ToolOrchestrator
from openpilot.tool_registry import ToolRegistry


def print_section(title: str):
    """Print a section header."""
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)
    print()


def print_tool_selection(selection):
    """Print tool selection details."""
    print(f"  Step: {selection.step_id}")
    print(f"  Tool: {selection.tool_name}")
    print(f"  Reason: {selection.reason}")
    print(f"  Confidence: {selection.confidence:.2%}")
    print(f"  Requires confirmation: {selection.requires_confirmation}")
    if selection.fallback_tools:
        print(f"  Fallback options: {', '.join(selection.fallback_tools)}")
    if selection.depends_on:
        print(f"  Depends on: {', '.join(selection.depends_on)}")
    print()


def demo_simple_workflow():
    """Demo: Simple file processing workflow."""
    print_section("Demo 1: Simple File Processing Workflow")

    # Setup
    registry = ToolRegistry()
    register_builtin_tools(registry)
    orchestrator = ToolOrchestrator(registry)

    # Create execution plan
    task_card = TaskCard(
        goal="Read a file and summarize it",
        task_type="research",
        risk_level="low"
    )

    execution_plan = ExecutionPlan(
        task_card=task_card,
        steps=[
            PlanStep(
                id="step_1",
                title="Read input file",
                description="Read the content from data.txt",
                risk_level="low",
                expected_output="File content"
            ),
            PlanStep(
                id="step_2",
                title="Summarize content",
                description="Generate a summary using LLM",
                risk_level="low",
                dependencies=["step_1"],
                expected_output="Summary text"
            ),
            PlanStep(
                id="step_3",
                title="Save summary",
                description="Write summary to summary.txt",
                risk_level="medium",
                dependencies=["step_2"],
                expected_output="File saved"
            )
        ],
        success_criteria=["Summary generated and saved"]
    )

    # Create orchestration context
    context = OrchestrationContext(
        task_type="research",
        max_permission_level="high",
        prefer_parallel=False
    )

    # Generate orchestration plan
    print("📋 Generating orchestration plan...")
    result = orchestrator.create_orchestration_plan(execution_plan, context)

    if not result.success:
        print(f"❌ Planning failed: {result.error}")
        return

    plan = result.plan
    print(f"✅ Plan generated in {result.planning_time_ms}ms")
    print()

    # Display plan details
    print("🎯 Goal:", plan.goal)
    print("📊 Execution Strategy:", plan.execution_strategy)
    print("⚠️  Risk Level:", plan.risk_level)
    print("⏱️  Estimated Duration:", plan.estimated_duration_seconds, "seconds")
    print("💰 Estimated Cost: $", plan.estimated_cost)
    print()

    # Display tool selections
    print("🔧 Tool Selections:")
    for selection in plan.tool_selections:
        print_tool_selection(selection)

    # Display recommendations
    if result.recommendations:
        print("💡 Recommendations:")
        for rec in result.recommendations:
            print(f"  • {rec}")
        print()

    # Display warnings
    if result.warnings:
        print("⚠️  Warnings:")
        for warn in result.warnings:
            print(f"  • {warn}")
        print()


def demo_parallel_execution():
    """Demo: Parallel execution detection."""
    print_section("Demo 2: Parallel Execution Detection")

    # Setup
    registry = ToolRegistry()
    register_builtin_tools(registry)
    orchestrator = ToolOrchestrator(registry)

    # Create execution plan with independent steps
    task_card = TaskCard(
        goal="Process multiple files in parallel",
        task_type="file_workflow",
        risk_level="low"
    )

    execution_plan = ExecutionPlan(
        task_card=task_card,
        steps=[
            PlanStep(
                id="step_1",
                title="Read file 1",
                description="Read content from file1.txt",
                risk_level="low",
                expected_output="File 1 content"
            ),
            PlanStep(
                id="step_2",
                title="Read file 2",
                description="Read content from file2.txt",
                risk_level="low",
                expected_output="File 2 content"
            ),
            PlanStep(
                id="step_3",
                title="Read file 3",
                description="Read content from file3.txt",
                risk_level="low",
                expected_output="File 3 content"
            ),
            PlanStep(
                id="step_4",
                title="Combine results",
                description="Combine all file contents using LLM",
                risk_level="low",
                dependencies=["step_1", "step_2", "step_3"],
                expected_output="Combined content"
            )
        ],
        success_criteria=["All files processed and combined"]
    )

    # Create context that prefers parallel execution
    context = OrchestrationContext(
        task_type="file_workflow",
        max_permission_level="high",
        prefer_parallel=True
    )

    # Generate plan
    print("📋 Generating orchestration plan with parallel execution...")
    result = orchestrator.create_orchestration_plan(execution_plan, context)

    if not result.success:
        print(f"❌ Planning failed: {result.error}")
        return

    plan = result.plan
    print(f"✅ Plan generated")
    print()

    # Display parallel groups
    if plan.parallel_groups:
        print("⚡ Parallel Execution Groups:")
        for group in plan.parallel_groups:
            print(f"  Group: {group.group_id}")
            print(f"  Tools: {len(group.tool_selections)}")
            print(f"  Timeout: {group.timeout_seconds}s")
            print(f"  Wait for all: {group.wait_for_all}")
            print()
            for selection in group.tool_selections:
                print(f"    • {selection.step_id}: {selection.tool_name}")
            print()
    else:
        print("ℹ️  No parallel execution opportunities detected")
        print()

    # Display sequential steps
    sequential_steps = [
        s for s in plan.tool_selections
        if not any(s in g.tool_selections for g in plan.parallel_groups)
    ]
    if sequential_steps:
        print("📝 Sequential Steps:")
        for selection in sequential_steps:
            print(f"  • {selection.step_id}: {selection.tool_name}")
        print()


def demo_fallback_strategies():
    """Demo: Fallback strategy generation."""
    print_section("Demo 3: Fallback Strategies")

    # Setup
    registry = ToolRegistry()
    register_builtin_tools(registry)
    orchestrator = ToolOrchestrator(registry)

    # Create execution plan
    task_card = TaskCard(
        goal="Write important data to file",
        task_type="file_workflow",
        risk_level="medium"
    )

    execution_plan = ExecutionPlan(
        task_card=task_card,
        steps=[
            PlanStep(
                id="step_1",
                title="Write data",
                description="Write important data to output.txt",
                risk_level="medium",
                expected_output="Data written"
            )
        ],
        success_criteria=["Data safely written"]
    )

    context = OrchestrationContext(
        task_type="file_workflow",
        max_permission_level="high"
    )

    # Generate plan
    print("📋 Generating orchestration plan with fallback strategies...")
    result = orchestrator.create_orchestration_plan(execution_plan, context)

    if not result.success:
        print(f"❌ Planning failed: {result.error}")
        return

    plan = result.plan
    print(f"✅ Plan generated")
    print()

    # Display fallback strategies
    if plan.fallback_strategies:
        print("🔄 Fallback Strategies:")
        for tool_name, strategy in plan.fallback_strategies.items():
            print(f"  Primary Tool: {strategy.primary_tool}")
            print(f"  Fallback Sequence: {' → '.join(strategy.fallback_sequence)}")
            print(f"  Trigger Errors: {', '.join(strategy.trigger_on_errors)}")
            print(f"  Max Attempts: {strategy.max_attempts}")
            print(f"  Backoff: {strategy.backoff_seconds}s")
            print()
    else:
        print("ℹ️  No fallback strategies needed")
        print()


def main():
    """Run all demos."""
    print()
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║         OpenPilot Phase 2 - Tool Orchestration Demo                 ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")

    demo_simple_workflow()
    demo_parallel_execution()
    demo_fallback_strategies()

    print_section("Summary")
    print("✅ OP-21 智能工具选择与编排 - 完成！")
    print()
    print("核心功能:")
    print("  • 智能工具选择（基于能力、权限、历史表现）")
    print("  • 工具调用链生成（考虑依赖关系）")
    print("  • 并行执行识别（提升效率）")
    print("  • 备选方案生成（提高可靠性）")
    print("  • 风险评估和确认控制")
    print()
    print("下一步：OP-22 安全执行器")
    print()


if __name__ == "__main__":
    main()
