"""Code Executor Tool - Execute code in a sandboxed environment."""

from __future__ import annotations

from typing import Any

from models.tool_models import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolFailureMode,
    ToolInputSchema,
    ToolOutputSchema,
)


CODE_EXECUTOR_DEFINITION = ToolDefinition(
    name="code_executor",
    display_name="Code Executor",
    description="Execute code in a sandboxed environment",
    version="1.0.0",
    capabilities=[ToolCapability.CODE_EXECUTION],
    permission_level=PermissionLevel.HIGH,
    input_schema=[
        ToolInputSchema(
            name="code",
            type="string",
            description="Code to execute",
            required=True
        ),
        ToolInputSchema(
            name="language",
            type="string",
            description="Programming language (python, shell, bash)",
            required=True
        ),
        ToolInputSchema(
            name="timeout",
            type="integer",
            description="Execution timeout in seconds (default: 30)",
            required=False,
            default=30
        )
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="Code execution results",
        properties={
            "success": {"type": "boolean", "description": "Whether execution succeeded"},
            "output": {"type": "string", "description": "Execution output (stdout)"},
            "error": {"type": "string", "description": "Error message (if failed)"},
            "exit_code": {"type": "integer", "description": "Process exit code"}
        }
    ),
    timeout_seconds=60,
    max_retries=1,
    failure_modes=[
        ToolFailureMode(
            error_type="execution_timeout",
            description="Code execution timed out",
            recovery_strategy="Increase timeout or optimize code"
        ),
        ToolFailureMode(
            error_type="execution_error",
            description="Code execution failed",
            recovery_strategy="Review code for errors and fix"
        ),
        ToolFailureMode(
            error_type="permission_denied",
            description="Insufficient permissions to execute code",
            recovery_strategy="Check execution permissions"
        )
    ],
    tags=["code", "execution", "sandbox", "runtime"],
    audit_required=True
)


def code_executor_executor(params: dict[str, Any]) -> dict[str, Any]:
    """
    Execute code executor tool.

    Args:
        params: Tool parameters (code, language, timeout)

    Returns:
        Dictionary with success, output, error, exit_code
    """
    from execution.code_executor import CodeExecutor
    from models.code_models import CodeLanguage, GeneratedCode
    import uuid

    code = params["code"]
    language_str = params["language"].lower()
    timeout = params.get("timeout", 30)

    # Map language string to CodeLanguage enum
    language_map = {
        "python": CodeLanguage.PYTHON,
        "shell": CodeLanguage.SHELL,
        "bash": CodeLanguage.BASH,
    }

    if language_str not in language_map:
        raise ValueError(f"Unsupported language: {language_str}. Use python, shell, or bash.")

    language = language_map[language_str]

    try:
        executor = CodeExecutor()

        # Create GeneratedCode object
        generated_code = GeneratedCode(
            code_id=f"code_{uuid.uuid4().hex[:8]}",
            request_id=f"req_{uuid.uuid4().hex[:8]}",
            language=language,
            code=code,
            line_count=len([line for line in code.split("\n") if line.strip()]),
            imports=[],
            functions=[],
            model_used="unknown",
            generation_time_ms=0
        )

        # Execute code
        result = executor.execute(
            generated_code=generated_code,
            timeout=timeout
        )

        return {
            "success": result.success,
            "output": result.stdout if result.success else result.stderr,
            "error": result.error_message or "",
            "exit_code": result.exit_code
        }
    except Exception as e:
        raise Exception(f"Code execution failed: {e}") from e
