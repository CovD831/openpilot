"""Demo script for validation and feedback functionality."""

from datetime import datetime

from openpilot.code_models import CodeExecutionResult, CodeLanguage
from openpilot.executor_models import (
    ExecutionError,
    ExecutionResult,
    ExecutionStatus,
    ResourceUsage,
)
from openpilot.feedback_collector import FeedbackCollector
from openpilot.output_validator import OutputValidator
from openpilot.result_validator import ResultValidator
from openpilot.validation_models import (
    FeedbackType,
    ValidationRule,
    ValidationSeverity,
    ValidationType,
)


def print_section(title: str):
    """Print a section header."""
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)
    print()


def demo_output_validation():
    """Demo: Output validation."""
    print_section("Demo 1: Output Validation")

    validator = OutputValidator()

    # Register validation rules
    rules = [
        ValidationRule(
            rule_id="type_check",
            name="Type Check",
            validation_type=ValidationType.TYPE,
            severity=ValidationSeverity.ERROR,
            expected_type="int",
            description="Check if output is integer",
        ),
        ValidationRule(
            rule_id="range_check",
            name="Range Check",
            validation_type=ValidationType.RANGE,
            severity=ValidationSeverity.WARNING,
            min_value=0,
            max_value=100,
            description="Check if value is in range 0-100",
        ),
    ]

    print("📋 Validation Rules:")
    for rule in rules:
        print(f"   • {rule.name}: {rule.description}")
    print()

    # Test case 1: Valid output
    print("Test 1: Valid output (42)")
    result = validator.validate(42, rules)
    print(f"   Result: {'✅ PASSED' if result.passed else '❌ FAILED'}")
    print(f"   Pass Rate: {result.pass_rate:.1%}")
    print()

    # Test case 2: Out of range
    print("Test 2: Out of range (150)")
    result = validator.validate(150, rules)
    print(f"   Result: {'✅ PASSED' if result.passed else '❌ FAILED'}")
    print(f"   Issues: {len(result.issues)}")
    if result.issues:
        for issue in result.issues:
            print(f"      - {issue.severity.value.upper()}: {issue.message}")
    print()

    # Test case 3: Wrong type
    print("Test 3: Wrong type ('hello')")
    result = validator.validate("hello", rules)
    print(f"   Result: {'✅ PASSED' if result.passed else '❌ FAILED'}")
    print(f"   Issues: {len(result.issues)}")
    if result.issues:
        for issue in result.issues:
            print(f"      - {issue.severity.value.upper()}: {issue.message}")
    print()


def demo_format_validation():
    """Demo: Format validation."""
    print_section("Demo 2: Format Validation")

    validator = OutputValidator()

    formats = [
        ("email", "test@example.com", "invalid-email"),
        ("url", "https://example.com", "not-a-url"),
        ("uuid", "550e8400-e29b-41d4-a716-446655440000", "invalid-uuid"),
    ]

    for format_type, valid_value, invalid_value in formats:
        rule = ValidationRule(
            rule_id=f"{format_type}_check",
            name=f"{format_type.upper()} Check",
            validation_type=ValidationType.FORMAT,
            severity=ValidationSeverity.ERROR,
            expected_format=format_type,
            description=f"Check {format_type} format",
        )

        print(f"Testing {format_type.upper()} format:")

        # Valid
        result = validator.validate(valid_value, [rule])
        print(f"   ✅ Valid: {valid_value} - {'PASSED' if result.passed else 'FAILED'}")

        # Invalid
        result = validator.validate(invalid_value, [rule])
        print(f"   ❌ Invalid: {invalid_value} - {'PASSED' if result.passed else 'FAILED'}")
        print()


def demo_result_validation():
    """Demo: Result validation."""
    print_section("Demo 3: Result Validation")

    validator = ResultValidator()

    # Test case 1: Successful execution
    print("Test 1: Successful execution")
    result = ExecutionResult(
        execution_id="exec_1",
        step_id="step_1",
        tool_name="test_tool",
        status=ExecutionStatus.SUCCESS,
        success=True,
        output={"result": "success", "value": 42},
        duration_seconds=0.5,
        resource_usage=ResourceUsage(cpu_percent=10.0, memory_mb=50.0),
        started_at=datetime.now(),
    )

    validation = validator.validate_execution_result(result)
    metrics = validator.calculate_quality_metrics(result, validation)

    print(f"   Validation: {'✅ PASSED' if validation.passed else '❌ FAILED'}")
    print(f"   Quality Metrics:")
    print(f"      • Overall Score: {metrics.overall_score:.2f}")
    print(f"      • Quality Level: {metrics.quality_level.value.upper()}")
    print(f"      • Correctness: {metrics.correctness_score:.2f}")
    print(f"      • Completeness: {metrics.completeness_score:.2f}")
    print(f"      • Efficiency: {metrics.efficiency_score:.2f}")
    print(f"      • Reliability: {metrics.reliability_score:.2f}")
    print()

    # Test case 2: Failed execution
    print("Test 2: Failed execution")
    result = ExecutionResult(
        execution_id="exec_2",
        step_id="step_2",
        tool_name="test_tool",
        status=ExecutionStatus.FAILED,
        success=False,
        error=ExecutionError(
            error_type="ValueError",
            error_message="Invalid input parameter",
            recoverable=True,
        ),
        duration_seconds=0.1,
        resource_usage=ResourceUsage(cpu_percent=5.0, memory_mb=20.0),
        started_at=datetime.now(),
    )

    validation = validator.validate_execution_result(result)
    metrics = validator.calculate_quality_metrics(result, validation)

    print(f"   Validation: {'✅ PASSED' if validation.passed else '❌ FAILED'}")
    print(f"   Issues: {len(validation.issues)}")
    if validation.issues:
        for issue in validation.issues:
            print(f"      - {issue.message}")
    print(f"   Quality Score: {metrics.overall_score:.2f} ({metrics.quality_level.value.upper()})")
    print()


def demo_feedback_collection():
    """Demo: Feedback collection."""
    print_section("Demo 4: Feedback Collection")

    collector = FeedbackCollector()

    # Collect user feedback
    print("Collecting user feedback...")

    feedback1 = collector.collect_feedback(
        target_id="exec_1",
        feedback_type=FeedbackType.POSITIVE,
        rating=4.5,
        comment="Excellent performance!",
        tags=["fast", "accurate"],
        suggestions=["Keep up the good work"],
    )
    print(f"   ✅ Positive feedback collected: {feedback1.feedback_id}")

    feedback2 = collector.collect_feedback(
        target_id="exec_2",
        feedback_type=FeedbackType.NEGATIVE,
        rating=2.0,
        comment="Too slow and errors",
        tags=["slow", "errors"],
        issues=["Execution timeout", "Invalid output"],
        suggestions=["Optimize performance", "Add error handling"],
    )
    print(f"   ❌ Negative feedback collected: {feedback2.feedback_id}")

    feedback3 = collector.collect_feedback(
        target_id="exec_3",
        feedback_type=FeedbackType.NEUTRAL,
        rating=3.0,
        comment="Works but could be better",
        tags=["acceptable"],
        suggestions=["Improve documentation"],
    )
    print(f"   ⚪ Neutral feedback collected: {feedback3.feedback_id}")
    print()

    # Get statistics
    print("📊 Feedback Statistics:")
    stats = collector.get_feedback_statistics()
    print(f"   Total Feedback: {stats.total_feedback}")
    print(f"   Positive: {stats.positive_feedback} ({stats.positive_rate:.1%})")
    print(f"   Negative: {stats.negative_feedback}")
    print(f"   Neutral: {stats.neutral_feedback}")
    print(f"   Average Rating: {stats.average_rating:.2f}/5.0")
    print()


def demo_automatic_feedback():
    """Demo: Automatic feedback."""
    print_section("Demo 5: Automatic Feedback")

    validator = ResultValidator()
    collector = FeedbackCollector()

    print("Generating automatic feedback based on quality metrics...")
    print()

    # High quality result
    print("Test 1: High quality result")
    result1 = ExecutionResult(
        execution_id="exec_high",
        step_id="step_high",
        tool_name="test_tool",
        status=ExecutionStatus.SUCCESS,
        success=True,
        output={"result": "perfect"},
        duration_seconds=0.3,
        resource_usage=ResourceUsage(cpu_percent=8.0, memory_mb=30.0),
        started_at=datetime.now(),
    )

    validation1 = validator.validate_execution_result(result1)
    metrics1 = validator.calculate_quality_metrics(result1, validation1)
    feedback1 = collector.collect_automatic_feedback("exec_high", metrics1, validation1)

    print(f"   Quality Score: {metrics1.overall_score:.2f}")
    print(f"   Feedback Type: {feedback1.feedback_type.value.upper()}")
    print(f"   Auto Rating: {feedback1.rating:.2f}/5.0")
    print(f"   Tags: {', '.join(feedback1.tags)}")
    print()

    # Low quality result
    print("Test 2: Low quality result")
    result2 = ExecutionResult(
        execution_id="exec_low",
        step_id="step_low",
        tool_name="test_tool",
        status=ExecutionStatus.SUCCESS,
        success=True,
        output=None,  # No output
        duration_seconds=35.0,  # Very slow
        resource_usage=ResourceUsage(cpu_percent=50.0, memory_mb=200.0),
        started_at=datetime.now(),
    )

    validation2 = validator.validate_execution_result(result2)
    metrics2 = validator.calculate_quality_metrics(result2, validation2)
    feedback2 = collector.collect_automatic_feedback("exec_low", metrics2, validation2)

    print(f"   Quality Score: {metrics2.overall_score:.2f}")
    print(f"   Feedback Type: {feedback2.feedback_type.value.upper()}")
    print(f"   Auto Rating: {feedback2.rating:.2f}/5.0")
    print(f"   Issues: {len(feedback2.issues)}")
    for issue in feedback2.issues[:3]:
        print(f"      - {issue}")
    print()


def demo_improvement_suggestions():
    """Demo: Improvement suggestions."""
    print_section("Demo 6: Improvement Suggestions")

    validator = ResultValidator()
    collector = FeedbackCollector()

    # Create a result with multiple issues
    result = ExecutionResult(
        execution_id="exec_improve",
        step_id="step_improve",
        tool_name="test_tool",
        status=ExecutionStatus.SUCCESS,
        success=True,
        output=None,  # Low completeness
        duration_seconds=40.0,  # Low efficiency
        resource_usage=ResourceUsage(cpu_percent=80.0, memory_mb=400.0),
        started_at=datetime.now(),
    )

    validation = validator.validate_execution_result(result)
    metrics = validator.calculate_quality_metrics(result, validation)
    suggestions = collector.generate_improvement_suggestions(
        "exec_improve", metrics, validation
    )

    print(f"Quality Score: {metrics.overall_score:.2f} ({metrics.quality_level.value.upper()})")
    print()
    print(f"💡 Generated {len(suggestions)} improvement suggestions:")
    print()

    for i, suggestion in enumerate(suggestions, 1):
        print(f"{i}. {suggestion.title}")
        print(f"   Category: {suggestion.category}")
        print(f"   Priority: {suggestion.priority.upper()}")
        print(f"   Description: {suggestion.description}")
        print(f"   Expected Improvement: {suggestion.expected_improvement}")
        print(f"   Action Items:")
        for action in suggestion.action_items[:3]:
            print(f"      • {action}")
        print()


def demo_code_execution_validation():
    """Demo: Code execution validation."""
    print_section("Demo 7: Code Execution Validation")

    validator = ResultValidator()

    # Successful code execution
    print("Test 1: Successful code execution")
    result = CodeExecutionResult(
        execution_id="code_exec_1",
        code_id="code_1",
        success=True,
        exit_code=0,
        stdout="Hello, World!\n",
        return_value=42,
        execution_time_ms=50,
        sandbox_used=True,
    )

    validation = validator.validate_code_execution_result(result)
    metrics = validator.calculate_code_quality_metrics(result, validation)

    print(f"   Validation: {'✅ PASSED' if validation.passed else '❌ FAILED'}")
    print(f"   Quality Score: {metrics.overall_score:.2f}")
    print(f"   Quality Level: {metrics.quality_level.value.upper()}")
    print()

    # Failed code execution
    print("Test 2: Failed code execution")
    result = CodeExecutionResult(
        execution_id="code_exec_2",
        code_id="code_2",
        success=False,
        exit_code=1,
        stderr="ZeroDivisionError: division by zero\n",
        error_type="ZeroDivisionError",
        error_message="division by zero",
        error_line=5,
        execution_time_ms=10,
        sandbox_used=True,
    )

    validation = validator.validate_code_execution_result(result)
    metrics = validator.calculate_code_quality_metrics(result, validation)

    print(f"   Validation: {'✅ PASSED' if validation.passed else '❌ FAILED'}")
    print(f"   Quality Score: {metrics.overall_score:.2f}")
    print(f"   Error: {result.error_type} at line {result.error_line}")
    print()


def main():
    """Run all demos."""
    print()
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║         OpenPilot Phase 2 - Validation & Feedback Demo              ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")

    demo_output_validation()
    demo_format_validation()
    demo_result_validation()
    demo_feedback_collection()
    demo_automatic_feedback()
    demo_improvement_suggestions()
    demo_code_execution_validation()

    # Summary
    print_section("Summary")
    print("✅ OP-24 结果验证与反馈 - 完成！")
    print()
    print("核心功能:")
    print("  • 输出验证（类型、范围、格式、模式、Schema）")
    print("  • 结果验证（工具执行、代码执行）")
    print("  • 质量指标计算（正确性、完整性、效率、可靠性）")
    print("  • 用户反馈收集")
    print("  • 自动反馈生成")
    print("  • 改进建议生成")
    print("  • 反馈统计分析")
    print()
    print("验证类型:")
    print("  • TYPE: 类型验证")
    print("  • RANGE: 范围验证")
    print("  • FORMAT: 格式验证（email, url, uuid, date, ipv4）")
    print("  • PATTERN: 正则模式验证")
    print("  • SCHEMA: 结构验证（JSON Schema）")
    print("  • CUSTOM: 自定义验证")
    print()
    print("质量等级:")
    print("  • EXCELLENT: >= 0.9")
    print("  • GOOD: >= 0.7")
    print("  • FAIR: >= 0.5")
    print("  • POOR: >= 0.3")
    print("  • VERY_POOR: < 0.3")
    print()
    print("Phase 2 第二阶段进度: 1/4 (25%) ✅")
    print()
    print("已完成:")
    print("  ✅ OP-20 工具注册与发现")
    print("  ✅ OP-21 工具编排引擎")
    print("  ✅ OP-22 安全执行器")
    print("  ✅ OP-23 代码生成与执行引擎")
    print("  ✅ OP-24 结果验证与反馈")
    print()
    print("下一步：OP-25 反思与优化")
    print()


if __name__ == "__main__":
    main()
