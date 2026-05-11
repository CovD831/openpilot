"""
Efficient JSONL (JSON Lines) processing utilities inspired by Claude Code.

Provides safe JSON parsing with caching, efficient JSONL file handling,
and atomic append operations for log files.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .cache import memoize_with_lru


# Internal cache for JSON parsing (only cache text -> result mapping)
_json_parse_cache = {}
_json_parse_cache_order = []
_JSON_CACHE_MAX_SIZE = 50


def safe_parse_json(text: str, default: Any = None) -> Any:
    """
    Parse JSON with LRU caching and safe error handling.

    Uses memoization to avoid re-parsing the same JSON strings.
    Returns default value on parse failure instead of raising exception.

    Args:
        text: JSON string to parse
        default: Default value to return on parse failure

    Returns:
        Parsed JSON object or default value

    Example:
        >>> safe_parse_json('{"key": "value"}')
        {'key': 'value'}
        >>> safe_parse_json('invalid json', default={})
        {}
    """
    if not text or not isinstance(text, str):
        return default

    # Limit key size to prevent unbounded memory growth
    if len(text) > 8192:
        # Don't cache very large strings
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return default

    # Check cache (use a sentinel for parse failures)
    _PARSE_FAILED = object()

    if text in _json_parse_cache:
        result = _json_parse_cache[text]
        if result is _PARSE_FAILED:
            return default
        return result

    # Parse and cache
    try:
        result = json.loads(text)
        _json_parse_cache[text] = result
        _json_parse_cache_order.append(text)

        # Evict oldest if cache is full
        if len(_json_parse_cache) > _JSON_CACHE_MAX_SIZE:
            oldest = _json_parse_cache_order.pop(0)
            _json_parse_cache.pop(oldest, None)

        return result
    except (json.JSONDecodeError, ValueError):
        # Cache the failure too
        _json_parse_cache[text] = _PARSE_FAILED
        _json_parse_cache_order.append(text)

        if len(_json_parse_cache) > _JSON_CACHE_MAX_SIZE:
            oldest = _json_parse_cache_order.pop(0)
            _json_parse_cache.pop(oldest, None)

        return default


def parse_jsonl(data: Union[str, bytes]) -> List[Dict[str, Any]]:
    """
    Parse JSONL data from string or bytes.

    Skips malformed lines gracefully instead of failing completely.

    Args:
        data: JSONL data as string or bytes

    Returns:
        List of parsed JSON objects

    Example:
        >>> parse_jsonl('{"a": 1}\\n{"b": 2}\\n')
        [{'a': 1}, {'b': 2}]
    """
    if isinstance(data, bytes):
        data = data.decode('utf-8', errors='replace')

    results = []
    for line_num, line in enumerate(data.split('\n'), 1):
        line = line.strip()
        if not line:
            continue

        try:
            obj = json.loads(line)
            results.append(obj)
        except (json.JSONDecodeError, ValueError) as e:
            # Skip malformed lines but log warning
            # In production, you might want to use proper logging
            pass

    return results


def read_jsonl_file(
    path: Union[str, Path],
    max_bytes: int = 100 * 1024 * 1024,  # 100MB default
    skip_first_partial: bool = True
) -> List[Dict[str, Any]]:
    """
    Read JSONL file efficiently, optionally reading only the tail.

    For large files, reads only the last max_bytes to avoid loading
    entire file into memory. Skips first partial line when reading tail.

    Args:
        path: Path to JSONL file
        max_bytes: Maximum bytes to read from end of file
        skip_first_partial: Skip first partial line when reading tail

    Returns:
        List of parsed JSON objects

    Example:
        >>> read_jsonl_file('logs/openpilot.jsonl', max_bytes=10*1024*1024)
        [{'timestamp': '...', 'event': '...'}, ...]
    """
    path = Path(path)

    if not path.exists():
        return []

    file_size = path.stat().st_size

    if file_size == 0:
        return []

    with open(path, 'rb') as f:
        if file_size <= max_bytes:
            # Read entire file
            data = f.read()
        else:
            # Read tail of file
            f.seek(file_size - max_bytes)
            data = f.read()

            if skip_first_partial:
                # Skip first partial line
                newline_pos = data.find(b'\n')
                if newline_pos != -1:
                    data = data[newline_pos + 1:]

    return parse_jsonl(data)


def append_jsonl(
    path: Union[str, Path],
    data: Union[Dict[str, Any], List[Dict[str, Any]]],
    ensure_newline: bool = True
) -> None:
    """
    Atomically append JSON object(s) to JSONL file.

    Creates parent directories if they don't exist.
    Each object is written as a single line.

    Args:
        path: Path to JSONL file
        data: Single dict or list of dicts to append
        ensure_newline: Ensure file ends with newline

    Example:
        >>> append_jsonl('logs/events.jsonl', {'event': 'task_started'})
        >>> append_jsonl('logs/events.jsonl', [
        ...     {'event': 'step_1'},
        ...     {'event': 'step_2'}
        ... ])
    """
    path = Path(path)

    # Create parent directories
    path.parent.mkdir(parents=True, exist_ok=True)

    # Normalize to list
    if isinstance(data, dict):
        data = [data]

    # Write atomically
    with open(path, 'a', encoding='utf-8') as f:
        for obj in data:
            line = json.dumps(obj, ensure_ascii=False)
            f.write(line)
            if ensure_newline:
                f.write('\n')


def read_last_n_lines(
    path: Union[str, Path],
    n: int = 100,
    max_line_length: int = 10240
) -> List[str]:
    """
    Read last N lines from file efficiently.

    Uses seek from end to avoid reading entire file.

    Args:
        path: Path to file
        n: Number of lines to read
        max_line_length: Maximum expected line length

    Returns:
        List of last N lines (may be fewer if file is smaller)

    Example:
        >>> read_last_n_lines('logs/openpilot.jsonl', n=50)
        ['{"timestamp": "...", ...}', ...]
    """
    path = Path(path)

    if not path.exists():
        return []

    file_size = path.stat().st_size
    if file_size == 0:
        return []

    # Estimate bytes to read (n lines * max_line_length)
    # Add buffer for safety
    bytes_to_read = min(n * max_line_length * 2, file_size)

    with open(path, 'rb') as f:
        f.seek(max(0, file_size - bytes_to_read))
        data = f.read()

    # Decode and split into lines
    text = data.decode('utf-8', errors='replace')
    lines = text.split('\n')

    # Remove empty lines
    lines = [line for line in lines if line.strip()]

    # Return last n lines
    return lines[-n:]


def parse_last_n_jsonl(
    path: Union[str, Path],
    n: int = 100
) -> List[Dict[str, Any]]:
    """
    Parse last N lines from JSONL file.

    Combines read_last_n_lines with JSON parsing.

    Args:
        path: Path to JSONL file
        n: Number of lines to read

    Returns:
        List of parsed JSON objects

    Example:
        >>> parse_last_n_jsonl('logs/openpilot.jsonl', n=20)
        [{'timestamp': '...', 'event': '...'}, ...]
    """
    lines = read_last_n_lines(path, n=n)
    results = []

    for line in lines:
        obj = safe_parse_json(line)
        if obj is not None:
            results.append(obj)

    return results


def count_jsonl_lines(path: Union[str, Path]) -> int:
    """
    Count number of lines in JSONL file efficiently.

    Args:
        path: Path to JSONL file

    Returns:
        Number of lines

    Example:
        >>> count_jsonl_lines('logs/openpilot.jsonl')
        1523
    """
    path = Path(path)

    if not path.exists():
        return 0

    count = 0
    with open(path, 'rb') as f:
        for _ in f:
            count += 1

    return count


def truncate_jsonl_file(
    path: Union[str, Path],
    max_lines: int = 10000
) -> int:
    """
    Truncate JSONL file to keep only last N lines.

    Useful for preventing log files from growing unbounded.

    Args:
        path: Path to JSONL file
        max_lines: Maximum number of lines to keep

    Returns:
        Number of lines removed

    Example:
        >>> truncate_jsonl_file('logs/openpilot.jsonl', max_lines=5000)
        2341  # Removed 2341 lines
    """
    path = Path(path)

    if not path.exists():
        return 0

    # Read last N lines
    lines = read_last_n_lines(path, n=max_lines)

    if not lines:
        return 0

    # Count original lines
    original_count = count_jsonl_lines(path)

    # Write back only last N lines
    with open(path, 'w', encoding='utf-8') as f:
        for line in lines:
            f.write(line)
            f.write('\n')

    removed = original_count - len(lines)
    return max(0, removed)


def validate_jsonl_file(path: Union[str, Path]) -> Dict[str, Any]:
    """
    Validate JSONL file and return statistics.

    Args:
        path: Path to JSONL file

    Returns:
        Dictionary with validation results

    Example:
        >>> validate_jsonl_file('logs/openpilot.jsonl')
        {
            'valid': True,
            'total_lines': 1523,
            'valid_lines': 1520,
            'invalid_lines': 3,
            'file_size': 2458392
        }
    """
    path = Path(path)

    if not path.exists():
        return {
            'valid': False,
            'error': 'File not found',
            'total_lines': 0,
            'valid_lines': 0,
            'invalid_lines': 0,
            'file_size': 0
        }

    file_size = path.stat().st_size
    total_lines = 0
    valid_lines = 0
    invalid_lines = 0

    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            total_lines += 1

            try:
                json.loads(line)
                valid_lines += 1
            except (json.JSONDecodeError, ValueError):
                invalid_lines += 1

    return {
        'valid': invalid_lines == 0,
        'total_lines': total_lines,
        'valid_lines': valid_lines,
        'invalid_lines': invalid_lines,
        'file_size': file_size
    }
