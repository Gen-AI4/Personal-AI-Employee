"""
Error Recovery and Retry Logic for the AI Employee.

Provides a retry decorator with exponential backoff and error classification
for graceful degradation across all system components.

Gold tier requirement: Error recovery and graceful degradation.
"""

import time
import logging
from functools import wraps
from typing import Callable

logger = logging.getLogger(__name__)


class TransientError(Exception):
    """Errors that may succeed on retry (network timeouts, rate limits)."""
    pass


class AuthenticationError(Exception):
    """Errors from expired tokens or revoked access. Requires human intervention."""
    pass


class DataError(Exception):
    """Errors from corrupted files or missing required fields."""
    pass


# Map common exception types to our error categories
TRANSIENT_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,
    TransientError,
)


def classify_error(error: Exception) -> str:
    """Classify an error into a category for appropriate handling.

    Returns one of: 'transient', 'authentication', 'data', 'logic', 'system'
    """
    if isinstance(error, TransientError):
        return "transient"
    if isinstance(error, TRANSIENT_EXCEPTIONS):
        return "transient"
    if isinstance(error, AuthenticationError):
        return "authentication"
    if isinstance(error, DataError):
        return "data"
    if isinstance(error, (ValueError, TypeError, KeyError)):
        return "logic"
    return "system"


def with_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable_exceptions: tuple = TRANSIENT_EXCEPTIONS,
    on_retry: Callable | None = None,
):
    """Decorator that retries a function on transient failures with exponential backoff.

    Args:
        max_attempts: Maximum number of retry attempts (total calls = max_attempts).
        base_delay: Initial delay in seconds before first retry.
        max_delay: Maximum delay cap in seconds.
        retryable_exceptions: Tuple of exception types that trigger a retry.
        on_retry: Optional callback(attempt, error, delay) called before each retry.

    Returns:
        Decorator function.

    Example:
        @with_retry(max_attempts=3, base_delay=2)
        def fetch_data():
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_error = e
                    if attempt == max_attempts - 1:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {e}"
                        )
                        raise
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    logger.warning(
                        f"{func.__name__} attempt {attempt + 1}/{max_attempts} "
                        f"failed ({type(e).__name__}: {e}), retrying in {delay:.1f}s"
                    )
                    if on_retry:
                        on_retry(attempt, e, delay)
                    time.sleep(delay)
            raise last_error  # Should not reach here, but safety net
        return wrapper
    return decorator


class ErrorTracker:
    """Tracks error counts and rates for monitoring and circuit-breaking.

    Maintains a count of errors by category and supports checking
    whether a component should be temporarily disabled (circuit breaker).
    """

    def __init__(self, threshold: int = 5, window_seconds: float = 300.0):
        """
        Args:
            threshold: Number of errors within window to trigger circuit break.
            window_seconds: Time window in seconds for error counting.
        """
        self.threshold = threshold
        self.window_seconds = window_seconds
        self._errors: list[tuple[float, str]] = []  # (timestamp, category)
        self._total_errors = 0

    def record_error(self, category: str) -> None:
        """Record an error occurrence."""
        self._errors.append((time.time(), category))
        self._total_errors += 1
        # Prune old errors outside the window
        cutoff = time.time() - self.window_seconds
        self._errors = [(t, c) for t, c in self._errors if t > cutoff]

    def recent_error_count(self) -> int:
        """Count errors within the current time window."""
        cutoff = time.time() - self.window_seconds
        self._errors = [(t, c) for t, c in self._errors if t > cutoff]
        return len(self._errors)

    def should_circuit_break(self) -> bool:
        """Check if the error rate exceeds the threshold (circuit breaker)."""
        return self.recent_error_count() >= self.threshold

    @property
    def total_errors(self) -> int:
        """Total lifetime error count."""
        return self._total_errors

    def get_status(self) -> dict:
        """Return error tracker status for dashboard display."""
        return {
            "total_errors": self._total_errors,
            "recent_errors": self.recent_error_count(),
            "circuit_breaker": self.should_circuit_break(),
            "threshold": self.threshold,
            "window_seconds": self.window_seconds,
        }
