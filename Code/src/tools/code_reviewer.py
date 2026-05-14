"""Code Reviewer Tool - Review code quality and suggest improvements using LLM."""

from __future__ import annotations

from typing import Any

from tools.tool_models import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolFailureMode,
    ToolInputSchema,
    ToolOutputSchema,
)


CODE_REVIEWER_DEFINITION = ToolDefinition(
    name="code_reviewer",
    display_name="Code Reviewer",
    description="Review code quality and suggest improvements using LLM",
    version="1.0.0",
    capabilities=[ToolCapability.CODE_EXECUTION, ToolCapability.LLM_CALL],
    permission_level=PermissionLevel.LOW,
    input_schema=[
        ToolInputSchema(
            name="code",
            type="string",
            description="Code to review",
            required=True
        ),
        ToolInputSchema(
            name="language",
            type="string",
            description="Programming language (python, shell, bash)",
            required=True
        )
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="Code review results",
        properties={
            "review": {"type": "string", "description": "Overall review summary"},
            "issues": {"type": "array", "description": "List of issues found"},
            "suggestions": {"type": "array", "description": "Improvement suggestions"},
            "approved": {"type": "boolean", "description": "Whether code is approved"}
        }
    ),
    timeout_seconds=60,
    max_retries=2,
    failure_modes=[
        ToolFailureMode(
            error_type="llm_timeout",
            description="LLM request timed out",
            recovery_strategy="Retry with shorter code snippet"
        ),
        ToolFailureMode(
            error_type="llm_error",
            description="LLM returned error",
            recovery_strategy="Check LLM configuration and API key"
        )
    ],
    tags=["code", "review", "quality", "llm"],
    audit_required=True
)


def code_reviewer_executor(params: dict[str, Any]) -> dict[str, Any]:
    """
    Execute code reviewer tool.

    Args:
        params: Tool parameters (code, language)

    Returns:
        Dictionary with review, issues, suggestions, approved
    """
    from execution.code_reviewer import CodeReviewer
    from execution.code_models import CodeLanguage, GeneratedCode
    import uuid

    code = params["code"]
    language_str = params["language"].lower()

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
        reviewer = CodeReviewer()

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

        # Review code
        result = reviewer.review_code(generated_code)

        return {
            "review": (
                "Approved"
                if result.approved
                else "Review found issues"
            ),
            "issues": [issue.dict() if hasattr(issue, 'dict') else str(issue) for issue in result.dangerous_operations],
            "suggestions": result.recommendations,
            "approved": result.approved,
            "syntax_errors": result.syntax_errors,
            "warnings": result.warnings,
            "quality_score": result.quality_score,
            "complexity_score": result.complexity_score,
        }
    except Exception as e:
        raise Exception(f"Code review failed: {e}") from e
