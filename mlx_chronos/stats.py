import math
import statistics

from mlx_chronos.constants import P95_MIN_TRIALS


def compute_stats(values: list[float], *, round_digits: int | None = 3) -> dict:
    """Compute summary statistics from a non-empty list of measurements."""
    if not values:
        raise ValueError("values must contain at least one measurement")

    def stored(value: float) -> float:
        return value if round_digits is None else round(value, round_digits)

    mean = statistics.mean(values)
    stddev = statistics.stdev(values) if len(values) > 1 else 0.0
    result = {
        "mean": stored(mean),
        "stddev": stored(stddev),
        "min": stored(min(values)),
        "max": stored(max(values)),
    }
    if len(values) >= P95_MIN_TRIALS:
        sorted_values = sorted(values)
        p95_index = math.ceil(0.95 * len(sorted_values)) - 1
        result["p95"] = stored(sorted_values[p95_index])
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
