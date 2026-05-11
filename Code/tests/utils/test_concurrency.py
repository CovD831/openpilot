"""Unit tests for concurrency utilities."""

import asyncio
import time
import unittest
from threading import Thread

from src.utils.concurrency import (
    CancellationToken,
    create_child_cancel_token,
    sleep_with_cancel,
    async_sleep_with_cancel,
    with_timeout,
    with_timeout_async,
    sequential,
    sequential_async,
    RateLimiter,
    rate_limited,
    Debouncer,
    retry_with_backoff,
)


class TestCancellationToken(unittest.TestCase):
    """Test cancellation token."""

    def test_basic_cancellation(self):
        """Test basic cancellation."""
        token = CancellationToken()
        self.assertFalse(token.is_cancelled())

        token.cancel()
        self.assertTrue(token.is_cancelled())

    def test_parent_child_cancellation(self):
        """Test parent-child cancellation."""
        parent = CancellationToken()
        child = create_child_cancel_token(parent)

        self.assertFalse(child.is_cancelled())

        parent.cancel()
        self.assertTrue(child.is_cancelled())

    def test_child_cancel_not_parent(self):
        """Test child cancellation doesn't affect parent."""
        parent = CancellationToken()
        child = create_child_cancel_token(parent)

        child.cancel()
        self.assertTrue(child.is_cancelled())
        self.assertFalse(parent.is_cancelled())


class TestSleepWithCancel(unittest.TestCase):
    """Test cancellable sleep."""

    def test_complete_sleep(self):
        """Test sleep completes normally."""
        token = CancellationToken()
        result = sleep_with_cancel(0.1, token)
        self.assertTrue(result)

    def test_cancelled_sleep(self):
        """Test sleep is cancelled."""
        token = CancellationToken()

        def cancel_after():
            time.sleep(0.05)
            token.cancel()

        Thread(target=cancel_after, daemon=True).start()

        result = sleep_with_cancel(1.0, token)
        self.assertFalse(result)


class TestAsyncSleepWithCancel(unittest.TestCase):
    """Test async cancellable sleep."""

    def test_complete_sleep(self):
        """Test async sleep completes normally."""
        async def run_test():
            token = CancellationToken()
            result = await async_sleep_with_cancel(0.1, token)
            self.assertTrue(result)

        asyncio.run(run_test())

    def test_cancelled_sleep(self):
        """Test async sleep is cancelled."""
        async def run_test():
            token = CancellationToken()

            async def cancel_after():
                await asyncio.sleep(0.05)
                token.cancel()

            asyncio.create_task(cancel_after())

            result = await async_sleep_with_cancel(1.0, token)
            self.assertFalse(result)

        asyncio.run(run_test())


class TestWithTimeout(unittest.TestCase):
    """Test timeout decorator."""

    def test_completes_in_time(self):
        """Test function completes within timeout."""
        @with_timeout(timeout_seconds=1.0)
        def fast_func():
            time.sleep(0.1)
            return 'done'

        result = fast_func()
        self.assertEqual(result, 'done')

    def test_timeout_exceeded(self):
        """Test function exceeds timeout."""
        @with_timeout(timeout_seconds=0.1, error_msg="Too slow")
        def slow_func():
            time.sleep(1.0)
            return 'done'

        with self.assertRaises(TimeoutError) as cm:
            slow_func()

        self.assertIn("Too slow", str(cm.exception))


class TestWithTimeoutAsync(unittest.TestCase):
    """Test async timeout decorator."""

    def test_completes_in_time(self):
        """Test async function completes within timeout."""
        async def run_test():
            @with_timeout_async(timeout_seconds=1.0)
            async def fast_func():
                await asyncio.sleep(0.1)
                return 'done'

            result = await fast_func()
            self.assertEqual(result, 'done')

        asyncio.run(run_test())

    def test_timeout_exceeded(self):
        """Test async function exceeds timeout."""
        async def run_test():
            @with_timeout_async(timeout_seconds=0.1, error_msg="Too slow")
            async def slow_func():
                await asyncio.sleep(1.0)
                return 'done'

            with self.assertRaises(TimeoutError):
                await slow_func()

        asyncio.run(run_test())


class TestSequential(unittest.TestCase):
    """Test sequential execution decorator."""

    def test_sequential_execution(self):
        """Test that calls execute sequentially."""
        results = []

        @sequential
        def func(value):
            results.append(f'start-{value}')
            time.sleep(0.1)
            results.append(f'end-{value}')

        # Start two threads
        t1 = Thread(target=lambda: func(1))
        t2 = Thread(target=lambda: func(2))

        t1.start()
        time.sleep(0.01)  # Ensure t1 starts first
        t2.start()

        t1.join()
        t2.join()

        # Should be sequential: start-1, end-1, start-2, end-2
        self.assertEqual(results[0], 'start-1')
        self.assertEqual(results[1], 'end-1')
        self.assertEqual(results[2], 'start-2')
        self.assertEqual(results[3], 'end-2')


class TestSequentialAsync(unittest.TestCase):
    """Test async sequential execution decorator."""

    def test_sequential_execution(self):
        """Test that async calls execute sequentially."""
        async def run_test():
            results = []

            @sequential_async
            async def func(value):
                results.append(f'start-{value}')
                await asyncio.sleep(0.1)
                results.append(f'end-{value}')

            # Start two concurrent tasks
            task1 = asyncio.create_task(func(1))
            await asyncio.sleep(0.01)  # Ensure task1 starts first
            task2 = asyncio.create_task(func(2))

            await task1
            await task2

            # Should be sequential
            self.assertEqual(results[0], 'start-1')
            self.assertEqual(results[1], 'end-1')
            self.assertEqual(results[2], 'start-2')
            self.assertEqual(results[3], 'end-2')

        asyncio.run(run_test())


class TestRateLimiter(unittest.TestCase):
    """Test rate limiter."""

    def test_within_limit(self):
        """Test calls within rate limit."""
        limiter = RateLimiter(max_calls=5, time_window=1.0)

        for _ in range(5):
            result = limiter.acquire(blocking=False)
            self.assertTrue(result)

    def test_exceeds_limit(self):
        """Test calls exceed rate limit."""
        limiter = RateLimiter(max_calls=2, time_window=1.0)

        limiter.acquire(blocking=False)
        limiter.acquire(blocking=False)

        # Third call should fail
        result = limiter.acquire(blocking=False)
        self.assertFalse(result)


class TestRateLimited(unittest.TestCase):
    """Test rate limited decorator."""

    def test_rate_limiting(self):
        """Test function is rate limited."""
        call_count = [0]

        @rate_limited(max_calls=2, time_window=1.0)
        def func():
            call_count[0] += 1

        func()
        func()

        # Should succeed
        self.assertEqual(call_count[0], 2)


class TestDebouncer(unittest.TestCase):
    """Test debouncer."""

    def test_debouncing(self):
        """Test function is debounced."""
        results = []

        def func(value):
            results.append(value)

        debouncer = Debouncer(wait_seconds=0.1)

        # Rapid calls
        debouncer.debounce(func, 1)
        debouncer.debounce(func, 2)
        debouncer.debounce(func, 3)

        # Wait for debounce
        time.sleep(0.2)

        # Only last call should execute
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0], 3)


class TestRetryWithBackoff(unittest.TestCase):
    """Test retry with backoff decorator."""

    def test_succeeds_first_try(self):
        """Test function succeeds on first try."""
        call_count = [0]

        @retry_with_backoff(max_retries=3, initial_delay=0.1)
        def func():
            call_count[0] += 1
            return 'success'

        result = func()
        self.assertEqual(result, 'success')
        self.assertEqual(call_count[0], 1)

    def test_succeeds_after_retries(self):
        """Test function succeeds after retries."""
        call_count = [0]

        @retry_with_backoff(max_retries=3, initial_delay=0.1)
        def func():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("Not yet")
            return 'success'

        result = func()
        self.assertEqual(result, 'success')
        self.assertEqual(call_count[0], 3)

    def test_fails_after_max_retries(self):
        """Test function fails after max retries."""
        call_count = [0]

        @retry_with_backoff(max_retries=2, initial_delay=0.1)
        def func():
            call_count[0] += 1
            raise ValueError("Always fails")

        with self.assertRaises(ValueError):
            func()

        self.assertEqual(call_count[0], 3)  # Initial + 2 retries


if __name__ == '__main__':
    unittest.main()
