"""Demo script for code generation and execution functionality."""

from openpilot.code_executor import CodeExecutor
from openpilot.code_generator import CodeGenerator
from openpilot.code_models import (
    CodeGenerationRequest,
    CodeLanguage,
    DangerLevel,
)
from openpilot.code_reviewer import CodeReviewer


def print_section(title: str):
    """Print a section header."""
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)
    print()


def print_code(code: str, language: str = "python"):
    """Print code with formatting."""
    print(f"```{language}")
    print(code)
    print("```")
    print()


def demo_code_generation():
    """Demo: Code generation."""
    print_section("Demo 1: Code Generation")

    generator = CodeGenerator()

    # Example 1: Simple Python function
    print("📝 Generating Python code to read a file...")
    request = CodeGenerationRequest(
        request_id="demo_1",
        task_description="Create a function to read a file and return its content",
        language=CodeLanguage.PYTHON,
        max_lines=50,
    )

    result = generator.generate_code(request)

    print(f"✅ Code generated successfully!")
    print(f"   Code ID: {result.code_id}")
    print(f"   Lines: {result.line_count}")
    print(f"   Imports: {', '.join(result.imports) if result.imports else 'None'}")
    print(f"   Functions: {', '.join(result.functions) if result.functions else 'None'}")
    print(f"   Generation time: {result.generation_time_ms}ms")
    print()
    print("Generated code:")
    print_code(result.code)

    return result


def demo_code_review(generated_code):
    """Demo: Code review."""
    print_section("Demo 2: Code Review")

    reviewer = CodeReviewer()

    print("🔍 Reviewing generated code...")
    review_result = reviewer.review_code(generated_code)

    print(f"Review Result:")
    print(f"   Approved: {'✅ Yes' if review_result.approved else '❌ No'}")
    print(f"   Danger Level: {review_result.overall_danger_level.value.upper()}")
    print(f"   Quality Score: {review_result.quality_score:.2f}/1.0")
    print(f"   Complexity Score: {review_result.complexity_score:.2f}/1.0")
    print()

    if review_result.dangerous_operations:
        print(f"⚠️  Dangerous Operations Found: {len(review_result.dangerous_operations)}")
        for op in review_result.dangerous_operations[:3]:
            print(f"   - Line {op.line_number}: {op.operation}")
            print(f"     Danger: {op.danger_level.value.upper()}")
            print(f"     Reason: {op.reason}")
            print(f"     Suggestion: {op.suggestion}")
        print()

    if review_result.warnings:
        print(f"⚠️  Warnings: {len(review_result.warnings)}")
        for warning in review_result.warnings[:3]:
            print(f"   - {warning}")
        print()

    if review_result.recommendations:
        print(f"💡 Recommendations:")
        for rec in review_result.recommendations[:3]:
            print(f"   - {rec}")
        print()

    return review_result


def demo_code_execution(generated_code):
    """Demo: Code execution."""
    print_section("Demo 3: Code Execution")

    executor = CodeExecutor()

    print("🚀 Executing code...")
    exec_result = executor.execute(generated_code)

    print(f"Execution Result:")
    print(f"   Success: {'✅ Yes' if exec_result.success else '❌ No'}")
    print(f"   Exit Code: {exec_result.exit_code}")
    print(f"   Execution Time: {exec_result.execution_time_ms}ms")
    print(f"   Sandbox Used: {exec_result.sandbox_used}")
    print()

    if exec_result.stdout:
        print(f"📤 Standard Output:")
        print(f"   {exec_result.stdout[:200]}")
        print()

    if exec_result.stderr:
        print(f"⚠️  Standard Error:")
        print(f"   {exec_result.stderr[:200]}")
        print()

    if exec_result.error_message:
        print(f"❌ Error:")
        print(f"   Type: {exec_result.error_type}")
        print(f"   Message: {exec_result.error_message}")
        if exec_result.error_line:
            print(f"   Line: {exec_result.error_line}")
        print()

    return exec_result


def demo_dangerous_code_detection():
    """Demo: Dangerous code detection."""
    print_section("Demo 4: Dangerous Code Detection")

    reviewer = CodeReviewer()

    dangerous_examples = [
        (
            "Using eval()",
            CodeLanguage.PYTHON,
            """
user_input = input("Enter expression: ")
result = eval(user_input)
print(result)
""",
        ),
        (
            "Using os.system()",
            CodeLanguage.PYTHON,
            """
import os
os.system("rm -rf /tmp/test")
""",
        ),
        (
            "Shell rm -rf",
            CodeLanguage.SHELL,
            """
#!/bin/bash
rm -rf /important/data
""",
        ),
    ]

    for name, language, code in dangerous_examples:
        print(f"🔍 Testing: {name}")

        from openpilot.code_models import GeneratedCode

        generated = GeneratedCode(
            code_id=f"dangerous_{name}",
            request_id="demo_dangerous",
            language=language,
            code=code,
            line_count=len(code.strip().split("\n")),
            imports=[],
            functions=[],
            model_used="test",
            generation_time_ms=0,
        )

        review = reviewer.review_code(generated)

        status = "✅ SAFE" if review.approved else "❌ BLOCKED"
        print(f"   Status: {status}")
        print(f"   Danger Level: {review.overall_danger_level.value.upper()}")

        if review.dangerous_operations:
            print(f"   Dangerous Operations: {len(review.dangerous_operations)}")
            for op in review.dangerous_operations[:1]:
                print(f"      - {op.operation}: {op.reason}")

        print()


def demo_full_pipeline():
    """Demo: Full pipeline with safe code."""
    print_section("Demo 5: Full Pipeline (Generate → Review → Execute)")

    generator = CodeGenerator()
    reviewer = CodeReviewer()
    executor = CodeExecutor()

    # Generate code
    print("Step 1: Generate Code")
    print("-" * 70)
    request = CodeGenerationRequest(
        request_id="pipeline_demo",
        task_description="Write a function to calculate factorial",
        language=CodeLanguage.PYTHON,
    )

    generated = generator.generate_code(request)
    print(f"✅ Generated {generated.line_count} lines of code")
    print()

    # Review code
    print("Step 2: Review Code")
    print("-" * 70)
    review = reviewer.review_code(generated)
    print(f"{'✅' if review.approved else '❌'} Review: {review.overall_danger_level.value.upper()}")
    print(f"   Quality: {review.quality_score:.2f}, Complexity: {review.complexity_score:.2f}")
    print()

    # Execute code (only if approved)
    print("Step 3: Execute Code")
    print("-" * 70)
    if review.approved:
        execution = executor.execute(generated)
        print(f"{'✅' if execution.success else '❌'} Execution: {'SUCCESS' if execution.success else 'FAILED'}")
        print(f"   Time: {execution.execution_time_ms}ms")
        if execution.stdout:
            print(f"   Output: {execution.stdout[:100]}")
    else:
        print("❌ Execution blocked due to failed review")

    print()


def demo_retry_mechanism():
    """Demo: Retry mechanism."""
    print_section("Demo 6: Retry Mechanism")

    executor = CodeExecutor()

    print("🔄 Testing retry mechanism...")

    from openpilot.code_models import GeneratedCode

    # Code that will succeed
    code = GeneratedCode(
        code_id="retry_test",
        request_id="retry_demo",
        language=CodeLanguage.PYTHON,
        code="""
print("Execution attempt")
result = 42
print(f"Result: {result}")
""",
        line_count=3,
        imports=[],
        functions=[],
        model_used="test",
        generation_time_ms=0,
    )

    result = executor.execute_with_retry(code, max_retries=3)

    print(f"✅ Execution: {'SUCCESS' if result.success else 'FAILED'}")
    print(f"   Exit Code: {result.exit_code}")
    print(f"   Time: {result.execution_time_ms}ms")
    print()


def demo_statistics():
    """Demo: Statistics collection."""
    print_section("Demo 7: Statistics")

    generator = CodeGenerator()
    reviewer = CodeReviewer()
    executor = CodeExecutor()

    # Generate and execute some code
    for i in range(3):
        request = CodeGenerationRequest(
            request_id=f"stats_{i}",
            task_description=f"Test task {i}",
            language=CodeLanguage.PYTHON,
        )
        generated = generator.generate_code(request)
        reviewer.review_code(generated)
        executor.execute(generated)

    # Show statistics
    print("📊 System Statistics:")
    print()

    gen_stats = generator.get_stats()
    print(f"Code Generator:")
    print(f"   Total Generations: {gen_stats['total_generations']}")
    print(f"   Model: {gen_stats['model']}")
    print()

    exec_stats = executor.get_stats()
    print(f"Code Executor:")
    print(f"   Total Executions: {exec_stats['total_executions']}")
    print(f"   Sandbox Enabled: {exec_stats['sandbox_enabled']}")
    print(f"   Default Timeout: {exec_stats['default_timeout']}s")
    print()


def main():
    """Run all demos."""
    print()
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║         OpenPilot Phase 2 - Code Generation & Execution Demo        ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")

    # Demo 1: Code Generation
    generated_code = demo_code_generation()

    # Demo 2: Code Review
    review_result = demo_code_review(generated_code)

    # Demo 3: Code Execution
    if review_result.approved:
        demo_code_execution(generated_code)

    # Demo 4: Dangerous Code Detection
    demo_dangerous_code_detection()

    # Demo 5: Full Pipeline
    demo_full_pipeline()

    # Demo 6: Retry Mechanism
    demo_retry_mechanism()

    # Demo 7: Statistics
    demo_statistics()

    # Summary
    print_section("Summary")
    print("✅ OP-23 代码生成与执行引擎 - 完成！")
    print()
    print("核心功能:")
    print("  • LLM 代码生成（Python/Shell）")
    print("  • 静态代码分析（AST + 模式匹配）")
    print("  • 危险操作检测（5个等级）")
    print("  • 代码质量评估")
    print("  • 沙箱安全执行")
    print("  • 超时控制")
    print("  • 错误捕获与追踪")
    print("  • 自动重试机制")
    print("  • 输出验证")
    print()
    print("安全特性:")
    print("  • 三层安全检查（生成前、审查、执行）")
    print("  • 危险模式库（eval, exec, os.system, rm -rf 等）")
    print("  • 语法错误检测")
    print("  • 资源限制（超时、内存）")
    print("  • 沙箱隔离")
    print()
    print("Phase 2 第一阶段完成度: 4/4 (100%) ✅")
    print()
    print("已完成:")
    print("  ✅ OP-20 工具注册与发现")
    print("  ✅ OP-21 工具编排引擎")
    print("  ✅ OP-22 安全执行器")
    print("  ✅ OP-23 代码生成与执行引擎")
    print()
    print("下一步：OP-24 结果验证与反馈")
    print()


if __name__ == "__main__":
    main()
