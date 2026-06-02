from dataclasses import dataclass


DECODE_TIMING_UNAVAILABLE = "unavailable"
DECODE_TIMING_ENGINE_RESPONSE = "engine_response"


@dataclass(frozen=True)
class ThroughputMeasurement:
    request_tokens_per_second: float
    completion_tokens: int
    token_count_source: str
    elapsed_seconds: float
    decode_tokens_per_second: float | None = None
    decode_timing_source: str = DECODE_TIMING_UNAVAILABLE

