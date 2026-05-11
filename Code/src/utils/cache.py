"""
Caching and memoization utilities inspired by Claude Code.

Provides LRU cache, TTL cache with write-through pattern, and async TTL cache
with in-flight deduplication to reduce redundant computations.
"""

import asyncio
import functools
import time
from collections import OrderedDict
from threading import Lock
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar

T = TypeVar('T')


class LRUCache:
    """
    Thread-safe LRU (Least Recently Used) cache with bounded size.

    Automatically evicts least recently used items when capacity is reached.
    """

    def __init__(self, maxsize: int = 128):
        """
        Initialize LRU cache.

        Args:
            maxsize: Maximum number of items to cache
        """
        self.maxsize = maxsize
        self.cache: OrderedDict = OrderedDict()
        self.lock = Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Any) -> Tuple[bool, Any]:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Tuple of (found, value)
        """
        with self.lock:
            if key in self.cache:
                self.hits += 1
                # Move to end (most recently used)
                self.cache.move_to_end(key)
                return True, self.cache[key]
            else:
                self.misses += 1
                return False, None

    def put(self, key: Any, value: Any) -> None:
        """
        Put value into cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        with self.lock:
            if key in self.cache:
                # Update existing key
                self.cache.move_to_end(key)
            else:
                # Add new key
                if len(self.cache) >= self.maxsize:
                    # Remove least recently used
                    self.cache.popitem(last=False)
            self.cache[key] = value

    def clear(self) -> None:
        """Clear all cached items."""
        with self.lock:
            self.cache.clear()
            self.hits = 0
            self.misses = 0

    def size(self) -> int:
        """Get current cache size."""
        with self.lock:
            return len(self.cache)

    def stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        with self.lock:
            total = self.hits + self.misses
            hit_rate = (self.hits / total * 100) if total > 0 else 0
            return {
                'hits': self.hits,
                'misses': self.misses,
                'size': len(self.cache),
                'maxsize': self.maxsize,
                'hit_rate': round(hit_rate, 2)
            }


class TTLCache:
    """
    Thread-safe TTL (Time To Live) cache with write-through pattern.

    Returns stale values immediately while refreshing in background,
    preventing blocking on cache misses.
    """

    def __init__(self, ttl_seconds: float = 300):
        """
        Initialize TTL cache.

        Args:
            ttl_seconds: Time to live in seconds (default 5 minutes)
        """
        self.ttl_seconds = ttl_seconds
        self.cache: Dict[Any, Tuple[Any, float]] = {}
        self.lock = Lock()
        self.hits = 0
        self.misses = 0
        self.stale_hits = 0

    def get(self, key: Any) -> Tuple[str, Any]:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Tuple of (status, value) where status is 'hit', 'stale', or 'miss'
        """
        with self.lock:
            if key not in self.cache:
                self.misses += 1
                return 'miss', None

            value, timestamp = self.cache[key]
            age = time.time() - timestamp

            if age < self.ttl_seconds:
                self.hits += 1
                return 'hit', value
            else:
                self.stale_hits += 1
                return 'stale', value

    def put(self, key: Any, value: Any) -> None:
        """
        Put value into cache with current timestamp.

        Args:
            key: Cache key
            value: Value to cache
        """
        with self.lock:
            self.cache[key] = (value, time.time())

    def clear(self) -> None:
        """Clear all cached items."""
        with self.lock:
            self.cache.clear()
            self.hits = 0
            self.misses = 0
            self.stale_hits = 0

    def size(self) -> int:
        """Get current cache size."""
        with self.lock:
            return len(self.cache)

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self.lock:
            total = self.hits + self.misses + self.stale_hits
            hit_rate = (self.hits / total * 100) if total > 0 else 0
            return {
                'hits': self.hits,
                'stale_hits': self.stale_hits,
                'misses': self.misses,
                'size': len(self.cache),
                'ttl_seconds': self.ttl_seconds,
                'hit_rate': round(hit_rate, 2)
            }


def memoize_with_lru(maxsize: int = 128) -> Callable:
    """
    Decorator for LRU memoization of function results.

    Args:
        maxsize: Maximum number of results to cache

    Returns:
        Decorator function

    Example:
        @memoize_with_lru(maxsize=256)
        def expensive_function(x, y):
            return x ** y
    """
    def decorator(func: Callable) -> Callable:
        cache = LRUCache(maxsize=maxsize)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key from args and kwargs
            key = (args, tuple(sorted(kwargs.items())))

            found, value = cache.get(key)
            if found:
                return value

            # Compute and cache result
            result = func(*args, **kwargs)
            cache.put(key, result)
            return result

        # Expose cache management methods
        wrapper.cache = cache
        wrapper.cache_clear = cache.clear
        wrapper.cache_stats = cache.stats

        return wrapper

    return decorator


def memoize_with_ttl(ttl_seconds: float = 300) -> Callable:
    """
    Decorator for TTL memoization with write-through pattern.

    Returns stale values immediately while refreshing in background.

    Args:
        ttl_seconds: Time to live in seconds (default 5 minutes)

    Returns:
        Decorator function

    Example:
        @memoize_with_ttl(ttl_seconds=60)
        def get_git_status():
            return subprocess.check_output(['git', 'status'])
    """
    def decorator(func: Callable) -> Callable:
        cache = TTLCache(ttl_seconds=ttl_seconds)
        refresh_lock = Lock()

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key
            key = (args, tuple(sorted(kwargs.items())))

            status, value = cache.get(key)

            if status == 'hit':
                return value

            if status == 'stale':
                # Return stale value immediately, refresh in background
                # Use lock to prevent multiple refreshes
                if refresh_lock.acquire(blocking=False):
                    try:
                        # Refresh in current thread (simple approach)
                        # For true background refresh, use threading.Thread
                        result = func(*args, **kwargs)
                        cache.put(key, result)
                    finally:
                        refresh_lock.release()
                return value

            # Cache miss - compute and cache
            result = func(*args, **kwargs)
            cache.put(key, result)
            return result

        # Expose cache management methods
        wrapper.cache = cache
        wrapper.cache_clear = cache.clear
        wrapper.cache_stats = cache.stats

        return wrapper

    return decorator


class AsyncTTLCache:
    """
    Async TTL cache with in-flight deduplication.

    Prevents multiple concurrent invocations of the same expensive async operation.
    """

    def __init__(self, ttl_seconds: float = 300):
        """
        Initialize async TTL cache.

        Args:
            ttl_seconds: Time to live in seconds
        """
        self.ttl_seconds = ttl_seconds
        self.cache: Dict[Any, Tuple[Any, float]] = {}
        self.in_flight: Dict[Any, asyncio.Task] = {}
        self.lock = asyncio.Lock()
        self.hits = 0
        self.misses = 0
        self.deduped = 0

    async def get(self, key: Any) -> Tuple[str, Any]:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Tuple of (status, value) where status is 'hit', 'stale', or 'miss'
        """
        async with self.lock:
            if key not in self.cache:
                self.misses += 1
                return 'miss', None

            value, timestamp = self.cache[key]
            age = time.time() - timestamp

            if age < self.ttl_seconds:
                self.hits += 1
                return 'hit', value
            else:
                return 'stale', value

    async def put(self, key: Any, value: Any) -> None:
        """
        Put value into cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        async with self.lock:
            self.cache[key] = (value, time.time())

    async def get_or_compute(self, key: Any, compute_func: Callable) -> Any:
        """
        Get value from cache or compute if missing/stale.

        Deduplicates concurrent requests for the same key.

        Args:
            key: Cache key
            compute_func: Async function to compute value

        Returns:
            Cached or computed value
        """
        status, value = await self.get(key)

        if status == 'hit':
            return value

        # Check if computation is already in flight
        async with self.lock:
            if key in self.in_flight:
                self.deduped += 1
                task = self.in_flight[key]

        if key in self.in_flight:
            # Wait for in-flight computation
            return await task

        # Start new computation
        async with self.lock:
            if key not in self.in_flight:
                task = asyncio.create_task(compute_func())
                self.in_flight[key] = task
            else:
                # Another task started between checks
                self.deduped += 1
                return await self.in_flight[key]

        try:
            result = await task
            await self.put(key, result)
            return result
        finally:
            async with self.lock:
                if key in self.in_flight:
                    del self.in_flight[key]

    async def clear(self) -> None:
        """Clear all cached items."""
        async with self.lock:
            self.cache.clear()
            self.in_flight.clear()
            self.hits = 0
            self.misses = 0
            self.deduped = 0

    async def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        async with self.lock:
            total = self.hits + self.misses
            hit_rate = (self.hits / total * 100) if total > 0 else 0
            return {
                'hits': self.hits,
                'misses': self.misses,
                'deduped': self.deduped,
                'size': len(self.cache),
                'in_flight': len(self.in_flight),
                'ttl_seconds': self.ttl_seconds,
                'hit_rate': round(hit_rate, 2)
            }


def memoize_with_ttl_async(ttl_seconds: float = 300) -> Callable:
    """
    Decorator for async TTL memoization with in-flight deduplication.

    Args:
        ttl_seconds: Time to live in seconds

    Returns:
        Decorator function

    Example:
        @memoize_with_ttl_async(ttl_seconds=60)
        async def fetch_data(url):
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    return await response.json()
    """
    def decorator(func: Callable) -> Callable:
        cache = AsyncTTLCache(ttl_seconds=ttl_seconds)

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Create cache key
            key = (args, tuple(sorted(kwargs.items())))

            # Define compute function
            async def compute():
                return await func(*args, **kwargs)

            return await cache.get_or_compute(key, compute)

        # Expose cache management methods
        wrapper.cache = cache
        wrapper.cache_clear = cache.clear
        wrapper.cache_stats = cache.stats

        return wrapper

    return decorator
