"""
Tree visualization utilities inspired by Claude Code.

Provides functions for rendering nested objects as ASCII trees
with support for circular reference detection and custom styling.
"""

from typing import Any, Set, Optional


def treeify(
    obj: Any,
    max_depth: int = 5,
    current_depth: int = 0,
    prefix: str = "",
    is_last: bool = True,
    seen: Optional[Set[int]] = None,
    show_types: bool = False
) -> str:
    """
    Render nested object as ASCII tree.

    Args:
        obj: Object to render
        max_depth: Maximum depth to traverse
        current_depth: Current depth (internal)
        prefix: Line prefix (internal)
        is_last: Whether this is the last item (internal)
        seen: Set of seen object IDs for circular reference detection
        show_types: Show type information

    Returns:
        ASCII tree string

    Example:
        >>> data = {'a': 1, 'b': {'c': 2, 'd': 3}}
        >>> tree = treeify(data)
        >>> 'a' in tree and 'b' in tree
        True
    """
    if seen is None:
        seen = set()

    # Check depth limit
    if current_depth >= max_depth:
        return f"{prefix}... (max depth reached)"

    # Check for circular references
    obj_id = id(obj)
    if obj_id in seen and isinstance(obj, (dict, list, tuple, set)):
        return f"{prefix}... (circular reference)"

    # Add to seen set
    if isinstance(obj, (dict, list, tuple, set)):
        seen = seen.copy()
        seen.add(obj_id)

    # Determine tree characters
    if current_depth == 0:
        connector = ""
        child_prefix = ""
    else:
        connector = "└── " if is_last else "├── "
        child_prefix = prefix + ("    " if is_last else "│   ")

    # Handle different types
    if obj is None:
        return f"{prefix}{connector}null"

    elif isinstance(obj, bool):
        return f"{prefix}{connector}{str(obj).lower()}"

    elif isinstance(obj, (int, float)):
        type_info = f" ({type(obj).__name__})" if show_types else ""
        return f"{prefix}{connector}{obj}{type_info}"

    elif isinstance(obj, str):
        # Truncate long strings
        display = obj if len(obj) <= 50 else obj[:47] + "..."
        type_info = f" (str)" if show_types else ""
        return f"{prefix}{connector}\"{display}\"{type_info}"

    elif isinstance(obj, dict):
        if not obj:
            return f"{prefix}{connector}{{}}"

        lines = [f"{prefix}{connector}{{}}"]
        items = list(obj.items())

        for i, (key, value) in enumerate(items):
            is_last_item = (i == len(items) - 1)
            key_str = f"\"{key}\"" if isinstance(key, str) else str(key)

            # Render value
            value_tree = treeify(
                value,
                max_depth=max_depth,
                current_depth=current_depth + 1,
                prefix=child_prefix,
                is_last=is_last_item,
                seen=seen,
                show_types=show_types
            )

            # Combine key and value
            if '\n' in value_tree:
                # Multi-line value
                lines.append(f"{child_prefix}{'└── ' if is_last_item else '├── '}{key_str}:")
                lines.append(value_tree)
            else:
                # Single-line value
                if connector and connector in value_tree:
                    value_part = value_tree.split(connector, 1)[-1]
                else:
                    value_part = value_tree
                lines.append(f"{child_prefix}{'└── ' if is_last_item else '├── '}{key_str}: {value_part}")

        return '\n'.join(lines)

    elif isinstance(obj, (list, tuple)):
        type_name = "[]" if isinstance(obj, list) else "()"
        if not obj:
            return f"{prefix}{connector}{type_name}"

        lines = [f"{prefix}{connector}{type_name}"]

        for i, item in enumerate(obj):
            is_last_item = (i == len(obj) - 1)

            item_tree = treeify(
                item,
                max_depth=max_depth,
                current_depth=current_depth + 1,
                prefix=child_prefix,
                is_last=is_last_item,
                seen=seen,
                show_types=show_types
            )

            if connector and connector in item_tree:
                item_part = item_tree.split(connector, 1)[-1]
            else:
                item_part = item_tree
            lines.append(f"{child_prefix}{'└── ' if is_last_item else '├── '}[{i}]: {item_part}")

        return '\n'.join(lines)

    elif isinstance(obj, set):
        if not obj:
            return f"{prefix}{connector}set()"

        lines = [f"{prefix}{connector}set()"]
        items = list(obj)

        for i, item in enumerate(items):
            is_last_item = (i == len(items) - 1)

            item_tree = treeify(
                item,
                max_depth=max_depth,
                current_depth=current_depth + 1,
                prefix=child_prefix,
                is_last=is_last_item,
                seen=seen,
                show_types=show_types
            )

            lines.append(item_tree)

        return '\n'.join(lines)

    elif callable(obj):
        func_name = getattr(obj, '__name__', 'function')
        return f"{prefix}{connector}<function {func_name}>"

    else:
        # Generic object
        type_name = type(obj).__name__
        try:
            # Try to get object attributes
            if hasattr(obj, '__dict__'):
                attrs = obj.__dict__
                if attrs:
                    lines = [f"{prefix}{connector}<{type_name}>"]
                    items = list(attrs.items())

                    for i, (key, value) in enumerate(items):
                        is_last_item = (i == len(items) - 1)

                        value_tree = treeify(
                            value,
                            max_depth=max_depth,
                            current_depth=current_depth + 1,
                            prefix=child_prefix,
                            is_last=is_last_item,
                            seen=seen,
                            show_types=show_types
                        )

                        if connector and connector in value_tree:
                            value_part = value_tree.split(connector, 1)[-1]
                        else:
                            value_part = value_tree
                        lines.append(f"{child_prefix}{'└── ' if is_last_item else '├── '}{key}: {value_part}")

                    return '\n'.join(lines)

            return f"{prefix}{connector}<{type_name}: {str(obj)[:50]}>"
        except Exception:
            return f"{prefix}{connector}<{type_name}>"


def treeify_compact(obj: Any, max_depth: int = 3) -> str:
    """
    Render object as compact tree (less verbose).

    Args:
        obj: Object to render
        max_depth: Maximum depth

    Returns:
        Compact ASCII tree string

    Example:
        >>> treeify_compact({'a': 1, 'b': 2})
        '{}\\n├── "a": 1\\n└── "b": 2'
    """
    return treeify(obj, max_depth=max_depth, show_types=False)


def treeify_with_types(obj: Any, max_depth: int = 5) -> str:
    """
    Render object as tree with type information.

    Args:
        obj: Object to render
        max_depth: Maximum depth

    Returns:
        ASCII tree string with types

    Example:
        >>> treeify_with_types({'a': 1})
        '{}\\n└── "a": 1 (int)'
    """
    return treeify(obj, max_depth=max_depth, show_types=True)


def format_tree_node(key: str, value: Any, is_last: bool = False) -> str:
    """
    Format a single tree node.

    Args:
        key: Node key
        value: Node value
        is_last: Whether this is the last node

    Returns:
        Formatted node string

    Example:
        >>> format_tree_node("name", "value", is_last=True)
        '└── name: value'
    """
    connector = "└── " if is_last else "├── "
    return f"{connector}{key}: {value}"
