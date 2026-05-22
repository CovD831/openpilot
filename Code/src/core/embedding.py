"""Embedding service for semantic search and similarity matching.

This module provides embedding capabilities for:
- Memory vault semantic search
- Text similarity computation
- Batch processing with caching
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Literal

import numpy as np
from openai import OpenAI

from core.config import EmbeddingSettings
from core.exceptions import OpenPilotError


class EmbeddingError(OpenPilotError):
    """Embedding-related errors."""
    pass


class EmbeddingService:
    """Service for generating and managing text embeddings."""

    def __init__(
        self,
        provider: Literal["openai", "openai-compatible", "local"] | str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        settings: EmbeddingSettings | None = None,
        cache_dir: str | Path = "data/embeddings_cache",
        batch_size: int = 100,
        timeout: int | float | None = None,
    ):
        """Initialize embedding service.

        Args:
            provider: Embedding provider ("openai" or "local")
            model: Model name for embeddings
            cache_dir: Directory for caching embeddings
            batch_size: Maximum batch size for batch processing
            timeout: Request timeout in seconds
        """
        settings = settings or EmbeddingSettings()
        self.provider = provider or settings.provider
        self.model = model or settings.model
        self.base_url = base_url or settings.base_url
        self.api_key = api_key or settings.api_key
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.batch_size = batch_size
        self.timeout = timeout if timeout is not None else settings.timeout_seconds

        # Initialize client based on provider
        if self.provider in {"openai", "openai-compatible"}:
            self._require_ready()
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)
            self.dimension = self._get_openai_dimension(self.model)
        elif self.provider == "local":
            # Placeholder for local embedding models
            # Could use sentence-transformers or similar
            raise NotImplementedError("Local embedding provider not yet implemented")
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

        # Cache for embeddings
        self._cache: dict[str, list[float]] = {}
        self._load_cache()

    def _require_ready(self) -> None:
        missing = []
        if not self.base_url or not str(self.base_url).strip():
            missing.append("embedding base_url")
        if not self.api_key or not str(self.api_key).strip():
            missing.append("embedding api_key")
        if missing:
            raise EmbeddingError(f"Missing embedding configuration: {', '.join(missing)}")

    def _get_openai_dimension(self, model: str) -> int:
        """Get embedding dimension for OpenAI model.

        Args:
            model: Model name

        Returns:
            Embedding dimension
        """
        dimensions = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }
        return dimensions.get(model, 1536)

    def _get_cache_key(self, text: str) -> str:
        """Generate cache key for text.

        Args:
            text: Input text

        Returns:
            Cache key (hash of text and model)
        """
        content = f"{self.provider}:{self.base_url}:{self.model}:{text}"
        return hashlib.sha256(content.encode()).hexdigest()

    def _load_cache(self) -> None:
        """Load embeddings cache from disk."""
        cache_file = self.cache_dir / "embeddings.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    self._cache = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._cache = {}

    def _save_cache(self) -> None:
        """Save embeddings cache to disk."""
        cache_file = self.cache_dir / "embeddings.json"
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(self._cache, f)
        except IOError as e:
            # Non-critical error, just log it
            print(f"Warning: Failed to save embedding cache: {e}")

    def embed_text(self, text: str, use_cache: bool = True) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: Input text
            use_cache: Whether to use cached embeddings

        Returns:
            Embedding vector

        Raises:
            EmbeddingError: If embedding generation fails
        """
        if not text or not text.strip():
            raise EmbeddingError("Cannot embed empty text")

        # Check cache
        cache_key = self._get_cache_key(text)
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]

        # Generate embedding
        try:
            if self.provider == "openai":
                response = self.client.embeddings.create(
                    model=self.model,
                    input=text
                )
                embedding = response.data[0].embedding
            else:
                raise NotImplementedError(f"Provider {self.provider} not implemented")

            # Cache the result
            if use_cache:
                self._cache[cache_key] = embedding
                self._save_cache()

            return embedding

        except Exception as e:
            raise EmbeddingError(f"Failed to generate embedding: {e}") from e

    def embed_batch(
        self,
        texts: list[str],
        use_cache: bool = True,
        show_progress: bool = False
    ) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of input texts
            use_cache: Whether to use cached embeddings
            show_progress: Whether to show progress

        Returns:
            List of embedding vectors

        Raises:
            EmbeddingError: If embedding generation fails
        """
        if not texts:
            return []

        embeddings: list[list[float] | None] = [None] * len(texts)
        texts_to_embed: list[tuple[int, str]] = []

        # Check cache for each text
        for i, text in enumerate(texts):
            if not text or not text.strip():
                raise EmbeddingError(f"Cannot embed empty text at index {i}")

            cache_key = self._get_cache_key(text)
            if use_cache and cache_key in self._cache:
                embeddings[i] = self._cache[cache_key]
            else:
                texts_to_embed.append((i, text))

        # Generate embeddings for uncached texts in batches
        if texts_to_embed:
            total_batches = (len(texts_to_embed) + self.batch_size - 1) // self.batch_size

            for batch_idx in range(total_batches):
                start_idx = batch_idx * self.batch_size
                end_idx = min(start_idx + self.batch_size, len(texts_to_embed))
                batch = texts_to_embed[start_idx:end_idx]

                if show_progress:
                    print(f"Processing batch {batch_idx + 1}/{total_batches}...")

                # Extract texts for this batch
                batch_texts = [text for _, text in batch]

                try:
                    if self.provider == "openai":
                        response = self.client.embeddings.create(
                            model=self.model,
                            input=batch_texts
                        )
                        batch_embeddings = [item.embedding for item in response.data]
                    else:
                        raise NotImplementedError(f"Provider {self.provider} not implemented")

                    # Store results
                    for (original_idx, text), embedding in zip(batch, batch_embeddings):
                        embeddings[original_idx] = embedding

                        # Cache the result
                        if use_cache:
                            cache_key = self._get_cache_key(text)
                            self._cache[cache_key] = embedding

                except Exception as e:
                    raise EmbeddingError(f"Failed to generate batch embeddings: {e}") from e

                # Small delay between batches to avoid rate limits
                if batch_idx < total_batches - 1:
                    time.sleep(0.1)

            # Save cache after batch processing
            if use_cache:
                self._save_cache()

        # Ensure all embeddings were generated
        if any(emb is None for emb in embeddings):
            raise EmbeddingError("Some embeddings failed to generate")

        return embeddings  # type: ignore

    def compute_similarity(
        self,
        emb1: list[float],
        emb2: list[float],
        method: Literal["cosine", "dot"] = "cosine"
    ) -> float:
        """Compute similarity between two embeddings.

        Args:
            emb1: First embedding vector
            emb2: Second embedding vector
            method: Similarity method ("cosine" or "dot")

        Returns:
            Similarity score

        Raises:
            ValueError: If embeddings have different dimensions
        """
        if len(emb1) != len(emb2):
            raise ValueError(f"Embedding dimensions don't match: {len(emb1)} vs {len(emb2)}")

        vec1 = np.array(emb1)
        vec2 = np.array(emb2)

        if method == "cosine":
            # Cosine similarity
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return float(np.dot(vec1, vec2) / (norm1 * norm2))
        elif method == "dot":
            # Dot product
            return float(np.dot(vec1, vec2))
        else:
            raise ValueError(f"Unknown similarity method: {method}")

    def find_similar(
        self,
        query_emb: list[float],
        candidates: list[list[float]],
        top_k: int = 10,
        method: Literal["cosine", "dot"] = "cosine",
        threshold: float | None = None
    ) -> list[tuple[int, float]]:
        """Find most similar embeddings to a query.

        Args:
            query_emb: Query embedding vector
            candidates: List of candidate embedding vectors
            top_k: Number of top results to return
            method: Similarity method ("cosine" or "dot")
            threshold: Optional minimum similarity threshold

        Returns:
            List of (index, similarity_score) tuples, sorted by similarity (descending)
        """
        if not candidates:
            return []

        # Compute similarities
        similarities = []
        for i, candidate_emb in enumerate(candidates):
            try:
                similarity = self.compute_similarity(query_emb, candidate_emb, method)
                if threshold is None or similarity >= threshold:
                    similarities.append((i, similarity))
            except ValueError:
                # Skip candidates with mismatched dimensions
                continue

        # Sort by similarity (descending) and return top-k
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_k]

    def get_dimension(self) -> int:
        """Get embedding dimension.

        Returns:
            Embedding dimension
        """
        return self.dimension

    def clear_cache(self) -> None:
        """Clear the embedding cache."""
        self._cache.clear()
        cache_file = self.cache_dir / "embeddings.json"
        if cache_file.exists():
            cache_file.unlink()

    def get_cache_size(self) -> int:
        """Get number of cached embeddings.

        Returns:
            Number of cached embeddings
        """
        return len(self._cache)

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        cache_file = self.cache_dir / "embeddings.json"
        cache_size_bytes = cache_file.stat().st_size if cache_file.exists() else 0

        return {
            "cached_embeddings": len(self._cache),
            "cache_size_bytes": cache_size_bytes,
            "cache_size_mb": cache_size_bytes / (1024 * 1024),
            "provider": self.provider,
            "model": self.model,
            "dimension": self.dimension
        }

    def __repr__(self) -> str:
        """String representation."""
        return f"EmbeddingService(provider={self.provider}, model={self.model}, cached={len(self._cache)})"
