"""Code Generator Tool - Generate code using LLM based on task description."""

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


CODE_GENERATOR_DEFINITION = ToolDefinition(
    name="code_generator",
    display_name="Code Generator",
    description="Generate code using LLM based on task description",
    version="1.0.0",
    capabilities=[ToolCapability.CODE_EXECUTION, ToolCapability.LLM_CALL],
    permission_level=PermissionLevel.MEDIUM,
    input_schema=[
        ToolInputSchema(
            name="task_description",
            type="string",
            description="Description of the code to generate",
            required=True
        ),
        ToolInputSchema(
            name="language",
            type="string",
            description="Programming language (python, shell, bash)",
            required=True
        ),
        ToolInputSchema(
            name="context",
            type="string",
            description="Additional context or requirements",
            required=False,
            default=""
        ),
        ToolInputSchema(
            name="prompt_context",
            type="object",
            description="Structured upper-layer Prompt Context from the autonomous agent",
            required=False,
            default={}
        ),
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="Generated code and metadata",
        properties={
            "code": {"type": "string", "description": "Generated code"},
            "language": {"type": "string", "description": "Programming language"},
            "explanation": {"type": "string", "description": "Code explanation"},
            "imports": {"type": "array", "description": "List of imported modules"},
            "functions": {"type": "array", "description": "List of function names"}
        }
    ),
    timeout_seconds=300,
    max_retries=2,
    failure_modes=[
        ToolFailureMode(
            error_type="llm_timeout",
            description="LLM request timed out",
            recovery_strategy="Retry with simpler task description"
        ),
        ToolFailureMode(
            error_type="llm_error",
            description="LLM returned error",
            recovery_strategy="Check LLM configuration and API key"
        ),
        ToolFailureMode(
            error_type="invalid_language",
            description="Unsupported programming language",
            recovery_strategy="Use python, shell, or bash"
        )
    ],
    tags=["code", "generation", "llm", "programming"],
    audit_required=True
)


def code_generator_executor(params: dict[str, Any]) -> dict[str, Any]:
    """
    Execute code generator tool.

    Args:
        params: Tool parameters (task_description, language, context)

    Returns:
        Dictionary with code, language, explanation, imports, functions
    """
    from execution.code_generator import CodeGenerator
    from execution.code_models import CodeGenerationRequest, CodeLanguage
    from core.llm import LLMClient
    import uuid

    task_description = params["task_description"]
    language_str = params["language"].lower()
    context = params.get("context", "")
    prompt_context = params.get("prompt_context") or {}

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
        llm_client = params.get("_llm_client")
        if llm_client is None:
            from core.config import LLMSettings
            settings = LLMSettings()
            llm_client = LLMClient(settings)

        generator = CodeGenerator(llm_client)

        # Create request
        request = CodeGenerationRequest(
            request_id=f"req_{uuid.uuid4().hex[:8]}",
            task_description=task_description,
            language=language,
            context=context,
            prompt_context=prompt_context if isinstance(prompt_context, dict) else {},
            max_lines=260 if (prompt_context.get("product_judgment") or {}).get("preferred_stack") == "pygame" else 100,
        )

        # Generate code
        result = generator.generate_code(request)

        return {
            "code": result.code,
            "language": result.language.value,
            "explanation": f"Generated {result.line_count} lines of {result.language.value} code",
            "imports": result.imports,
            "functions": result.functions
        }
    except Exception as e:
        raise Exception(f"Code generation failed: {e}") from e
