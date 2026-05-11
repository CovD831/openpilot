"""
Concurrency control utilities inspired by Claude Code.

Provides sequential execution decorator, cancellable sleep, timeout management,
and hierarchical cancellation tokens for async operations.
"""

import asyncio
import functools
import threading
import time
from typing import Any, Callable, Optional, TypeVar

T = TypeVar('T')


class CancellationToken:
    """
    Cancellation token for cooperative cancellation.

    Similar to threading.Event but with parent-child relationships.
    """

    def __init__(self, parent: Optional['CancellationToken'] = None):
        """
        Initialize cancellation token.

        Args:
            parent: Parent token (child cancels when parent cancels)
        """
        self._cancelled = threading.Event()
        self._parent = parent
        self._children = []

        if parent:
            parent._children.append(self)
            # If parent already cancelled, cancel immediately
            if parent.is_cancelled():
                self.cancel()

    def cancel(self) -> None:
        """Cancel this token and all children."""
        if not self._cancelled.is_set():
            self._cancelled.set()

            # Cancel all children
            for child in self._children:
                child.cancel()

    def is_cancelled(self) -> bool:
        """Check if token is cancelled."""
        if self._cancelled.is_set():
            return True

        # Check parent
        if self._parent and self._parent.is_cancelled():
            self.cancel()
            return True

        return False

    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for cancellation.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            True if cancelled, False if timeout
        """
        return self._cancelled.wait(timeout=timeout)

    def throw_if_cancelled(self, error_class: type = RuntimeError) -> None:
        """
        Raise exception if cancelled.

        Args:
            error_class: Exception class to raise
        """
        if self.is_cancelled():
            raise error_class("Operation cancelled")


def create_child_cancel_token(parent: Optional[CancellationToken] = None) -> CancellationToken:
    """
    Create child cancellation token.

    Child cancels when parent cancels, but not vice versa.

    Args:
        parent: Parent token

    Returns:
        Child cancellation token

    Example:
        >>> parent = CancellationToken()
        >>> child = create_child_cancel_token(parent)
        >>> parent.cancel()
        >>> child.is_cancelled()
        True
    """
    return CancellationToken(parent=parent)


def sleep_with_cancel(
    seconds: float,
    cancel_token: Optional[CancellationToken] = None,
    check_interval: float = 0.1
) -> bool:
    """
    Sleep with cancellation support.

    Args:
        seconds: Time to sleep in seconds
        cancel_token: Cancellation token to check
        check_interval: How often to check cancellation

    Returns:
        True if completed, False if cancelled

    Example:
        >>> token = CancellationToken()
        >>> sleep_with_cancel(5.0, token)
        True
    """
    if cancel_token is None:
        time.sleep(seconds)
        return True

    elapsed = 0.0
    while elapsed < seconds:
        if cancel_token.is_cancelled():
            return False

        sleep_time = min(check_interval, seconds - elapsed)
        time.sleep(sleep_time)
        elapsed += sleep_time

    return True


async def async_sleep_with_cancel(
    seconds: float,
    cancel_token: Optional[CancellationToken] = None,
    check_interval: float = 0.1
) -> bool:
    """
    Async sleep with cancellation support.

    Args:
        seconds: Time to sleep in seconds
        cancel_token: Cancellation token to check
        check_interval: How often to check cancellation

    Returns:
        True if completed, False if cancelled

    Example:
        >>> token = CancellationToken()
        >>> await async_sleep_with_cancel(5.0, token)
        True
    """
    if cancel_token is None:
        await asyncio.sleep(seconds)
        return True

    elapsed = 0.0
    while elapsed < seconds:
        if cancel_token.is_cancelled():
            return False

        sleep_time = min(check_interval, seconds - elapsed)
        await asyncio.sleep(sleep_time)
        elapsed += sleep_time

    return True


def with_timeout(timeout_seconds: float, error_msg: str = "Operation timed out") -> Callable:
    """
    Decorator to add timeout to function.

    Args:
        timeout_seconds: Timeout in seconds
        error_msg: Error message if timeout

    Returns:
        Decorator function

    Example:
        @with_timeout(timeout_seconds=30, error_msg="Function took too long")
        def slow_function():
            time.sleep(60)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = [None]
            exception = [None]

            def target():
                try:
                    result[0] = func(*args, **kwargs)
                except Exception as e:
                    exception[0] = e

            thread = threading.Thread(target=target)
            thread.daemon = True
            thread.start()
            thread.join(timeout=timeout_seconds)

            if thread.is_alive():
                # Timeout occurred
                raise TimeoutError(error_msg)

            if exception[0]:
                raise exception[0]

            return result[0]

        return wrapper

    return decorator


def with_timeout_async(timeout_seconds: float, error_msg: str = "Operation timed out") -> Callable:
    """
    Decorator to add timeout to async function.

    Args:
        timeout_seconds: Timeout in seconds
        error_msg: Error message if timeout

    Returns:
        Decorator function

    Example:
        @with_timeout_async(timeout_seconds=30)
        async def slow_async_function():
            await asyncio.sleep(60)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                raise TimeoutError(error_msg)

        return wrapper

    return decorator


def sequential(func: Callable) -> Callable:
    """
    Decorator to force sequential execution of function.

    Prevents race conditions by ensuring only one invocation runs at a time.
    Queues subsequent calls and processes them in order.

    Args:
        func: Function to wrap

    Returns:
        Wrapped function

    Example:
        @sequential
        def write_to_file(data):
            with open('output.txt', 'a') as f:
                f.write(data)
    """
    lock = threading.Lock()

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with lock:
            return func(*args, **kwargs)

    return wrapper


def sequential_async(func: Callable) -> Callable:
    """
    Decorator to force sequential execution of async function.

    Args:
        func: Async function to wrap

    Returns:
        Wrapped async function

    Example:
        @sequential_async
        async def write_to_file(data):
            async with aiofiles.open('output.txt', 'a') as f:
                await f.write(data)
    """
    lock = asyncio.Lock()

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        async with lock:
            return await func(*args, **kwargs)

    return wrapper


class RateLimiter:
    """
    Rate limiter for controlling operation frequency.

    Uses token bucket algorithm.
    """

    def __init__(self, max_calls: int, time_window: float):
        """
        Initialize rate limiter.

        Args:
            max_calls: Maximum calls allowed in time window
            time_window: Time window in seconds
        """
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = []
        self.lock = threading.Lock()

    def acquire(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        """
        Acquire permission to make a call.

        Args:
            blocking: Wait if rate limit exceeded
            timeout: Maximum time to wait

        Returns:
            True if acquired, False if rate limit exceeded

        Example:
            >>> limiter = RateLimiter(max_calls=10, time_window=60)
            >>> if limiter.acquire():
            ...     make_api_call()
        """
        start_time = time.time()

        while True:
            with self.lock:
                now = time.time()

                # Remove old calls outside time window
                self.calls = [t for t in self.calls if now - t < self.time_window]

                # Check if we can make a call
                if len(self.calls) < self.max_calls:
                    self.calls.append(now)
                    return True

            if not blocking:
                return False

            if timeout is not None:
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    return False

            # Wait a bit before retrying
            time.sleep(0.1)

    def __enter__(self):
        """Context manager support."""
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager support."""
        pass


def rate_limited(max_calls: int, time_window: float) -> Callable:
    """
    Decorator to rate limit function calls.

    Args:
        max_calls: Maximum calls allowed in time window
        time_window: Time window in seconds

    Returns:
        Decorator function

    Example:
        @rate_limited(max_calls=10, time_window=60)
        def api_call():
            return requests.get('https://api.example.com')
    """
    limiter = RateLimiter(max_calls=max_calls, time_window=time_window)

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            limiter.acquire()
            return func(*args, **kwargs)

        return wrapper

    return decorator


class Debouncer:
    """
    Debouncer for delaying function execution until calls stop.

    Useful for handling rapid successive calls (e.g., user input).
    """

    def __init__(self, wait_seconds: float):
        """
        Initialize debouncer.

        Args:
            wait_seconds: Time to wait after last call
        """
        self.wait_seconds = wait_seconds
        self.timer = None
        self.lock = threading.Lock()

    def debounce(self, func: Callable, *args, **kwargs) -> None:
        """
        Debounce function call.

        Args:
            func: Function to call
            *args: Function arguments
            **kwargs: Function keyword arguments

        Example:
            >>> debouncer = Debouncer(wait_seconds=0.5)
            >>> debouncer.debounce(save_file, data)
        """
        with self.lock:
            # Cancel previous timer
            if self.timer:
                self.timer.cancel()

            # Start new timer
            self.timer = threading.Timer(
                self.wait_seconds,
                func,
                args=args,
                kwargs=kwargs
            )
            self.timer.start()

    def cancel(self) -> None:
        """Cancel pending debounced call."""
        with self.lock:
            if self.timer:
                self.timer.cancel()
                self.timer = None


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 60.0,
    retryable_exceptions: tuple = (Exception,)
) -> Callable:
    """
    Decorator to retry function with exponential backoff.

    Args:
        max_retries: Maximum number of retries
        initial_delay: Initial delay in seconds
        backoff_factor: Multiplier for delay after each retry
        max_delay: Maximum delay between retries
        retryable_exceptions: Tuple of exceptions to retry on

    Returns:
        Decorator function

    Example:
        @retry_with_backoff(max_retries=3, initial_delay=1.0)
        def unstable_api_call():
            return requests.get('https://api.example.com')
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e

                    if attempt < max_retries:
                        time.sleep(delay)
                        delay = min(delay * backoff_factor, max_delay)
                    else:
                        # Last attempt failed
                        raise

            # Should not reach here, but just in case
            if last_exception:
                raise last_exception

        return wrapper

    return decorator
