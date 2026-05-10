"""Tests for code generation, review, and execution."""

import pytest

from openpilot.code_executor import CodeExecutor
from openpilot.code_generator import CodeGenerator
from openpilot.code_models import (
    CodeGenerationRequest,
    CodeLanguage,
    DangerLevel,
    GeneratedCode,
)
from openpilot.code_reviewer import CodeReviewer


# ============================================================================
# Code Generator Tests
# ============================================================================

def test_generator_python_basic():
    """Test basic Python code generation."""
    generator = CodeGenerator()

    request = CodeGenerationRequest(
        request_id="req_1",
        task_description="Create a function to read a file",
        language=CodeLanguage.PYTHON,
    )

    result = generator.generate_code(request)

    assert result.code_id.startswith("code_")
    assert result.language == CodeLanguage.PYTHON
    assert result.code
    assert result.line_count > 0
    assert result.generation_time_ms >= 0


def test_generator_python_with_constraints():
    """Test Python generation with constraints."""
    generator = CodeGenerator()

    request = CodeGenerationRequest(
        request_id="req_2",
        task_description="Write a file writer function",
        language=CodeLanguage.PYTHON,
        max_lines=50,
        allowed_imports=["os", "pathlib"],
        forbidden_operations=["eval", "exec"],
    )

    result = generator.generate_code(request)

    assert result.code
    assert "write" in result.code.lower()
    # Check that forbidden operations are not in code
    assert "eval(" not in result.code
    assert "exec(" not in result.code


def test_generator_shell_basic():
    """Test basic Shell code generation."""
    generator = CodeGenerator()

    request = CodeGenerationRequest(
        request_id="req_3",
        task_description="Create a script to list files",
        language=CodeLanguage.SHELL,
    )

    result = generator.generate_code(request)

    assert result.language == CodeLanguage.SHELL
    assert result.code
    assert result.line_count > 0


def test_generator_extract_imports():
    """Test import extraction."""
    generator = CodeGenerator()

    code = """
import os
import sys
from pathlib import Path
from typing import List, Dict

def main():
    pass
"""

    imports = generator._extract_imports(code, CodeLanguage.PYTHON)

    assert "os" in imports
    assert "sys" in imports
    assert "pathlib" in imports
    assert "typing" in imports


def test_generator_extract_functions():
    """Test function extraction."""
    generator = CodeGenerator()

    code = """
def read_file(path):
    pass

def write_file(path, content):
    pass

class MyClass:
    def method(self):
        pass
"""

    functions = generator._extract_functions(code, CodeLanguage.PYTHON)

    assert "read_file" in functions
    assert "write_file" in functions
    assert "method" in functions


# ============================================================================
# Code Reviewer Tests
# ============================================================================

def test_reviewer_safe_code():
    """Test review of safe code."""
    reviewer = CodeReviewer()

    generated_code = GeneratedCode(
        code_id="code_1",
        request_id="req_1",
        language=CodeLanguage.PYTHON,
        code="""
def add_numbers(a, b):
    return a + b

result = add_numbers(1, 2)
print(result)
""",
        line_count=5,
        imports=[],
        functions=["add_numbers"],
        model_used="test",
        generation_time_ms=100,
    )

    result = reviewer.review_code(generated_code)

    assert result.approved
    assert result.overall_danger_level == DangerLevel.SAFE
    assert len(result.dangerous_operations) == 0
    assert len(result.syntax_errors) == 0


def test_reviewer_dangerous_eval():
    """Test detection of eval usage."""
    reviewer = CodeReviewer()

    generated_code = GeneratedCode(
        code_id="code_2",
        request_id="req_2",
        language=CodeLanguage.PYTHON,
        code="""
user_input = input("Enter code: ")
result = eval(user_input)
print(result)
""",
        line_count=3,
        imports=[],
        functions=[],
        model_used="test",
        generation_time_ms=100,
    )

    result = reviewer.review_code(generated_code)

    assert not result.approved
    assert result.overall_danger_level == DangerLevel.CRITICAL
    assert len(result.dangerous_operations) > 0
    assert any(op.operation == "eval" for op in result.dangerous_operations)


def test_reviewer_dangerous_os_system():
    """Test detection of os.system usage."""
    reviewer = CodeReviewer()

    generated_code = GeneratedCode(
        code_id="code_3",
        request_id="req_3",
        language=CodeLanguage.PYTHON,
        code="""
import os
os.system("rm -rf /tmp/test")
""",
        line_count=2,
        imports=["os"],
        functions=[],
        model_used="test",
        generation_time_ms=100,
    )

    result = reviewer.review_code(generated_code)

    assert not result.approved
    assert result.overall_danger_level == DangerLevel.CRITICAL
    assert any("os.system" in op.operation for op in result.dangerous_operations)


def test_reviewer_syntax_error():
    """Test detection of syntax errors."""
    reviewer = CodeReviewer()

    generated_code = GeneratedCode(
        code_id="code_4",
        request_id="req_4",
        language=CodeLanguage.PYTHON,
        code="""
def broken_function(
    print("Missing closing parenthesis")
""",
        line_count=2,
        imports=[],
        functions=[],
        model_used="test",
        generation_time_ms=100,
    )

    result = reviewer.review_code(generated_code)

    assert not result.approved
    assert len(result.syntax_errors) > 0


def test_reviewer_shell_dangerous_rm():
    """Test detection of dangerous rm command."""
    reviewer = CodeReviewer()

    generated_code = GeneratedCode(
        code_id="code_5",
        request_id="req_5",
        language=CodeLanguage.SHELL,
        code="""
#!/bin/bash
rm -rf /important/data
""",
        line_count=2,
        imports=[],
        functions=[],
        model_used="test",
        generation_time_ms=100,
    )

    result = reviewer.review_code(generated_code)

    assert not result.approved
    assert result.overall_danger_level == DangerLevel.CRITICAL


def test_reviewer_quality_score():
    """Test code quality scoring."""
    reviewer = CodeReviewer()

    # Good quality code
    generated_code = GeneratedCode(
        code_id="code_6",
        request_id="req_6",
        language=CodeLanguage.PYTHON,
        code="""
def calculate_sum(numbers):
    \"\"\"Calculate sum of numbers.\"\"\"
    total = 0
    for num in numbers:
        total += num
    return total

def main():
    \"\"\"Main function.\"\"\"
    result = calculate_sum([1, 2, 3, 4, 5])
    print(f"Sum: {result}")

if __name__ == "__main__":
    main()
""",
        line_count=13,
        imports=[],
        functions=["calculate_sum", "main"],
        model_used="test",
        generation_time_ms=100,
    )

    result = reviewer.review_code(generated_code)

    assert result.approved
    assert result.quality_score > 0.7
    assert result.complexity_score > 0.7


# ============================================================================
# Code Executor Tests
# ============================================================================

def test_executor_python_success():
    """Test successful Python execution."""
    executor = CodeExecutor()

    generated_code = GeneratedCode(
        code_id="code_7",
        request_id="req_7",
        language=CodeLanguage.PYTHON,
        code="""
def main():
    return 42

result = main()
print(f"Result: {result}")
""",
        line_count=5,
        imports=[],
        functions=["main"],
        model_used="test",
        generation_time_ms=100,
    )

    result = executor.execute(generated_code)

    assert result.success
    assert result.exit_code == 0
    assert "Result: 42" in result.stdout
    assert result.execution_time_ms >= 0


def test_executor_python_with_input():
    """Test Python execution with input data."""
    executor = CodeExecutor()

    generated_code = GeneratedCode(
        code_id="code_8",
        request_id="req_8",
        language=CodeLanguage.PYTHON,
        code="""
result = x + y
print(f"Sum: {result}")
""",
        line_count=2,
        imports=[],
        functions=[],
        model_used="test",
        generation_time_ms=100,
    )

    result = executor.execute(generated_code, input_data={"x": 10, "y": 20})

    assert result.success
    assert "Sum: 30" in result.stdout


def test_executor_python_error():
    """Test Python execution with error."""
    executor = CodeExecutor()

    generated_code = GeneratedCode(
        code_id="code_9",
        request_id="req_9",
        language=CodeLanguage.PYTHON,
        code="""
result = 1 / 0
""",
        line_count=1,
        imports=[],
        functions=[],
        model_used="test",
        generation_time_ms=100,
    )

    result = executor.execute(generated_code)

    assert not result.success
    assert result.error_type == "ZeroDivisionError"
    assert result.error_message


def test_executor_python_syntax_error():
    """Test Python execution with syntax error."""
    executor = CodeExecutor()

    generated_code = GeneratedCode(
        code_id="code_10",
        request_id="req_10",
        language=CodeLanguage.PYTHON,
        code="""
def broken(
    print("Missing closing")
""",
        line_count=2,
        imports=[],
        functions=[],
        model_used="test",
        generation_time_ms=100,
    )

    result = executor.execute(generated_code)

    assert not result.success
    assert result.error_type == "SyntaxError"


def test_executor_shell_success():
    """Test successful Shell execution."""
    executor = CodeExecutor()

    generated_code = GeneratedCode(
        code_id="code_11",
        request_id="req_11",
        language=CodeLanguage.SHELL,
        code="""
echo "Hello from shell"
exit 0
""",
        line_count=2,
        imports=[],
        functions=[],
        model_used="test",
        generation_time_ms=100,
    )

    result = executor.execute(generated_code)

    assert result.success
    assert result.exit_code == 0
    assert "Hello from shell" in result.stdout


def test_executor_shell_error():
    """Test Shell execution with error."""
    executor = CodeExecutor()

    generated_code = GeneratedCode(
        code_id="code_12",
        request_id="req_12",
        language=CodeLanguage.SHELL,
        code="""
cat /nonexistent/file.txt
""",
        line_count=1,
        imports=[],
        functions=[],
        model_used="test",
        generation_time_ms=100,
    )

    result = executor.execute(generated_code)

    assert not result.success
    assert result.exit_code != 0


def test_executor_with_retry():
    """Test execution with retry."""
    executor = CodeExecutor()

    generated_code = GeneratedCode(
        code_id="code_13",
        request_id="req_13",
        language=CodeLanguage.PYTHON,
        code="""
print("Execution attempt")
""",
        line_count=1,
        imports=[],
        functions=[],
        model_used="test",
        generation_time_ms=100,
    )

    result = executor.execute_with_retry(generated_code, max_retries=2)

    assert result.success


def test_executor_validate_output():
    """Test output validation."""
    executor = CodeExecutor()

    generated_code = GeneratedCode(
        code_id="code_14",
        request_id="req_14",
        language=CodeLanguage.PYTHON,
        code="""
def main():
    return 42
""",
        line_count=2,
        imports=[],
        functions=["main"],
        model_used="test",
        generation_time_ms=100,
    )

    result = executor.execute(generated_code)

    # Validate with expected output
    is_valid, error = executor.validate_output(result, expected_output=42)
    assert is_valid
    assert error is None

    # Validate with custom validator
    def validator(output):
        return output == 42

    is_valid, error = executor.validate_output(result, output_validator=validator)
    assert is_valid


# ============================================================================
# Integration Tests
# ============================================================================

def test_full_pipeline_safe_code():
    """Test full pipeline: generate -> review -> execute."""
    generator = CodeGenerator()
    reviewer = CodeReviewer()
    executor = CodeExecutor()

    # 1. Generate code
    request = CodeGenerationRequest(
        request_id="req_int_1",
        task_description="Create a function to add two numbers",
        language=CodeLanguage.PYTHON,
    )

    generated = generator.generate_code(request)
    assert generated.code

    # 2. Review code
    review = reviewer.review_code(generated)
    assert review.approved
    assert review.overall_danger_level in (DangerLevel.SAFE, DangerLevel.LOW)

    # 3. Execute code
    execution = executor.execute(generated)
    assert execution.success


def test_full_pipeline_dangerous_code():
    """Test full pipeline with dangerous code."""
    reviewer = CodeReviewer()
    executor = CodeExecutor()

    # Create dangerous code manually
    dangerous_code = GeneratedCode(
        code_id="code_dangerous",
        request_id="req_dangerous",
        language=CodeLanguage.PYTHON,
        code="""
import os
os.system("echo 'This is dangerous'")
""",
        line_count=2,
        imports=["os"],
        functions=[],
        model_used="test",
        generation_time_ms=100,
    )

    # Review should reject
    review = reviewer.review_code(dangerous_code)
    assert not review.approved
    assert review.overall_danger_level == DangerLevel.CRITICAL

    # Should not execute if not approved
    # (In real system, execution would be blocked)


def test_stats_collection():
    """Test statistics collection."""
    generator = CodeGenerator()
    reviewer = CodeReviewer()
    executor = CodeExecutor()

    # Generate some code
    request = CodeGenerationRequest(
        request_id="req_stats",
        task_description="Test stats",
        language=CodeLanguage.PYTHON,
    )

    generated = generator.generate_code(request)
    reviewer.review_code(generated)
    executor.execute(generated)

    # Check stats
    gen_stats = generator.get_stats()
    assert gen_stats["total_generations"] > 0

    exec_stats = executor.get_stats()
    assert exec_stats["total_executions"] > 0
