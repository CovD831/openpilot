"""LLM Summarizer Tool - Generate summary or analysis using LLM."""

from __future__ import annotations

from typing import Any

from core.llm import LLMClient, LLMMessage, LLMRequest
from core.tool_contracts import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolFailureMode,
    ToolInputSchema,
    ToolOutputSchema,
)


LLM_SUMMARIZER_DEFINITION = ToolDefinition(
    name="llm_summarizer",
    display_name="LLM Summarizer",
    description="Generate summary or analysis using LLM",
    version="1.0.0",
    capabilities=[ToolCapability.LLM_CALL],
    permission_level=PermissionLevel.LOW,
    input_schema=[
        ToolInputSchema(
            name="text",
            type="string",
            description="Text to summarize or analyze",
            required=True
        ),
        ToolInputSchema(
            name="instruction",
            type="string",
            description="Instruction for the LLM (e.g., 'Summarize in 3 sentences')",
            required=False,
            default="Summarize the following text concisely."
        ),
        ToolInputSchema(
            name="max_tokens",
            type="integer",
            description="Maximum tokens in response",
            required=False,
            default=500
        )
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="LLM response and metadata",
        properties={
            "summary": {"type": "string", "description": "Generated summary"},
            "tokens_used": {"type": "integer", "description": "Number of tokens used"},
            "model": {"type": "string", "description": "Model used"}
        }
    ),
    timeout_seconds=60,
    max_retries=3,
    failure_modes=[
        ToolFailureMode(
            error_type="llm_timeout",
            description="LLM request timed out",
            recovery_strategy="Retry with shorter text or higher timeout"
        ),
        ToolFailureMode(
            error_type="llm_error",
            description="LLM returned error",
            recovery_strategy="Check LLM configuration and API key"
        ),
        ToolFailureMode(
            error_type="text_too_long",
            description="Input text exceeds model context limit",
            recovery_strategy="Split text into chunks or use longer context model"
        )
    ],
    tags=["llm", "summarize", "analysis", "text"],
    audit_required=True
)


def llm_summarizer_executor(params: dict[str, Any]) -> dict[str, Any]:
    """
    Execute LLM summarizer tool.

    Args:
        params: Tool parameters (text, instruction, max_tokens)

    Returns:
        Dictionary with summary, tokens_used, model

    Raises:
        ValueError: If text too long or invalid parameters
        Exception: If LLM call fails
    """
    text = params["text"]
    instruction = params.get("instruction", "Summarize the following text concisely.")
    max_tokens = params.get("max_tokens", 500)

    # Build prompt
    prompt = f"{instruction}\n\n{text}"

    # Call LLM
    try:
        from core.config import LLMSettings
        settings = LLMSettings()
        client = LLMClient(settings)

        response = client.complete(
            LLMRequest(
                messages=[LLMMessage(role="user", content=prompt)],
                response_format="text",
                max_tokens=max_tokens,
                temperature=0.3,
            )
        )

        return {
            "summary": response.content,
            "tokens_used": response.usage.get("total_tokens", 0) if response.usage else 0,
            "model": settings.model
        }
    except Exception as e:
        raise Exception(f"LLM summarizer failed: {e}") from e
