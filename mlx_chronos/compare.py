"""Compare sealed local results with pairwise, metric-specific cautions.

Exploratory comparisons do not need public-submission eligibility. Differences
and missing evidence are reported without certifying equivalence or causality.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypedDict

from pydantic import ValidationError

from mlx_chronos.integrity import IntegrityError, validate_integrity_seal
from mlx_chronos.schema import BenchmarkResult
from mlx_chronos.stats import compute_series_stats


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


# Metric direction is metadata; it never changes a descriptive delta's sign.
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
    baseline: BenchmarkResult,
    result: BenchmarkResult,
    index: int,
    *,
    within_series: bool = False,
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
        warning: ComparisonWarning = {
            "baseline_index": 0,
            "result_index": index,
            "metrics": metrics,
            "kind": kind,
            "field": field,
            "baseline_value": left,
            "value": right,
            "message": message,
        }
        if warning not in warnings:
            warnings.append(warning)

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
    # Across series, engine upgrades may be the variable under study. Within
    # one series, report differing names/versions as well as unknown versions.
    if within_series:
        for field in ("name", "version"):
            check(
                f"engine.{field}",
                getattr(baseline.engine, field),
                getattr(result.engine, field),
                category="engine",
            )
    elif _unknown(baseline.engine.version) or _unknown(result.engine.version):
        check(
            "engine.version",
            baseline.engine.version,
            result.engine.version,
            category="engine version",
        )
    for field in ("power_source", "low_power_mode"):
        check(f"hardware.{field}", getattr(baseline.hardware, field),
              getattr(result.hardware, field), category="power conditions")
        left, right = getattr(baseline.hardware, field), getattr(result.hardware, field)
        concerning = "battery" if field == "power_source" else "on"
        if concerning in (left, right):
            add(f"hardware.{field}", left, right, ALL_METRICS, "run_warning",
                f"measurement conditions include {field}={concerning}")
    for section in ("observed", "declared"):
        values = [getattr(item.engine.serving_config, section, None) for item in (baseline, result)]
        if section == "declared":
            # No manual claims is known absence, not missing observation.
            values = [value or {} for value in values]
        else:
            values = [value or None for value in values]
        check(f"engine.serving_config.{section}", values[0], values[1],
              category=f"server configuration ({section})")
    progress_invalid = any(
        item.progress_chronology_issue(index)
        for item in (baseline, result) for index in range(item.trials.count)
    )
    for item in (baseline, result):
        if item.engine.version_source in {"client_cli", "client_package"}:
            add("engine.version_source", baseline.engine.version_source, result.engine.version_source,
                ALL_METRICS, "incomplete", "engine version detected locally; serving version is unverified")
        elif item.engine.version_source == "process_package":
            add("engine.version_source", baseline.engine.version_source, result.engine.version_source,
                ALL_METRICS, "incomplete", "version read from the server process installation; the loaded runtime did not report its version")
    if progress_invalid:
        add("trials.throughput_progress_samples_raw", None, None,
            THROUGHPUT_METRICS, "run_warning",
            "legacy progress has inconsistent chronology; do not use it to interpret within-trial trends or throttling")
    for field in ("source", "worst_state", "non_nominal_phases", "sampling_errors"):
        values = [getattr(item.meta.thermal_monitor, field)
                  if field in item.meta.thermal_monitor.model_fields_set else None
                  for item in (baseline, result)]
        check(f"meta.thermal_monitor.{field}", values[0], values[1], category="thermal conditions")
    for item in (baseline, result):
        monitor = item.meta.thermal_monitor
        if (monitor.non_nominal_observed or monitor.sampling_errors
                or monitor.sample_span_seconds is None):
            add("meta.thermal_monitor", baseline.meta.thermal_monitor.model_dump(),
                result.meta.thermal_monitor.model_dump(), ALL_METRICS,
                "run_warning" if monitor.non_nominal_observed or monitor.sampling_errors else "incomplete",
                "thermal pressure, sampling errors, or undocumented thermal coverage")
            break
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
        left_tokens, right_tokens = left_phase.input_tokens, right_phase.input_tokens
        if phase != "throughput" and left_tokens is None and right_tokens is None:
            # Standard warmup/TTFT requests do not collect input usage. Its
            # absence on both sides is expected, not a failed observation.
            pass
        elif (
            left_tokens is None or right_tokens is None
            or (None not in left_tokens and None not in right_tokens)
        ):
            check(
                f"{prefix}.input_tokens", left_tokens, right_tokens, metrics,
                category="input token count metadata",
            )
        else:
            add(
                f"{prefix}.input_tokens", left_tokens, right_tokens, metrics,
                "incomplete", "incomplete information: "
                f"{prefix}.input_tokens (some prompt counts are unavailable)",
            )
            changed_positions = [
                str(i + 1)
                for i, (a, b) in enumerate(zip(left_tokens, right_tokens))
                if a is not None and b is not None and a != b
            ]
            if changed_positions:
                add(
                    f"{prefix}.input_tokens", left_tokens, right_tokens, metrics,
                    "difference", "input token counts differ: "
                    f"{prefix}.input_tokens (prompt positions: {', '.join(changed_positions)})",
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
    for field in ("system_ram_monitor_errors", "engine_ram_monitor_errors", "memory_pressure_warning"):
        if any(field not in item.meta.model_fields_set for item in (baseline, result)):
            add(f"meta.{field}",
                getattr(baseline.meta, field) if field in baseline.meta.model_fields_set else None,
                getattr(result.meta, field) if field in result.meta.model_fields_set else None,
                ALL_METRICS if field == "memory_pressure_warning" else RAM_METRICS,
                "incomplete", f"incomplete information: {field}")
    for field, metrics, message in (
        ("warmup_failures", ALL_METRICS, "warmup calls failed before measurement"),
        ("memory_pressure_warning", ALL_METRICS, "system-wide swap grew during measurement"),
        ("system_ram_monitor_errors", RAM_METRICS, "system RAM monitoring was incomplete"),
        ("engine_ram_monitor_errors", RAM_METRICS, "engine RAM monitoring was incomplete"),
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
            if field == "sustained_throttling_warning" and progress_invalid:
                message = "recorded sustained warning is unverified because legacy progress chronology is inconsistent"
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


def summarize_results(results: list[BenchmarkResult]) -> dict:
    """One observation per complete session, never a pool of unlike prompts."""
    if not results:
        raise ValueError("at least one session is required")
    raw_fields = {
        REQUEST_TPS: "tokens_per_second_raw",
        DECODE_TPS: "decode_tokens_per_second_raw",
        TTFT_COLD: "ttft_cold_raw",
        TTFT_CACHED: "ttft_cached_raw",
    }
    sources = {result.metrics.token_count_source for result in results}
    token_source = next(iter(sources)) if len(sources) == 1 else "mixed"
    rows = []
    for label, extractor, higher_is_better in COMPARE_METRICS:
        values = []
        for result in results:
            if label in raw_fields:
                raw = getattr(result.trials, raw_fields[label])
                values.append(statistics.mean(raw) if raw is not None else None)
            else:
                values.append(extractor(result))
        incompatible_units = label in THROUGHPUT_METRICS and token_source == "mixed"
        rows.append(
            {
                "label": label,
                "values": values,
                "stats": None if incompatible_units else compute_series_stats(values),
                "unavailable_reason": "incompatible completion count units within series"
                if incompatible_units
                else None,
                "higher_is_better": higher_is_better,
            }
        )
    return {"count": len(results), "token_count_source": token_source, "rows": rows}


def _load_series(
    paths: list[Path],
) -> tuple[list[BenchmarkResult], list[Path], list[Path]]:
    if not paths:
        raise ValueError("each series requires at least one result file")
    results: list[BenchmarkResult] = []
    unique_paths: list[Path] = []
    duplicates: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        result = load_result_for_compare(path)
        if result.integrity.digest in seen:
            duplicates.append(path)
        else:
            seen.add(result.integrity.digest)
            results.append(result)
            unique_paths.append(path)
    return results, unique_paths, duplicates


def series_warnings(
    results: list[BenchmarkResult], *, offset: int = 0
) -> list[ComparisonWarning]:
    """Assess each member against its series reference, preserving pair indices."""
    warnings = []
    for index, result in enumerate(results[1:], start=1):
        for warning in _pair_warnings(results[0], result, index, within_series=True):
            warning["baseline_index"] += offset
            warning["result_index"] += offset
            warnings.append(warning)
    return warnings


def compare_series(paths_a: list[Path], paths_b: list[Path]) -> dict:
    """Describe two explicitly selected series; do not infer campaign identity."""
    results_a, unique_a, duplicates_a = _load_series(paths_a)
    results_b, unique_b, duplicates_b = _load_series(paths_b)
    digests_a = {result.integrity.digest for result in results_a}
    for path, result in zip(unique_b, results_b):
        if result.integrity.digest in digests_a:
            raise CompareError(
                f"{path}: the same benchmark result appears in both series; choose disjoint series"
            )
    summary_a, summary_b = summarize_results(results_a), summarize_results(results_b)
    warnings = series_warnings(results_a) + series_warnings(
        results_b, offset=len(results_a)
    )
    warnings += [
        warning
        for index, result in enumerate(results_b, start=len(results_a))
        for warning in _pair_warnings(results_a[0], result, index)
    ]
    rows = []
    for left, right in zip(summary_a["rows"], summary_b["rows"]):
        values = [
            row["stats"]["median"] if row["stats"] is not None else None
            for row in (left, right)
        ]
        reason = left["unavailable_reason"] or right["unavailable_reason"]
        delta = (
            (None, "unavailable", reason)
            if reason
            else _delta(
                values[1],
                values[0],
                token_sources=(
                    summary_a["token_count_source"],
                    summary_b["token_count_source"],
                )
                if left["label"] in THROUGHPUT_METRICS
                else None,
            )
        )
        rows.append(
            {
                "label": left["label"],
                "values": values,
                "delta_percent": delta[0],
                "delta_status": delta[1],
                "delta_reason": delta[2],
            }
        )
    return {
        "summaries": [summary_a, summary_b],
        "rows": rows,
        "warnings": warnings,
        "columns": _comparison_columns(unique_a + unique_b, results_a + results_b),
        "labels": [f"A[{i + 1}]" for i in range(len(results_a))]
        + [f"B[{i + 1}]" for i in range(len(results_b))],
        "ignored_duplicates": duplicates_a + duplicates_b,
    }


def _comparison_columns(
    paths: list[Path], results: list[BenchmarkResult]
) -> list[dict]:
    return [
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

    columns = _comparison_columns(paths, results)

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
