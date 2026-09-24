"""Compare two or more local benchmark result files side by side.

The most obvious local use case this project never had a command for: did
throughput change after an engine upgrade, or between two quantizations of
the same model. Every result file already carries everything needed to
answer that; this just loads a few of them and lines the numbers up.

Results need a valid schema and integrity seal, but not the stricter
public-submission conditions. Exploratory local runs remain comparable.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from mlx_chronos.integrity import IntegrityError, validate_integrity_seal
from mlx_chronos.schema import BenchmarkResult


class CompareError(RuntimeError):
    """Raised when a file cannot be loaded and parsed as a benchmark result."""


def load_result_for_compare(path: Path) -> BenchmarkResult:
    """Load and validate one result file for comparison.

    Raises CompareError, naming the offending file, for anything that isn't a
    valid BenchmarkResult — a missing file, invalid JSON, or a file that
    fails schema validation.
    """
    if not path.exists():
        raise CompareError(f"{path}: file not found")
    if not path.is_file():
        raise CompareError(f"{path}: not a file")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CompareError(f"{path}: could not read file: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CompareError(f"{path}: not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CompareError(f"{path}: result must be a JSON object")
    try:
        result = BenchmarkResult(**data)
        validate_integrity_seal(data)
        return result
    except ValidationError as exc:
        raise CompareError(f"{path}: not a valid benchmark result: {exc}") from exc
    except IntegrityError as exc:
        raise CompareError(f"{path}: invalid integrity seal: {exc}") from exc


def _decode_tps_or_none(result: BenchmarkResult) -> float | None:
    stats = result.metrics.decode_tokens_per_second
    return stats.mean if stats is not None else None


# (label, extractor, higher_is_better). higher_is_better only affects how a
# delta is annotated for the person reading it (better/worse), never how it's
# computed.
CompareExtractor = Callable[[BenchmarkResult], "float | None"]
COMPARE_METRICS: list[tuple[str, CompareExtractor, bool]] = [
    ("Request tok/s", lambda r: r.metrics.request_tokens_per_second.mean, True),
    ("Decode tok/s", _decode_tps_or_none, True),
    ("TTFT cold (s)", lambda r: r.metrics.ttft_cold.mean, False),
    ("TTFT cached (s)", lambda r: r.metrics.ttft_cached.mean, False),
    ("RAM peak (GB)", lambda r: r.metrics.system_ram_peak_gb, False),
    ("System RAM rise (GB)", lambda r: r.metrics.system_ram_delta_gb, False),
]


def compare_results(paths: list[Path]) -> dict:
    """Load each path and build a metric-by-metric comparison against the first.

    Returns a dict with:
      - "columns": one entry per file, with identifying metadata
      - "rows": one entry per compared metric, with each file's value and its
        percentage delta against the first file (the "baseline")

    Raises ValueError if fewer than two paths are given, and CompareError
    (via load_result_for_compare) for any file that cannot be loaded.
    """
    if len(paths) < 2:
        raise ValueError("at least two result files are required to compare")

    results = [load_result_for_compare(path) for path in paths]

    baseline_result = results[0]
    warnings: list[str] = []
    if any(
        result.meta.benchmark_profile != baseline_result.meta.benchmark_profile
        for result in results[1:]
    ):
        warnings.append("benchmark profiles differ; throughput deltas are not like-for-like")
    if any(
        (result.hardware.chip, result.hardware.memory_gb)
        != (baseline_result.hardware.chip, baseline_result.hardware.memory_gb)
        for result in results[1:]
    ):
        warnings.append("hardware differs; throughput deltas are not like-for-like")
    if any(
        (result.model.reference_url, result.model.quantization)
        != (baseline_result.model.reference_url, baseline_result.model.quantization)
        for result in results[1:]
    ):
        warnings.append("model reference or quantization differs")
    if any(
        result.meta.benchmark_protocol != baseline_result.meta.benchmark_protocol
        for result in results[1:]
    ):
        warnings.append(
            "benchmark protocol differs; check phase settings before interpreting deltas"
        )

    columns = [
        {
            "path": str(path),
            "engine": result.engine.name,
            "engine_version": result.engine.version,
            "model": result.model.name,
            "quantization": result.model.quantization,
            "chip": result.hardware.chip,
            "benchmark_profile": result.meta.benchmark_profile,
            "timestamp": result.meta.timestamp.isoformat(),
        }
        for path, result in zip(paths, results)
    ]

    rows = []
    for label, extractor, higher_is_better in COMPARE_METRICS:
        values = [extractor(result) for result in results]
        baseline = values[0]
        deltas_percent = [
            None
            if baseline is None or value is None or baseline == 0
            else round(100.0 * (value - baseline) / baseline, 1)
            for value in values
        ]
        rows.append(
            {
                "label": label,
                "values": values,
                "deltas_percent": deltas_percent,
                "higher_is_better": higher_is_better,
            }
        )

    return {"columns": columns, "rows": rows, "warnings": warnings}
