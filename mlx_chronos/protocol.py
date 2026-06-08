BASELINE_PROTOCOL_VERSION = "2"
TTFT_MAX_TOKENS = 1
WARMUP_MAX_TOKENS = 30
DEFAULT_THROUGHPUT_MAX_TOKENS = 100

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

THROUGHPUT_PROMPT = (
    "Explain in detail how the attention mechanism works in transformer "
    "neural networks, including the role of queries, keys, and values."
)


def _protocol_phase(
    prompts: list[str],
    requested_max_tokens: int,
    requested_min_tokens: int | None = None,
    request_mode: str | None = None,
    stream_usage_requested: bool | None = None,
) -> dict:
    return {
        "prompts": prompts,
        "requested_max_tokens": requested_max_tokens,
        "requested_min_tokens": requested_min_tokens,
        "request_mode": request_mode,
        "stream_usage_requested": stream_usage_requested,
        "input_tokens": None,
        "input_token_count_source": "unavailable",
    }


def build_benchmark_protocol(
    trials: int,
    throughput_max_tokens: int,
    throughput_min_tokens: int | None,
    name: str = "baseline",
) -> dict:
    return {
        "name": name,
        "version": BASELINE_PROTOCOL_VERSION,
        "warmup": _protocol_phase(
            [THROUGHPUT_PROMPT],
            WARMUP_MAX_TOKENS,
            request_mode="streaming",
            stream_usage_requested=True,
        ),
        "ttft_cold": _protocol_phase(
            COLD_PROMPTS[:trials],
            TTFT_MAX_TOKENS,
            request_mode="streaming",
            stream_usage_requested=False,
        ),
        "ttft_cached": _protocol_phase(
            [CACHED_TTFT_PROMPT],
            TTFT_MAX_TOKENS,
            request_mode="streaming",
            stream_usage_requested=False,
        ),
        "throughput": _protocol_phase(
            [THROUGHPUT_PROMPT],
            throughput_max_tokens,
            throughput_min_tokens,
            request_mode="streaming",
            stream_usage_requested=True,
        ),
    }
