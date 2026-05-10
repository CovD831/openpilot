"""Tests for validation and feedback system."""

import pytest
from datetime import datetime, timedelta

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
    QualityLevel,
    ValidationRule,
    ValidationSeverity,
    ValidationType,
)


# ============================================================================
# Output Validator Tests
# ============================================================================

def test_output_validator_type_validation():
    """Test type validation."""
    validator = OutputValidator()

    rule = ValidationRule(
        rule_id="type_check",
        name="Type Check",
        validation_type=ValidationType.TYPE,
        severity=ValidationSeverity.ERROR,
        expected_type="int",
        description="Check if output is integer",
    )

    # Valid case
    result = validator.validate(42, [rule])
    assert result.passed
    assert len(result.issues) == 0

    # Invalid case
    result = validator.validate("not an int", [rule])
    assert not result.passed
    assert len(result.issues) == 1
    assert result.issues[0].severity == ValidationSeverity.ERROR


def test_output_validator_range_validation():
    """Test range validation."""
    validator = OutputValidator()

    rule = ValidationRule(
        rule_id="range_check",
        name="Range Check",
        validation_type=ValidationType.RANGE,
        severity=ValidationSeverity.WARNING,
        min_value=0,
        max_value=100,
        description="Check if value is in range",
    )

    # Valid case
    result = validator.validate(50, [rule])
    assert result.passed

    # Below minimum
    result = validator.validate(-10, [rule])
    assert not result.passed
    assert "小于最小值" in result.issues[0].message

    # Above maximum
    result = validator.validate(150, [rule])
    assert not result.passed
    assert "大于最大值" in result.issues[0].message


def test_output_validator_pattern_validation():
    """Test pattern validation."""
    validator = OutputValidator()

    rule = ValidationRule(
        rule_id="pattern_check",
        name="Pattern Check",
        validation_type=ValidationType.PATTERN,
        severity=ValidationSeverity.ERROR,
        pattern=r"^\d{3}-\d{4}$",  # Phone number pattern
        description="Check phone number format",
    )

    # Valid case
    result = validator.validate("123-4567", [rule])
    assert result.passed

    # Invalid case
    result = validator.validate("invalid", [rule])
    assert not result.passed


def test_output_validator_format_validation():
    """Test format validation."""
    validator = OutputValidator()

    # Email format
    email_rule = ValidationRule(
        rule_id="email_check",
        name="Email Check",
        validation_type=ValidationType.FORMAT,
        severity=ValidationSeverity.ERROR,
        expected_format="email",
        description="Check email format",
    )

    result = validator.validate("test@example.com", [email_rule])
    assert result.passed

    result = validator.validate("invalid-email", [email_rule])
    assert not result.passed

    # URL format
    url_rule = ValidationRule(
        rule_id="url_check",
        name="URL Check",
        validation_type=ValidationType.FORMAT,
        severity=ValidationSeverity.ERROR,
        expected_format="url",
        description="Check URL format",
    )

    result = validator.validate("https://example.com", [url_rule])
    assert result.passed

    result = validator.validate("not-a-url", [url_rule])
    assert not result.passed


def test_output_validator_custom_validation():
    """Test custom validation."""
    validator = OutputValidator()

    # Register custom validator
    def is_even(value, rule):
        if isinstance(value, int) and value % 2 == 0:
            return True, None
        return False, "Value must be even"

    validator.register_custom_validator("is_even", is_even)

    rule = ValidationRule(
        rule_id="even_check",
        name="Even Check",
        validation_type=ValidationType.CUSTOM,
        severity=ValidationSeverity.WARNING,
        custom_validator="is_even",
        description="Check if value is even",
    )

    # Valid case
    result = validator.validate(42, [rule])
    assert result.passed

    # Invalid case
    result = validator.validate(43, [rule])
    assert not result.passed


def test_output_validator_schema_validation():
    """Test schema validation."""
    validator = OutputValidator()

    rule = ValidationRule(
        rule_id="schema_check",
        name="Schema Check",
        validation_type=ValidationType.SCHEMA,
        severity=ValidationSeverity.ERROR,
        schema={
            "type": "object",
            "required": ["name", "age"],
        },
        description="Check object schema",
    )

    # Valid case
    result = validator.validate({"name": "John", "age": 30}, [rule])
    assert result.passed

    # Missing required field
    result = validator.validate({"name": "John"}, [rule])
    assert not result.passed
    assert "缺少必需字段" in result.issues[0].message


# ============================================================================
# Result Validator Tests
# ============================================================================

def test_result_validator_successful_execution():
    """Test validation of successful execution."""
    validator = ResultValidator()

    result = ExecutionResult(
        execution_id="exec_1",
        step_id="step_1",
        tool_name="test_tool",
        status=ExecutionStatus.SUCCESS,
        success=True,
        output={"result": 42},
        duration_seconds=0.5,
        resource_usage=ResourceUsage(cpu_percent=10.0, memory_mb=50.0),
        started_at=datetime.now(),
    )

    validation = validator.validate_execution_result(result)
    assert validation.passed


def test_result_validator_failed_execution():
    """Test validation of failed execution."""
    validator = ResultValidator()

    result = ExecutionResult(
        execution_id="exec_2",
        step_id="step_2",
        tool_name="test_tool",
        status=ExecutionStatus.FAILED,
        success=False,
        error=ExecutionError(
            error_type="ValueError",
            error_message="Invalid input",
            recoverable=True,
        ),
        duration_seconds=0.1,
        resource_usage=ResourceUsage(cpu_percent=5.0, memory_mb=20.0),
        started_at=datetime.now(),
    )

    validation = validator.validate_execution_result(result)
    assert not validation.passed
    assert validation.critical_count == 1


def test_result_validator_with_expected_output():
    """Test validation with expected output."""
    validator = ResultValidator()

    result = ExecutionResult(
        execution_id="exec_3",
        step_id="step_3",
        tool_name="test_tool",
        status=ExecutionStatus.SUCCESS,
        success=True,
        output=42,
        duration_seconds=0.3,
        resource_usage=ResourceUsage(cpu_percent=8.0, memory_mb=30.0),
        started_at=datetime.now(),
    )

    # Matching output
    validation = validator.validate_execution_result(result, expected_output=42)
    assert validation.passed

    # Non-matching output
    validation = validator.validate_execution_result(result, expected_output=100)
    assert not validation.passed
    assert any("不匹配" in issue.message for issue in validation.issues)


def test_result_validator_quality_metrics():
    """Test quality metrics calculation."""
    validator = ResultValidator()

    result = ExecutionResult(
        execution_id="exec_4",
        step_id="step_4",
        tool_name="test_tool",
        status=ExecutionStatus.SUCCESS,
        success=True,
        output={"data": "test"},
        duration_seconds=0.5,
        resource_usage=ResourceUsage(cpu_percent=10.0, memory_mb=50.0),
        started_at=datetime.now(),
    )

    validation = validator.validate_execution_result(result)
    metrics = validator.calculate_quality_metrics(result, validation)

    assert 0.0 <= metrics.overall_score <= 1.0
    assert metrics.correctness_score >= 0  # Can be 0 if no validation rules
    assert metrics.completeness_score > 0
    assert metrics.efficiency_score > 0
    assert metrics.reliability_score > 0
    assert metrics.quality_level in QualityLevel


def test_result_validator_code_execution():
    """Test code execution result validation."""
    validator = ResultValidator()

    result = CodeExecutionResult(
        execution_id="code_exec_1",
        code_id="code_1",
        success=True,
        exit_code=0,
        stdout="Hello, World!",
        return_value=42,
        execution_time_ms=100,
        sandbox_used=True,
    )

    validation = validator.validate_code_execution_result(result)
    assert validation.passed

    metrics = validator.calculate_code_quality_metrics(result, validation)
    assert metrics.overall_score > 0.5
    assert metrics.quality_level != QualityLevel.VERY_POOR


# ============================================================================
# Feedback Collector Tests
# ============================================================================

def test_feedback_collector_collect_feedback():
    """Test feedback collection."""
    collector = FeedbackCollector()

    feedback = collector.collect_feedback(
        target_id="exec_1",
        feedback_type=FeedbackType.POSITIVE,
        rating=4.5,
        comment="Great result!",
        tags=["fast", "accurate"],
        issues=[],
        suggestions=["Keep it up"],
    )

    assert feedback.feedback_id.startswith("fb_")
    assert feedback.target_id == "exec_1"
    assert feedback.feedback_type == FeedbackType.POSITIVE
    assert feedback.rating == 4.5


def test_feedback_collector_automatic_feedback():
    """Test automatic feedback collection."""
    collector = FeedbackCollector()
    validator = ResultValidator()

    result = ExecutionResult(
        execution_id="exec_5",
        step_id="step_5",
        tool_name="test_tool",
        status=ExecutionStatus.SUCCESS,
        success=True,
        output={"result": "success"},
        duration_seconds=0.3,
        resource_usage=ResourceUsage(cpu_percent=10.0, memory_mb=50.0),
        started_at=datetime.now(),
    )

    validation = validator.validate_execution_result(result)
    metrics = validator.calculate_quality_metrics(result, validation)

    feedback = collector.collect_automatic_feedback("exec_5", metrics, validation)

    assert feedback.source == "system"
    assert feedback.rating is not None
    assert len(feedback.tags) > 0


def test_feedback_collector_improvement_suggestions():
    """Test improvement suggestion generation."""
    collector = FeedbackCollector()
    validator = ResultValidator()

    # Create a result with low quality
    result = ExecutionResult(
        execution_id="exec_6",
        step_id="step_6",
        tool_name="test_tool",
        status=ExecutionStatus.SUCCESS,
        success=True,
        output=None,  # No output - low completeness
        duration_seconds=35.0,  # Slow - low efficiency
        resource_usage=ResourceUsage(cpu_percent=10.0, memory_mb=50.0),
        started_at=datetime.now(),
    )

    validation = validator.validate_execution_result(result)
    metrics = validator.calculate_quality_metrics(result, validation)

    suggestions = collector.generate_improvement_suggestions(
        "exec_6", metrics, validation
    )

    assert len(suggestions) > 0
    # Check that we have suggestions for low efficiency
    assert any(s.category == "efficiency" for s in suggestions)


def test_feedback_collector_statistics():
    """Test feedback statistics."""
    collector = FeedbackCollector()

    # Collect some feedback
    for i in range(10):
        feedback_type = (
            FeedbackType.POSITIVE if i < 7 else FeedbackType.NEGATIVE
        )
        collector.collect_feedback(
            target_id=f"exec_{i}",
            feedback_type=feedback_type,
            rating=4.0 if i < 7 else 2.0,
            issues=["issue1"] if i >= 7 else [],
        )

    stats = collector.get_feedback_statistics()

    assert stats.total_feedback == 10
    assert stats.positive_feedback == 7
    assert stats.negative_feedback == 3
    assert stats.positive_rate == 0.7
    assert stats.average_rating > 0


def test_feedback_collector_get_feedback_for_target():
    """Test getting feedback for specific target."""
    collector = FeedbackCollector()

    # Collect feedback for multiple targets
    collector.collect_feedback(
        target_id="exec_1",
        feedback_type=FeedbackType.POSITIVE,
        rating=4.0,
    )
    collector.collect_feedback(
        target_id="exec_1",
        feedback_type=FeedbackType.POSITIVE,
        rating=5.0,
    )
    collector.collect_feedback(
        target_id="exec_2",
        feedback_type=FeedbackType.NEGATIVE,
        rating=2.0,
    )

    feedback_list = collector.get_feedback_for_target("exec_1")
    assert len(feedback_list) == 2
    assert all(fb.target_id == "exec_1" for fb in feedback_list)


# ============================================================================
# Integration Tests
# ============================================================================

def test_full_validation_pipeline():
    """Test full validation and feedback pipeline."""
    output_validator = OutputValidator()
    result_validator = ResultValidator(output_validator)
    feedback_collector = FeedbackCollector()

    # Create execution result
    result = ExecutionResult(
        execution_id="exec_full",
        step_id="step_full",
        tool_name="test_tool",
        status=ExecutionStatus.SUCCESS,
        success=True,
        output=42,
        duration_seconds=0.5,
        resource_usage=ResourceUsage(cpu_percent=10.0, memory_mb=50.0),
        started_at=datetime.now(),
    )

    # Validate result
    validation = result_validator.validate_execution_result(result)
    assert validation.passed

    # Calculate quality metrics
    metrics = result_validator.calculate_quality_metrics(result, validation)
    assert metrics.overall_score > 0

    # Collect automatic feedback
    feedback = feedback_collector.collect_automatic_feedback(
        "exec_full", metrics, validation
    )
    assert feedback.feedback_id

    # Generate improvement suggestions
    suggestions = feedback_collector.generate_improvement_suggestions(
        "exec_full", metrics, validation
    )
    # High quality result may have no suggestions
    assert isinstance(suggestions, list)


def test_validation_with_multiple_rules():
    """Test validation with multiple rules."""
    validator = OutputValidator()

    rules = [
        ValidationRule(
            rule_id="type_check",
            name="Type Check",
            validation_type=ValidationType.TYPE,
            severity=ValidationSeverity.ERROR,
            expected_type="int",
            description="Check type",
        ),
        ValidationRule(
            rule_id="range_check",
            name="Range Check",
            validation_type=ValidationType.RANGE,
            severity=ValidationSeverity.WARNING,
            min_value=0,
            max_value=100,
            description="Check range",
        ),
    ]

    # All rules pass
    result = validator.validate(50, rules)
    assert result.passed
    assert result.passed_rules == 2

    # One rule fails
    result = validator.validate(150, rules)
    assert not result.passed
    assert result.passed_rules == 1
    assert result.failed_rules == 1


def test_stats_collection():
    """Test statistics collection."""
    output_validator = OutputValidator()
    result_validator = ResultValidator(output_validator)
    feedback_collector = FeedbackCollector()

    # Perform some operations
    rule = ValidationRule(
        rule_id="test",
        name="Test",
        validation_type=ValidationType.TYPE,
        severity=ValidationSeverity.ERROR,
        expected_type="int",
        description="Test",
    )

    output_validator.validate(42, [rule])
    output_validator.validate(43, [rule])

    feedback_collector.collect_feedback(
        target_id="test",
        feedback_type=FeedbackType.POSITIVE,
        rating=4.0,
    )

    # Check stats
    output_stats = output_validator.get_stats()
    assert output_stats["total_validations"] == 2

    result_stats = result_validator.get_stats()
    assert "output_validator_stats" in result_stats

    feedback_stats = feedback_collector.get_stats()
    assert feedback_stats["total_feedback"] == 1
