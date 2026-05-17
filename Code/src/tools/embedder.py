"""Embedder Tool - Generate semantic embeddings for text queries."""

from __future__ import annotations

from typing import Any

from core.tool_contracts import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolFailureMode,
    ToolInputSchema,
    ToolOutputSchema,
)


EMBEDDER_DEFINITION = ToolDefinition(
    name="embedder",
    display_name="Embedder",
    description="Embed text into a semantic vector",
    version="1.0.0",
    capabilities=[ToolCapability.LLM_CALL],
    permission_level=PermissionLevel.MEDIUM,
    input_schema=[
        ToolInputSchema(
            name="query",
            type="string",
            description="Text to embed",
            required=True,
        ),
        ToolInputSchema(
            name="provider",
            type="string",
            description="Embedding provider",
            required=False,
            default="openai",
        ),
        ToolInputSchema(
            name="model",
            type="string",
            description="Embedding model name",
            required=False,
            default="text-embedding-3-small",
        ),
        ToolInputSchema(
            name="use_cache",
            type="boolean",
            description="Use cached embeddings when available",
            required=False,
            default=True,
        ),
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="Embedding vector and metadata",
        properties={
            "embedding": {"type": "array", "description": "Embedding vector"},
            "dimension": {"type": "integer", "description": "Embedding vector dimension"},
            "model": {"type": "string", "description": "Embedding model used"},
            "provider": {"type": "string", "description": "Embedding provider used"},
            "cached": {"type": "boolean", "description": "Whether the embedding was found in cache"},
        },
    ),
    timeout_seconds=60,
    max_retries=1,
    failure_modes=[
        ToolFailureMode(
            error_type="empty_query",
            description="Query text is empty",
            recovery_strategy="Provide non-empty text to embed",
        ),
        ToolFailureMode(
            error_type="embedding_error",
            description="Embedding generation failed",
            recovery_strategy="Check embedding provider configuration, API key, and model name",
        ),
    ],
    tags=["embedding", "semantic", "vector", "memory"],
    audit_required=True,
)


def embedder_executor(params: dict[str, Any]) -> dict[str, Any]:
    """Execute the standard embedder tool."""
    query = str(params.get("query") or "").strip()
    if not query:
        raise ValueError("Empty query: provide non-empty text to embed")

    provider = str(params.get("provider") or "openai")
    model = str(params.get("model") or "text-embedding-3-small")
    use_cache = bool(params.get("use_cache", True))
    service = params.get("_embedding_service")
    if service is None:
        from core.embedding import EmbeddingService

        service = EmbeddingService(provider=provider, model=model)

    cached = _is_cached(service, query, use_cache)
    embedding = service.embed_text(query, use_cache=use_cache)

    return {
        "embedding": embedding,
        "dimension": len(embedding),
        "model": getattr(service, "model", model),
        "provider": getattr(service, "provider", provider),
        "cached": cached,
    }


def _is_cached(service: Any, query: str, use_cache: bool) -> bool:
    """Best-effort cache check for EmbeddingService-like objects."""
    if not use_cache:
        return False

    get_cache_key = getattr(service, "_get_cache_key", None)
    cache = getattr(service, "_cache", None)
    if not callable(get_cache_key) or not isinstance(cache, dict):
        return False

    return get_cache_key(query) in cache
