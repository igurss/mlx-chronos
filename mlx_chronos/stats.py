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

