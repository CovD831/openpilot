"""Unit tests for context compressor."""

import pytest
from unittest.mock import Mock, MagicMock

from memory.context_compressor import ContextCompressor, CompressionResult
from memory.short_memory import Message
from core.llm import LLMClient, LLMResponse


class TestContextCompressor:
    """Tests for ContextCompressor."""

    @pytest.fixture
    def mock_llm_client(self):
        """Mock LLM client."""
        client = Mock(spec=LLMClient)
        response = LLMResponse(
            content="This is a summary of the conversation.",
            model="test-model",
            provider="openai",
            usage={"input_tokens": 100, "output_tokens": 50}
        )
        client.complete.return_value = response
        return client

    def test_initialization(self, mock_llm_client):
        """Test compressor initialization."""
        compressor = ContextCompressor(
            llm_client=mock_llm_client,
            compression_threshold=100000
        )

        assert compressor.compression_threshold == 100000
        assert compressor.min_preserved_messages == 10

    def test_estimate_tokens(self, mock_llm_client):
        """Test token estimation."""
        compressor = ContextCompressor(mock_llm_client)

        messages = [
            Message(role="user", content="Hello" * 100),
            Message(role="assistant", content="Hi" * 100)
        ]

        tokens = compressor.estimate_tokens(messages)
        assert tokens > 0

    def test_should_compress_below_threshold(self, mock_llm_client):
        """Test should_compress with messages below threshold."""
        compressor = ContextCompressor(mock_llm_client, compression_threshold=10000)

        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi")
        ]

        assert not compressor.should_compress(messages)

    def test_should_compress_above_threshold(self, mock_llm_client):
        """Test should_compress with messages above threshold."""
        compressor = ContextCompressor(mock_llm_client, compression_threshold=100)

        messages = [
            Message(role="user", content="Hello" * 1000),
            Message(role="assistant", content="Hi" * 1000)
        ]

        assert compressor.should_compress(messages)

    def test_compress_too_few_messages(self, mock_llm_client):
        """Test compression with too few messages."""
        compressor = ContextCompressor(mock_llm_client, min_preserved_messages=10)

        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi")
        ]

        result = compressor.compress(messages)

        assert len(result.compressed_messages) == 2
        assert result.compression_ratio == 1.0
        assert "No compression needed" in result.compression_summary

    def test_compress_with_llm(self, mock_llm_client):
        """Test compression using LLM."""
        compressor = ContextCompressor(mock_llm_client, min_preserved_messages=2)

        messages = []
        for i in range(20):
            messages.append(Message(role="user", content=f"Message {i}"))

        result = compressor.compress(messages)

        # Should have compression boundary + preserved messages
        assert len(result.compressed_messages) > 0
        assert result.compressed_messages[0].role == "system"
        assert "[COMPRESSION BOUNDARY]" in result.compressed_messages[0].content
        assert result.compression_ratio < 1.0

        # LLM should have been called
        mock_llm_client.complete.assert_called_once()

    def test_compress_with_fallback(self, mock_llm_client):
        """Test compression with LLM failure (fallback)."""
        # Make LLM fail
        mock_llm_client.complete.side_effect = Exception("LLM error")

        compressor = ContextCompressor(mock_llm_client, min_preserved_messages=2)

        messages = []
        for i in range(20):
            messages.append(Message(role="user", content=f"Message {i}"))

        result = compressor.compress(messages)

        # Should still compress using fallback
        assert len(result.compressed_messages) > 0
        assert result.compressed_messages[0].role == "system"
        assert "Compressed" in result.compression_summary

    def test_compress_with_preservation(self, mock_llm_client):
        """Test compression with pattern preservation."""
        compressor = ContextCompressor(mock_llm_client, min_preserved_messages=2)

        messages = [
            Message(role="user", content="Normal message 1"),
            Message(role="user", content="Important: This is critical"),
            Message(role="user", content="Normal message 2"),
            Message(role="user", content="Error: Something went wrong"),
            Message(role="user", content="Normal message 3"),
        ]

        result = compressor.compress_with_preservation(
            messages,
            preserve_patterns=["important", "error"]
        )

        # Should preserve messages with patterns
        preserved_content = [msg.content for msg in result.compressed_messages]
        assert any("critical" in content.lower() for content in preserved_content)
        assert any("error" in content.lower() for content in preserved_content)

    def test_get_compression_stats(self, mock_llm_client):
        """Test getting compression statistics."""
        compressor = ContextCompressor(mock_llm_client, compression_threshold=1000)

        messages = []
        for i in range(20):
            messages.append(Message(role="user", content=f"Message {i}" * 100))

        stats = compressor.get_compression_stats(messages)

        assert "total_messages" in stats
        assert "estimated_tokens" in stats
        assert "would_compress" in stats
        assert stats["total_messages"] == 20
        assert stats["would_compress"] is True

    def test_compression_result_fields(self, mock_llm_client):
        """Test CompressionResult has all expected fields."""
        compressor = ContextCompressor(mock_llm_client, min_preserved_messages=2)

        messages = []
        for i in range(20):
            messages.append(Message(role="user", content=f"Message {i}"))

        result = compressor.compress(messages)

        assert hasattr(result, 'compressed_messages')
        assert hasattr(result, 'compression_summary')
        assert hasattr(result, 'original_token_count')
        assert hasattr(result, 'compressed_token_count')
        assert hasattr(result, 'compression_ratio')
        assert hasattr(result, 'preserved_message_count')

        assert result.original_token_count > 0
        assert result.compressed_token_count > 0
        assert 0 < result.compression_ratio <= 1.0
