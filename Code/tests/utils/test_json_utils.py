"""Unit tests for JSON utilities."""

import json
import tempfile
import unittest
from pathlib import Path

from src.utils.json_utils import (
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


class TestSafeParseJSON(unittest.TestCase):
    """Test safe JSON parsing."""

    def test_valid_json(self):
        """Test parsing valid JSON."""
        result = safe_parse_json('{"key": "value"}')
        self.assertEqual(result, {"key": "value"})

    def test_invalid_json(self):
        """Test parsing invalid JSON returns default."""
        result = safe_parse_json('invalid json', default={})
        self.assertEqual(result, {})

    def test_empty_string(self):
        """Test parsing empty string."""
        result = safe_parse_json('', default=None)
        self.assertIsNone(result)

    def test_caching(self):
        """Test that results are cached."""
        # Parse same JSON twice
        result1 = safe_parse_json('{"key": "value"}')
        result2 = safe_parse_json('{"key": "value"}')

        self.assertEqual(result1, result2)


class TestParseJSONL(unittest.TestCase):
    """Test JSONL parsing."""

    def test_valid_jsonl(self):
        """Test parsing valid JSONL."""
        data = '{"a": 1}\n{"b": 2}\n{"c": 3}'
        result = parse_jsonl(data)

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], {"a": 1})
        self.assertEqual(result[1], {"b": 2})
        self.assertEqual(result[2], {"c": 3})

    def test_empty_lines(self):
        """Test that empty lines are skipped."""
        data = '{"a": 1}\n\n{"b": 2}\n'
        result = parse_jsonl(data)

        self.assertEqual(len(result), 2)

    def test_malformed_lines(self):
        """Test that malformed lines are skipped."""
        data = '{"a": 1}\ninvalid json\n{"b": 2}'
        result = parse_jsonl(data)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], {"a": 1})
        self.assertEqual(result[1], {"b": 2})

    def test_bytes_input(self):
        """Test parsing from bytes."""
        data = b'{"a": 1}\n{"b": 2}'
        result = parse_jsonl(data)

        self.assertEqual(len(result), 2)


class TestReadJSONLFile(unittest.TestCase):
    """Test reading JSONL files."""

    def test_read_small_file(self):
        """Test reading small file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            f.write('{"a": 1}\n')
            f.write('{"b": 2}\n')
            f.write('{"c": 3}\n')
            temp_path = f.name

        try:
            result = read_jsonl_file(temp_path)
            self.assertEqual(len(result), 3)
            self.assertEqual(result[0], {"a": 1})
        finally:
            Path(temp_path).unlink()

    def test_read_nonexistent_file(self):
        """Test reading nonexistent file."""
        result = read_jsonl_file('/nonexistent/file.jsonl')
        self.assertEqual(result, [])

    def test_read_empty_file(self):
        """Test reading empty file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            temp_path = f.name

        try:
            result = read_jsonl_file(temp_path)
            self.assertEqual(result, [])
        finally:
            Path(temp_path).unlink()


class TestAppendJSONL(unittest.TestCase):
    """Test appending to JSONL files."""

    def test_append_single_object(self):
        """Test appending single object."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / 'test.jsonl'

            append_jsonl(file_path, {"a": 1})

            result = read_jsonl_file(file_path)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0], {"a": 1})

    def test_append_multiple_objects(self):
        """Test appending multiple objects."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / 'test.jsonl'

            append_jsonl(file_path, [{"a": 1}, {"b": 2}])

            result = read_jsonl_file(file_path)
            self.assertEqual(len(result), 2)

    def test_append_creates_directory(self):
        """Test that parent directories are created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / 'subdir' / 'test.jsonl'

            append_jsonl(file_path, {"a": 1})

            self.assertTrue(file_path.exists())


class TestReadLastNLines(unittest.TestCase):
    """Test reading last N lines."""

    def test_read_last_lines(self):
        """Test reading last N lines."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            for i in range(10):
                f.write(f'line {i}\n')
            temp_path = f.name

        try:
            result = read_last_n_lines(temp_path, n=3)
            self.assertEqual(len(result), 3)
            self.assertEqual(result[-1], 'line 9')
        finally:
            Path(temp_path).unlink()


class TestCountJSONLLines(unittest.TestCase):
    """Test counting JSONL lines."""

    def test_count_lines(self):
        """Test counting lines."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            for i in range(5):
                f.write(f'{{"line": {i}}}\n')
            temp_path = f.name

        try:
            count = count_jsonl_lines(temp_path)
            self.assertEqual(count, 5)
        finally:
            Path(temp_path).unlink()

    def test_count_nonexistent_file(self):
        """Test counting nonexistent file."""
        count = count_jsonl_lines('/nonexistent/file.jsonl')
        self.assertEqual(count, 0)


class TestTruncateJSONLFile(unittest.TestCase):
    """Test truncating JSONL files."""

    def test_truncate_file(self):
        """Test truncating file to max lines."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            for i in range(10):
                f.write(f'{{"line": {i}}}\n')
            temp_path = f.name

        try:
            removed = truncate_jsonl_file(temp_path, max_lines=5)
            self.assertEqual(removed, 5)

            count = count_jsonl_lines(temp_path)
            self.assertEqual(count, 5)
        finally:
            Path(temp_path).unlink()


class TestValidateJSONLFile(unittest.TestCase):
    """Test validating JSONL files."""

    def test_valid_file(self):
        """Test validating valid file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            f.write('{"a": 1}\n')
            f.write('{"b": 2}\n')
            temp_path = f.name

        try:
            result = validate_jsonl_file(temp_path)
            self.assertTrue(result['valid'])
            self.assertEqual(result['total_lines'], 2)
            self.assertEqual(result['valid_lines'], 2)
            self.assertEqual(result['invalid_lines'], 0)
        finally:
            Path(temp_path).unlink()

    def test_invalid_lines(self):
        """Test validating file with invalid lines."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            f.write('{"a": 1}\n')
            f.write('invalid json\n')
            f.write('{"b": 2}\n')
            temp_path = f.name

        try:
            result = validate_jsonl_file(temp_path)
            self.assertFalse(result['valid'])
            self.assertEqual(result['total_lines'], 3)
            self.assertEqual(result['valid_lines'], 2)
            self.assertEqual(result['invalid_lines'], 1)
        finally:
            Path(temp_path).unlink()

    def test_nonexistent_file(self):
        """Test validating nonexistent file."""
        result = validate_jsonl_file('/nonexistent/file.jsonl')
        self.assertFalse(result['valid'])
        self.assertIn('error', result)


if __name__ == '__main__':
    unittest.main()
