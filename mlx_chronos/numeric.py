"""Shared validation for externally configurable numeric values."""

from __future__ import annotations

import math
from typing import TypeGuard


def is_finite_number(value: object) -> TypeGuard[int | float]:
    """Return whether ``value`` is a finite, non-boolean built-in number."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def require_finite_positive(value: object, *, name: str) -> None:
    """Raise ``ValueError`` unless ``value`` is finite and greater than zero."""
    if not is_finite_number(value):
        raise ValueError(f"{name} must be a finite number greater than 0")
    if value <= 0:
        raise ValueError(f"{name} must be a finite number greater than 0")


def require_finite_non_negative(value: object, *, name: str) -> None:
    """Raise ``ValueError`` unless ``value`` is finite and at least zero."""
    if not is_finite_number(value):
        raise ValueError(f"{name} must be a finite number greater than or equal to 0")
    if value < 0:
        raise ValueError(f"{name} must be a finite number greater than or equal to 0")
