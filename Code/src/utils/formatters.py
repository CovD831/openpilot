"""
Formatting utilities inspired by Claude Code.

Provides consistent formatting for file sizes, durations, numbers,
and relative times for better user experience.
"""

from datetime import datetime, timedelta
from typing import Optional


def format_file_size(bytes_size: int) -> str:
    """
    Format file size in human-readable format.

    Args:
        bytes_size: Size in bytes

    Returns:
        Formatted string (e.g., "1.5 MB", "234 KB")

    Example:
        >>> format_file_size(1024)
        '1.0 KB'
        >>> format_file_size(1536000)
        '1.5 MB'
    """
    if bytes_size < 0:
        return "0 B"

    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    size = float(bytes_size)
    unit_index = 0

    while size >= 1024.0 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1

    # Format with appropriate precision
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    else:
        return f"{size:.1f} {units[unit_index]}"


def format_duration(milliseconds: float) -> str:
    """
    Format duration in human-readable format.

    Args:
        milliseconds: Duration in milliseconds

    Returns:
        Formatted string (e.g., "1d 2h 3m 4s", "5.2s")

    Example:
        >>> format_duration(5200)
        '5.2s'
        >>> format_duration(90000)
        '1m 30s'
    """
    if milliseconds < 0:
        return "0s"

    seconds = milliseconds / 1000.0

    # Less than 1 minute - show seconds with decimal
    if seconds < 60:
        return f"{seconds:.1f}s"

    # Build components
    parts = []

    days = int(seconds // 86400)
    if days > 0:
        parts.append(f"{days}d")
        seconds %= 86400

    hours = int(seconds // 3600)
    if hours > 0:
        parts.append(f"{hours}h")
        seconds %= 3600

    minutes = int(seconds // 60)
    if minutes > 0:
        parts.append(f"{minutes}m")
        seconds %= 60

    if seconds > 0 or not parts:
        parts.append(f"{int(seconds)}s")

    return ' '.join(parts)


def format_seconds_short(seconds: float) -> str:
    """
    Format seconds in short format (always keeps decimal).

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted string (e.g., "1.2s", "0.5s")

    Example:
        >>> format_seconds_short(1.234)
        '1.2s'
    """
    return f"{seconds:.1f}s"


def format_number_compact(num: float) -> str:
    """
    Format number in compact notation.

    Args:
        num: Number to format

    Returns:
        Formatted string (e.g., "1.3k", "900", "2.5M")

    Example:
        >>> format_number_compact(1300)
        '1.3k'
        >>> format_number_compact(900)
        '900'
        >>> format_number_compact(2500000)
        '2.5M'
    """
    if num < 0:
        return f"-{format_number_compact(-num)}"

    if num < 1000:
        return str(int(num))

    units = [
        (1_000_000_000, 'B'),
        (1_000_000, 'M'),
        (1_000, 'k'),
    ]

    for threshold, suffix in units:
        if num >= threshold:
            value = num / threshold
            # Remove .0 from compact numbers
            if value == int(value):
                return f"{int(value)}{suffix}"
            return f"{value:.1f}{suffix}"

    return str(int(num))


def format_tokens(tokens: int) -> str:
    """
    Format token count (removes .0 from compact numbers).

    Args:
        tokens: Number of tokens

    Returns:
        Formatted string

    Example:
        >>> format_tokens(1000)
        '1k'
        >>> format_tokens(1500)
        '1.5k'
    """
    return format_number_compact(tokens)


def format_relative_time(
    timestamp: datetime,
    now: Optional[datetime] = None,
    max_units: int = 2
) -> str:
    """
    Format timestamp as relative time.

    Args:
        timestamp: Timestamp to format
        now: Current time (default: datetime.now())
        max_units: Maximum number of time units to show

    Returns:
        Formatted string (e.g., "2 hours ago", "in 3 days")

    Example:
        >>> from datetime import datetime, timedelta
        >>> now = datetime(2024, 1, 1, 12, 0, 0)
        >>> past = datetime(2024, 1, 1, 10, 0, 0)
        >>> format_relative_time(past, now)
        '2 hours ago'
    """
    if now is None:
        now = datetime.now()

    # Ensure both are timezone-aware or both naive
    if timestamp.tzinfo is not None and now.tzinfo is None:
        from datetime import timezone
        now = now.replace(tzinfo=timezone.utc)
    elif timestamp.tzinfo is None and now.tzinfo is not None:
        from datetime import timezone
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    delta = now - timestamp
    is_future = delta.total_seconds() < 0

    if is_future:
        delta = -delta
        suffix = ""
        prefix = "in "
    else:
        suffix = " ago"
        prefix = ""

    seconds = abs(delta.total_seconds())

    # Define time units
    units = [
        (31536000, 'year', 'years'),
        (2592000, 'month', 'months'),
        (604800, 'week', 'weeks'),
        (86400, 'day', 'days'),
        (3600, 'hour', 'hours'),
        (60, 'minute', 'minutes'),
        (1, 'second', 'seconds'),
    ]

    parts = []
    for threshold, singular, plural in units:
        if seconds >= threshold:
            count = int(seconds // threshold)
            unit = singular if count == 1 else plural
            parts.append(f"{count} {unit}")
            seconds %= threshold

            if len(parts) >= max_units:
                break

    if not parts:
        return "just now"

    time_str = ' '.join(parts)
    return f"{prefix}{time_str}{suffix}"


def format_percentage(value: float, total: float, decimals: int = 1) -> str:
    """
    Format percentage.

    Args:
        value: Current value
        total: Total value
        decimals: Number of decimal places

    Returns:
        Formatted percentage string

    Example:
        >>> format_percentage(25, 100)
        '25.0%'
        >>> format_percentage(1, 3, decimals=2)
        '33.33%'
    """
    if total == 0:
        return "0%"

    percentage = (value / total) * 100
    return f"{percentage:.{decimals}f}%"


def format_log_attributes(
    timestamp: Optional[datetime] = None,
    file_size: Optional[int] = None,
    branch: Optional[str] = None,
    pr_number: Optional[int] = None
) -> str:
    """
    Format log attributes combining time, size, branch, PR info.

    Args:
        timestamp: Log timestamp
        file_size: Log file size in bytes
        branch: Git branch name
        pr_number: Pull request number

    Returns:
        Formatted attributes string

    Example:
        >>> format_log_attributes(file_size=1536000, branch="main")
        '1.5 MB | main'
    """
    parts = []

    if timestamp:
        parts.append(format_relative_time(timestamp))

    if file_size is not None:
        parts.append(format_file_size(file_size))

    if branch:
        parts.append(branch)

    if pr_number is not None:
        parts.append(f"PR #{pr_number}")

    return ' | '.join(parts) if parts else ''


def format_count(count: int, singular: str, plural: Optional[str] = None) -> str:
    """
    Format count with singular/plural form.

    Args:
        count: Number to format
        singular: Singular form
        plural: Plural form (default: singular + 's')

    Returns:
        Formatted string

    Example:
        >>> format_count(1, 'file')
        '1 file'
        >>> format_count(5, 'file')
        '5 files'
        >>> format_count(2, 'child', 'children')
        '2 children'
    """
    if plural is None:
        plural = singular + 's'

    word = singular if count == 1 else plural
    return f"{count} {word}"


def format_list(items: list, max_items: int = 3, conjunction: str = 'and') -> str:
    """
    Format list of items with conjunction.

    Args:
        items: List of items
        max_items: Maximum items to show before truncating
        conjunction: Conjunction word ('and' or 'or')

    Returns:
        Formatted string

    Example:
        >>> format_list(['a', 'b', 'c'])
        'a, b, and c'
        >>> format_list(['a', 'b', 'c', 'd', 'e'], max_items=3)
        'a, b, c, and 2 more'
    """
    if not items:
        return ''

    if len(items) == 1:
        return str(items[0])

    if len(items) <= max_items:
        if len(items) == 2:
            return f"{items[0]} {conjunction} {items[1]}"
        else:
            return f"{', '.join(str(i) for i in items[:-1])}, {conjunction} {items[-1]}"

    # Truncate
    shown = items[:max_items]
    remaining = len(items) - max_items
    shown_str = ', '.join(str(i) for i in shown)
    return f"{shown_str}, {conjunction} {remaining} more"
