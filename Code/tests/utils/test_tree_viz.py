"""Unit tests for tree visualization."""

import unittest

from src.utils.tree_viz import (
    treeify,
    treeify_compact,
    treeify_with_types,
    format_tree_node,
)


class TestTreeify(unittest.TestCase):
    """Test tree visualization."""

    def test_simple_dict(self):
        """Test simple dictionary."""
        data = {'a': 1, 'b': 2}
        tree = treeify(data)
        self.assertIn('a', tree)
        self.assertIn('b', tree)

    def test_nested_dict(self):
        """Test nested dictionary."""
        data = {'a': 1, 'b': {'c': 2, 'd': 3}}
        tree = treeify(data)
        self.assertIn('a', tree)
        self.assertIn('b', tree)
        self.assertIn('c', tree)
        self.assertIn('d', tree)

    def test_list(self):
        """Test list."""
        data = [1, 2, 3]
        tree = treeify(data)
        self.assertIn('[0]', tree)
        self.assertIn('[1]', tree)
        self.assertIn('[2]', tree)

    def test_empty_dict(self):
        """Test empty dictionary."""
        data = {}
        tree = treeify(data)
        self.assertIn('{}', tree)

    def test_empty_list(self):
        """Test empty list."""
        data = []
        tree = treeify(data)
        self.assertIn('[]', tree)

    def test_null(self):
        """Test null value."""
        tree = treeify(None)
        self.assertIn('null', tree)

    def test_boolean(self):
        """Test boolean values."""
        tree_true = treeify(True)
        tree_false = treeify(False)
        self.assertIn('true', tree_true.lower())
        self.assertIn('false', tree_false.lower())

    def test_string(self):
        """Test string value."""
        tree = treeify("hello")
        self.assertIn('hello', tree)

    def test_number(self):
        """Test number value."""
        tree = treeify(42)
        self.assertIn('42', tree)

    def test_max_depth(self):
        """Test max depth limit."""
        data = {'a': {'b': {'c': {'d': {'e': 1}}}}}
        tree = treeify(data, max_depth=2)
        self.assertIn('max depth', tree)

    def test_circular_reference(self):
        """Test circular reference detection."""
        data = {'a': 1}
        data['self'] = data
        tree = treeify(data)
        self.assertIn('circular', tree)

    def test_long_string_truncation(self):
        """Test long string truncation."""
        long_string = 'x' * 100
        tree = treeify(long_string)
        self.assertIn('...', tree)

    def test_tuple(self):
        """Test tuple."""
        data = (1, 2, 3)
        tree = treeify(data)
        self.assertIn('()', tree)

    def test_set(self):
        """Test set."""
        data = {1, 2, 3}
        tree = treeify(data)
        self.assertIn('set()', tree)


class TestTreeifyCompact(unittest.TestCase):
    """Test compact tree visualization."""

    def test_compact(self):
        """Test compact format."""
        data = {'a': 1, 'b': 2}
        tree = treeify_compact(data)
        self.assertIn('a', tree)
        self.assertIn('b', tree)


class TestTreeifyWithTypes(unittest.TestCase):
    """Test tree visualization with types."""

    def test_with_types(self):
        """Test with type information."""
        data = {'a': 1}
        tree = treeify_with_types(data)
        self.assertIn('a', tree)
        # Type info might be shown for numbers


class TestFormatTreeNode(unittest.TestCase):
    """Test tree node formatting."""

    def test_last_node(self):
        """Test last node formatting."""
        result = format_tree_node("key", "value", is_last=True)
        self.assertIn('└──', result)
        self.assertIn('key', result)
        self.assertIn('value', result)

    def test_middle_node(self):
        """Test middle node formatting."""
        result = format_tree_node("key", "value", is_last=False)
        self.assertIn('├──', result)
        self.assertIn('key', result)
        self.assertIn('value', result)


if __name__ == '__main__':
    unittest.main()
