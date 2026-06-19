"""Small HTTP retry helpers for transient local/network failures."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
import logging
import sys
import time
from typing import TypeVar

import httpx


DEFAULT_HTTP_RETRY_ATTEMPTS = 3
DEFAULT_HTTP_RETRY_BACKOFF_SECONDS = 0.25
DEFAULT_HTTP_RETRY_MAX_BACKOFF_SECONDS = 8.0
TRANSIENT_HTTP_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.NetworkError,
)

T = TypeVar("T")


def _validate_retry_settings(
    attempts: int,
    backoff_seconds: float,
    max_backoff_seconds: float,
) -> None:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    if backoff_seconds < 0:
        raise ValueError("backoff_seconds must be non-negative")
    if max_backoff_seconds < 0:
        raise ValueError("max_backoff_seconds must be non-negative")


def _retry_delay(
    backoff_seconds: float,
    max_backoff_seconds: float,
    attempt: int,
) -> float:
    delay = min(backoff_seconds, max_backoff_seconds)
    for _ in range(max(0, attempt - 1)):
        if delay >= max_backoff_seconds:
            break
        delay = min(delay * 2, max_backoff_seconds)
    return delay


def request_with_retry(
    call: Callable[[], T],
    *,
    action: str,
    attempts: int = DEFAULT_HTTP_RETRY_ATTEMPTS,
    backoff_seconds: float = DEFAULT_HTTP_RETRY_BACKOFF_SECONDS,
    max_backoff_seconds: float = DEFAULT_HTTP_RETRY_MAX_BACKOFF_SECONDS,
    logger: logging.Logger | None = None,
) -> T:
    """Run a non-streaming HTTP call with retries for transient failures."""
    _validate_retry_settings(attempts, backoff_seconds, max_backoff_seconds)

    for attempt in range(1, attempts + 1):
        try:
            return call()
        except TRANSIENT_HTTP_EXCEPTIONS as exc:
            if attempt == attempts:
                raise
            if logger is not None:
                logger.warning(
                    "%s failed with transient HTTP error (%s); retrying %s/%s.",
                    action,
                    exc,
                    attempt + 1,
                    attempts,
                )
            time.sleep(
                _retry_delay(backoff_seconds, max_backoff_seconds, attempt)
            )

    raise RuntimeError("unreachable HTTP retry state")


@contextmanager
def stream_with_retry(
    open_stream: Callable[[], AbstractContextManager[T]],
    *,
    action: str,
    attempts: int = DEFAULT_HTTP_RETRY_ATTEMPTS,
    backoff_seconds: float = DEFAULT_HTTP_RETRY_BACKOFF_SECONDS,
    max_backoff_seconds: float = DEFAULT_HTTP_RETRY_MAX_BACKOFF_SECONDS,
    logger: logging.Logger | None = None,
) -> Iterator[T]:
    """Open a streaming HTTP context with setup retries.

    Only failures that happen while opening/entering the stream are retried. Once
    the caller starts consuming the response body, retrying would duplicate a
    generation request and corrupt the measurement, so body-consumption errors
    are propagated directly.
    """
    _validate_retry_settings(attempts, backoff_seconds, max_backoff_seconds)

    manager: AbstractContextManager[T] | None = None
    response: T | None = None
    for attempt in range(1, attempts + 1):
        manager = None
        try:
            manager = open_stream()
            response = manager.__enter__()
            break
        except TRANSIENT_HTTP_EXCEPTIONS as exc:
            if manager is not None:
                try:
                    manager.__exit__(*sys.exc_info())
                except Exception:
                    pass
            if attempt == attempts:
                raise
            if logger is not None:
                logger.warning(
                    "%s failed with transient HTTP error (%s); retrying %s/%s.",
                    action,
                    exc,
                    attempt + 1,
                    attempts,
                )
            time.sleep(
                _retry_delay(backoff_seconds, max_backoff_seconds, attempt)
            )
        except BaseException:
            if manager is not None:
                manager.__exit__(*sys.exc_info())
            raise
    else:
        raise RuntimeError("unreachable HTTP stream retry state")

    if manager is None or response is None:
        raise RuntimeError("stream context did not produce a response")

    try:
        yield response
    except BaseException:
        manager.__exit__(*sys.exc_info())
        raise
    else:
        manager.__exit__(None, None, None)
