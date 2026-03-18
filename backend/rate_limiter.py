"""
Leaky bucket rate limiter for HTTP scraping pipelines.

Provides a reusable, async-safe rate limiter that enforces a maximum
request rate with burst capacity. Can be used as a context manager
or directly with acquire/release.

Usage:
    limiter = LeakyBucket(rate=2.0, burst=3)  # 2 req/sec, burst of 3

    async with limiter:
        await client.get(url)

    # Or in a pipeline:
    pipeline = ScrapePipeline(rate=1.5, burst=2, max_retries=3)
    results = await pipeline.run(tasks, worker_fn, concurrency=4)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class LeakyBucket:
    """
    Async leaky bucket rate limiter.

    Tokens drain at a fixed rate. Each request consumes one token.
    If no tokens are available, the caller waits until one drains.

    Args:
        rate: Tokens per second (e.g., 2.0 = 2 requests/sec)
        burst: Maximum burst capacity (tokens can accumulate up to this)
    """

    def __init__(self, rate: float = 1.0, burst: int = 1):
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self):
        """Add tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
        self._last_refill = now

    async def acquire(self):
        """Wait until a token is available, then consume it."""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # Calculate wait time for next token
                wait = (1.0 - self._tokens) / self.rate
            await asyncio.sleep(wait)

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *exc):
        pass

    @property
    def available_tokens(self) -> float:
        self._refill()
        return self._tokens


@dataclass
class TaskResult:
    """Result of a pipeline task."""
    task_id: str
    success: bool
    data: Any = None
    error: str | None = None
    attempts: int = 0
    elapsed_ms: float = 0


@dataclass
class PipelineStats:
    """Aggregate stats for a pipeline run."""
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    retried: int = 0
    total_elapsed_ms: float = 0
    errors: dict[str, int] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        return self.succeeded / self.total if self.total else 0

    def summary(self) -> str:
        return (
            f"{self.succeeded}/{self.total} succeeded "
            f"({self.success_rate:.0%}), "
            f"{self.failed} failed, {self.retried} retries, "
            f"{self.total_elapsed_ms / 1000:.1f}s total"
        )


class ScrapePipeline:
    """
    Rate-limited async scraping pipeline with retries and progress tracking.

    Runs a batch of tasks through a worker function, enforcing rate limits
    and retrying on failure with exponential backoff.

    Args:
        rate: Requests per second
        burst: Burst capacity for the rate limiter
        max_retries: Max retry attempts per task (0 = no retries)
        backoff_base: Base delay for exponential backoff (seconds)
        timeout: Per-task timeout in seconds
    """

    def __init__(
        self,
        rate: float = 1.5,
        burst: int = 2,
        max_retries: int = 3,
        backoff_base: float = 2.0,
        timeout: float = 30.0,
    ):
        self.limiter = LeakyBucket(rate=rate, burst=burst)
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.timeout = timeout
        self.stats = PipelineStats()
        self._progress_callback: Callable[[int, int, str], None] | None = None

    def on_progress(self, callback: Callable[[int, int, str], None]):
        """Set a progress callback: fn(completed, total, task_id)."""
        self._progress_callback = callback

    async def _run_task(
        self,
        task_id: str,
        task_data: Any,
        worker: Callable[..., Coroutine],
        semaphore: asyncio.Semaphore,
    ) -> TaskResult:
        """Run a single task with rate limiting, retries, and timeout."""
        attempts = 0

        for attempt in range(self.max_retries + 1):
            attempts = attempt + 1
            start = time.monotonic()

            try:
                # Wait for rate limit token
                await self.limiter.acquire()

                # Acquire concurrency slot
                async with semaphore:
                    result = await asyncio.wait_for(
                        worker(task_id, task_data),
                        timeout=self.timeout,
                    )
                    elapsed = (time.monotonic() - start) * 1000

                    return TaskResult(
                        task_id=task_id,
                        success=True,
                        data=result,
                        attempts=attempts,
                        elapsed_ms=elapsed,
                    )

            except asyncio.TimeoutError:
                elapsed = (time.monotonic() - start) * 1000
                error = f"Timeout after {self.timeout}s"
                logger.warning(f"[{task_id}] {error} (attempt {attempts})")

            except Exception as e:
                elapsed = (time.monotonic() - start) * 1000
                error = str(e)
                logger.warning(f"[{task_id}] {error} (attempt {attempts})")

            # Retry with exponential backoff
            if attempt < self.max_retries:
                delay = self.backoff_base ** attempt
                logger.info(f"[{task_id}] Retrying in {delay:.1f}s...")
                self.stats.retried += 1
                await asyncio.sleep(delay)

        return TaskResult(
            task_id=task_id,
            success=False,
            error=error,
            attempts=attempts,
            elapsed_ms=elapsed,
        )

    async def run(
        self,
        tasks: dict[str, Any],
        worker: Callable[..., Coroutine],
        concurrency: int = 3,
    ) -> dict[str, TaskResult]:
        """
        Run all tasks through the pipeline.

        Args:
            tasks: Dict of task_id -> task_data
            worker: Async function(task_id, task_data) -> result
            concurrency: Max concurrent tasks (independent of rate limit)

        Returns:
            Dict of task_id -> TaskResult
        """
        self.stats = PipelineStats(total=len(tasks))
        semaphore = asyncio.Semaphore(concurrency)
        completed = 0

        async def tracked_task(task_id, task_data):
            nonlocal completed
            result = await self._run_task(task_id, task_data, worker, semaphore)
            completed += 1

            if result.success:
                self.stats.succeeded += 1
            else:
                self.stats.failed += 1
                err_key = result.error or "unknown"
                self.stats.errors[err_key] = self.stats.errors.get(err_key, 0) + 1

            self.stats.total_elapsed_ms += result.elapsed_ms

            if self._progress_callback:
                self._progress_callback(completed, len(tasks), task_id)

            return task_id, result

        # Launch all tasks
        coros = [tracked_task(tid, tdata) for tid, tdata in tasks.items()]
        pairs = await asyncio.gather(*coros, return_exceptions=True)

        results = {}
        for item in pairs:
            if isinstance(item, Exception):
                logger.error(f"Pipeline task raised: {item}")
                continue
            task_id, result = item
            results[task_id] = result

        logger.info(f"Pipeline complete: {self.stats.summary()}")
        return results
