"""Example benchmark payloads used by smoke checks, docs, and tests."""

# Keep EXAMPLE_RESULT aligned with the current schema and release metadata.
# If this payload changes, regenerate the integrity digest with seal_result().

EXAMPLE_RESULT = {
    "hardware": {
        "chip": "Apple M2",
        "machine_model": "Mac14,2",
        "memory_gb": 8.0,
        "macos_version": "15.3.1",
        "python_version": "3.11.4",
        "architecture": "arm64",
        "thermal_state": "unavailable_permission",
        "power_source": "ac_power",
        "low_power_mode": "off",
    },
    "engine": {
        "name": "omlx",
        "version": "0.3.9",
    },
    "model": {
        "name": "Qwen3.5-4B-OptiQ-4bit",
        "quantization": "4bit",
    },
    "metrics": {
        "ttft_cold": {"mean": 0.041, "stddev": 0.015, "min": 0.028, "max": 0.066},
        "ttft_cached": {"mean": 0.010, "stddev": 0.002, "min": 0.007, "max": 0.012},
        "tokens_per_second": {"mean": 18.44, "stddev": 0.097, "min": 18.27, "max": 18.51},
        "request_tokens_per_second": {"mean": 18.44, "stddev": 0.097, "min": 18.27, "max": 18.51},
        "decode_tokens_per_second": {
            "mean": 18.654,
            "stddev": 0.095,
            "min": 18.49,
            "max": 18.73,
        },
        "decode_timing_source": "client_stream",
        "ram_peak_gb": 7.22,
        "ram_is_process_rss": False,
        "ram_measurement_method": "system_fallback",
        "system_ram_peak_gb": 7.22,
        "system_ram_peak_percent": 90.2,
        "token_count_source": "usage.completion_tokens",
    },
    "trials": {
        "count": 5,
        "ttft_cold_raw": [0.044, 0.066, 0.028, 0.039, 0.030],
        "ttft_cached_raw": [0.011, 0.007, 0.008, 0.010, 0.012],
        "tokens_per_second_raw": [18.48, 18.27, 18.51, 18.48, 18.46],
        "throughput_elapsed_seconds_raw": [5.411, 5.473, 5.402, 5.411, 5.417],
        "decode_tokens_per_second_raw": [18.7, 18.49, 18.73, 18.69, 18.66],
        "completion_tokens_raw": [100, 100, 100, 100, 100],
    },
    "meta": {
        "chronos_version": "0.2.1",
        "timestamp": "2026-06-08T12:00:00Z",
        "benchmark_profile": "baseline",
        "ram_sample_interval_seconds": 0.05,
        "elapsed_since_last_benchmark_seconds": None,
        "cooldown_seconds": 0.0,
        "phase_timings_seconds": {
            "warmup": 10.512,
            "ttft_cold": 0.208,
            "cache_priming": 0.010,
            "ttft_cached": 0.050,
            "throughput": 27.104,
            "total_runtime": 38.100,
        },
        "thermal_monitor": {
            "sample_interval_seconds": 1.0,
            "source": "unavailable",
            "start_state": "unavailable_foundation",
            "end_state": "unavailable_foundation",
            "worst_state": "unavailable_foundation",
            "samples": 2,
            "changed_during_run": False,
            "non_nominal_observed": False,
            "non_nominal_phases": [],
        },
        "warmup_failures": 0,
        "word_fallback_warning": False,
        "engine_version_warning": False,
        "sustained_throttling_warning": False,
        "cached_ttft_warning": False,
        "benchmark_protocol": {
            "name": "baseline",
            "version": "3",
            "warmup": {
                "prompts": [
                    "Describe one practical reason local inference can be useful on a laptop."
                ],
                "requested_max_tokens": 30,
                "requested_min_tokens": None,
                "request_mode": "streaming",
                "stream_usage_requested": True,
                "connection_mode": "persistent",
                "generation_parameters": {
                    "temperature": 0.0,
                    "top_p": 1.0,
                },
                "input_tokens": None,
                "input_token_count_source": "unavailable",
            },
            "ttft_cold": {
                "prompts": [
                    "What is the capital of Australia?",
                    "Explain what a transformer neural network is in one sentence.",
                    "What does RAM stand for in computing?",
                    "Describe the difference between a CPU and a GPU briefly.",
                    "What is the boiling point of water in Celsius?",
                ],
                "requested_max_tokens": 1,
                "requested_min_tokens": None,
                "request_mode": "streaming",
                "stream_usage_requested": False,
                "connection_mode": "persistent",
                "generation_parameters": {
                    "temperature": 0.0,
                    "top_p": 1.0,
                },
                "input_tokens": None,
                "input_token_count_source": "unavailable",
            },
            "ttft_cached": {
                "prompts": [
                    "Explain the concept of unified memory in Apple Silicon in one sentence."
                ],
                "requested_max_tokens": 1,
                "requested_min_tokens": None,
                "request_mode": "streaming",
                "stream_usage_requested": False,
                "connection_mode": "persistent",
                "generation_parameters": {
                    "temperature": 0.0,
                    "top_p": 1.0,
                },
                "input_tokens": None,
                "input_token_count_source": "unavailable",
            },
            "throughput": {
                "prompts": [
                    "Explain in detail how the attention mechanism works in transformer "
                    "neural networks, including the role of queries, keys, and values.",
                    "Explain how a transformer decoder processes a user prompt from token "
                    "embedding through final text generation.",
                    "Describe the main performance tradeoffs between prompt prefill and "
                    "token-by-token decode in local language model serving.",
                    "Explain how quantization changes memory use and arithmetic behavior "
                    "when running a language model on Apple Silicon.",
                    "Describe how unified memory can affect model loading, cache growth, "
                    "and inference throughput on a Mac.",
                ],
                "requested_max_tokens": 100,
                "requested_min_tokens": None,
                "request_mode": "streaming",
                "stream_usage_requested": True,
                "connection_mode": "persistent",
                "generation_parameters": {
                    "temperature": 0.0,
                    "top_p": 1.0,
                },
                "input_tokens": None,
                "input_token_count_source": "unavailable",
            },
        },
        "notes": "Test run",
    },
    "integrity": {
        "schema": "mlx-chronos-integrity-v1",
        "algorithm": "sha256-canonical-json",
        "signed_payload": "benchmark-result-without-integrity",
        "digest": "6ef2d48b40d25ef62b5af51801295c8608104350a177b1cfe0e08e988b99e085",
    },
}
