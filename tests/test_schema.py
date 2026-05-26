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
