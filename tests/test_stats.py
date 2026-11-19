import math
import statistics
import sys

import pytest

from mlx_chronos.stats import compute_series_stats


def test_series_stats_preserve_an_extreme_observation_and_show_robust_center():
    stats = compute_series_stats([10, 11, 12, 13, 100])
    assert stats["count"] == 5
    assert stats["mean"] == 29.2
    assert stats["median"] == 12
    assert stats["mad"] == 1
    assert (stats["q1"], stats["q3"]) == (11, 13)
    assert (stats["min"], stats["max"]) == (10, 100)


def test_two_observations_use_inclusive_quartiles_and_sample_deviation():
    stats = compute_series_stats([10, None, 14, None])
    assert (stats["count"], stats["missing"]) == (2, 2)
    assert (stats["mean"], stats["median"], stats["mad"]) == (12, 12, 2)
    assert (stats["q1"], stats["q3"]) == (11, 13)
    assert stats["stddev"] == pytest.approx(math.sqrt(8))


@pytest.mark.parametrize("values", [[], [None, None]])
def test_unavailable_observations_do_not_become_zeroes(values):
    stats = compute_series_stats(values)
    assert stats["count"] == 0
    assert stats["missing"] == len(values)
    assert all(
        stats[key] is None
        for key in ("mean", "median", "min", "max", "stddev", "q1", "q3", "mad")
    )


def test_one_session_has_no_between_session_dispersion():
    stats = compute_series_stats([12, None])
    assert stats["count"] == 1
    assert stats["mean"] == stats["median"] == stats["min"] == stats["max"] == 12
    assert all(stats[key] is None for key in ("stddev", "q1", "q3", "mad"))


def test_small_latency_variation_is_not_rounded_away():
    stats = compute_series_stats([0.000101, 0.000102, 0.000105])
    assert stats["mean"] == pytest.approx(0.00010266666666666666)
    assert stats["mad"] == pytest.approx(0.000001)
    assert stats["stddev"] > 0


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_series_stats_reject_non_finite_observations(value):
    with pytest.raises(ValueError, match="finite"):
        compute_series_stats([10, value])


@pytest.mark.parametrize("value", [1e308, sys.float_info.max])
def test_large_constant_series_has_finite_center_and_zero_dispersion(value):
    stats = compute_series_stats([value, None, value])
    assert (stats["count"], stats["missing"]) == (2, 1)
    assert all(stats[key] == value for key in ("mean", "median", "min", "max", "q1", "q3"))
    assert stats["mad"] == stats["stddev"] == 0.0


def test_large_series_retains_interpolated_center_and_dispersion():
    stats = compute_series_stats([1e308, 1.2e308])
    assert stats["median"] == pytest.approx(1.1e308)
    assert stats["q1"] == pytest.approx(1.05e308)
    assert stats["q3"] == pytest.approx(1.15e308)
    assert stats["mad"] == pytest.approx(1e307)
    assert stats["stddev"] == pytest.approx(math.sqrt(2) * 1e307)


def test_tiny_observations_survive_an_extreme_outlier():
    stats = compute_series_stats([1e-308, 2e-308, 1e308])
    assert stats["median"] == 2e-308
    assert stats["q1"] == pytest.approx(1.5e-308, rel=1e-12, abs=0)
    assert stats["mad"] == pytest.approx(1e-308, rel=1e-12, abs=0)
    assert all(math.isfinite(stats[key]) for key in ("mean", "stddev", "q3"))


def test_opposite_large_values_have_finite_quartiles_and_mad():
    stats = compute_series_stats([-1e308, 1e308])
    assert stats["median"] == 0.0
    assert (stats["q1"], stats["q3"]) == (-5e307, 5e307)
    assert stats["mad"] == 1e308
    assert stats["stddev"] == pytest.approx(math.sqrt(2) * 1e308)


def test_neighbouring_large_values_preserve_small_relative_dispersion():
    left = 1e308
    right = math.nextafter(left, math.inf)
    stats = compute_series_stats([left, right])
    assert stats["mad"] == (right - left) / 2
    assert stats["stddev"] == pytest.approx((right - left) / math.sqrt(2), rel=1e-14)


def test_unrepresentable_integer_reports_a_numeric_error():
    with pytest.raises(ValueError, match="finite floating-point"):
        compute_series_stats([10**1000])


def test_unrepresentable_standard_deviation_reports_a_numeric_error():
    with pytest.raises(ValueError, match="standard deviation.*floating-point range"):
        compute_series_stats([-sys.float_info.max, sys.float_info.max])


def test_python310_variance_overflow_preserves_representable_deviation(monkeypatch):
    # Python 3.10 converts variance before taking its root; reproduce that
    # standard-library path without requiring a second installed interpreter.
    def legacy_stdev(values):
        variance = statistics.variance(values)
        return variance.sqrt() if hasattr(variance, "sqrt") else math.sqrt(variance)

    monkeypatch.setattr(statistics, "stdev", legacy_stdev)
    left = 1e308
    right = math.nextafter(left, math.inf)
    stats = compute_series_stats([left, right])
    assert stats["stddev"] == pytest.approx((right - left) / math.sqrt(2), rel=1e-14)
