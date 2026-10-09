"""Bounded UTF-8 line decoding for completion streams."""
from __future__ import annotations

import codecs
import re
import time
from collections.abc import Callable, Iterator

MAX_STREAM_LINE_BYTES = 1024 * 1024


def completion_lines(
    response, *, deadline: float, context: str, clock: Callable[[], float] = time.monotonic,
) -> Iterator[str]:
    # Check each transport chunk, before the line decoder can buffer indefinitely.
    # HTTPX's read timeout still bounds an individual blocking read.
    decoder = codecs.getincrementaldecoder('utf-8')(errors='strict')
    pending = bytearray()
    try:
        for chunk in response.iter_bytes():
            if clock() >= deadline:
                raise RuntimeError(f'{context}; completion stream deadline exceeded')
            # Scan bytes before decoding, so the limit is in bytes, not codepoints.
            start = 0
            for boundary in re.finditer(b"[\r\n]", chunk):
                index = boundary.start()
                if len(pending) + index - start > MAX_STREAM_LINE_BYTES:
                    raise RuntimeError(f'{context}; completion stream line exceeds size limit')
                pending.extend(chunk[start:index])
                yield decoder.decode(bytes(pending), final=True)
                decoder.reset()
                pending.clear()
                start = index + 1
            if len(pending) + len(chunk) - start > MAX_STREAM_LINE_BYTES:
                raise RuntimeError(f'{context}; completion stream line exceeds size limit')
            pending.extend(chunk[start:])
        if clock() >= deadline:
            raise RuntimeError(f'{context}; completion stream deadline exceeded')
        if pending:
            yield decoder.decode(bytes(pending), final=True)
    except UnicodeDecodeError as exc:
        raise RuntimeError(f'{context}; invalid UTF-8 completion stream') from exc
