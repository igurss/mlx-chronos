from dataclasses import dataclass
import math

from mlx_chronos.constants import TOKEN_COUNT_SOURCE_USAGE, TOKEN_COUNT_SOURCE_WORD_FALLBACK
from mlx_chronos.numeric import is_finite_number


DECODE_TIMING_UNAVAILABLE = "unavailable"
DECODE_TIMING_CLIENT_STREAM = "client_stream"
INPUT_TOKEN_COUNT_UNAVAILABLE = "unavailable"
INPUT_TOKEN_COUNT_ENGINE = "engine"


@dataclass(frozen=True)
class ThroughputMeasurement:
    request_tokens_per_second: float
    completion_tokens: int
    token_count_source: str
    elapsed_seconds: float
    decode_tokens_per_second: float | None = None
    decode_elapsed_seconds: float | None = None
    decode_timing_source: str = DECODE_TIMING_UNAVAILABLE
    progress_samples: tuple[dict, ...] = ()
    finish_reason: str | None = None
    input_tokens: int | None = None


@dataclass(frozen=True)
class TTFTMeasurement:
    """TTFT and optional input tokens reported by the serving engine."""

    ttft_seconds: float
    input_tokens: int | None = None
    input_token_count_source: str = INPUT_TOKEN_COUNT_UNAVAILABLE


def validate_throughput_measurement(
    value: object, *, max_tokens: int | None = None, min_tokens: int | None = None,
) -> ThroughputMeasurement:
    """Validate a measured request before any consumer aggregates it."""
    if not isinstance(value, ThroughputMeasurement):
        raise RuntimeError("engine returned an invalid throughput measurement; expected ThroughputMeasurement")
    if (
        type(value.completion_tokens) is not int or value.completion_tokens <= 0
        or not is_finite_number(value.elapsed_seconds) or value.elapsed_seconds <= 0
        or not is_finite_number(value.request_tokens_per_second)
        or value.request_tokens_per_second <= 0
    ):
        raise RuntimeError("engine returned an invalid throughput measurement")
    if not isinstance(value.token_count_source, str) or value.token_count_source not in {
        TOKEN_COUNT_SOURCE_USAGE, TOKEN_COUNT_SOURCE_WORD_FALLBACK,
    }:
        raise RuntimeError("engine returned an invalid throughput measurement: no valid token count source")
    if value.input_tokens is not None and (
        type(value.input_tokens) is not int or value.input_tokens <= 0
    ):
        raise RuntimeError("engine returned an invalid input token count")
    try:
        expected = round(value.completion_tokens / value.elapsed_seconds, 2)
    except OverflowError as exc:
        raise RuntimeError("engine returned an invalid throughput measurement") from exc
    if not math.isfinite(expected) or abs(expected - value.request_tokens_per_second) > 0.02:
        raise RuntimeError("throughput must match completion tokens divided by elapsed seconds")
    if value.token_count_source == TOKEN_COUNT_SOURCE_USAGE:
        if max_tokens is not None and value.completion_tokens > max_tokens:
            raise RuntimeError("throughput completion token count exceeded requested max_tokens")
        if min_tokens is not None and value.completion_tokens < min_tokens:
            raise RuntimeError("throughput completion token count was below requested min_tokens")
    decode = (value.decode_tokens_per_second, value.decode_elapsed_seconds)
    if decode == (None, None):
        if value.decode_timing_source != DECODE_TIMING_UNAVAILABLE:
            raise RuntimeError("decode timing source requires decode measurements")
    else:
        tps, elapsed = decode
        if (
            not is_finite_number(tps) or tps <= 0
            or not is_finite_number(elapsed) or elapsed <= 0
            or elapsed > value.elapsed_seconds + 0.001
            or value.token_count_source != TOKEN_COUNT_SOURCE_USAGE
            or value.completion_tokens <= 1
            or value.decode_timing_source != DECODE_TIMING_CLIENT_STREAM
        ):
            raise RuntimeError("engine returned an invalid decode throughput measurement")
        expected_decode = round((value.completion_tokens - 1) / elapsed, 2)
        if not math.isfinite(expected_decode) or abs(expected_decode - tps) > 0.02:
            raise RuntimeError("decode throughput must match tokens minus one divided by decode elapsed")
    return value
