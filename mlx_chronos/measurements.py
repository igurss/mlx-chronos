from dataclasses import dataclass


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


@dataclass(frozen=True)
class TTFTMeasurement:
    """TTFT and optional input tokens reported by the serving engine."""

    ttft_seconds: float
    input_tokens: int | None = None
    input_token_count_source: str = INPUT_TOKEN_COUNT_UNAVAILABLE
