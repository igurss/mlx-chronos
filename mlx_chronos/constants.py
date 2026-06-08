"""Shared constants for benchmark result contracts."""

MAX_TRIALS = 30
P95_MIN_TRIALS = 20

DEFAULT_RAM_SAMPLE_INTERVAL = 0.05
DEFAULT_THERMAL_SAMPLE_INTERVAL = 1.0
RECENT_BENCHMARK_WARNING_SECONDS = 300.0

# Phase durations and total runtime are rounded independently before validation.
PHASE_TIMING_TOLERANCE_SECONDS = 0.05
ERROR_RESPONSE_BODY_LIMIT = 500

ENGINE_NAME_OMLX = "omlx"
ENGINE_NAME_RAPID_MLX = "rapid-mlx"
ENGINE_NAME_MLX_LM = "mlx-lm"
ENGINE_NAME_OLLAMA = "ollama"
# Keep in sync with engines.ENGINES and schema.EngineName. constants.py is kept
# dependency-light, so tests enforce the registry/schema match instead.
VALID_ENGINE_NAMES = {
    ENGINE_NAME_OMLX,
    ENGINE_NAME_RAPID_MLX,
    ENGINE_NAME_MLX_LM,
    ENGINE_NAME_OLLAMA,
}

TOKEN_COUNT_SOURCE_USAGE = "usage.completion_tokens"
TOKEN_COUNT_SOURCE_WORD_FALLBACK = "word_fallback"
TOKEN_COUNT_SOURCE_MIXED = "mixed"
TOKEN_COUNT_SOURCES = {
    TOKEN_COUNT_SOURCE_USAGE,
    TOKEN_COUNT_SOURCE_WORD_FALLBACK,
    TOKEN_COUNT_SOURCE_MIXED,
}

RAM_MEASUREMENT_PROCESS_RSS = "process_rss"
RAM_MEASUREMENT_SYSTEM_FALLBACK = "system_fallback"
RAM_MEASUREMENT_METHODS = {
    RAM_MEASUREMENT_PROCESS_RSS,
    RAM_MEASUREMENT_SYSTEM_FALLBACK,
}
