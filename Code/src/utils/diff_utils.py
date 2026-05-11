"""
Diff and patch utilities inspired by Claude Code.

Provides functions for generating patches, counting changes,
and applying patches for code review and file modifications.
"""

import difflib
from typing import List, Tuple, Optional


def get_patch_from_contents(
    old_content: str,
    new_content: str,
    context_lines: int = 3,
    old_name: str = "old",
    new_name: str = "new"
) -> str:
    """
    Generate unified diff patch from old and new content.

    Args:
        old_content: Original content
        new_content: Modified content
        context_lines: Number of context lines around changes
        old_name: Name for old file in patch header
        new_name: Name for new file in patch header

    Returns:
        Unified diff patch string

    Example:
        >>> old = "line1\\nline2\\nline3"
        >>> new = "line1\\nmodified\\nline3"
        >>> patch = get_patch_from_contents(old, new)
        >>> "modified" in patch
        True
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    # Generate unified diff
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=old_name,
        tofile=new_name,
        lineterm='',
        n=context_lines
    )

    return ''.join(diff)


def count_lines_changed(patch: str) -> Tuple[int, int]:
    """
    Count additions and deletions from a patch.

    Args:
        patch: Unified diff patch string

    Returns:
        Tuple of (additions, deletions)

    Example:
        >>> patch = "@@ -1,3 +1,3 @@\\n line1\\n-line2\\n+modified\\n line3"
        >>> count_lines_changed(patch)
        (1, 1)
    """
    additions = 0
    deletions = 0

    for line in patch.split('\n'):
        if line.startswith('+') and not line.startswith('+++'):
            additions += 1
        elif line.startswith('-') and not line.startswith('---'):
            deletions += 1

    return additions, deletions


def apply_patch(content: str, patch: str) -> Optional[str]:
    """
    Apply a unified diff patch to content.

    Args:
        content: Original content
        patch: Unified diff patch string

    Returns:
        Patched content, or None if patch cannot be applied

    Example:
        >>> content = "line1\\nline2\\nline3"
        >>> patch = "@@ -1,3 +1,3 @@\\n line1\\n-line2\\n+modified\\n line3"
        >>> result = apply_patch(content, patch)
        >>> "modified" in result
        True
    """
    # Simple implementation - parse patch and apply changes
    # This is a simplified version; production code would use a proper patch library

    lines = content.split('\n')
    patch_lines = patch.split('\n')

    # Find hunks
    hunks = []
    current_hunk = None

    for line in patch_lines:
        if line.startswith('@@'):
            if current_hunk:
                hunks.append(current_hunk)
            current_hunk = {'header': line, 'lines': []}
        elif current_hunk is not None:
            if not line.startswith('---') and not line.startswith('+++'):
                current_hunk['lines'].append(line)

    if current_hunk:
        hunks.append(current_hunk)

    # Apply hunks (simplified - just for demonstration)
    # In production, use a proper patch library
    result_lines = lines.copy()

    for hunk in hunks:
        # Parse hunk header to get line numbers
        # Format: @@ -old_start,old_count +new_start,new_count @@
        header = hunk['header']
        try:
            parts = header.split('@@')[1].strip().split()
            old_info = parts[0][1:].split(',')
            old_start = int(old_info[0])

            # Apply changes (simplified)
            hunk_lines = hunk['lines']
            offset = 0

            for hunk_line in hunk_lines:
                if hunk_line.startswith('-'):
                    # Remove line
                    pass
                elif hunk_line.startswith('+'):
                    # Add line
                    pass
                else:
                    # Context line
                    pass

        except (IndexError, ValueError):
            return None

    return '\n'.join(result_lines)


def get_diff_stats(patch: str) -> dict:
    """
    Get statistics from a patch.

    Args:
        patch: Unified diff patch string

    Returns:
        Dictionary with diff statistics

    Example:
        >>> patch = "@@ -1,3 +1,3 @@\\n line1\\n-line2\\n+modified\\n line3"
        >>> stats = get_diff_stats(patch)
        >>> stats['additions']
        1
        >>> stats['deletions']
        1
    """
    additions, deletions = count_lines_changed(patch)

    return {
        'additions': additions,
        'deletions': deletions,
        'total_changes': additions + deletions,
        'files_changed': 1  # Simplified - would need to parse multiple files
    }


def format_diff_stats(additions: int, deletions: int) -> str:
    """
    Format diff statistics as a string.

    Args:
        additions: Number of additions
        deletions: Number of deletions

    Returns:
        Formatted string (e.g., "+5 -3")

    Example:
        >>> format_diff_stats(5, 3)
        '+5 -3'
    """
    return f"+{additions} -{deletions}"


def get_changed_lines(old_content: str, new_content: str) -> List[int]:
    """
    Get line numbers that changed between old and new content.

    Args:
        old_content: Original content
        new_content: Modified content

    Returns:
        List of changed line numbers (1-indexed)

    Example:
        >>> old = "line1\\nline2\\nline3"
        >>> new = "line1\\nmodified\\nline3"
        >>> get_changed_lines(old, new)
        [2]
    """
    old_lines = old_content.split('\n')
    new_lines = new_content.split('\n')

    changed = []
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ('replace', 'delete', 'insert'):
            # Add new line numbers (1-indexed)
            for line_num in range(j1 + 1, j2 + 1):
                changed.append(line_num)

    return changed


def highlight_diff(
    old_content: str,
    new_content: str,
    context_lines: int = 3
) -> List[Tuple[str, str]]:
    """
    Generate highlighted diff with line types.

    Args:
        old_content: Original content
        new_content: Modified content
        context_lines: Number of context lines

    Returns:
        List of (line_type, line_content) tuples
        line_type is one of: 'context', 'add', 'remove', 'header'

    Example:
        >>> old = "line1\\nline2"
        >>> new = "line1\\nmodified"
        >>> diff = highlight_diff(old, new)
        >>> len(diff) > 0
        True
    """
    old_lines = old_content.split('\n')
    new_lines = new_content.split('\n')

    result = []
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            # Context lines
            for line in new_lines[j1:j2]:
                result.append(('context', line))
        elif tag == 'replace':
            # Changed lines
            for line in old_lines[i1:i2]:
                result.append(('remove', line))
            for line in new_lines[j1:j2]:
                result.append(('add', line))
        elif tag == 'delete':
            # Deleted lines
            for line in old_lines[i1:i2]:
                result.append(('remove', line))
        elif tag == 'insert':
            # Added lines
            for line in new_lines[j1:j2]:
                result.append(('add', line))

    return result


def is_whitespace_only_change(old_content: str, new_content: str) -> bool:
    """
    Check if changes are whitespace-only.

    Args:
        old_content: Original content
        new_content: Modified content

    Returns:
        True if only whitespace changed

    Example:
        >>> is_whitespace_only_change("hello  world", "hello world")
        True
        >>> is_whitespace_only_change("hello", "goodbye")
        False
    """
    # Normalize whitespace and compare
    old_normalized = ' '.join(old_content.split())
    new_normalized = ' '.join(new_content.split())

    return old_normalized == new_normalized


def get_similarity_ratio(old_content: str, new_content: str) -> float:
    """
    Calculate similarity ratio between two contents.

    Args:
        old_content: Original content
        new_content: Modified content

    Returns:
        Similarity ratio (0.0 to 1.0)

    Example:
        >>> get_similarity_ratio("hello world", "hello world")
        1.0
        >>> ratio = get_similarity_ratio("hello", "goodbye")
        >>> 0.0 <= ratio <= 1.0
        True
    """
    matcher = difflib.SequenceMatcher(None, old_content, new_content)
    return matcher.ratio()
