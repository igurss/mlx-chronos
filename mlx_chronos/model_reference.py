"""Model reference URL helpers."""

from __future__ import annotations

from urllib.parse import urlparse


def normalize_model_reference_url(value: str | None) -> str | None:
    """Return a stripped HTTP(S) model reference URL or None."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("model reference URL must be a string")
    normalized = value.strip()
    if not normalized:
        return None

    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("model reference URL must be an http(s) URL")
    return normalized
