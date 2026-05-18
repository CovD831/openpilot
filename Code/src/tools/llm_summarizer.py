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

    try:
        injected_client = params.get("_llm_client")
        if injected_client is not None:
            client = injected_client
            model = getattr(injected_client, "model", "injected")
        else:
            from core.config import LLMSettings

            settings = LLMSettings()
            client = LLMClient(settings)
            model = settings.model

        prompt = f"{instruction}\n\n{text}"
        response = _complete_summary(client, prompt=prompt, max_tokens=max_tokens)
        attempts = [_summary_attempt(response, prompt_chars=len(prompt), max_tokens=max_tokens)]
        summary = response.content or ""

        if not summary.strip() and getattr(response, "finish_reason", None) == "length":
            retry_instruction = (
                f"{instruction}\n\n"
                "The previous response was empty because the output token budget was exhausted. "
                "Return the final answer directly as visible Markdown. Do not spend tokens on private reasoning, "
                "analysis preambles, or metadata."
            )
            retry_prompt = f"{retry_instruction}\n\n{text}"
            retry_max_tokens = _retry_max_tokens(max_tokens)
            response = _complete_summary(client, prompt=retry_prompt, max_tokens=retry_max_tokens)
            attempts.append(_summary_attempt(response, prompt_chars=len(retry_prompt), max_tokens=retry_max_tokens))
            summary = response.content or ""

        tokens_used = sum(int(attempt.get("tokens_used") or 0) for attempt in attempts)
        if not tokens_used:
            tokens_used = response.usage.get("total_tokens", 0) if response.usage else 0
        return {
            "summary": summary,
            "tokens_used": tokens_used,
            "model": getattr(response, "model", None) or model,
            "finish_reason": getattr(response, "finish_reason", None),
            "response_chars": len(summary),
            "prompt_chars": attempts[-1]["prompt_chars"] if attempts else len(prompt),
            "attempts": attempts,
        }
    except Exception as e:
        raise Exception(f"LLM summarizer failed: {e}") from e


def _complete_summary(client: Any, *, prompt: str, max_tokens: int) -> Any:
    return client.complete(
        LLMRequest(
            messages=[LLMMessage(role="user", content=prompt)],
            response_format="text",
            max_tokens=max_tokens,
            temperature=0.3,
            metadata={"tool": "llm_summarizer", "task": "summarize"},
        )
    )


def _summary_attempt(response: Any, *, prompt_chars: int, max_tokens: int) -> dict[str, Any]:
    summary = response.content or ""
    return {
        "model": getattr(response, "model", ""),
        "finish_reason": getattr(response, "finish_reason", None),
        "response_chars": len(summary),
        "prompt_chars": prompt_chars,
        "max_tokens": max_tokens,
        "tokens_used": response.usage.get("total_tokens", 0) if getattr(response, "usage", None) else 0,
    }


def _retry_max_tokens(max_tokens: int) -> int:
    try:
        base = int(max_tokens)
    except (TypeError, ValueError):
        base = 500
    return min(max(base * 2, base + 800, 1800), 4096)
