"""
Data structures for bounded memory usage inspired by Claude Code.

Provides circular buffers and truncating accumulators to prevent
unbounded memory growth in long-running processes.
"""

from collections import deque
from typing import Any, List, Optional


class CircularBuffer:
    """
    Fixed-size circular buffer with automatic eviction of oldest items.

    Thread-safe implementation using deque with maxlen.
    Useful for maintaining rolling windows of data (logs, events, history).
    """

    def __init__(self, maxsize: int):
        """
        Initialize circular buffer.

        Args:
            maxsize: Maximum number of items to store
        """
        if maxsize <= 0:
            raise ValueError("maxsize must be positive")

        self.maxsize = maxsize
        self._buffer = deque(maxlen=maxsize)

    def add(self, item: Any) -> None:
        """
        Add item to buffer.

        If buffer is full, oldest item is automatically evicted.

        Args:
            item: Item to add

        Example:
            >>> buffer = CircularBuffer(maxsize=3)
            >>> buffer.add(1)
            >>> buffer.add(2)
            >>> buffer.add(3)
            >>> buffer.add(4)  # Evicts 1
            >>> buffer.to_list()
            [2, 3, 4]
        """
        self._buffer.append(item)

    def add_all(self, items: List[Any]) -> None:
        """
        Add multiple items to buffer.

        Args:
            items: Items to add

        Example:
            >>> buffer = CircularBuffer(maxsize=5)
            >>> buffer.add_all([1, 2, 3, 4, 5, 6])
            >>> buffer.to_list()
            [2, 3, 4, 5, 6]
        """
        for item in items:
            self._buffer.append(item)

    def get_recent(self, count: int) -> List[Any]:
        """
        Get most recent N items.

        Args:
            count: Number of items to retrieve

        Returns:
            List of most recent items (may be fewer if buffer is smaller)

        Example:
            >>> buffer = CircularBuffer(maxsize=10)
            >>> buffer.add_all([1, 2, 3, 4, 5])
            >>> buffer.get_recent(3)
            [3, 4, 5]
        """
        if count <= 0:
            return []

        # Get last N items
        items = list(self._buffer)
        return items[-count:] if len(items) > count else items

    def to_list(self) -> List[Any]:
        """
        Convert buffer to list.

        Returns:
            List of all items in buffer (oldest to newest)

        Example:
            >>> buffer = CircularBuffer(maxsize=3)
            >>> buffer.add_all([1, 2, 3])
            >>> buffer.to_list()
            [1, 2, 3]
        """
        return list(self._buffer)

    def clear(self) -> None:
        """
        Clear all items from buffer.

        Example:
            >>> buffer = CircularBuffer(maxsize=5)
            >>> buffer.add_all([1, 2, 3])
            >>> buffer.clear()
            >>> buffer.length()
            0
        """
        self._buffer.clear()

    def length(self) -> int:
        """
        Get current number of items in buffer.

        Returns:
            Number of items

        Example:
            >>> buffer = CircularBuffer(maxsize=10)
            >>> buffer.add_all([1, 2, 3])
            >>> buffer.length()
            3
        """
        return len(self._buffer)

    def is_full(self) -> bool:
        """
        Check if buffer is full.

        Returns:
            True if buffer is at capacity

        Example:
            >>> buffer = CircularBuffer(maxsize=3)
            >>> buffer.add_all([1, 2])
            >>> buffer.is_full()
            False
            >>> buffer.add(3)
            >>> buffer.is_full()
            True
        """
        return len(self._buffer) >= self.maxsize

    def __len__(self) -> int:
        """Get length of buffer."""
        return len(self._buffer)

    def __iter__(self):
        """Iterate over buffer items."""
        return iter(self._buffer)

    def __repr__(self) -> str:
        """String representation."""
        return f"CircularBuffer(maxsize={self.maxsize}, length={len(self._buffer)})"


class EndTruncatingAccumulator:
    """
    Safe string accumulator that truncates from the end when size limit exceeded.

    Prevents RangeError crashes while preserving beginning of output.
    Tracks total bytes received vs. truncated amount.
    """

    def __init__(self, max_size: int):
        """
        Initialize accumulator.

        Args:
            max_size: Maximum size in bytes
        """
        if max_size <= 0:
            raise ValueError("max_size must be positive")

        self.max_size = max_size
        self._buffer = []
        self._current_size = 0
        self._total_bytes = 0
        self._truncated_bytes = 0

    def add(self, text: str) -> None:
        """
        Add text to accumulator.

        If adding text would exceed max_size, truncates from end.

        Args:
            text: Text to add

        Example:
            >>> acc = EndTruncatingAccumulator(max_size=100)
            >>> acc.add("Hello ")
            >>> acc.add("World")
            >>> acc.get_value()
            'Hello World'
        """
        if not text:
            return

        text_bytes = len(text.encode('utf-8'))
        self._total_bytes += text_bytes

        if self._current_size + text_bytes <= self.max_size:
            # Fits within limit
            self._buffer.append(text)
            self._current_size += text_bytes
        else:
            # Would exceed limit - truncate from end
            available = self.max_size - self._current_size

            if available > 0:
                # Add what we can
                truncated_text = self._truncate_to_bytes(text, available)
                self._buffer.append(truncated_text)
                self._current_size += len(truncated_text.encode('utf-8'))

            self._truncated_bytes += text_bytes - (len(truncated_text.encode('utf-8')) if available > 0 else 0)

    def _truncate_to_bytes(self, text: str, max_bytes: int) -> str:
        """
        Truncate text to fit within byte limit (UTF-8 safe).

        Args:
            text: Text to truncate
            max_bytes: Maximum bytes

        Returns:
            Truncated text
        """
        if not text:
            return text

        encoded = text.encode('utf-8')
        if len(encoded) <= max_bytes:
            return text

        # Truncate and decode, handling incomplete characters
        truncated = encoded[:max_bytes]

        while truncated:
            try:
                return truncated.decode('utf-8')
            except UnicodeDecodeError:
                truncated = truncated[:-1]

        return ''

    def get_value(self) -> str:
        """
        Get accumulated text.

        Returns:
            Accumulated string

        Example:
            >>> acc = EndTruncatingAccumulator(max_size=20)
            >>> acc.add("Hello ")
            >>> acc.add("World")
            >>> acc.get_value()
            'Hello World'
        """
        return ''.join(self._buffer)

    def get_stats(self) -> dict:
        """
        Get accumulator statistics.

        Returns:
            Dictionary with statistics

        Example:
            >>> acc = EndTruncatingAccumulator(max_size=10)
            >>> acc.add("Hello World!")
            >>> stats = acc.get_stats()
            >>> stats['truncated']
            True
        """
        return {
            'current_size': self._current_size,
            'max_size': self.max_size,
            'total_bytes': self._total_bytes,
            'truncated_bytes': self._truncated_bytes,
            'truncated': self._truncated_bytes > 0,
            'utilization': round(self._current_size / self.max_size * 100, 2)
        }

    def clear(self) -> None:
        """
        Clear accumulator.

        Example:
            >>> acc = EndTruncatingAccumulator(max_size=100)
            >>> acc.add("Hello")
            >>> acc.clear()
            >>> acc.get_value()
            ''
        """
        self._buffer.clear()
        self._current_size = 0
        self._total_bytes = 0
        self._truncated_bytes = 0

    def is_truncated(self) -> bool:
        """
        Check if any truncation has occurred.

        Returns:
            True if truncation occurred

        Example:
            >>> acc = EndTruncatingAccumulator(max_size=5)
            >>> acc.add("Hello World")
            >>> acc.is_truncated()
            True
        """
        return self._truncated_bytes > 0

    def __len__(self) -> int:
        """Get current size in bytes."""
        return self._current_size

    def __repr__(self) -> str:
        """String representation."""
        return f"EndTruncatingAccumulator(max_size={self.max_size}, current_size={self._current_size}, truncated={self.is_truncated()})"
