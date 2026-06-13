"""Small HTTP retry helpers for transient local/network failures."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import logging
import sys
import time
from typing import TypeVar

import httpx


DEFAULT_HTTP_RETRY_ATTEMPTS = 3
DEFAULT_HTTP_RETRY_BACKOFF_SECONDS = 0.25
TRANSIENT_HTTP_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.NetworkError,
)

T = TypeVar("T")


def request_with_retry(
    call: Callable[[], T],
    *,
    action: str,
    attempts: int = DEFAULT_HTTP_RETRY_ATTEMPTS,
    backoff_seconds: float = DEFAULT_HTTP_RETRY_BACKOFF_SECONDS,
    logger: logging.Logger | None = None,
) -> T:
    """Run a non-streaming HTTP call with retries for transient failures."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

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
            time.sleep(backoff_seconds * (2 ** (attempt - 1)))

    raise RuntimeError("unreachable HTTP retry state")


@contextmanager
def stream_with_retry(
    open_stream: Callable[[], object],
    *,
    action: str,
    attempts: int = DEFAULT_HTTP_RETRY_ATTEMPTS,
    backoff_seconds: float = DEFAULT_HTTP_RETRY_BACKOFF_SECONDS,
    logger: logging.Logger | None = None,
):
    """Open a streaming HTTP context with setup retries.

    Only failures that happen while opening/entering the stream are retried. Once
    the caller starts consuming the response body, retrying would duplicate a
    generation request and corrupt the measurement, so body-consumption errors
    are propagated directly.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    manager = None
    response = None
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
            time.sleep(backoff_seconds * (2 ** (attempt - 1)))
        except BaseException:
            if manager is not None:
                manager.__exit__(*sys.exc_info())
            raise
    else:
        raise RuntimeError("unreachable HTTP stream retry state")

    try:
        yield response
    except BaseException:
        manager.__exit__(*sys.exc_info())
        raise
    else:
        manager.__exit__(None, None, None)
