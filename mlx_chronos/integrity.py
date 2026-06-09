"""Tamper-evident integrity seals for benchmark result JSON."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from collections.abc import Mapping
from typing import Any


INTEGRITY_SCHEMA = "mlx-chronos-integrity-v1"
INTEGRITY_ALGORITHM = "sha256-canonical-json"
INTEGRITY_SIGNED_PAYLOAD = "benchmark-result-without-integrity"
INTEGRITY_DIGEST_BYTES = 32
INTEGRITY_DIGEST_HEX_LENGTH = INTEGRITY_DIGEST_BYTES * 2


class IntegrityError(ValueError):
    """Raised when a benchmark result integrity seal is missing or invalid."""


def unsigned_result(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deep copy of result data without the top-level integrity seal."""
    if not isinstance(data, Mapping):
        raise IntegrityError("result must be a JSON object")
    result = deepcopy(dict(data))
    result.pop("integrity", None)
    return result


def canonical_result_bytes(data: Mapping[str, Any]) -> bytes:
    """Serialize result JSON deterministically for integrity hashing."""
    return json.dumps(
        unsigned_result(data),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def result_digest(data: Mapping[str, Any]) -> str:
    """Return the canonical SHA-256 digest for benchmark result data."""
    return hashlib.sha256(canonical_result_bytes(data)).hexdigest()


def build_integrity_seal(data: Mapping[str, Any]) -> dict[str, str]:
    """Build an integrity seal for benchmark result data."""
    return {
        "schema": INTEGRITY_SCHEMA,
        "algorithm": INTEGRITY_ALGORITHM,
        "signed_payload": INTEGRITY_SIGNED_PAYLOAD,
        "digest": result_digest(data),
    }


def placeholder_integrity_seal() -> dict[str, str]:
    """Return a schema-valid placeholder used before final result sealing."""
    return {
        "schema": INTEGRITY_SCHEMA,
        "algorithm": INTEGRITY_ALGORITHM,
        "signed_payload": INTEGRITY_SIGNED_PAYLOAD,
        "digest": "0" * INTEGRITY_DIGEST_HEX_LENGTH,
    }


def seal_result(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return result data with a fresh top-level integrity seal."""
    result = unsigned_result(data)
    result["integrity"] = build_integrity_seal(result)
    return result


def validate_integrity_seal(data: Mapping[str, Any]) -> None:
    """Raise IntegrityError if the top-level result integrity seal is invalid."""
    if not isinstance(data, Mapping):
        raise IntegrityError("result must be a JSON object")
    seal = data.get("integrity")
    if not isinstance(seal, Mapping):
        raise IntegrityError("result integrity seal is missing")

    expected_fields = {"schema", "algorithm", "signed_payload", "digest"}
    extra_fields = set(seal) - expected_fields
    missing_fields = expected_fields - set(seal)
    if extra_fields or missing_fields:
        details = []
        if missing_fields:
            details.append(f"missing={sorted(missing_fields)}")
        if extra_fields:
            details.append(f"extra={sorted(extra_fields)}")
        raise IntegrityError("result integrity seal has invalid fields: " + ", ".join(details))

    if seal["schema"] != INTEGRITY_SCHEMA:
        raise IntegrityError(f"unsupported integrity schema: {seal['schema']!r}")
    if seal["algorithm"] != INTEGRITY_ALGORITHM:
        raise IntegrityError(f"unsupported integrity algorithm: {seal['algorithm']!r}")
    if seal["signed_payload"] != INTEGRITY_SIGNED_PAYLOAD:
        raise IntegrityError(f"unsupported signed payload: {seal['signed_payload']!r}")

    digest = seal["digest"]
    if (
        not isinstance(digest, str)
        or len(digest) != INTEGRITY_DIGEST_HEX_LENGTH
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise IntegrityError("result integrity digest must be 64 lowercase hex characters")

    expected_digest = result_digest(data)
    if digest != expected_digest:
        raise IntegrityError("result integrity digest does not match result content")
