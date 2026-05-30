import json
from pathlib import Path

import httpx
from pydantic import ValidationError

from mlx_chronos.schema import BenchmarkResult


SUBMIT_ENDPOINT_ENV = "MLX_CHRONOS_SUBMIT_ENDPOINT"
DEFAULT_SUBMIT_ENDPOINT = "https://usebasin.com/f/29157002c003"
PUBLIC_TOKEN_COUNT_SOURCE = "usage.completion_tokens"


class SubmissionError(RuntimeError):
    """Raised when a benchmark result cannot be submitted."""


def load_publishable_result(path: Path) -> tuple[bytes, BenchmarkResult]:
    """Load, validate, and check whether a result can be submitted publicly."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SubmissionError(f"could not read result file: {path}") from exc

    try:
        data = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise SubmissionError("result file must be UTF-8 encoded JSON") from exc
    except json.JSONDecodeError as exc:
        raise SubmissionError(f"result file is not valid JSON: {exc}") from exc

    try:
        result = BenchmarkResult.model_validate(data)
    except ValidationError as exc:
        raise SubmissionError(f"result does not match the mlx-chronos schema: {exc}") from exc

    token_source = result.metrics.token_count_source
    if token_source != PUBLIC_TOKEN_COUNT_SOURCE:
        raise SubmissionError(
            "leaderboard submissions must use "
            f"{PUBLIC_TOKEN_COUNT_SOURCE!r}; got {token_source!r}"
        )

    return raw, result


def submit_result_file(
    path: Path,
    endpoint: str,
    timeout: float = 30.0,
) -> BenchmarkResult:
    """Send a validated result JSON file to a maintainer inbox endpoint."""
    endpoint = endpoint.strip()
    if not endpoint:
        raise SubmissionError(
            f"submission endpoint is required; pass --endpoint or set {SUBMIT_ENDPOINT_ENV}"
        )

    raw, result = load_publishable_result(path)
    files = {
        "result_json": (
            path.name,
            raw,
            "application/json",
        )
    }

    try:
        response = httpx.post(
            endpoint,
            files=files,
            timeout=timeout,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise SubmissionError(f"submission request failed: {exc}") from exc

    if response.status_code >= 400:
        body = response.text.strip()
        if len(body) > 500:
            body = body[:500] + "..."
        detail = f": {body}" if body else ""
        raise SubmissionError(
            f"submission endpoint returned HTTP {response.status_code}{detail}"
        )

    return result
