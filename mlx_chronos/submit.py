import json
from pathlib import Path

import httpx
from pydantic import ValidationError

from mlx_chronos.constants import (
    DEFAULT_THROUGHPUT_MAX_TOKENS,
    PHASE_TIMING_TOLERANCE_SECONDS,
    PUBLIC_LEADERBOARD_MIN_TRIALS,
    SUSTAINED_THROUGHPUT_MAX_TOKENS,
    SUSTAINED_TRIALS,
    TOKEN_COUNT_SOURCE_USAGE,
)
from mlx_chronos.integrity import IntegrityError, validate_integrity_seal
from mlx_chronos.protocol import BASELINE_PROTOCOL_VERSION
from mlx_chronos.schema import BenchmarkResult


SUBMIT_ENDPOINT_ENV = "MLX_CHRONOS_SUBMIT_ENDPOINT"
DEFAULT_SUBMIT_ENDPOINT = "https://usebasin.com/f/29157002c003"
SUBMITTER_EMAIL_ENV = "MLX_CHRONOS_SUBMITTER_EMAIL"
DEFAULT_SUBMITTER_EMAIL = "182094468+igurss@users.noreply.github.com"
PUBLIC_TOKEN_COUNT_SOURCE = TOKEN_COUNT_SOURCE_USAGE
PUBLIC_PROFILE_BASELINE = "baseline"
PUBLIC_PROFILE_SUSTAINED = "sustained"


class SubmissionError(RuntimeError):
    """Raised when a benchmark result cannot be submitted."""


def validate_publishable_result(result: BenchmarkResult) -> None:
    """Check public leaderboard comparability constraints."""
    token_source = result.metrics.token_count_source
    if token_source != PUBLIC_TOKEN_COUNT_SOURCE:
        raise SubmissionError(
            "leaderboard submissions must use "
            f"{PUBLIC_TOKEN_COUNT_SOURCE!r}; got {token_source!r}"
        )

    profile = result.meta.benchmark_profile

    if profile not in {PUBLIC_PROFILE_BASELINE, PUBLIC_PROFILE_SUSTAINED}:
        raise SubmissionError(
            "leaderboard submissions must use a standard profile "
            f"({PUBLIC_PROFILE_BASELINE!r} or {PUBLIC_PROFILE_SUSTAINED!r}); "
            f"got {profile!r}"
        )

    protocol = result.meta.benchmark_protocol
    if protocol.version != BASELINE_PROTOCOL_VERSION:
        raise SubmissionError(
            "leaderboard submissions must use current benchmark protocol "
            f"version {BASELINE_PROTOCOL_VERSION}; got {protocol.version!r}"
        )

    throughput = protocol.throughput
    requested_max_tokens = throughput.requested_max_tokens
    requested_min_tokens = throughput.requested_min_tokens

    elapsed_sum = sum(result.trials.throughput_elapsed_seconds_raw)
    phase_elapsed = result.meta.phase_timings_seconds.throughput
    # The phase timer should cover all per-trial throughput elapsed durations;
    # tolerate tiny differences from independent rounding.
    if phase_elapsed + PHASE_TIMING_TOLERANCE_SECONDS < elapsed_sum:
        raise SubmissionError(
            "throughput phase timing must cover raw throughput elapsed seconds"
        )

    if requested_min_tokens is not None:
        raise SubmissionError(
            "leaderboard submissions must not request throughput min_tokens; "
            f"got {requested_min_tokens}"
        )

    if profile == PUBLIC_PROFILE_BASELINE:
        if result.trials.count < PUBLIC_LEADERBOARD_MIN_TRIALS:
            raise SubmissionError(
                "baseline leaderboard submissions must include at least "
                f"{PUBLIC_LEADERBOARD_MIN_TRIALS} trials; got {result.trials.count}"
            )
        if (
            requested_max_tokens is not None
            and requested_max_tokens != DEFAULT_THROUGHPUT_MAX_TOKENS
        ):
            raise SubmissionError(
                "baseline leaderboard submissions must use standard throughput "
                f"max_tokens={DEFAULT_THROUGHPUT_MAX_TOKENS}; got "
                f"{requested_max_tokens}"
            )
        return

    if result.trials.count != SUSTAINED_TRIALS:
        raise SubmissionError(
            "sustained leaderboard submissions must use the standard sustained "
            f"trial count ({SUSTAINED_TRIALS}); got {result.trials.count}"
        )
    if requested_max_tokens != SUSTAINED_THROUGHPUT_MAX_TOKENS:
        raise SubmissionError(
            "sustained leaderboard submissions must use standard sustained "
            f"max_tokens={SUSTAINED_THROUGHPUT_MAX_TOKENS}; got "
            f"{requested_max_tokens}"
        )


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
        validate_integrity_seal(data)
    except IntegrityError as exc:
        raise SubmissionError(f"result integrity check failed: {exc}") from exc

    try:
        result = BenchmarkResult.model_validate(data)
    except ValidationError as exc:
        raise SubmissionError(f"result does not match the mlx-chronos schema: {exc}") from exc

    validate_publishable_result(result)

    return raw, result


def submit_result_file(
    path: Path,
    endpoint: str,
    timeout: float = 30.0,
    submitter_email: str = DEFAULT_SUBMITTER_EMAIL,
    raw: bytes | None = None,
    result: BenchmarkResult | None = None,
) -> BenchmarkResult:
    """Send a validated result JSON file to a maintainer inbox endpoint."""
    endpoint = endpoint.strip()
    if not endpoint:
        raise SubmissionError(
            f"submission endpoint is required; pass --endpoint or set {SUBMIT_ENDPOINT_ENV}"
        )

    if raw is None or result is None:
        raw, result = load_publishable_result(path)
    data = {
        "email": submitter_email.strip() or DEFAULT_SUBMITTER_EMAIL,
        "name": "mlx-chronos CLI",
        "subject": f"mlx-chronos benchmark result: {result.engine.name}",
        "message": (
            "Automated mlx-chronos benchmark result submission.\n"
            f"Engine: {result.engine.name}\n"
            f"Model: {result.model.name}\n"
            f"Hardware: {result.hardware.chip} / {result.hardware.memory_gb} GB\n"
            f"Token count source: {result.metrics.token_count_source}\n"
            "The full benchmark result is attached as result_json."
        ),
    }
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
            data=data,
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
