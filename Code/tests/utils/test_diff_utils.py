"""Unit tests for diff utilities."""

import unittest

from src.utils.diff_utils import (
    get_patch_from_contents,
    count_lines_changed,
    get_diff_stats,
    format_diff_stats,
    get_changed_lines,
    is_whitespace_only_change,
    get_similarity_ratio,
)


class TestGetPatchFromContents(unittest.TestCase):
    """Test patch generation."""

    def test_no_changes(self):
        """Test no changes."""
        old = "line1\nline2\nline3"
        new = "line1\nline2\nline3"
        patch = get_patch_from_contents(old, new)
        self.assertEqual(patch, "")

    def test_single_line_change(self):
        """Test single line change."""
        old = "line1\nline2\nline3"
        new = "line1\nmodified\nline3"
        patch = get_patch_from_contents(old, new)
        self.assertIn("modified", patch)
        self.assertIn("-line2", patch)

    def test_addition(self):
        """Test line addition."""
        old = "line1\nline2"
        new = "line1\nline2\nline3"
        patch = get_patch_from_contents(old, new)
        self.assertIn("+line3", patch)

    def test_deletion(self):
        """Test line deletion."""
        old = "line1\nline2\nline3"
        new = "line1\nline3"
        patch = get_patch_from_contents(old, new)
        self.assertIn("-line2", patch)


class TestCountLinesChanged(unittest.TestCase):
    """Test counting changed lines."""

    def test_no_changes(self):
        """Test no changes."""
        patch = ""
        additions, deletions = count_lines_changed(patch)
        self.assertEqual(additions, 0)
        self.assertEqual(deletions, 0)

    def test_additions_only(self):
        """Test additions only."""
        patch = "+line1\n+line2"
        additions, deletions = count_lines_changed(patch)
        self.assertEqual(additions, 2)
        self.assertEqual(deletions, 0)

    def test_deletions_only(self):
        """Test deletions only."""
        patch = "-line1\n-line2"
        additions, deletions = count_lines_changed(patch)
        self.assertEqual(additions, 0)
        self.assertEqual(deletions, 2)

    def test_mixed_changes(self):
        """Test mixed changes."""
        patch = "+line1\n-line2\n+line3"
        additions, deletions = count_lines_changed(patch)
        self.assertEqual(additions, 2)
        self.assertEqual(deletions, 1)

    def test_ignore_headers(self):
        """Test ignoring patch headers."""
        patch = "+++file.txt\n---file.txt\n+line1\n-line2"
        additions, deletions = count_lines_changed(patch)
        self.assertEqual(additions, 1)
        self.assertEqual(deletions, 1)


class TestGetDiffStats(unittest.TestCase):
    """Test diff statistics."""

    def test_basic_stats(self):
        """Test basic statistics."""
        patch = "+line1\n-line2"
        stats = get_diff_stats(patch)
        self.assertEqual(stats['additions'], 1)
        self.assertEqual(stats['deletions'], 1)
        self.assertEqual(stats['total_changes'], 2)


class TestFormatDiffStats(unittest.TestCase):
    """Test diff stats formatting."""

    def test_format(self):
        """Test formatting."""
        result = format_diff_stats(5, 3)
        self.assertEqual(result, "+5 -3")

    def test_zero(self):
        """Test zero changes."""
        result = format_diff_stats(0, 0)
        self.assertEqual(result, "+0 -0")


class TestGetChangedLines(unittest.TestCase):
    """Test getting changed line numbers."""

    def test_no_changes(self):
        """Test no changes."""
        old = "line1\nline2"
        new = "line1\nline2"
        changed = get_changed_lines(old, new)
        self.assertEqual(changed, [])

    def test_single_change(self):
        """Test single line change."""
        old = "line1\nline2\nline3"
        new = "line1\nmodified\nline3"
        changed = get_changed_lines(old, new)
        self.assertEqual(changed, [2])

    def test_addition(self):
        """Test line addition."""
        old = "line1\nline2"
        new = "line1\nline2\nline3"
        changed = get_changed_lines(old, new)
        self.assertEqual(changed, [3])


class TestIsWhitespaceOnlyChange(unittest.TestCase):
    """Test whitespace-only change detection."""

    def test_whitespace_only(self):
        """Test whitespace-only change."""
        old = "hello  world"
        new = "hello world"
        self.assertTrue(is_whitespace_only_change(old, new))

    def test_content_change(self):
        """Test content change."""
        old = "hello"
        new = "goodbye"
        self.assertFalse(is_whitespace_only_change(old, new))

    def test_no_change(self):
        """Test no change."""
        old = "hello world"
        new = "hello world"
        self.assertTrue(is_whitespace_only_change(old, new))


class TestGetSimilarityRatio(unittest.TestCase):
    """Test similarity ratio calculation."""

    def test_identical(self):
        """Test identical content."""
        ratio = get_similarity_ratio("hello", "hello")
        self.assertEqual(ratio, 1.0)

    def test_completely_different(self):
        """Test completely different content."""
        ratio = get_similarity_ratio("abc", "xyz")
        self.assertLess(ratio, 0.5)

    def test_similar(self):
        """Test similar content."""
        ratio = get_similarity_ratio("hello world", "hello world!")
        self.assertGreater(ratio, 0.9)


if __name__ == '__main__':
    unittest.main()
