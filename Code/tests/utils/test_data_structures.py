"""Unit tests for data structures."""

import unittest

from src.utils.data_structures import (
    CircularBuffer,
    EndTruncatingAccumulator,
)


class TestCircularBuffer(unittest.TestCase):
    """Test circular buffer functionality."""

    def test_basic_operations(self):
        """Test basic add and retrieve operations."""
        buffer = CircularBuffer(maxsize=5)

        buffer.add(1)
        buffer.add(2)
        buffer.add(3)

        self.assertEqual(buffer.length(), 3)
        self.assertEqual(buffer.to_list(), [1, 2, 3])

    def test_eviction(self):
        """Test automatic eviction when full."""
        buffer = CircularBuffer(maxsize=3)

        buffer.add(1)
        buffer.add(2)
        buffer.add(3)
        buffer.add(4)  # Should evict 1

        self.assertEqual(buffer.length(), 3)
        self.assertEqual(buffer.to_list(), [2, 3, 4])

    def test_add_all(self):
        """Test adding multiple items."""
        buffer = CircularBuffer(maxsize=5)

        buffer.add_all([1, 2, 3, 4, 5, 6])

        self.assertEqual(buffer.length(), 5)
        self.assertEqual(buffer.to_list(), [2, 3, 4, 5, 6])

    def test_get_recent(self):
        """Test getting recent items."""
        buffer = CircularBuffer(maxsize=10)

        buffer.add_all([1, 2, 3, 4, 5])

        recent = buffer.get_recent(3)
        self.assertEqual(recent, [3, 4, 5])

    def test_get_recent_more_than_available(self):
        """Test getting more items than available."""
        buffer = CircularBuffer(maxsize=10)

        buffer.add_all([1, 2, 3])

        recent = buffer.get_recent(5)
        self.assertEqual(recent, [1, 2, 3])

    def test_clear(self):
        """Test clearing buffer."""
        buffer = CircularBuffer(maxsize=5)

        buffer.add_all([1, 2, 3])
        buffer.clear()

        self.assertEqual(buffer.length(), 0)
        self.assertEqual(buffer.to_list(), [])

    def test_is_full(self):
        """Test checking if buffer is full."""
        buffer = CircularBuffer(maxsize=3)

        self.assertFalse(buffer.is_full())

        buffer.add_all([1, 2])
        self.assertFalse(buffer.is_full())

        buffer.add(3)
        self.assertTrue(buffer.is_full())

    def test_iteration(self):
        """Test iterating over buffer."""
        buffer = CircularBuffer(maxsize=5)

        buffer.add_all([1, 2, 3])

        items = list(buffer)
        self.assertEqual(items, [1, 2, 3])

    def test_len(self):
        """Test __len__ method."""
        buffer = CircularBuffer(maxsize=5)

        buffer.add_all([1, 2, 3])

        self.assertEqual(len(buffer), 3)

    def test_invalid_maxsize(self):
        """Test invalid maxsize raises error."""
        with self.assertRaises(ValueError):
            CircularBuffer(maxsize=0)

        with self.assertRaises(ValueError):
            CircularBuffer(maxsize=-1)


class TestEndTruncatingAccumulator(unittest.TestCase):
    """Test end truncating accumulator functionality."""

    def test_basic_accumulation(self):
        """Test basic text accumulation."""
        acc = EndTruncatingAccumulator(max_size=100)

        acc.add("Hello ")
        acc.add("World")

        self.assertEqual(acc.get_value(), "Hello World")
        self.assertFalse(acc.is_truncated())

    def test_truncation(self):
        """Test truncation when exceeding max size."""
        acc = EndTruncatingAccumulator(max_size=10)

        acc.add("Hello ")
        acc.add("World!")  # Total would be 12 bytes

        self.assertTrue(acc.is_truncated())
        self.assertTrue(len(acc.get_value().encode('utf-8')) <= 10)

    def test_utf8_safety(self):
        """Test UTF-8 safe truncation."""
        acc = EndTruncatingAccumulator(max_size=10)

        acc.add("你好世界")  # Each Chinese char is 3 bytes

        # Should not break multi-byte characters
        result = acc.get_value()
        result.encode('utf-8')  # Should not raise

    def test_stats(self):
        """Test getting statistics."""
        acc = EndTruncatingAccumulator(max_size=20)

        acc.add("Hello ")
        acc.add("World")

        stats = acc.get_stats()

        self.assertEqual(stats['current_size'], 11)
        self.assertEqual(stats['max_size'], 20)
        self.assertEqual(stats['total_bytes'], 11)
        self.assertEqual(stats['truncated_bytes'], 0)
        self.assertFalse(stats['truncated'])

    def test_stats_with_truncation(self):
        """Test statistics with truncation."""
        acc = EndTruncatingAccumulator(max_size=10)

        acc.add("Hello World!")  # 12 bytes

        stats = acc.get_stats()

        self.assertTrue(stats['truncated'])
        self.assertGreater(stats['truncated_bytes'], 0)
        self.assertEqual(stats['total_bytes'], 12)

    def test_clear(self):
        """Test clearing accumulator."""
        acc = EndTruncatingAccumulator(max_size=100)

        acc.add("Hello")
        acc.clear()

        self.assertEqual(acc.get_value(), '')
        self.assertEqual(len(acc), 0)
        self.assertFalse(acc.is_truncated())

    def test_empty_string(self):
        """Test adding empty string."""
        acc = EndTruncatingAccumulator(max_size=100)

        acc.add("")
        acc.add("Hello")

        self.assertEqual(acc.get_value(), "Hello")

    def test_len(self):
        """Test __len__ method."""
        acc = EndTruncatingAccumulator(max_size=100)

        acc.add("Hello")

        self.assertEqual(len(acc), 5)

    def test_invalid_max_size(self):
        """Test invalid max_size raises error."""
        with self.assertRaises(ValueError):
            EndTruncatingAccumulator(max_size=0)

        with self.assertRaises(ValueError):
            EndTruncatingAccumulator(max_size=-1)

    def test_large_text(self):
        """Test handling large text."""
        acc = EndTruncatingAccumulator(max_size=100)

        # Add text that exceeds limit
        large_text = "x" * 200
        acc.add(large_text)

        self.assertTrue(acc.is_truncated())
        self.assertEqual(len(acc), 100)

    def test_multiple_additions_with_truncation(self):
        """Test multiple additions with truncation."""
        acc = EndTruncatingAccumulator(max_size=20)

        acc.add("Hello ")  # 6 bytes
        acc.add("World ")  # 6 bytes
        acc.add("Test")    # 4 bytes - total 16, fits
        acc.add("Extra")   # 5 bytes - would be 21, truncates

        self.assertTrue(acc.is_truncated())
        self.assertTrue(len(acc) <= 20)

    def test_utilization(self):
        """Test utilization calculation."""
        acc = EndTruncatingAccumulator(max_size=100)

        acc.add("Hello")  # 5 bytes

        stats = acc.get_stats()
        self.assertEqual(stats['utilization'], 5.0)


if __name__ == '__main__':
    unittest.main()
