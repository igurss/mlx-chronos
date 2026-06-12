from mlx_chronos.constants import (
    BENCHMARK_REQUEST_TEMPERATURE,
    BENCHMARK_REQUEST_TOP_P,
    DEFAULT_THROUGHPUT_MAX_TOKENS,
)


BASELINE_PROTOCOL_VERSION = "3"
CONNECTION_MODE_PER_REQUEST = "per_request"
CONNECTION_MODE_PERSISTENT = "persistent"
VALID_CONNECTION_MODES = {
    CONNECTION_MODE_PER_REQUEST,
    CONNECTION_MODE_PERSISTENT,
}
TTFT_MAX_TOKENS = 1
WARMUP_MAX_TOKENS = 30

# Prompt pool for cold TTFT. The fixed order is part of the benchmark protocol.
COLD_PROMPTS = [
    "What is the capital of Australia?",
    "Explain what a transformer neural network is in one sentence.",
    "What does RAM stand for in computing?",
    "Describe the difference between a CPU and a GPU briefly.",
    "What is the boiling point of water in Celsius?",
    "Name the three laws of thermodynamics in one sentence each.",
    "What is gradient descent in machine learning?",
    "Explain what an operating system does in simple terms.",
    "What is the difference between supervised and unsupervised learning?",
    "Define latency in the context of computer networks.",
    "What does a compiler do?",
    "Explain why caches can improve application performance.",
    "What is a database index used for?",
    "Describe the purpose of an operating system kernel.",
    "What is the difference between RAM and storage?",
    "Explain what a neural network parameter is.",
    "What is batch processing in computing?",
    "Describe what a GPU shader is in one sentence.",
    "What is the purpose of an API?",
    "Explain what model quantization means.",
    "What is a context window in a language model?",
    "Describe the difference between prefill and decode in LLM inference.",
    "What does HTTP streaming allow a client to receive?",
    "Explain what a benchmark trial measures.",
    "What is statistical variance?",
    "Describe what memory pressure means on a computer.",
    "What is the difference between throughput and latency?",
    "Explain what a token is in language model inference.",
    "What is the role of Metal on Apple Silicon?",
    "Describe why repeated measurements are useful in benchmarking.",
]

CACHED_TTFT_PROMPT = (
    "Explain the concept of unified memory in Apple Silicon in one sentence."
)

WARMUP_PROMPT = (
    "Describe one practical reason local inference can be useful on a laptop."
)

THROUGHPUT_PROMPTS = [
    (
        "Explain in detail how the attention mechanism works in transformer "
        "neural networks, including the role of queries, keys, and values."
    ),
    (
        "Explain how a transformer decoder processes a user prompt from token "
        "embedding through final text generation."
    ),
    (
        "Describe the main performance tradeoffs between prompt prefill and "
        "token-by-token decode in local language model serving."
    ),
    (
        "Explain how quantization changes memory use and arithmetic behavior "
        "when running a language model on Apple Silicon."
    ),
    (
        "Describe how unified memory can affect model loading, cache growth, "
        "and inference throughput on a Mac."
    ),
    (
        "Explain the purpose of a key-value cache in autoregressive inference "
        "and how it changes repeated token generation."
    ),
    (
        "Describe how batching multiple requests can improve throughput while "
        "sometimes increasing individual request latency."
    ),
    (
        "Explain why streaming responses are useful for interactive assistants "
        "even when total request time stays the same."
    ),
    (
        "Describe how thermal pressure can alter sustained inference speed on "
        "a passively cooled or compact computer."
    ),
    (
        "Explain the difference between measuring model-internal decode speed "
        "and client-observed request throughput."
    ),
    (
        "Describe how a server scheduler can balance prefill work and decode "
        "work when several generation requests are active."
    ),
    (
        "Explain why first-token latency and total throughput can move in "
        "different directions when an inference engine is optimized."
    ),
    (
        "Describe how memory bandwidth, compute throughput, and cache locality "
        "interact during transformer inference."
    ),
    (
        "Explain the practical differences between running a model through a "
        "CLI wrapper, an HTTP server, and a library API."
    ),
    (
        "Describe why benchmark runs should record hardware, engine version, "
        "model name, and runtime conditions with the measured numbers."
    ),
    (
        "Explain how prompt length can influence prefill cost and why fixed "
        "benchmark prompts improve comparability."
    ),
    (
        "Describe the role of tokenizer behavior in reported completion token "
        "counts and throughput calculations."
    ),
    (
        "Explain why a benchmark may separate cold prompt latency from cached "
        "prompt latency instead of reporting one latency number."
    ),
    (
        "Describe how local model serving differs from cloud model serving in "
        "resource limits, network overhead, and user privacy."
    ),
    (
        "Explain how Metal acceleration helps MLX workloads execute efficiently "
        "on Apple GPUs."
    ),
    (
        "Describe why persistent HTTP connections reduce measurement noise in "
        "a repeated local benchmark loop."
    ),
    (
        "Explain how output token limits shape benchmark duration, memory use, "
        "and the stability of throughput estimates."
    ),
    (
        "Describe the difference between average throughput, standard deviation, "
        "minimum throughput, and maximum throughput in repeated trials."
    ),
    (
        "Explain why a benchmark should avoid relying on estimated word counts "
        "when an engine can report exact completion token usage."
    ),
    (
        "Describe how background system activity can interfere with local "
        "inference measurements and how repeated trials help reveal variance."
    ),
    (
        "Explain why deterministic generation settings make performance results "
        "easier to compare across engines."
    ),
    (
        "Describe how an inference server can expose OpenAI-compatible endpoints "
        "while using a different backend implementation internally."
    ),
    (
        "Explain why long sustained generation runs are useful for detecting "
        "late-run throttling or cache behavior changes."
    ),
    (
        "Describe how model size, quantization format, and available RAM combine "
        "to influence local inference performance."
    ),
    (
        "Explain how a community leaderboard can remain useful while still "
        "allowing flexible local diagnostic benchmark runs."
    ),
]

THROUGHPUT_PROMPT = THROUGHPUT_PROMPTS[0]


def _generation_parameters() -> dict:
    return {
        "temperature": BENCHMARK_REQUEST_TEMPERATURE,
        "top_p": BENCHMARK_REQUEST_TOP_P,
    }


def _protocol_phase(
    prompts: list[str],
    requested_max_tokens: int,
    requested_min_tokens: int | None = None,
    request_mode: str | None = None,
    stream_usage_requested: bool | None = None,
    connection_mode: str | None = None,
) -> dict:
    return {
        "prompts": prompts,
        "requested_max_tokens": requested_max_tokens,
        "requested_min_tokens": requested_min_tokens,
        "request_mode": request_mode,
        "stream_usage_requested": stream_usage_requested,
        "connection_mode": connection_mode,
        "generation_parameters": _generation_parameters(),
        "input_tokens": None,
        "input_token_count_source": "unavailable",
    }


def build_benchmark_protocol(
    trials: int,
    throughput_max_tokens: int,
    throughput_min_tokens: int | None,
    name: str = "baseline",
    connection_mode: str = CONNECTION_MODE_PERSISTENT,
) -> dict:
    if connection_mode not in VALID_CONNECTION_MODES:
        raise ValueError(
            f"connection_mode must be one of {sorted(VALID_CONNECTION_MODES)}"
        )
    return {
        "name": name,
        "version": BASELINE_PROTOCOL_VERSION,
        "warmup": _protocol_phase(
            [WARMUP_PROMPT],
            WARMUP_MAX_TOKENS,
            request_mode="streaming",
            stream_usage_requested=True,
            connection_mode=connection_mode,
        ),
        "ttft_cold": _protocol_phase(
            COLD_PROMPTS[:trials],
            TTFT_MAX_TOKENS,
            request_mode="streaming",
            stream_usage_requested=False,
            connection_mode=connection_mode,
        ),
        "ttft_cached": _protocol_phase(
            [CACHED_TTFT_PROMPT],
            TTFT_MAX_TOKENS,
            request_mode="streaming",
            stream_usage_requested=False,
            connection_mode=connection_mode,
        ),
        "throughput": _protocol_phase(
            THROUGHPUT_PROMPTS[:trials],
            throughput_max_tokens,
            throughput_min_tokens,
            request_mode="streaming",
            stream_usage_requested=True,
            connection_mode=connection_mode,
        ),
    }
