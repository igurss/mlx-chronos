import json
import logging
from pathlib import Path

import httpx
from pydantic import ValidationError

from mlx_chronos.constants import (
    BENCHMARK_REQUEST_TEMPERATURE,
    BENCHMARK_REQUEST_TOP_P,
    DEFAULT_THROUGHPUT_MAX_TOKENS,
    PHASE_TIMING_TOLERANCE_SECONDS,
    PUBLIC_BASELINE_TRIALS,
    PUBLIC_MIN_COMPLETION_TOKEN_RATIO,
    SUSTAINED_THROUGHPUT_MAX_TOKENS,
    SUSTAINED_TRIALS,
    TOKEN_COUNT_SOURCE_USAGE,
)
from mlx_chronos.integrity import IntegrityError, validate_integrity_seal
from mlx_chronos.http_retry import request_with_retry
from mlx_chronos.protocol import (
    BASELINE_PROTOCOL_VERSION,
    CONNECTION_MODE_PERSISTENT,
    build_benchmark_protocol,
)
from mlx_chronos.schema import BenchmarkProtocol, BenchmarkResult


SUBMIT_ENDPOINT_ENV = "MLX_CHRONOS_SUBMIT_ENDPOINT"
DEFAULT_SUBMIT_ENDPOINT = "https://usebasin.com/f/29157002c003"
SUBMITTER_EMAIL_ENV = "MLX_CHRONOS_SUBMITTER_EMAIL"
DEFAULT_SUBMITTER_EMAIL = "182094468+igurss@users.noreply.github.com"
PUBLIC_TOKEN_COUNT_SOURCE = TOKEN_COUNT_SOURCE_USAGE
PUBLIC_PROFILE_BASELINE = "baseline"
PUBLIC_PROFILE_SUSTAINED = "sustained"
PUBLIC_LOW_POWER_MODE = "off"
logger = logging.getLogger("mlx_chronos")


class SubmissionError(RuntimeError):
    """Raised when a benchmark result cannot be submitted."""


def _validate_public_generation_parameters(result: BenchmarkResult) -> None:
    protocol = result.meta.benchmark_protocol
    for phase_name in ("warmup", "ttft_cold", "ttft_cached", "throughput"):
        phase = getattr(protocol, phase_name)
        params = phase.generation_parameters
        if (
            params.temperature != BENCHMARK_REQUEST_TEMPERATURE
            or params.top_p != BENCHMARK_REQUEST_TOP_P
        ):
            raise SubmissionError(
                "leaderboard submissions must use standard generation "
                f"parameters in {phase_name}: "
                f"temperature={BENCHMARK_REQUEST_TEMPERATURE}, "
                f"top_p={BENCHMARK_REQUEST_TOP_P}; got "
                f"temperature={params.temperature}, top_p={params.top_p}"
            )


def _first_protocol_difference(
    expected: object,
    actual: object,
    path: str = "benchmark_protocol",
) -> str | None:
    if isinstance(expected, dict) and isinstance(actual, dict):
        expected_keys = set(expected)
        actual_keys = set(actual)
        if expected_keys != actual_keys:
            missing = sorted(expected_keys - actual_keys)
            extra = sorted(actual_keys - expected_keys)
            details = []
            if missing:
                details.append(f"missing={missing}")
            if extra:
                details.append(f"extra={extra}")
            return f"{path} keys differ ({', '.join(details)})"
        for key in sorted(expected):
            difference = _first_protocol_difference(
                expected[key],
                actual[key],
                f"{path}.{key}",
            )
            if difference:
                return difference
        return None

    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return f"{path} length expected {len(expected)}, got {len(actual)}"
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            difference = _first_protocol_difference(
                expected_item,
                actual_item,
                f"{path}[{index}]",
            )
            if difference:
                return difference
        return None

    if expected != actual:
        return f"{path} expected {expected!r}, got {actual!r}"
    return None


def _expected_public_profile_shape(profile: str) -> tuple[int, int]:
    if profile == PUBLIC_PROFILE_BASELINE:
        return PUBLIC_BASELINE_TRIALS, DEFAULT_THROUGHPUT_MAX_TOKENS
    return SUSTAINED_TRIALS, SUSTAINED_THROUGHPUT_MAX_TOKENS


def _validate_public_protocol(result: BenchmarkResult) -> None:
    expected_trials, expected_max_tokens = _expected_public_profile_shape(
        result.meta.benchmark_profile
    )
    expected_protocol = BenchmarkProtocol.model_validate(
        build_benchmark_protocol(
            expected_trials,
            expected_max_tokens,
            None,
            name=result.meta.benchmark_profile,
            connection_mode=CONNECTION_MODE_PERSISTENT,
        )
    ).model_dump(mode="json")
    actual_protocol = result.meta.benchmark_protocol.model_dump(mode="json")

    difference = _first_protocol_difference(expected_protocol, actual_protocol)
    if difference:
        raise SubmissionError(
            "leaderboard submissions must match the standard benchmark "
            f"protocol exactly; {difference}"
        )


def _validate_public_completion_tokens(
    result: BenchmarkResult,
    expected_max_tokens: int,
) -> None:
    minimum_tokens = int(expected_max_tokens * PUBLIC_MIN_COMPLETION_TOKEN_RATIO)
    if minimum_tokens < 1:
        minimum_tokens = 1
    for index, tokens in enumerate(result.trials.completion_tokens_raw, start=1):
        if tokens < minimum_tokens:
            raise SubmissionError(
                "leaderboard submissions must generate at least "
                f"{PUBLIC_MIN_COMPLETION_TOKEN_RATIO:.0%} of the standard "
                f"throughput max_tokens on every trial (trial {index}: "
                f"minimum {minimum_tokens}, got {tokens})"
            )


def validate_publishable_result(
    result: BenchmarkResult,
    *,
    allow_legacy_missing_model_reference: bool = False,
) -> None:
    """Check public leaderboard comparability constraints."""
    token_source = result.metrics.token_count_source
    if token_source != PUBLIC_TOKEN_COUNT_SOURCE:
        raise SubmissionError(
            "leaderboard submissions must use "
            f"{PUBLIC_TOKEN_COUNT_SOURCE!r}; got {token_source!r}"
        )

    if (
        result.model.reference_url is None
        and not allow_legacy_missing_model_reference
    ):
        raise SubmissionError(
            "leaderboard submissions must include model.reference_url. "
            "Pass --model-url when running the benchmark."
        )

    profile = result.meta.benchmark_profile

    if profile not in {PUBLIC_PROFILE_BASELINE, PUBLIC_PROFILE_SUSTAINED}:
        raise SubmissionError(
            "leaderboard submissions must use a standard profile "
            f"({PUBLIC_PROFILE_BASELINE!r} or {PUBLIC_PROFILE_SUSTAINED!r}); "
            f"got {profile!r}"
        )

    expected_trials, expected_max_tokens = _expected_public_profile_shape(profile)

    protocol = result.meta.benchmark_protocol
    if protocol.version != BASELINE_PROTOCOL_VERSION:
        raise SubmissionError(
            "leaderboard submissions must use the current internal protocol "
            f"label {BASELINE_PROTOCOL_VERSION!r}; got {protocol.version!r}"
        )
    _validate_public_generation_parameters(result)

    low_power_mode = result.hardware.low_power_mode
    if low_power_mode != PUBLIC_LOW_POWER_MODE:
        raise SubmissionError(
            "leaderboard submissions must be run with macOS Low Power Mode "
            f"disabled; got {low_power_mode!r}. Check System Settings > "
            "Battery, or run `pmset -g custom` and make sure lowpowermode is 0."
        )

    if result.meta.warmup_failures != 0:
        raise SubmissionError(
            "leaderboard submissions must complete all warmup calls without "
            f"failures; got warmup_failures={result.meta.warmup_failures}"
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
        if result.trials.count != expected_trials:
            raise SubmissionError(
                "baseline leaderboard submissions must use the standard baseline "
                f"trial count ({expected_trials}); got {result.trials.count}"
            )
        if (
            requested_max_tokens is not None
            and requested_max_tokens != expected_max_tokens
        ):
            raise SubmissionError(
                "baseline leaderboard submissions must use standard throughput "
                f"max_tokens={expected_max_tokens}; got "
                f"{requested_max_tokens}"
            )
    elif result.trials.count != expected_trials:
        raise SubmissionError(
            "sustained leaderboard submissions must use the standard sustained "
            f"trial count ({expected_trials}); got {result.trials.count}"
        )
    elif requested_max_tokens != expected_max_tokens:
        raise SubmissionError(
            "sustained leaderboard submissions must use standard sustained "
            f"max_tokens={expected_max_tokens}; got "
            f"{requested_max_tokens}"
        )

    _validate_public_completion_tokens(result, expected_max_tokens)
    _validate_public_protocol(result)


def load_publishable_result(
    path: Path,
    *,
    allow_legacy_missing_model_reference: bool = False,
) -> tuple[bytes, BenchmarkResult]:
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

    validate_publishable_result(
        result,
        allow_legacy_missing_model_reference=allow_legacy_missing_model_reference,
    )

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
        response = request_with_retry(
            lambda: httpx.post(
                endpoint,
                data=data,
                files=files,
                timeout=timeout,
                follow_redirects=True,
            ),
            action="submit result",
            logger=logger,
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
