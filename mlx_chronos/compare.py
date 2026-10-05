"""Compare sealed local results with pairwise, metric-specific cautions.

Exploratory comparisons do not need public-submission eligibility. Differences
and missing evidence are reported without certifying equivalence or causality.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypedDict

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
    except (OSError, UnicodeError) as exc:
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
REQUEST_TPS = "Request tok/s"
DECODE_TPS = "Decode tok/s"
TTFT_COLD = "TTFT cold (s)"
TTFT_CACHED = "TTFT cached (s)"
RAM_PEAK = "RAM peak (GB)"
RAM_RISE = "System RAM rise (GB)"
COMPARE_METRICS: list[tuple[str, CompareExtractor, bool]] = [
    (REQUEST_TPS, lambda r: r.metrics.request_tokens_per_second.mean, True),
    (DECODE_TPS, _decode_tps_or_none, True),
    (TTFT_COLD, lambda r: r.metrics.ttft_cold.mean, False),
    (TTFT_CACHED, lambda r: r.metrics.ttft_cached.mean, False),
    (RAM_PEAK, lambda r: r.metrics.system_ram_peak_gb, False),
    (RAM_RISE, lambda r: r.metrics.system_ram_delta_gb, False),
]


ALL_METRICS = tuple(label for label, _, _ in COMPARE_METRICS)
THROUGHPUT_METRICS = (REQUEST_TPS, DECODE_TPS)
RAM_METRICS = (RAM_PEAK, RAM_RISE)
TTFT_METRICS = (TTFT_COLD, TTFT_CACHED)
# Earlier phases can affect later measurements through cache/thermal state.
# The cached phase also describes its unrecorded priming request. System RAM
# sampling starts before warmup and spans every phase, unlike process RSS.
PHASE_METRICS = {
    "warmup": ALL_METRICS,
    "ttft_cold": ALL_METRICS,
    "ttft_cached": (TTFT_CACHED, *THROUGHPUT_METRICS, *RAM_METRICS),
    "throughput": (*THROUGHPUT_METRICS, *RAM_METRICS),
}


class ComparisonWarning(TypedDict):
    baseline_index: int
    result_index: int
    metrics: tuple[str, ...]
    kind: Literal["difference", "incomplete", "run_warning"]
    field: str
    baseline_value: object
    value: object
    message: str


def _unknown(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {
            "",
            "unknown",
            "unavailable",
            "n/a",
        } or normalized.startswith("unavailable_")
    return False


def _pair_warnings(
    baseline: BenchmarkResult, result: BenchmarkResult, index: int
) -> list[ComparisonWarning]:
    warnings: list[ComparisonWarning] = []

    def add(
        field: str,
        left: object,
        right: object,
        metrics: tuple[str, ...],
        kind: Literal["difference", "incomplete", "run_warning"],
        message: str,
    ) -> None:
        warnings.append(
            {
                "baseline_index": 0,
                "result_index": index,
                "metrics": metrics,
                "kind": kind,
                "field": field,
                "baseline_value": left,
                "value": right,
                "message": message,
            }
        )

    def check(
        field: str,
        left: object,
        right: object,
        metrics: tuple[str, ...] = ALL_METRICS,
        *,
        category: str,
        none_is_known: bool = False,
    ) -> None:
        if (_unknown(left) and not (left is None and none_is_known)) or (
            _unknown(right) and not (right is None and none_is_known)
        ):
            add(
                field,
                left,
                right,
                metrics,
                "incomplete",
                f"incomplete information: {field}",
            )
        elif left != right:
            message = f"{category} differs: {field}"
            if (
                field.endswith(".prompts")
                and isinstance(left, list)
                and isinstance(right, list)
            ):
                positions = [
                    str(i + 1)
                    for i in range(max(len(left), len(right)))
                    if i >= len(left) or i >= len(right) or left[i] != right[i]
                ]
                message += f" (changed prompt positions: {', '.join(positions)})"
            add(field, left, right, metrics, "difference", message)

    check(
        "meta.benchmark_profile",
        baseline.meta.benchmark_profile,
        result.meta.benchmark_profile,
        category="benchmark profile",
    )
    check(
        "hardware.chip",
        baseline.hardware.chip,
        result.hardware.chip,
        category="hardware",
    )
    check(
        "hardware.memory_gb",
        baseline.hardware.memory_gb or None,
        result.hardware.memory_gb or None,
        category="hardware",
    )
    for field in ("name", "reference_url", "quantization", "format"):
        check(
            f"model.{field}",
            getattr(baseline.model, field),
            getattr(result.model, field),
            category="model",
        )
    # Engine upgrades are often the variable under study. Only unknown versions
    # need a caution; known versions remain visible in the identifying columns.
    if _unknown(baseline.engine.version) or _unknown(result.engine.version):
        check(
            "engine.version",
            baseline.engine.version,
            result.engine.version,
            category="engine version",
        )
    check(
        "metrics.token_count_source",
        baseline.metrics.token_count_source,
        result.metrics.token_count_source,
        THROUGHPUT_METRICS,
        category="completion token count provenance",
    )
    check(
        "trials.count",
        baseline.trials.count,
        result.trials.count,
        category="trial count",
    )
    check(
        "meta.ram_sample_interval_seconds",
        baseline.meta.ram_sample_interval_seconds,
        result.meta.ram_sample_interval_seconds,
        RAM_METRICS,
        category="RAM sampling interval",
    )
    check(
        "meta.benchmark_protocol.version",
        baseline.meta.benchmark_protocol.version,
        result.meta.benchmark_protocol.version,
        category="benchmark protocol",
    )
    for phase, metrics in PHASE_METRICS.items():
        left_phase = getattr(baseline.meta.benchmark_protocol, phase)
        right_phase = getattr(result.meta.benchmark_protocol, phase)
        left, right = left_phase.model_dump(), right_phase.model_dump()
        prefix = f"meta.benchmark_protocol.{phase}"
        for field in (
            "prompts",
            "requested_max_tokens",
            "requested_min_tokens",
            "request_mode",
            "stream_usage_requested",
            "connection_mode",
            "input_tokens",
        ):
            # An explicit None means no minimum requested. An omitted optional
            # field remains unknown, even if schema parsing supplies None.
            check(
                f"{prefix}.{field}",
                left[field],
                right[field],
                metrics,
                category="benchmark protocol",
                none_is_known=(
                    field == "requested_min_tokens"
                    and field in left_phase.model_fields_set
                    and field in right_phase.model_fields_set
                ),
            )
        if left["input_tokens"] is not None and right["input_tokens"] is not None:
            check(
                f"{prefix}.input_token_count_source",
                left["input_token_count_source"],
                right["input_token_count_source"],
                metrics,
                category="input token count provenance",
            )
        for field in ("temperature", "top_p"):
            check(
                f"{prefix}.generation_parameters.{field}",
                left["generation_parameters"][field],
                right["generation_parameters"][field],
                metrics,
                category="benchmark protocol",
            )

    left_cache, right_cache = (
        baseline.meta.cache_validation,
        result.meta.cache_validation,
    )
    if left_cache is None or right_cache is None:
        add(
            "meta.cache_validation",
            left_cache.model_dump() if left_cache else None,
            right_cache.model_dump() if right_cache else None,
            TTFT_METRICS,
            "incomplete",
            "incomplete information: cache validation evidence",
        )
    else:
        check(
            "meta.cache_validation.source",
            left_cache.source if "source" in left_cache.model_fields_set else None,
            right_cache.source if "source" in right_cache.model_fields_set else None,
            TTFT_METRICS,
            category="cache validation method",
        )
        check(
            "meta.cache_validation.cold_cache_cleared",
            left_cache.cold_cache_cleared
            if "cold_cache_cleared" in left_cache.model_fields_set
            else None,
            right_cache.cold_cache_cleared
            if "cold_cache_cleared" in right_cache.model_fields_set
            else None,
            (TTFT_COLD,),
            category="cold cache clearing evidence",
        )
        if (
            not left_cache.cached_prefix_hit_verified
            or not right_cache.cached_prefix_hit_verified
        ):
            add(
                "meta.cache_validation.cached_prefix_hit_verified",
                left_cache.cached_prefix_hit_verified
                if "cached_prefix_hit_verified" in left_cache.model_fields_set
                else None,
                right_cache.cached_prefix_hit_verified
                if "cached_prefix_hit_verified" in right_cache.model_fields_set
                else None,
                (TTFT_CACHED,),
                "incomplete",
                "incomplete information: cached prefix hit is not API-verified in both results",
            )
    for field, metrics, message in (
        ("warmup_failures", ALL_METRICS, "warmup calls failed before measurement"),
        ("cached_ttft_warning", (TTFT_CACHED,), "cached TTFT is close to cold TTFT"),
        (
            "sustained_throttling_warning",
            THROUGHPUT_METRICS,
            "sustained throughput drop with thermal pressure",
        ),
    ):
        left_value, right_value = (
            getattr(baseline.meta, field),
            getattr(result.meta, field),
        )
        if left_value or right_value:
            add(
                f"meta.{field}",
                left_value,
                right_value,
                metrics,
                "run_warning",
                message,
            )
    return warnings


def _delta(
    value: float | None,
    baseline: float | None,
    *,
    token_sources: tuple[str, str] | None,
) -> tuple[float | None, str, str | None]:
    """Return a descriptive delta, its qualification, and any refusal reason."""
    if baseline is None or value is None:
        return None, "unavailable", "metric missing from reference or result"
    if baseline == 0:
        return None, "unavailable", "reference value is zero"
    status = "descriptive"
    if token_sources is not None:
        left, right = token_sources
        if "mixed" in token_sources:
            return None, "unavailable", "mixed completion token counts"
        if left != right:
            return (
                None,
                "unavailable",
                "exact and estimated completion counts use different units",
            )
        if left == "word_fallback":
            status = "estimated"
    return round(100.0 * (value - baseline) / baseline, 1), status, None


def compare_results(paths: list[Path]) -> dict:
    """Load each path and build a metric-by-metric comparison against the first.

    Returns a dict with:
      - "columns": one entry per file, with identifying metadata
      - "rows": one entry per compared metric, with each file's value and its
        percentage delta against the first file (the "baseline"), its status
        (descriptive/estimated/unavailable), and any unavailability reason
      - "warnings": structured cautions scoped to one baseline/result pair
        and the metrics affected; missing evidence is distinct from differences

    Raises ValueError if fewer than two paths are given, and CompareError
    (via load_result_for_compare) for any file that cannot be loaded.
    """
    if len(paths) < 2:
        raise ValueError("at least two result files are required to compare")

    results = [load_result_for_compare(path) for path in paths]

    baseline_result = results[0]
    warnings = [
        warning
        for index, result in enumerate(results[1:], start=1)
        for warning in _pair_warnings(baseline_result, result, index)
    ]

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
        deltas = [
            _delta(
                value,
                baseline,
                token_sources=(
                    baseline_result.metrics.token_count_source,
                    result.metrics.token_count_source,
                )
                if label in THROUGHPUT_METRICS
                else None,
            )
            for value, result in zip(values, results)
        ]
        rows.append(
            {
                "label": label,
                "values": values,
                "deltas_percent": [delta[0] for delta in deltas],
                "delta_status": [delta[1] for delta in deltas],
                "delta_reasons": [delta[2] for delta in deltas],
                "higher_is_better": higher_is_better,
            }
        )

    return {"columns": columns, "rows": rows, "warnings": warnings}
