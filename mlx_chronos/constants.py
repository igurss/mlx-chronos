"""Shared constants for benchmark result contracts."""

MAX_TRIALS = 30
PUBLIC_BASELINE_TRIALS = 5
P95_MIN_TRIALS = 20
DEFAULT_THROUGHPUT_MAX_TOKENS = 100
SUSTAINED_THROUGHPUT_MAX_TOKENS = 1000
SUSTAINED_TRIALS = 1
SUSTAINED_PROGRESS_SAMPLE_INTERVAL_TOKENS = 100
PUBLIC_MIN_COMPLETION_TOKEN_RATIO = 0.8
BENCHMARK_REQUEST_TEMPERATURE = 0.0
BENCHMARK_REQUEST_TOP_P = 1.0

DEFAULT_RAM_SAMPLE_INTERVAL = 0.05
# A system-wide swap rise is a memory-pressure warning, not proof that this
# benchmark caused paging or that its throughput was distorted.
MEMORY_PRESSURE_SWAP_GROWTH_GB = 0.5
DEFAULT_THERMAL_SAMPLE_INTERVAL = 1.0
RECENT_BENCHMARK_WARNING_SECONDS = 300.0

# Phase durations and total runtime are rounded independently before validation.
PHASE_TIMING_TOLERANCE_SECONDS = 0.05
MAX_PHASE_TIMING_OVERHEAD_SECONDS = 30.0
ERROR_RESPONSE_BODY_LIMIT = 500

THERMAL_STATE_ORDER = {
    "nominal": 0,
    "fair": 1,
    "serious": 2,
    "critical": 3,
}

ENGINE_NAME_OMLX = "omlx"
ENGINE_NAME_RAPID_MLX = "rapid-mlx"
ENGINE_NAME_VLLM_MLX = "vllm-mlx"
ENGINE_NAME_MLX_LM = "mlx-lm"
ENGINE_NAME_OLLAMA = "ollama"
ENGINE_NAME_LM_STUDIO = "lmstudio"
# LM Studio ships both a llama.cpp runtime and an MLX runtime. Only the MLX one
# is in scope for this project, so a result is accepted only when the model is
# an MLX build *and* the runtime that actually served the request supports MLX.
LM_STUDIO_MLX_COMPATIBILITY_TYPE = "mlx"
LM_STUDIO_REJECTED_COMPATIBILITY_TYPES = frozenset({"gguf"})
OLLAMA_MLX_MODEL_FORMATS = frozenset({"safetensors"})
OLLAMA_REJECTED_MODEL_FORMATS = frozenset({"gguf"})
# Keep in sync with engines.ENGINES and schema.EngineName. constants.py is kept
# dependency-light, so tests enforce the registry/schema match instead.
VALID_ENGINE_NAMES = {
    ENGINE_NAME_OMLX,
    ENGINE_NAME_LM_STUDIO,
    ENGINE_NAME_RAPID_MLX,
    ENGINE_NAME_VLLM_MLX,
    ENGINE_NAME_MLX_LM,
    ENGINE_NAME_OLLAMA,
}

TOKEN_COUNT_SOURCE_USAGE = "usage.completion_tokens"
TOKEN_COUNT_SOURCE_WORD_FALLBACK = "word_fallback"
TOKEN_COUNT_SOURCE_MIXED = "mixed"

RAM_MEASUREMENT_PROCESS_RSS = "process_rss"
RAM_MEASUREMENT_SYSTEM_FALLBACK = "system_fallback"
