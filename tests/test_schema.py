from datetime import datetime
from typing import get_args

import pytest
from pydantic import ValidationError
from mlx_chronos.constants import MAX_TRIALS, P95_MIN_TRIALS, VALID_ENGINE_NAMES
from mlx_chronos.examples import EXAMPLE_RESULT
from mlx_chronos.integrity import IntegrityError, validate_integrity_seal
from mlx_chronos.schema import BenchmarkResult, Engine, TrialStats

def test_valid_schema():
    """Test that the example result is fully valid."""
    result = BenchmarkResult(**EXAMPLE_RESULT)
    assert result.engine.name == "omlx"
    assert result.metrics.tokens_per_second.mean == 18.44
    assert result.metrics.request_tokens_per_second.mean == 18.44
    assert result.metrics.decode_tokens_per_second.mean == 18.654
    assert result.metrics.decode_timing_source == "client_stream"
    assert isinstance(result.meta.timestamp, datetime)
    assert result.meta.ram_sample_interval_seconds == 0.05
    assert result.meta.benchmark_profile == "baseline"
    assert result.meta.elapsed_since_last_benchmark_seconds is None
    assert result.meta.cooldown_seconds == 0.0
    assert result.meta.warmup_failures == 0
    assert result.meta.word_fallback_warning is False
    assert result.meta.engine_version_warning is False
    assert result.meta.sustained_throttling_warning is False
    assert result.meta.cached_ttft_warning is False
    assert result.meta.phase_timings_seconds.total_runtime == 38.1
    assert result.meta.thermal_monitor.source == "unavailable"
    assert result.meta.thermal_monitor.start_state == "unavailable_foundation"
    assert result.hardware.architecture == "arm64"
    assert result.hardware.power_source == "ac_power"
    assert result.hardware.low_power_mode == "off"
    assert result.metrics.token_count_source == "usage.completion_tokens"
    assert result.metrics.ram_measurement_method == "system_fallback"
    assert result.metrics.system_ram_peak_gb == 7.22
    assert result.metrics.system_ram_peak_percent == 90.2
    assert result.trials.completion_tokens_raw == [100, 100, 100, 100, 100]
    assert result.trials.throughput_elapsed_seconds_raw == [
        5.411,
        5.473,
        5.402,
        5.411,
        5.417,
    ]
    assert result.meta.benchmark_protocol is not None
    assert result.meta.benchmark_protocol.name == "baseline"
    assert result.meta.benchmark_protocol.version == "3"
    assert result.meta.benchmark_protocol.throughput.requested_max_tokens == 100
    assert result.meta.benchmark_protocol.throughput.request_mode == "streaming"
    assert result.meta.benchmark_protocol.throughput.stream_usage_requested is True
    assert result.meta.benchmark_protocol.throughput.connection_mode == "persistent"
    assert (
        result.meta.benchmark_protocol.throughput.input_token_count_source
        == "unavailable"
    )
    assert result.integrity.schema_name == "mlx-chronos-integrity-v1"
    validate_integrity_seal(EXAMPLE_RESULT)

def test_legacy_thermal_state_is_normalized():
    data = EXAMPLE_RESULT.copy()
    data["hardware"] = data["hardware"].copy()
    data["hardware"]["thermal_state"] = "unavailable_no_sudo"

    result = BenchmarkResult(**data)

    assert result.hardware.thermal_state == "unavailable_permission"

def test_invalid_engine_name():
    """Test that an unknown engine name raises a validation error."""
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["engine"] = invalid_data["engine"].copy()
    invalid_data["engine"]["name"] = "unknown-engine"
    
    with pytest.raises(ValidationError):
        BenchmarkResult(**invalid_data)


def test_engine_name_is_literal_typed():
    assert set(get_args(Engine.model_fields["name"].annotation)) == VALID_ENGINE_NAMES


def test_missing_required_field():
    """Test that missing required fields raise validation errors."""
    invalid_data = EXAMPLE_RESULT.copy()
    # Remove a required field
    del invalid_data["hardware"]
    
    with pytest.raises(ValidationError):
        BenchmarkResult(**invalid_data)

def test_trial_count_must_match_raw_lengths():
    """Test that raw trial arrays must match trials.count."""
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["trials"] = invalid_data["trials"].copy()
    invalid_data["trials"]["ttft_cold_raw"] = [0.1]

    with pytest.raises(ValidationError, match="trials.count"):
        BenchmarkResult(**invalid_data)

def test_completion_token_raw_lengths_must_match_trial_count():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["trials"] = invalid_data["trials"].copy()
    invalid_data["trials"]["completion_tokens_raw"] = [100]

    with pytest.raises(ValidationError, match="trials.count"):
        BenchmarkResult(**invalid_data)

def test_completion_token_raw_is_required():
    data = EXAMPLE_RESULT.copy()
    data["trials"] = data["trials"].copy()
    del data["trials"]["completion_tokens_raw"]
    del data["trials"]["throughput_elapsed_seconds_raw"]

    with pytest.raises(ValidationError):
        BenchmarkResult(**data)


def test_completion_tokens_and_elapsed_seconds_are_required():
    data = EXAMPLE_RESULT.copy()
    data["trials"] = data["trials"].copy()
    del data["trials"]["completion_tokens_raw"]

    with pytest.raises(ValidationError):
        BenchmarkResult(**data)

    data = EXAMPLE_RESULT.copy()
    data["trials"] = data["trials"].copy()
    del data["trials"]["throughput_elapsed_seconds_raw"]

    with pytest.raises(ValidationError):
        BenchmarkResult(**data)

def test_request_throughput_raw_fields_are_required():
    data = EXAMPLE_RESULT.copy()
    data["trials"] = data["trials"].copy()
    del data["trials"]["throughput_elapsed_seconds_raw"]
    del data["trials"]["completion_tokens_raw"]
    data["metrics"] = data["metrics"].copy()
    del data["metrics"]["request_tokens_per_second"]

    with pytest.raises(ValidationError):
        BenchmarkResult(**data)

def test_decode_timing_source_accepts_client_stream():
    data = EXAMPLE_RESULT.copy()
    data["metrics"] = data["metrics"].copy()
    data["trials"] = data["trials"].copy()
    data["metrics"]["decode_tokens_per_second"] = {
        "mean": 20.0,
        "stddev": 0.354,
        "min": 19.5,
        "max": 20.5,
    }
    data["metrics"]["decode_timing_source"] = "client_stream"
    data["trials"]["decode_tokens_per_second_raw"] = [
        19.5,
        20.0,
        20.5,
        20.0,
        20.0,
    ]

    result = BenchmarkResult(**data)

    assert result.metrics.decode_timing_source == "client_stream"


def test_decode_timing_source_rejects_unproduced_engine_response():
    data = EXAMPLE_RESULT.copy()
    data["metrics"] = data["metrics"].copy()
    data["metrics"]["decode_timing_source"] = "engine_response"

    with pytest.raises(ValidationError, match="decode_timing_source"):
        BenchmarkResult(**data)

def test_benchmark_protocol_is_required():
    data = EXAMPLE_RESULT.copy()
    data["meta"] = data["meta"].copy()
    del data["meta"]["benchmark_protocol"]

    with pytest.raises(ValidationError):
        BenchmarkResult(**data)

def test_benchmark_protocol_generation_parameters_are_required():
    data = EXAMPLE_RESULT.copy()
    data["meta"] = data["meta"].copy()
    data["meta"]["benchmark_protocol"] = {
        **data["meta"]["benchmark_protocol"],
        "throughput": {
            **data["meta"]["benchmark_protocol"]["throughput"],
        },
    }
    del data["meta"]["benchmark_protocol"]["throughput"]["generation_parameters"]

    with pytest.raises(ValidationError, match="generation_parameters"):
        BenchmarkResult(**data)

def test_benchmark_protocol_throughput_prompts_must_match_trials():
    data = EXAMPLE_RESULT.copy()
    data["meta"] = data["meta"].copy()
    data["meta"]["benchmark_protocol"] = {
        **data["meta"]["benchmark_protocol"],
        "throughput": {
            **data["meta"]["benchmark_protocol"]["throughput"],
            "prompts": data["meta"]["benchmark_protocol"]["throughput"]["prompts"][:1],
        },
    }

    with pytest.raises(ValidationError, match="throughput prompts"):
        BenchmarkResult(**data)

def test_phase_timings_and_thermal_monitor_are_required():
    data = EXAMPLE_RESULT.copy()
    data["meta"] = data["meta"].copy()
    del data["meta"]["phase_timings_seconds"]
    del data["meta"]["thermal_monitor"]

    with pytest.raises(ValidationError):
        BenchmarkResult(**data)


def test_warmup_failures_is_required():
    data = EXAMPLE_RESULT.copy()
    data["meta"] = data["meta"].copy()
    del data["meta"]["warmup_failures"]

    with pytest.raises(ValidationError):
        BenchmarkResult(**data)


def test_cached_ttft_warning_is_required():
    data = EXAMPLE_RESULT.copy()
    data["meta"] = data["meta"].copy()
    del data["meta"]["cached_ttft_warning"]

    with pytest.raises(ValidationError):
        BenchmarkResult(**data)


def test_integrity_seal_rejects_tampering():
    data = EXAMPLE_RESULT.copy()
    data["metrics"] = data["metrics"].copy()
    data["metrics"]["tokens_per_second"] = {
        **data["metrics"]["tokens_per_second"],
        "mean": 99.0,
    }

    with pytest.raises(IntegrityError, match="digest"):
        validate_integrity_seal(data)


def test_integrity_seal_is_required():
    data = EXAMPLE_RESULT.copy()
    del data["integrity"]

    with pytest.raises(IntegrityError, match="missing"):
        validate_integrity_seal(data)


def test_phase_timings_reject_total_shorter_than_phase_sum():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["meta"] = invalid_data["meta"].copy()
    invalid_data["meta"]["phase_timings_seconds"] = {
        **invalid_data["meta"]["phase_timings_seconds"],
        "warmup": 1.0,
        "ttft_cold": 1.0,
        "cache_priming": 1.0,
        "ttft_cached": 1.0,
        "throughput": 1.0,
        "total_runtime": 4.0,
    }

    with pytest.raises(ValidationError, match="total_runtime"):
        BenchmarkResult(**invalid_data)

def test_thermal_monitor_rejects_unmarked_state_change():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["meta"] = invalid_data["meta"].copy()
    invalid_data["meta"]["thermal_monitor"] = {
        **invalid_data["meta"]["thermal_monitor"],
        "source": "foundation",
        "start_state": "nominal",
        "end_state": "fair",
        "worst_state": "fair",
        "changed_during_run": False,
    }

    with pytest.raises(ValidationError, match="changed_during_run"):
        BenchmarkResult(**invalid_data)

def test_thermal_monitor_rejects_phases_without_non_nominal_flag():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["meta"] = invalid_data["meta"].copy()
    invalid_data["meta"]["thermal_monitor"] = {
        **invalid_data["meta"]["thermal_monitor"],
        "source": "foundation",
        "start_state": "nominal",
        "end_state": "fair",
        "worst_state": "fair",
        "changed_during_run": True,
        "non_nominal_observed": False,
        "non_nominal_phases": ["throughput"],
    }

    with pytest.raises(ValidationError, match="non_nominal_observed"):
        BenchmarkResult(**invalid_data)

def test_benchmark_protocol_rejects_invalid_token_bounds():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["meta"] = invalid_data["meta"].copy()
    invalid_data["meta"]["benchmark_protocol"] = {
        **invalid_data["meta"]["benchmark_protocol"],
        "throughput": {
            **invalid_data["meta"]["benchmark_protocol"]["throughput"],
            "requested_max_tokens": 50,
            "requested_min_tokens": 80,
        },
    }

    with pytest.raises(ValidationError, match="requested_min_tokens"):
        BenchmarkResult(**invalid_data)

def test_benchmark_protocol_rejects_unlabeled_input_tokens():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["meta"] = invalid_data["meta"].copy()
    invalid_data["meta"]["benchmark_protocol"] = {
        **invalid_data["meta"]["benchmark_protocol"],
            "throughput": {
                **invalid_data["meta"]["benchmark_protocol"]["throughput"],
                "input_tokens": [20, 21, 22, 23, 24],
                "input_token_count_source": "unavailable",
            },
        }

    with pytest.raises(ValidationError, match="input_token_count_source"):
        BenchmarkResult(**invalid_data)

def test_benchmark_protocol_rejects_stream_usage_for_non_streaming_phase():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["meta"] = invalid_data["meta"].copy()
    invalid_data["meta"]["benchmark_protocol"] = {
        **invalid_data["meta"]["benchmark_protocol"],
        "throughput": {
            **invalid_data["meta"]["benchmark_protocol"]["throughput"],
            "request_mode": "non_streaming",
            "stream_usage_requested": True,
        },
    }

    with pytest.raises(ValidationError, match="stream_usage_requested"):
        BenchmarkResult(**invalid_data)


def test_benchmark_protocol_rejects_invalid_connection_mode():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["meta"] = invalid_data["meta"].copy()
    invalid_data["meta"]["benchmark_protocol"] = {
        **invalid_data["meta"]["benchmark_protocol"],
        "throughput": {
            **invalid_data["meta"]["benchmark_protocol"]["throughput"],
            "connection_mode": "pooled",
        },
    }

    with pytest.raises(ValidationError):
        BenchmarkResult(**invalid_data)


def test_throughput_progress_samples_validate_tps():
    data = EXAMPLE_RESULT.copy()
    data["trials"] = data["trials"].copy()
    data["trials"]["throughput_progress_samples_raw"] = [
        [
            {
                "completion_tokens": 100,
                "elapsed_seconds": elapsed,
                "tokens_per_second": round(100 / elapsed, 2),
                "token_count_source": "usage.completion_tokens",
            }
        ]
        for elapsed in data["trials"]["throughput_elapsed_seconds_raw"]
    ]

    result = BenchmarkResult(**data)

    assert result.trials.throughput_progress_samples_raw[0][0].tokens_per_second == 18.48

def test_throughput_progress_samples_reject_bad_tps():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["trials"] = invalid_data["trials"].copy()
    invalid_data["trials"]["throughput_progress_samples_raw"] = [
        [
            {
                "completion_tokens": 100,
                "elapsed_seconds": 5.0,
                "tokens_per_second": 99.0,
                "token_count_source": "usage.completion_tokens",
            }
        ]
    ] * invalid_data["trials"]["count"]

    with pytest.raises(ValidationError, match="tokens_per_second"):
        BenchmarkResult(**invalid_data)

def test_raw_trial_values_must_be_non_negative():
    """Test that raw trial measurements cannot be negative."""
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["trials"] = invalid_data["trials"].copy()
    invalid_data["trials"]["tokens_per_second_raw"] = [18.48, -1.0, 18.51, 18.48, 18.46]

    with pytest.raises(ValidationError):
        BenchmarkResult(**invalid_data)

def test_trial_stats_range_must_be_consistent():
    """Test that summary stats cannot contradict their min/max range."""
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["metrics"] = invalid_data["metrics"].copy()
    invalid_data["metrics"]["tokens_per_second"] = {
        "mean": 30.0,
        "stddev": 0.1,
        "min": 18.0,
        "max": 20.0,
    }

    with pytest.raises(ValidationError, match="mean must be between"):
        BenchmarkResult(**invalid_data)

def test_trial_stats_rejects_stddev_when_min_equals_max():
    with pytest.raises(ValidationError, match="stddev must be 0"):
        TrialStats(mean=1.0, stddev=0.1, min=1.0, max=1.0)

def test_summary_stats_must_match_raw_trials():
    """Test that summary statistics must be derived from raw trial values."""
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["metrics"] = invalid_data["metrics"].copy()
    invalid_data["metrics"]["ttft_cold"] = invalid_data["metrics"]["ttft_cold"].copy()
    invalid_data["metrics"]["ttft_cold"]["mean"] = 0.05

    with pytest.raises(ValidationError, match="metrics.ttft_cold.mean"):
        BenchmarkResult(**invalid_data)

def test_request_tps_must_match_completion_tokens_and_elapsed():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["trials"] = invalid_data["trials"].copy()
    invalid_data["trials"]["tokens_per_second_raw"] = [
        99.0,
        18.27,
        18.51,
        18.48,
        18.46,
    ]
    invalid_data["metrics"] = invalid_data["metrics"].copy()
    invalid_data["metrics"]["tokens_per_second"] = {
        "mean": 34.544,
        "stddev": 36.032,
        "min": 18.27,
        "max": 99.0,
    }
    invalid_data["metrics"]["request_tokens_per_second"] = {
        **invalid_data["metrics"]["tokens_per_second"]
    }

    with pytest.raises(ValidationError, match="completion token counts"):
        BenchmarkResult(**invalid_data)

def test_throughput_elapsed_seconds_must_be_positive():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["trials"] = invalid_data["trials"].copy()
    invalid_data["trials"]["throughput_elapsed_seconds_raw"] = [
        0.0,
        5.473,
        5.402,
        5.411,
        5.417,
    ]

    with pytest.raises(ValidationError):
        BenchmarkResult(**invalid_data)

def test_p95_is_required_for_large_trial_sets():
    data = EXAMPLE_RESULT.copy()
    data["trials"] = data["trials"].copy()
    data["metrics"] = data["metrics"].copy()
    raw_values = [float(value) for value in range(1, P95_MIN_TRIALS + 1)]
    data["trials"]["count"] = P95_MIN_TRIALS
    data["trials"]["ttft_cold_raw"] = raw_values
    data["trials"]["ttft_cached_raw"] = raw_values
    data["trials"]["tokens_per_second_raw"] = raw_values
    data["trials"]["completion_tokens_raw"] = [100] * P95_MIN_TRIALS
    data["trials"]["throughput_elapsed_seconds_raw"] = [5.0] * P95_MIN_TRIALS
    data["trials"]["decode_tokens_per_second_raw"] = None
    data["metrics"]["decode_tokens_per_second"] = None
    data["metrics"]["decode_timing_source"] = "unavailable"
    data["metrics"]["ttft_cold"] = {
        "mean": 10.5,
        "stddev": 5.916,
        "min": 1.0,
        "max": 20.0,
    }

    with pytest.raises(ValidationError, match="p95"):
        BenchmarkResult(**data)

def test_p95_is_rejected_for_small_trial_sets():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["metrics"] = invalid_data["metrics"].copy()
    invalid_data["metrics"]["tokens_per_second"] = {
        **invalid_data["metrics"]["tokens_per_second"],
        "p95": 18.51,
    }

    with pytest.raises(ValidationError, match="p95 must be omitted"):
        BenchmarkResult(**invalid_data)

def test_timestamp_must_be_timezone_aware():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["meta"] = invalid_data["meta"].copy()
    invalid_data["meta"]["timestamp"] = "2026-05-23T15:08:36"

    with pytest.raises(ValidationError, match="timezone-aware"):
        BenchmarkResult(**invalid_data)


def test_benchmark_protocol_name_must_be_known_profile():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["meta"] = invalid_data["meta"].copy()
    invalid_data["meta"]["benchmark_protocol"] = {
        **invalid_data["meta"]["benchmark_protocol"],
        "name": "custom",
    }

    with pytest.raises(ValidationError):
        BenchmarkResult(**invalid_data)


def test_quantization_is_normalized():
    data = EXAMPLE_RESULT.copy()
    data["model"] = data["model"].copy()
    data["model"]["quantization"] = "4-bit"

    result = BenchmarkResult(**data)
    assert result.model.quantization == "4bit"


def test_model_accepts_optional_identity_metadata():
    data = EXAMPLE_RESULT.copy()
    data["model"] = {
        **data["model"],
        "source": "mlx-community/example",
        "revision": "abc123",
        "weight_hash": "sha256:weights",
        "tokenizer_hash": "sha256:tokenizer",
        "chat_template_hash": "sha256:template",
        "architecture": "qwen3",
    }

    result = BenchmarkResult(**data)

    assert result.model.source == "mlx-community/example"
    assert result.model.revision == "abc123"
    assert result.model.architecture == "qwen3"

def test_uncommon_quantization_is_allowed():
    data = EXAMPLE_RESULT.copy()
    data["model"] = data["model"].copy()
    data["model"]["quantization"] = "q4_k_m"

    result = BenchmarkResult(**data)
    assert result.model.quantization == "q4km"

def test_empty_quantization_is_rejected():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["model"] = invalid_data["model"].copy()
    invalid_data["model"]["quantization"] = "  "

    with pytest.raises(ValidationError, match="quantization must not be empty"):
        BenchmarkResult(**invalid_data)

def test_empty_model_name_is_rejected():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["model"] = invalid_data["model"].copy()
    invalid_data["model"]["name"] = "  "

    with pytest.raises(ValidationError, match="model name must not be empty"):
        BenchmarkResult(**invalid_data)

def test_trial_count_has_maximum():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["trials"] = invalid_data["trials"].copy()
    invalid_data["trials"]["count"] = MAX_TRIALS + 1
    invalid_data["trials"]["ttft_cold_raw"] = [0.1] * (MAX_TRIALS + 1)
    invalid_data["trials"]["ttft_cached_raw"] = [0.1] * (MAX_TRIALS + 1)
    invalid_data["trials"]["tokens_per_second_raw"] = [10.0] * (MAX_TRIALS + 1)

    with pytest.raises(ValidationError):
        BenchmarkResult(**invalid_data)

def test_ram_measurement_method_must_match_boolean():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["metrics"] = invalid_data["metrics"].copy()
    invalid_data["metrics"]["ram_measurement_method"] = "process_rss"

    with pytest.raises(ValidationError, match="ram_measurement_method"):
        BenchmarkResult(**invalid_data)

def test_pre_run_system_ram_baseline_is_rejected():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["hardware"] = invalid_data["hardware"].copy()
    invalid_data["hardware"]["system_ram_usage_percent"] = 50.0

    with pytest.raises(ValidationError):
        BenchmarkResult(**invalid_data)

def test_extra_fields_are_rejected():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["unexpected"] = True

    with pytest.raises(ValidationError):
        BenchmarkResult(**invalid_data)
