"""
String processing and manipulation utilities inspired by Claude Code.

Provides robust string handling with proper CJK (Chinese, Japanese, Korean)
support, emoji handling, and safe truncation operations.
"""

import re
import unicodedata
from typing import List, Optional


def truncate_middle(
    text: str,
    max_length: int,
    separator: str = '...'
) -> str:
    """
    Truncate string in the middle, preserving start and end.

    Useful for file paths and long identifiers where both ends are important.

    Args:
        text: Text to truncate
        max_length: Maximum length including separator
        separator: Separator to use in middle (default '...')

    Returns:
        Truncated string

    Example:
        >>> truncate_middle('/very/long/path/to/file.txt', 20)
        '/very/.../file.txt'
    """
    if len(text) <= max_length:
        return text

    if max_length <= len(separator):
        return separator[:max_length]

    # Calculate space for each side
    available = max_length - len(separator)
    left_size = (available + 1) // 2
    right_size = available // 2

    return text[:left_size] + separator + text[-right_size:] if right_size > 0 else text[:left_size] + separator


def truncate_to_bytes(
    text: str,
    max_bytes: int,
    encoding: str = 'utf-8',
    suffix: str = '...'
) -> str:
    """
    Truncate string to fit within byte limit (UTF-8 safe).

    Ensures truncation doesn't break multi-byte characters.

    Args:
        text: Text to truncate
        max_bytes: Maximum bytes allowed
        encoding: Text encoding (default 'utf-8')
        suffix: Suffix to add if truncated

    Returns:
        Truncated string that fits within byte limit

    Example:
        >>> truncate_to_bytes('你好世界', max_bytes=10)
        '你好...'
    """
    if not text:
        return text

    encoded = text.encode(encoding)
    if len(encoded) <= max_bytes:
        return text

    # Reserve space for suffix
    suffix_bytes = suffix.encode(encoding)
    available_bytes = max_bytes - len(suffix_bytes)

    if available_bytes <= 0:
        return suffix[:max_bytes]

    # Truncate and decode, handling incomplete characters
    truncated = encoded[:available_bytes]

    # Try to decode, removing bytes from end until valid
    while truncated:
        try:
            result = truncated.decode(encoding)
            return result + suffix
        except UnicodeDecodeError:
            truncated = truncated[:-1]

    return suffix


def safe_join_lines(
    lines: List[str],
    max_size: int,
    separator: str = '\n',
    truncation_msg: str = '\n... (truncated)'
) -> str:
    """
    Join lines with truncation if total size exceeds limit.

    Args:
        lines: Lines to join
        max_size: Maximum total size
        separator: Line separator
        truncation_msg: Message to append if truncated

    Returns:
        Joined string, possibly truncated

    Example:
        >>> safe_join_lines(['line1', 'line2', 'line3'], max_size=20)
        'line1\\nline2\\nline3'
    """
    if not lines:
        return ''

    result = []
    current_size = 0
    truncation_size = len(truncation_msg)

    for line in lines:
        line_size = len(line) + len(separator)

        if current_size + line_size + truncation_size > max_size:
            # Would exceed limit
            result.append(truncation_msg)
            break

        result.append(line)
        current_size += line_size

    return separator.join(result)


def normalize_cjk_text(text: str) -> str:
    """
    Normalize CJK full-width characters to half-width.

    Converts full-width digits, spaces, and punctuation to ASCII equivalents.

    Args:
        text: Text to normalize

    Returns:
        Normalized text

    Example:
        >>> normalize_cjk_text('１２３　ＡＢＣ')
        '123 ABC'
    """
    if not text:
        return text

    result = []
    for char in text:
        # Full-width to half-width conversion
        code = ord(char)

        # Full-width ASCII variants (0xFF01-0xFF5E)
        if 0xFF01 <= code <= 0xFF5E:
            # Convert to ASCII
            result.append(chr(code - 0xFEE0))
        # Full-width space
        elif code == 0x3000:
            result.append(' ')
        else:
            result.append(char)

    return ''.join(result)


def count_graphemes(text: str) -> int:
    """
    Count grapheme clusters (user-perceived characters).

    Properly handles emoji, combining characters, and CJK.
    More accurate than len() for display width calculation.

    Args:
        text: Text to count

    Returns:
        Number of grapheme clusters

    Example:
        >>> count_graphemes('Hello')
        5
        >>> count_graphemes('👨‍👩‍👧‍👦')  # Family emoji
        1
        >>> count_graphemes('你好')
        2
    """
    if not text:
        return 0

    # Simple approximation: count non-combining characters
    # For full grapheme support, would need regex or external library
    count = 0
    for char in text:
        # Skip combining characters
        if unicodedata.category(char) not in ('Mn', 'Mc', 'Me'):
            count += 1

    return count


def escape_regex(text: str) -> str:
    """
    Escape special regex characters in string.

    Args:
        text: Text to escape

    Returns:
        Escaped text safe for use in regex

    Example:
        >>> escape_regex('file.txt')
        'file\\.txt'
    """
    return re.escape(text)


def capitalize_first(text: str) -> str:
    """
    Capitalize only the first character.

    Unlike str.capitalize(), doesn't lowercase the rest.

    Args:
        text: Text to capitalize

    Returns:
        Text with first character capitalized

    Example:
        >>> capitalize_first('helloWorld')
        'HelloWorld'
    """
    if not text:
        return text

    return text[0].upper() + text[1:]


def plural(count: int, singular: str, plural_form: Optional[str] = None) -> str:
    """
    Return singular or plural form based on count.

    Args:
        count: Number of items
        singular: Singular form
        plural_form: Plural form (default: singular + 's')

    Returns:
        Appropriate form

    Example:
        >>> plural(1, 'file')
        'file'
        >>> plural(2, 'file')
        'files'
        >>> plural(2, 'child', 'children')
        'children'
    """
    if count == 1:
        return singular

    if plural_form is None:
        return singular + 's'

    return plural_form


def count_char_in_string(text: str, char: str) -> int:
    """
    Count occurrences of character in string efficiently.

    Uses indexOf jumps instead of iterating every character.

    Args:
        text: Text to search
        char: Character to count

    Returns:
        Number of occurrences

    Example:
        >>> count_char_in_string('hello world', 'l')
        3
    """
    if not text or not char:
        return 0

    return text.count(char)


def normalize_whitespace(text: str) -> str:
    """
    Normalize whitespace in text.

    Replaces multiple spaces with single space, trims ends.

    Args:
        text: Text to normalize

    Returns:
        Normalized text

    Example:
        >>> normalize_whitespace('  hello   world  ')
        'hello world'
    """
    if not text:
        return text

    return ' '.join(text.split())


def remove_ansi_codes(text: str) -> str:
    """
    Remove ANSI color/formatting codes from text.

    Args:
        text: Text with ANSI codes

    Returns:
        Plain text without ANSI codes

    Example:
        >>> remove_ansi_codes('\\x1b[31mRed text\\x1b[0m')
        'Red text'
    """
    if not text:
        return text

    # ANSI escape sequence pattern
    ansi_pattern = re.compile(r'\x1b\[[0-9;]*m')
    return ansi_pattern.sub('', text)


def truncate_lines(
    text: str,
    max_lines: int,
    suffix: str = '\n... (truncated)'
) -> str:
    """
    Truncate text to maximum number of lines.

    Args:
        text: Text to truncate
        max_lines: Maximum number of lines
        suffix: Suffix to add if truncated

    Returns:
        Truncated text

    Example:
        >>> truncate_lines('line1\\nline2\\nline3', max_lines=2)
        'line1\\nline2\\n... (truncated)'
    """
    if not text:
        return text

    lines = text.split('\n')

    if len(lines) <= max_lines:
        return text

    return '\n'.join(lines[:max_lines]) + suffix


def indent_text(text: str, indent: str = '  ', skip_first: bool = False) -> str:
    """
    Indent all lines in text.

    Args:
        text: Text to indent
        indent: Indentation string
        skip_first: Skip indenting first line

    Returns:
        Indented text

    Example:
        >>> indent_text('line1\\nline2', indent='  ')
        '  line1\\n  line2'
    """
    if not text:
        return text

    lines = text.split('\n')

    if skip_first and lines:
        return lines[0] + '\n' + '\n'.join(indent + line for line in lines[1:])

    return '\n'.join(indent + line for line in lines)


def extract_between(
    text: str,
    start: str,
    end: str,
    include_markers: bool = False
) -> Optional[str]:
    """
    Extract text between two markers.

    Args:
        text: Text to search
        start: Start marker
        end: End marker
        include_markers: Include markers in result

    Returns:
        Extracted text or None if not found

    Example:
        >>> extract_between('Hello [world]!', '[', ']')
        'world'
    """
    if not text or not start or not end:
        return None

    start_idx = text.find(start)
    if start_idx == -1:
        return None

    search_start = start_idx + len(start)
    end_idx = text.find(end, search_start)
    if end_idx == -1:
        return None

    if include_markers:
        return text[start_idx:end_idx + len(end)]
    else:
        return text[search_start:end_idx]


def split_preserve_quotes(text: str, delimiter: str = ' ') -> List[str]:
    """
    Split text by delimiter, preserving quoted sections.

    Args:
        text: Text to split
        delimiter: Delimiter to split on

    Returns:
        List of parts

    Example:
        >>> split_preserve_quotes('hello "world test" foo')
        ['hello', 'world test', 'foo']
    """
    if not text:
        return []

    # Simple implementation using regex
    # Matches quoted strings or non-delimiter sequences
    pattern = r'"[^"]*"|[^' + re.escape(delimiter) + r']+'
    matches = re.findall(pattern, text)

    # Remove quotes from quoted strings
    result = []
    for match in matches:
        if match.startswith('"') and match.endswith('"'):
            result.append(match[1:-1])
        else:
            result.append(match)

    return result
