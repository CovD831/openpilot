"""Unit tests for embedding service."""

import pytest
from pathlib import Path
import tempfile
import json
from unittest.mock import Mock, patch, MagicMock

from core.embedding import EmbeddingService, EmbeddingError


class TestEmbeddingService:
    """Tests for EmbeddingService class."""

    @pytest.fixture
    def mock_openai_client(self):
        """Mock OpenAI client."""
        with patch('core.embedding.OpenAI') as mock_client:
            # Mock embeddings response
            mock_response = Mock()
            mock_response.data = [Mock(embedding=[0.1] * 1536)]
            mock_client.return_value.embeddings.create.return_value = mock_response
            yield mock_client

    @pytest.fixture
    def temp_cache_dir(self):
        """Create temporary cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_create_service(self, mock_openai_client, temp_cache_dir):
        """Test service creation."""
        service = EmbeddingService(
            provider="openai",
            model="text-embedding-3-small",
            cache_dir=temp_cache_dir
        )
        assert service.provider == "openai"
        assert service.model == "text-embedding-3-small"
        assert service.dimension == 1536

    def test_embed_text(self, mock_openai_client, temp_cache_dir):
        """Test embedding single text."""
        service = EmbeddingService(cache_dir=temp_cache_dir)

        embedding = service.embed_text("Hello world")
        assert len(embedding) == 1536
        assert all(isinstance(x, float) for x in embedding)

    def test_embed_text_empty(self, mock_openai_client, temp_cache_dir):
        """Test embedding empty text."""
        service = EmbeddingService(cache_dir=temp_cache_dir)

        with pytest.raises(EmbeddingError, match="Cannot embed empty text"):
            service.embed_text("")

    def test_embed_text_caching(self, mock_openai_client, temp_cache_dir):
        """Test embedding caching."""
        service = EmbeddingService(cache_dir=temp_cache_dir)

        # First call - should hit API
        embedding1 = service.embed_text("Hello world")
        call_count_1 = mock_openai_client.return_value.embeddings.create.call_count

        # Second call - should use cache
        embedding2 = service.embed_text("Hello world")
        call_count_2 = mock_openai_client.return_value.embeddings.create.call_count

        assert embedding1 == embedding2
        assert call_count_2 == call_count_1  # No additional API call

    def test_embed_batch(self, mock_openai_client, temp_cache_dir):
        """Test batch embedding."""
        # Mock batch response
        mock_response = Mock()
        mock_response.data = [
            Mock(embedding=[0.1] * 1536),
            Mock(embedding=[0.2] * 1536),
            Mock(embedding=[0.3] * 1536)
        ]
        mock_openai_client.return_value.embeddings.create.return_value = mock_response

        service = EmbeddingService(cache_dir=temp_cache_dir)
        texts = ["text1", "text2", "text3"]

        embeddings = service.embed_batch(texts)
        assert len(embeddings) == 3
        assert all(len(emb) == 1536 for emb in embeddings)

    def test_embed_batch_with_cache(self, mock_openai_client, temp_cache_dir):
        """Test batch embedding with partial cache hits."""
        service = EmbeddingService(cache_dir=temp_cache_dir)

        # Cache first text
        service.embed_text("text1")

        # Mock batch response for remaining texts
        mock_response = Mock()
        mock_response.data = [
            Mock(embedding=[0.2] * 1536),
            Mock(embedding=[0.3] * 1536)
        ]
        mock_openai_client.return_value.embeddings.create.return_value = mock_response

        texts = ["text1", "text2", "text3"]
        embeddings = service.embed_batch(texts)

        assert len(embeddings) == 3

    def test_compute_similarity_cosine(self, mock_openai_client, temp_cache_dir):
        """Test cosine similarity computation."""
        service = EmbeddingService(cache_dir=temp_cache_dir)

        emb1 = [1.0, 0.0, 0.0]
        emb2 = [1.0, 0.0, 0.0]
        emb3 = [0.0, 1.0, 0.0]

        # Identical vectors
        similarity = service.compute_similarity(emb1, emb2, method="cosine")
        assert abs(similarity - 1.0) < 1e-6

        # Orthogonal vectors
        similarity = service.compute_similarity(emb1, emb3, method="cosine")
        assert abs(similarity - 0.0) < 1e-6

    def test_compute_similarity_dot(self, mock_openai_client, temp_cache_dir):
        """Test dot product similarity."""
        service = EmbeddingService(cache_dir=temp_cache_dir)

        emb1 = [1.0, 2.0, 3.0]
        emb2 = [2.0, 3.0, 4.0]

        similarity = service.compute_similarity(emb1, emb2, method="dot")
        expected = 1.0 * 2.0 + 2.0 * 3.0 + 3.0 * 4.0  # 20.0
        assert abs(similarity - expected) < 1e-6

    def test_compute_similarity_dimension_mismatch(self, mock_openai_client, temp_cache_dir):
        """Test similarity with mismatched dimensions."""
        service = EmbeddingService(cache_dir=temp_cache_dir)

        emb1 = [1.0, 2.0, 3.0]
        emb2 = [1.0, 2.0]

        with pytest.raises(ValueError, match="dimensions don't match"):
            service.compute_similarity(emb1, emb2)

    def test_find_similar(self, mock_openai_client, temp_cache_dir):
        """Test finding similar embeddings."""
        service = EmbeddingService(cache_dir=temp_cache_dir)

        query_emb = [1.0, 0.0, 0.0]
        candidates = [
            [1.0, 0.0, 0.0],  # Identical
            [0.9, 0.1, 0.0],  # Very similar
            [0.0, 1.0, 0.0],  # Orthogonal
            [0.5, 0.5, 0.0],  # Somewhat similar
        ]

        results = service.find_similar(query_emb, candidates, top_k=2)

        assert len(results) == 2
        assert results[0][0] == 0  # Index of most similar
        assert results[0][1] > results[1][1]  # Scores are descending

    def test_find_similar_with_threshold(self, mock_openai_client, temp_cache_dir):
        """Test finding similar embeddings with threshold."""
        service = EmbeddingService(cache_dir=temp_cache_dir)

        query_emb = [1.0, 0.0, 0.0]
        candidates = [
            [1.0, 0.0, 0.0],  # similarity = 1.0
            [0.9, 0.1, 0.0],  # similarity > 0.9
            [0.0, 1.0, 0.0],  # similarity = 0.0
        ]

        results = service.find_similar(query_emb, candidates, top_k=10, threshold=0.9)

        # Only first two should pass threshold
        assert len(results) <= 2

    def test_cache_persistence(self, mock_openai_client, temp_cache_dir):
        """Test cache persistence across service instances."""
        # First service instance
        service1 = EmbeddingService(cache_dir=temp_cache_dir)
        service1.embed_text("test text")

        # Second service instance
        service2 = EmbeddingService(cache_dir=temp_cache_dir)

        # Should load from cache
        assert service2.get_cache_size() > 0

    def test_clear_cache(self, mock_openai_client, temp_cache_dir):
        """Test cache clearing."""
        service = EmbeddingService(cache_dir=temp_cache_dir)
        service.embed_text("test text")

        assert service.get_cache_size() > 0

        service.clear_cache()
        assert service.get_cache_size() == 0

    def test_get_cache_stats(self, mock_openai_client, temp_cache_dir):
        """Test cache statistics."""
        service = EmbeddingService(cache_dir=temp_cache_dir)
        service.embed_text("test text")

        stats = service.get_cache_stats()
        assert "cached_embeddings" in stats
        assert "cache_size_bytes" in stats
        assert "provider" in stats
        assert "model" in stats
        assert stats["cached_embeddings"] > 0

    def test_get_dimension(self, mock_openai_client, temp_cache_dir):
        """Test getting embedding dimension."""
        service = EmbeddingService(
            cache_dir=temp_cache_dir,
            model="text-embedding-3-small"
        )
        assert service.get_dimension() == 1536

        service = EmbeddingService(
            cache_dir=temp_cache_dir,
            model="text-embedding-3-large"
        )
        assert service.get_dimension() == 3072

    def test_invalid_provider(self, temp_cache_dir):
        """Test invalid provider."""
        with pytest.raises(ValueError, match="Unknown provider"):
            EmbeddingService(provider="invalid", cache_dir=temp_cache_dir)

    def test_local_provider_not_implemented(self, temp_cache_dir):
        """Test local provider not implemented."""
        with pytest.raises(NotImplementedError):
            EmbeddingService(provider="local", cache_dir=temp_cache_dir)

    def test_repr(self, mock_openai_client, temp_cache_dir):
        """Test string representation."""
        service = EmbeddingService(cache_dir=temp_cache_dir)
        repr_str = repr(service)
        assert "EmbeddingService" in repr_str
        assert "openai" in repr_str
