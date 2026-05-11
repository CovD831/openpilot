"""Unit tests for text utilities."""

import unittest

from src.utils.text_utils import (
    truncate_middle,
    truncate_to_bytes,
    safe_join_lines,
    normalize_cjk_text,
    count_graphemes,
    escape_regex,
    capitalize_first,
    plural,
    normalize_whitespace,
    remove_ansi_codes,
    truncate_lines,
    indent_text,
    extract_between,
    split_preserve_quotes,
)


class TestTruncateMiddle(unittest.TestCase):
    """Test middle truncation."""

    def test_short_text(self):
        """Test text shorter than max length."""
        result = truncate_middle('hello', 10)
        self.assertEqual(result, 'hello')

    def test_long_text(self):
        """Test text longer than max length."""
        result = truncate_middle('/very/long/path/to/file.txt', 20)
        self.assertEqual(len(result), 20)
        self.assertIn('...', result)
        self.assertTrue(result.startswith('/very'))
        self.assertTrue(result.endswith('.txt'))

    def test_custom_separator(self):
        """Test custom separator."""
        result = truncate_middle('hello world', 10, separator='--')
        self.assertIn('--', result)


class TestTruncateToBytes(unittest.TestCase):
    """Test byte-safe truncation."""

    def test_ascii_text(self):
        """Test ASCII text."""
        result = truncate_to_bytes('hello world', max_bytes=10)
        self.assertTrue(len(result.encode('utf-8')) <= 10)

    def test_cjk_text(self):
        """Test CJK text (multi-byte characters)."""
        result = truncate_to_bytes('你好世界', max_bytes=10)
        # Should not break multi-byte characters
        result.encode('utf-8')  # Should not raise
        self.assertTrue(len(result.encode('utf-8')) <= 10)

    def test_emoji(self):
        """Test emoji (multi-byte characters)."""
        result = truncate_to_bytes('Hello 👋 World', max_bytes=15)
        result.encode('utf-8')  # Should not raise
        self.assertTrue(len(result.encode('utf-8')) <= 15)


class TestSafeJoinLines(unittest.TestCase):
    """Test safe line joining."""

    def test_within_limit(self):
        """Test joining within limit."""
        lines = ['line1', 'line2', 'line3']
        result = safe_join_lines(lines, max_size=100)
        self.assertEqual(result, 'line1\nline2\nline3')

    def test_exceeds_limit(self):
        """Test joining exceeds limit."""
        lines = ['line1', 'line2', 'line3']
        result = safe_join_lines(lines, max_size=15)
        self.assertIn('truncated', result)


class TestNormalizeCJKText(unittest.TestCase):
    """Test CJK text normalization."""

    def test_full_width_digits(self):
        """Test full-width digit conversion."""
        result = normalize_cjk_text('１２３')
        self.assertEqual(result, '123')

    def test_full_width_space(self):
        """Test full-width space conversion."""
        result = normalize_cjk_text('hello　world')
        self.assertEqual(result, 'hello world')

    def test_mixed_text(self):
        """Test mixed text."""
        result = normalize_cjk_text('１２３　ＡＢＣ')
        self.assertEqual(result, '123 ABC')


class TestCountGraphemes(unittest.TestCase):
    """Test grapheme counting."""

    def test_ascii(self):
        """Test ASCII text."""
        count = count_graphemes('Hello')
        self.assertEqual(count, 5)

    def test_cjk(self):
        """Test CJK characters."""
        count = count_graphemes('你好')
        self.assertEqual(count, 2)

    def test_empty_string(self):
        """Test empty string."""
        count = count_graphemes('')
        self.assertEqual(count, 0)


class TestEscapeRegex(unittest.TestCase):
    """Test regex escaping."""

    def test_special_chars(self):
        """Test escaping special characters."""
        result = escape_regex('file.txt')
        self.assertEqual(result, r'file\.txt')

    def test_multiple_special_chars(self):
        """Test multiple special characters."""
        result = escape_regex('test[0-9]+')
        # Should escape special characters
        self.assertIn(r'\[', result)
        self.assertIn(r'\+', result)


class TestCapitalizeFirst(unittest.TestCase):
    """Test first character capitalization."""

    def test_lowercase(self):
        """Test lowercase string."""
        result = capitalize_first('hello')
        self.assertEqual(result, 'Hello')

    def test_camel_case(self):
        """Test camelCase preservation."""
        result = capitalize_first('helloWorld')
        self.assertEqual(result, 'HelloWorld')

    def test_empty_string(self):
        """Test empty string."""
        result = capitalize_first('')
        self.assertEqual(result, '')


class TestPlural(unittest.TestCase):
    """Test plural form selection."""

    def test_singular(self):
        """Test singular form."""
        result = plural(1, 'file')
        self.assertEqual(result, 'file')

    def test_plural_default(self):
        """Test plural form with default."""
        result = plural(2, 'file')
        self.assertEqual(result, 'files')

    def test_plural_custom(self):
        """Test plural form with custom."""
        result = plural(2, 'child', 'children')
        self.assertEqual(result, 'children')

    def test_zero(self):
        """Test zero count."""
        result = plural(0, 'file')
        self.assertEqual(result, 'files')


class TestNormalizeWhitespace(unittest.TestCase):
    """Test whitespace normalization."""

    def test_multiple_spaces(self):
        """Test multiple spaces."""
        result = normalize_whitespace('hello   world')
        self.assertEqual(result, 'hello world')

    def test_leading_trailing(self):
        """Test leading and trailing spaces."""
        result = normalize_whitespace('  hello world  ')
        self.assertEqual(result, 'hello world')

    def test_tabs_newlines(self):
        """Test tabs and newlines."""
        result = normalize_whitespace('hello\t\nworld')
        self.assertEqual(result, 'hello world')


class TestRemoveAnsiCodes(unittest.TestCase):
    """Test ANSI code removal."""

    def test_colored_text(self):
        """Test removing color codes."""
        result = remove_ansi_codes('\x1b[31mRed text\x1b[0m')
        self.assertEqual(result, 'Red text')

    def test_plain_text(self):
        """Test plain text unchanged."""
        result = remove_ansi_codes('Plain text')
        self.assertEqual(result, 'Plain text')


class TestTruncateLines(unittest.TestCase):
    """Test line truncation."""

    def test_within_limit(self):
        """Test within line limit."""
        result = truncate_lines('line1\nline2\nline3', max_lines=5)
        self.assertEqual(result, 'line1\nline2\nline3')

    def test_exceeds_limit(self):
        """Test exceeding line limit."""
        result = truncate_lines('line1\nline2\nline3', max_lines=2)
        self.assertIn('truncated', result)
        self.assertIn('line1', result)
        self.assertIn('line2', result)
        self.assertNotIn('line3', result.replace('truncated', ''))


class TestIndentText(unittest.TestCase):
    """Test text indentation."""

    def test_basic_indent(self):
        """Test basic indentation."""
        result = indent_text('line1\nline2', indent='  ')
        self.assertEqual(result, '  line1\n  line2')

    def test_skip_first(self):
        """Test skipping first line."""
        result = indent_text('line1\nline2', indent='  ', skip_first=True)
        self.assertEqual(result, 'line1\n  line2')


class TestExtractBetween(unittest.TestCase):
    """Test extracting text between markers."""

    def test_basic_extraction(self):
        """Test basic extraction."""
        result = extract_between('Hello [world]!', '[', ']')
        self.assertEqual(result, 'world')

    def test_include_markers(self):
        """Test including markers."""
        result = extract_between('Hello [world]!', '[', ']', include_markers=True)
        self.assertEqual(result, '[world]')

    def test_not_found(self):
        """Test markers not found."""
        result = extract_between('Hello world', '[', ']')
        self.assertIsNone(result)


class TestSplitPreserveQuotes(unittest.TestCase):
    """Test splitting with quote preservation."""

    def test_basic_split(self):
        """Test basic split."""
        result = split_preserve_quotes('hello world foo')
        self.assertEqual(result, ['hello', 'world', 'foo'])

    def test_quoted_section(self):
        """Test quoted section."""
        result = split_preserve_quotes('hello "world test" foo')
        self.assertEqual(result, ['hello', 'world test', 'foo'])

    def test_multiple_quotes(self):
        """Test multiple quoted sections."""
        result = split_preserve_quotes('"hello world" "foo bar"')
        self.assertEqual(result, ['hello world', 'foo bar'])


if __name__ == '__main__':
    unittest.main()
