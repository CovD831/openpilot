"""Unit tests for formatters."""

import unittest
from datetime import datetime, timedelta, timezone

from src.utils.formatters import (
    format_file_size,
    format_duration,
    format_seconds_short,
    format_number_compact,
    format_tokens,
    format_relative_time,
    format_percentage,
    format_log_metadata,
    format_count,
    format_list,
)


class TestFormatFileSize(unittest.TestCase):
    """Test file size formatting."""

    def test_bytes(self):
        """Test bytes formatting."""
        self.assertEqual(format_file_size(0), "0 B")
        self.assertEqual(format_file_size(500), "500 B")
        self.assertEqual(format_file_size(1023), "1023 B")

    def test_kilobytes(self):
        """Test kilobytes formatting."""
        self.assertEqual(format_file_size(1024), "1.0 KB")
        self.assertEqual(format_file_size(1536), "1.5 KB")

    def test_megabytes(self):
        """Test megabytes formatting."""
        self.assertEqual(format_file_size(1024 * 1024), "1.0 MB")
        self.assertEqual(format_file_size(1536 * 1024), "1.5 MB")

    def test_gigabytes(self):
        """Test gigabytes formatting."""
        self.assertEqual(format_file_size(1024 * 1024 * 1024), "1.0 GB")

    def test_negative(self):
        """Test negative size."""
        self.assertEqual(format_file_size(-100), "0 B")


class TestFormatDuration(unittest.TestCase):
    """Test duration formatting."""

    def test_seconds(self):
        """Test seconds formatting."""
        self.assertEqual(format_duration(5200), "5.2s")
        self.assertEqual(format_duration(1000), "1.0s")

    def test_minutes(self):
        """Test minutes formatting."""
        self.assertEqual(format_duration(90000), "1m 30s")
        self.assertEqual(format_duration(120000), "2m")

    def test_hours(self):
        """Test hours formatting."""
        self.assertEqual(format_duration(3600000), "1h")
        self.assertEqual(format_duration(3661000), "1h 1m 1s")

    def test_days(self):
        """Test days formatting."""
        self.assertEqual(format_duration(86400000), "1d")

    def test_negative(self):
        """Test negative duration."""
        self.assertEqual(format_duration(-1000), "0s")


class TestFormatNumberCompact(unittest.TestCase):
    """Test compact number formatting."""

    def test_small_numbers(self):
        """Test small numbers."""
        self.assertEqual(format_number_compact(0), "0")
        self.assertEqual(format_number_compact(500), "500")
        self.assertEqual(format_number_compact(999), "999")

    def test_thousands(self):
        """Test thousands."""
        self.assertEqual(format_number_compact(1000), "1k")
        self.assertEqual(format_number_compact(1300), "1.3k")
        self.assertEqual(format_number_compact(1500), "1.5k")

    def test_millions(self):
        """Test millions."""
        self.assertEqual(format_number_compact(1000000), "1M")
        self.assertEqual(format_number_compact(2500000), "2.5M")

    def test_billions(self):
        """Test billions."""
        self.assertEqual(format_number_compact(1000000000), "1B")

    def test_negative(self):
        """Test negative numbers."""
        self.assertEqual(format_number_compact(-1300), "-1.3k")


class TestFormatRelativeTime(unittest.TestCase):
    """Test relative time formatting."""

    def test_just_now(self):
        """Test just now."""
        now = datetime(2024, 1, 1, 12, 0, 0)
        result = format_relative_time(now, now)
        self.assertEqual(result, "just now")

    def test_minutes_ago(self):
        """Test minutes ago."""
        now = datetime(2024, 1, 1, 12, 0, 0)
        past = datetime(2024, 1, 1, 11, 55, 0)
        result = format_relative_time(past, now)
        self.assertEqual(result, "5 minutes ago")

    def test_hours_ago(self):
        """Test hours ago."""
        now = datetime(2024, 1, 1, 12, 0, 0)
        past = datetime(2024, 1, 1, 10, 0, 0)
        result = format_relative_time(past, now)
        self.assertEqual(result, "2 hours ago")

    def test_days_ago(self):
        """Test days ago."""
        now = datetime(2024, 1, 5, 12, 0, 0)
        past = datetime(2024, 1, 1, 12, 0, 0)
        result = format_relative_time(past, now)
        self.assertEqual(result, "4 days ago")

    def test_future(self):
        """Test future time."""
        now = datetime(2024, 1, 1, 12, 0, 0)
        future = datetime(2024, 1, 1, 14, 0, 0)
        result = format_relative_time(future, now)
        self.assertEqual(result, "in 2 hours")


class TestFormatPercentage(unittest.TestCase):
    """Test percentage formatting."""

    def test_basic(self):
        """Test basic percentage."""
        self.assertEqual(format_percentage(25, 100), "25.0%")
        self.assertEqual(format_percentage(50, 100), "50.0%")

    def test_decimals(self):
        """Test decimal places."""
        self.assertEqual(format_percentage(1, 3, decimals=2), "33.33%")

    def test_zero_total(self):
        """Test zero total."""
        self.assertEqual(format_percentage(10, 0), "0%")


class TestFormatCount(unittest.TestCase):
    """Test count formatting."""

    def test_singular(self):
        """Test singular form."""
        self.assertEqual(format_count(1, 'file'), "1 file")

    def test_plural(self):
        """Test plural form."""
        self.assertEqual(format_count(5, 'file'), "5 files")

    def test_custom_plural(self):
        """Test custom plural form."""
        self.assertEqual(format_count(2, 'child', 'children'), "2 children")


class TestFormatList(unittest.TestCase):
    """Test list formatting."""

    def test_empty(self):
        """Test empty list."""
        self.assertEqual(format_list([]), '')

    def test_single(self):
        """Test single item."""
        self.assertEqual(format_list(['a']), 'a')

    def test_two_items(self):
        """Test two items."""
        self.assertEqual(format_list(['a', 'b']), 'a and b')

    def test_three_items(self):
        """Test three items."""
        self.assertEqual(format_list(['a', 'b', 'c']), 'a, b, and c')

    def test_truncation(self):
        """Test truncation."""
        result = format_list(['a', 'b', 'c', 'd', 'e'], max_items=3)
        self.assertEqual(result, 'a, b, c, and 2 more')

    def test_or_conjunction(self):
        """Test or conjunction."""
        self.assertEqual(format_list(['a', 'b'], conjunction='or'), 'a or b')


if __name__ == '__main__':
    unittest.main()
