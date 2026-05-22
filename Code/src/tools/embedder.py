"""Embedder Tool - Generate semantic embeddings for text queries."""

from __future__ import annotations

from typing import Any

from metadata import ToolContractMetadata, ToolInputMetadata, ToolResultMetadata, metadata_tool_result
from core.config import EmbeddingSettings

from core.tool_contracts import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolFailureMode,
)


EMBEDDER_DEFINITION = ToolDefinition(
    name="embedder",
    display_name="Embedder",
    description="Embed text into a semantic vector",
    version="1.0.0",
    capabilities=[ToolCapability.LLM_CALL],
    permission_level=PermissionLevel.MEDIUM,
    contract_metadata=ToolContractMetadata(
        tool_name='embedder',
        input_metadata_type="ToolInputMetadata",
        output_metadata_type="ToolResultMetadata",
        required_input_fields=['query'],
        input_defaults={'provider': None, 'model': None, 'base_url': None, 'use_cache': True},
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


@metadata_tool_result('embedder')
def embedder_executor(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
    params = input_metadata.to_params()
    """Execute the standard embedder tool."""
    query = str(params.get("query") or "").strip()
    if not query:
        raise ValueError("Empty query: provide non-empty text to embed")

    settings = EmbeddingSettings()
    provider = str(params.get("provider") or settings.provider)
    model = str(params.get("model") or settings.model)
    base_url = str(params.get("base_url") or settings.base_url or "")
    use_cache = bool(params.get("use_cache", True))
    service = params.get("_embedding_service")
    if service is None:
        from core.embedding import EmbeddingService

        service = EmbeddingService(provider=provider, model=model, base_url=base_url or None, settings=settings)

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
