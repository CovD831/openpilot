"""Unit tests for cache utilities."""

import asyncio
import time
import unittest

from src.utils.cache import (
    LRUCache,
    TTLCache,
    AsyncTTLCache,
    memoize_with_lru,
    memoize_with_ttl,
    memoize_with_ttl_async,
)


class TestLRUCache(unittest.TestCase):
    """Test LRU cache functionality."""

    def test_basic_operations(self):
        """Test basic get/put operations."""
        cache = LRUCache(maxsize=3)

        cache.put('a', 1)
        cache.put('b', 2)
        cache.put('c', 3)

        found, value = cache.get('a')
        self.assertTrue(found)
        self.assertEqual(value, 1)

        found, value = cache.get('d')
        self.assertFalse(found)
        self.assertIsNone(value)

    def test_eviction(self):
        """Test LRU eviction."""
        cache = LRUCache(maxsize=2)

        cache.put('a', 1)
        cache.put('b', 2)
        cache.put('c', 3)  # Should evict 'a'

        found, _ = cache.get('a')
        self.assertFalse(found)

        found, value = cache.get('b')
        self.assertTrue(found)
        self.assertEqual(value, 2)

    def test_update_moves_to_end(self):
        """Test that accessing item moves it to end."""
        cache = LRUCache(maxsize=2)

        cache.put('a', 1)
        cache.put('b', 2)
        cache.get('a')  # Access 'a', moves to end
        cache.put('c', 3)  # Should evict 'b', not 'a'

        found, _ = cache.get('a')
        self.assertTrue(found)

        found, _ = cache.get('b')
        self.assertFalse(found)

    def test_stats(self):
        """Test cache statistics."""
        cache = LRUCache(maxsize=10)

        cache.put('a', 1)
        cache.get('a')  # Hit
        cache.get('b')  # Miss

        stats = cache.stats()
        self.assertEqual(stats['hits'], 1)
        self.assertEqual(stats['misses'], 1)
        self.assertEqual(stats['size'], 1)


class TestTTLCache(unittest.TestCase):
    """Test TTL cache functionality."""

    def test_fresh_value(self):
        """Test getting fresh value."""
        cache = TTLCache(ttl_seconds=1.0)

        cache.put('key', 'value')
        status, value = cache.get('key')

        self.assertEqual(status, 'hit')
        self.assertEqual(value, 'value')

    def test_stale_value(self):
        """Test getting stale value."""
        cache = TTLCache(ttl_seconds=0.1)

        cache.put('key', 'value')
        time.sleep(0.2)  # Wait for TTL to expire

        status, value = cache.get('key')
        self.assertEqual(status, 'stale')
        self.assertEqual(value, 'value')

    def test_miss(self):
        """Test cache miss."""
        cache = TTLCache(ttl_seconds=1.0)

        status, value = cache.get('nonexistent')
        self.assertEqual(status, 'miss')
        self.assertIsNone(value)


class TestMemoizeWithLRU(unittest.TestCase):
    """Test LRU memoization decorator."""

    def test_caching(self):
        """Test that results are cached."""
        call_count = [0]

        @memoize_with_lru(maxsize=10)
        def expensive_func(x):
            call_count[0] += 1
            return x * 2

        result1 = expensive_func(5)
        result2 = expensive_func(5)

        self.assertEqual(result1, 10)
        self.assertEqual(result2, 10)
        self.assertEqual(call_count[0], 1)  # Only called once

    def test_different_args(self):
        """Test that different args create different cache entries."""
        @memoize_with_lru(maxsize=10)
        def func(x):
            return x * 2

        result1 = func(5)
        result2 = func(10)

        self.assertEqual(result1, 10)
        self.assertEqual(result2, 20)

    def test_cache_stats(self):
        """Test cache statistics."""
        @memoize_with_lru(maxsize=10)
        def func(x):
            return x * 2

        func(5)
        func(5)
        func(10)

        stats = func.cache_stats()
        self.assertEqual(stats['hits'], 1)
        self.assertEqual(stats['misses'], 2)


class TestMemoizeWithTTL(unittest.TestCase):
    """Test TTL memoization decorator."""

    def test_caching(self):
        """Test that results are cached."""
        call_count = [0]

        @memoize_with_ttl(ttl_seconds=1.0)
        def func(x):
            call_count[0] += 1
            return x * 2

        result1 = func(5)
        result2 = func(5)

        self.assertEqual(result1, 10)
        self.assertEqual(result2, 10)
        self.assertEqual(call_count[0], 1)

    def test_stale_refresh(self):
        """Test that stale values are returned while refreshing."""
        call_count = [0]

        @memoize_with_ttl(ttl_seconds=0.1)
        def func(x):
            call_count[0] += 1
            return x * 2

        func(5)
        time.sleep(0.2)  # Wait for TTL to expire
        result = func(5)  # Should return stale value

        self.assertEqual(result, 10)
        # Function may or may not have been called again (race condition)


class TestAsyncTTLCache(unittest.TestCase):
    """Test async TTL cache functionality."""

    def test_basic_operations(self):
        """Test basic async cache operations."""
        async def run_test():
            cache = AsyncTTLCache(ttl_seconds=1.0)

            await cache.put('key', 'value')
            status, value = await cache.get('key')

            self.assertEqual(status, 'hit')
            self.assertEqual(value, 'value')

        asyncio.run(run_test())

    def test_get_or_compute(self):
        """Test get_or_compute with deduplication."""
        async def run_test():
            cache = AsyncTTLCache(ttl_seconds=1.0)
            call_count = [0]

            async def compute():
                call_count[0] += 1
                await asyncio.sleep(0.1)
                return 'computed'

            # Start two concurrent computations
            task1 = asyncio.create_task(cache.get_or_compute('key', compute))
            task2 = asyncio.create_task(cache.get_or_compute('key', compute))

            result1 = await task1
            result2 = await task2

            self.assertEqual(result1, 'computed')
            self.assertEqual(result2, 'computed')
            self.assertEqual(call_count[0], 1)  # Only computed once

        asyncio.run(run_test())


class TestMemoizeWithTTLAsync(unittest.TestCase):
    """Test async TTL memoization decorator."""

    def test_caching(self):
        """Test that async results are cached."""
        async def run_test():
            call_count = [0]

            @memoize_with_ttl_async(ttl_seconds=1.0)
            async def func(x):
                call_count[0] += 1
                await asyncio.sleep(0.01)
                return x * 2

            result1 = await func(5)
            result2 = await func(5)

            self.assertEqual(result1, 10)
            self.assertEqual(result2, 10)
            self.assertEqual(call_count[0], 1)

        asyncio.run(run_test())

    def test_deduplication(self):
        """Test in-flight deduplication."""
        async def run_test():
            call_count = [0]

            @memoize_with_ttl_async(ttl_seconds=1.0)
            async def func(x):
                call_count[0] += 1
                await asyncio.sleep(0.1)
                return x * 2

            # Start two concurrent calls
            task1 = asyncio.create_task(func(5))
            task2 = asyncio.create_task(func(5))

            result1 = await task1
            result2 = await task2

            self.assertEqual(result1, 10)
            self.assertEqual(result2, 10)
            self.assertEqual(call_count[0], 1)  # Only called once

        asyncio.run(run_test())


if __name__ == '__main__':
    unittest.main()
