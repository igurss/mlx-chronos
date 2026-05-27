from datetime import datetime

import pytest
from pydantic import ValidationError
from mlx_chronos.schema import BenchmarkResult, EXAMPLE_RESULT

def test_valid_schema():
    """Test that the example result is fully valid."""
    result = BenchmarkResult(**EXAMPLE_RESULT)
    assert result.engine.name == "omlx"
    assert result.metrics.tokens_per_second.mean == 18.44
    assert isinstance(result.meta.timestamp, datetime)
    assert result.meta.ram_sample_interval_seconds == 0.05
    assert result.hardware.architecture == "arm64"
    assert result.metrics.token_count_source == "usage.completion_tokens"
    assert result.metrics.ram_measurement_method == "system_fallback"
    assert result.metrics.system_ram_peak_gb == 7.22
    assert result.metrics.system_ram_peak_percent == 90.2

def test_invalid_engine_name():
    """Test that an unknown engine name raises a validation error."""
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["engine"] = invalid_data["engine"].copy()
    invalid_data["engine"]["name"] = "unknown-engine"
    
    with pytest.raises(ValidationError):
        BenchmarkResult(**invalid_data)

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

def test_summary_stats_must_match_raw_trials():
    """Test that summary statistics must be derived from raw trial values."""
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["metrics"] = invalid_data["metrics"].copy()
    invalid_data["metrics"]["ttft_cold"] = invalid_data["metrics"]["ttft_cold"].copy()
    invalid_data["metrics"]["ttft_cold"]["mean"] = 0.05

    with pytest.raises(ValidationError, match="metrics.ttft_cold.mean"):
        BenchmarkResult(**invalid_data)

def test_timestamp_must_be_timezone_aware():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["meta"] = invalid_data["meta"].copy()
    invalid_data["meta"]["timestamp"] = "2026-05-23T15:08:36"

    with pytest.raises(ValidationError, match="timezone-aware"):
        BenchmarkResult(**invalid_data)

def test_quantization_is_normalized():
    data = EXAMPLE_RESULT.copy()
    data["model"] = data["model"].copy()
    data["model"]["quantization"] = "4-bit"

    result = BenchmarkResult(**data)
    assert result.model.quantization == "4bit"

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

def test_trial_count_has_maximum():
    invalid_data = EXAMPLE_RESULT.copy()
    invalid_data["trials"] = invalid_data["trials"].copy()
    invalid_data["trials"]["count"] = 9
    invalid_data["trials"]["ttft_cold_raw"] = [0.1] * 9
    invalid_data["trials"]["ttft_cached_raw"] = [0.1] * 9
    invalid_data["trials"]["tokens_per_second_raw"] = [10.0] * 9

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
