import pytest
from mlx_chronos.benchmark import compute_stats

def test_compute_stats_normal():
    values = [10.0, 12.0, 14.0, 16.0, 18.0]
    stats = compute_stats(values)
    assert stats["mean"] == 14.0
    assert stats["stddev"] == pytest.approx(3.162, 0.01)
    assert stats["min"] == 10.0
    assert stats["max"] == 18.0

def test_compute_stats_empty():
    with pytest.raises(ValueError, match="at least one measurement"):
        compute_stats([])

def test_compute_stats_single():
    values = [10.0]
    stats = compute_stats(values)
    assert stats["mean"] == 10.0
    assert stats["stddev"] == 0.0
    assert stats["min"] == 10.0
    assert stats["max"] == 10.0

def test_compute_stats_rounding():
    values = [10.1234, 10.5678]
    stats = compute_stats(values)
    # The compute_stats function rounds to 3 decimal places
    assert stats["mean"] == 10.346
    assert stats["min"] == 10.123
    assert stats["max"] == 10.568
