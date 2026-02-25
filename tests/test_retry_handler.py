"""Tests for the retry handler module (Gold tier)."""

import time
import pytest
from unittest.mock import MagicMock, patch

from retry_handler import (
    with_retry,
    ErrorTracker,
    classify_error,
    TransientError,
    AuthenticationError,
    DataError,
    TRANSIENT_EXCEPTIONS,
)


# --- classify_error ---


class TestClassifyError:
    """Tests for error classification."""

    def test_classify_transient_error(self):
        assert classify_error(TransientError("timeout")) == "transient"

    def test_classify_connection_error(self):
        assert classify_error(ConnectionError("failed")) == "transient"

    def test_classify_timeout_error(self):
        assert classify_error(TimeoutError("timed out")) == "transient"

    def test_classify_os_error(self):
        assert classify_error(OSError("disk full")) == "transient"

    def test_classify_authentication_error(self):
        assert classify_error(AuthenticationError("token expired")) == "authentication"

    def test_classify_data_error(self):
        assert classify_error(DataError("bad data")) == "data"

    def test_classify_value_error(self):
        assert classify_error(ValueError("invalid")) == "logic"

    def test_classify_type_error(self):
        assert classify_error(TypeError("wrong type")) == "logic"

    def test_classify_key_error(self):
        assert classify_error(KeyError("missing")) == "logic"

    def test_classify_generic_exception(self):
        assert classify_error(RuntimeError("crash")) == "system"


# --- with_retry decorator ---


class TestWithRetry:
    """Tests for the with_retry decorator."""

    def test_success_on_first_try(self):
        call_count = 0

        @with_retry(max_attempts=3)
        def func():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = func()
        assert result == "ok"
        assert call_count == 1

    def test_retries_on_transient_error(self):
        call_count = 0

        @with_retry(max_attempts=3, base_delay=0.01)
        def func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "ok"

        result = func()
        assert result == "ok"
        assert call_count == 3

    def test_raises_after_max_attempts(self):
        @with_retry(max_attempts=3, base_delay=0.01)
        def func():
            raise ConnectionError("always fails")

        with pytest.raises(ConnectionError):
            func()

    def test_does_not_retry_non_transient(self):
        call_count = 0

        @with_retry(max_attempts=3, base_delay=0.01)
        def func():
            nonlocal call_count
            call_count += 1
            raise ValueError("not transient")

        with pytest.raises(ValueError):
            func()
        # Only 1 attempt since ValueError is not in retryable exceptions
        assert call_count == 1

    def test_respects_max_delay(self):
        delays = []

        def capture_retry(attempt, error, delay):
            delays.append(delay)

        @with_retry(max_attempts=3, base_delay=100, max_delay=5.0, on_retry=capture_retry)
        def func():
            raise ConnectionError("fail")

        with pytest.raises(ConnectionError):
            func()

        # All delays should be capped at max_delay
        for d in delays:
            assert d <= 5.0

    def test_exponential_backoff(self):
        delays = []

        def capture_retry(attempt, error, delay):
            delays.append(delay)

        @with_retry(max_attempts=4, base_delay=1.0, max_delay=100.0, on_retry=capture_retry)
        def func():
            raise ConnectionError("fail")

        with pytest.raises(ConnectionError):
            func()

        # Delays should be 1.0, 2.0, 4.0 (exponential)
        assert len(delays) == 3
        assert delays[0] == 1.0
        assert delays[1] == 2.0
        assert delays[2] == 4.0

    def test_on_retry_callback_called(self):
        retry_calls = []

        def on_retry(attempt, error, delay):
            retry_calls.append((attempt, type(error).__name__, delay))

        @with_retry(max_attempts=3, base_delay=0.01, on_retry=on_retry)
        def func():
            raise ConnectionError("fail")

        with pytest.raises(ConnectionError):
            func()

        assert len(retry_calls) == 2  # 2 retries before final failure
        assert retry_calls[0][0] == 0  # attempt 0
        assert retry_calls[0][1] == "ConnectionError"

    def test_preserves_function_name(self):
        @with_retry(max_attempts=3)
        def my_function():
            pass

        assert my_function.__name__ == "my_function"

    def test_custom_retryable_exceptions(self):
        call_count = 0

        @with_retry(max_attempts=3, base_delay=0.01, retryable_exceptions=(ValueError,))
        def func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("retry this")
            return "ok"

        result = func()
        assert result == "ok"
        assert call_count == 3

    def test_success_returns_result(self):
        @with_retry()
        def func():
            return {"status": "success", "data": [1, 2, 3]}

        result = func()
        assert result == {"status": "success", "data": [1, 2, 3]}


# --- ErrorTracker ---


class TestErrorTracker:
    """Tests for the ErrorTracker circuit breaker."""

    def test_initial_state(self):
        tracker = ErrorTracker(threshold=5, window_seconds=60)
        assert tracker.total_errors == 0
        assert tracker.recent_error_count() == 0
        assert not tracker.should_circuit_break()

    def test_record_error_increments_count(self):
        tracker = ErrorTracker(threshold=5, window_seconds=60)
        tracker.record_error("transient")
        assert tracker.total_errors == 1
        assert tracker.recent_error_count() == 1

    def test_circuit_break_at_threshold(self):
        tracker = ErrorTracker(threshold=3, window_seconds=60)
        for _ in range(3):
            tracker.record_error("system")
        assert tracker.should_circuit_break()

    def test_no_circuit_break_below_threshold(self):
        tracker = ErrorTracker(threshold=5, window_seconds=60)
        for _ in range(4):
            tracker.record_error("transient")
        assert not tracker.should_circuit_break()

    def test_old_errors_pruned(self):
        tracker = ErrorTracker(threshold=3, window_seconds=0.01)
        for _ in range(5):
            tracker.record_error("transient")
        # Wait for window to expire
        time.sleep(0.05)
        # Old errors should be pruned
        assert tracker.recent_error_count() == 0
        assert not tracker.should_circuit_break()

    def test_total_errors_not_pruned(self):
        tracker = ErrorTracker(threshold=3, window_seconds=0.01)
        for _ in range(5):
            tracker.record_error("transient")
        time.sleep(0.05)
        # Total count persists even after window expires
        assert tracker.total_errors == 5

    def test_get_status_dict(self):
        tracker = ErrorTracker(threshold=5, window_seconds=60)
        tracker.record_error("transient")
        tracker.record_error("logic")
        status = tracker.get_status()
        assert status["total_errors"] == 2
        assert status["recent_errors"] == 2
        assert status["circuit_breaker"] is False
        assert status["threshold"] == 5
        assert status["window_seconds"] == 60

    def test_circuit_breaker_in_status(self):
        tracker = ErrorTracker(threshold=2, window_seconds=60)
        tracker.record_error("system")
        tracker.record_error("system")
        status = tracker.get_status()
        assert status["circuit_breaker"] is True
