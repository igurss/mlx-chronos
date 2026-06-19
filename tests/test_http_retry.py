import httpx
import pytest
from unittest.mock import patch

from mlx_chronos.http_retry import request_with_retry, stream_with_retry


class EnterFailingManager:
    def __init__(self):
        self.exited = False

    def __enter__(self):
        raise httpx.ConnectError("connection reset")

    def __exit__(self, exc_type, exc, traceback):
        self.exited = True
        return False


class SuppressingManager:
    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, traceback):
        return True


def test_stream_with_retry_cleans_up_failed_enter():
    manager = EnterFailingManager()

    with pytest.raises(httpx.ConnectError):
        with stream_with_retry(lambda: manager, action="stream", attempts=1):
            pass

    assert manager.exited is True


def test_stream_with_retry_does_not_suppress_body_exceptions():
    with pytest.raises(ValueError, match="boom"):
        with stream_with_retry(lambda: SuppressingManager(), action="stream"):
            raise ValueError("boom")


def test_request_retry_backoff_is_capped():
    attempts = 8
    call_count = 0

    def fail():
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("offline")

    with patch("mlx_chronos.http_retry.time.sleep") as mock_sleep:
        with pytest.raises(httpx.ConnectError):
            request_with_retry(
                fail,
                action="request",
                attempts=attempts,
                backoff_seconds=1.0,
                max_backoff_seconds=4.0,
            )

    assert call_count == attempts
    assert [call.args[0] for call in mock_sleep.call_args_list] == [
        1.0,
        2.0,
        4.0,
        4.0,
        4.0,
        4.0,
        4.0,
    ]


@pytest.mark.parametrize("field", ["backoff_seconds", "max_backoff_seconds"])
def test_retry_rejects_negative_backoff(field):
    kwargs = {field: -1.0}
    with pytest.raises(ValueError, match=field):
        request_with_retry(lambda: None, action="request", **kwargs)
