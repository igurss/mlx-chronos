import httpx
import pytest

from mlx_chronos.http_retry import stream_with_retry


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
