import math
import statistics

from mlx_chronos.constants import P95_MIN_TRIALS


def compute_stats(values: list[float]) -> dict:
    """Compute summary statistics from a non-empty list of measurements."""
    if not values:
        raise ValueError("values must contain at least one measurement")

    mean = statistics.mean(values)
    stddev = statistics.stdev(values) if len(values) > 1 else 0.0
    result = {
        "mean": round(mean, 3),
        "stddev": round(stddev, 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }
    if len(values) >= P95_MIN_TRIALS:
        sorted_values = sorted(values)
        p95_index = math.ceil(0.95 * len(sorted_values)) - 1
        result["p95"] = round(sorted_values[p95_index], 3)
    return result


def compute_series_stats(values: list[float | None]) -> dict:
    """Describe session-level observations without claiming independence.

    Quartiles use the inclusive interpolation convention. MAD is unscaled.
    A single observation has no measured between-session dispersion. Values
    remain unrounded until presentation, and missing observations stay counted.
    """
    available = [value for value in values if value is not None]
    if any(not math.isfinite(value) for value in available):
        raise ValueError("series observations must be finite")
    count = len(available)
    result: dict = dict.fromkeys(
        ("mean", "median", "stddev", "min", "max", "q1", "q3", "mad")
    )
    result.update(count=count, missing=len(values) - count)
    if not count:
        return result
    median = statistics.median(available)
    result.update(
        mean=statistics.mean(available),
        median=median,
        min=min(available),
        max=max(available),
    )
    if count > 1:
        quartiles = statistics.quantiles(available, n=4, method="inclusive")
        result.update(
            stddev=statistics.stdev(available),
            q1=quartiles[0],
            q3=quartiles[2],
            mad=statistics.median(abs(value - median) for value in available),
        )
    return result
