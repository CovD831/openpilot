"""
Utility functions and helpers for OpenPilot.

This package contains reusable utilities inspired by Claude Code best practices:
- cache: Memoization and caching decorators
- json_utils: Efficient JSONL processing
- data_structures: Circular buffers and accumulators
- input_utils: Interactive input helpers
- path_boundary: Project-relative path resolution and containment checks
"""

__version__ = "0.1.0"

# Import commonly used utilities for convenience
from .cache import (
    LRUCache,
    TTLCache,
    AsyncTTLCache,
    memoize_with_lru,
    memoize_with_ttl,
    memoize_with_ttl_async,
)

from .json_utils import (
    safe_parse_json,
    parse_jsonl,
    read_jsonl_file,
    append_jsonl,
    read_last_n_lines,
    parse_last_n_jsonl,
    count_jsonl_lines,
    truncate_jsonl_file,
    validate_jsonl_file,
)

from .data_structures import (
    CircularBuffer,
    EndTruncatingAccumulator,
)

from .input_utils import (
    read_text,
    read_confirm,
)

__all__ = [
    # Cache
    'LRUCache',
    'TTLCache',
    'AsyncTTLCache',
    'memoize_with_lru',
    'memoize_with_ttl',
    'memoize_with_ttl_async',
    # JSON
    'safe_parse_json',
    'parse_jsonl',
    'read_jsonl_file',
    'append_jsonl',
    'read_last_n_lines',
    'parse_last_n_jsonl',
    'count_jsonl_lines',
    'truncate_jsonl_file',
    'validate_jsonl_file',
    # Data Structures
    'CircularBuffer',
    'EndTruncatingAccumulator',
    # Input
    'read_text',
    'read_confirm',
]
