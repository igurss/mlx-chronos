import math

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
