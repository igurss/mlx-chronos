"""Validation and index generation for the public benchmark archive."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Iterable

from mlx_chronos.constants import (
    DEFAULT_THROUGHPUT_MAX_TOKENS,
    PUBLIC_BASELINE_TRIALS,
    PUBLIC_MIN_COMPLETION_TOKEN_RATIO,
    SUSTAINED_THROUGHPUT_MAX_TOKENS,
    SUSTAINED_TRIALS,
)
from mlx_chronos.schema import BenchmarkResult
from mlx_chronos.submit import load_publishable_result


class DuplicateResultError(ValueError):
    """Raised when the public archive contains the same result more than once."""


@dataclass(frozen=True)
class ArchiveResult:
    path: Path
    result: BenchmarkResult


def model_identity(result: BenchmarkResult) -> tuple[str, ...]:
    model = result.model
    return (
        model.name,
        model.quantization,
        model.format or "",
        model.reference_url or "",
    )


def run_identity(result: BenchmarkResult) -> tuple[str, ...]:
    hardware = result.hardware
    engine = result.engine
    return (
        result.meta.timestamp.isoformat(),
        hardware.architecture,
        hardware.chip,
        hardware.machine_model,
        engine.name,
        engine.version,
        result.meta.benchmark_profile,
        *model_identity(result),
    )


def assert_unique_results(records: Iterable[ArchiveResult]) -> None:
    digests: dict[str, Path] = {}
    identities: dict[tuple[str, ...], Path] = {}
    errors: list[str] = []

    for record in records:
        digest = record.result.integrity.digest
        previous_digest = digests.get(digest)
        if previous_digest is not None:
            errors.append(
                f"duplicate digest in {record.path} and {previous_digest}: {digest}"
            )
        else:
            digests[digest] = record.path

        identity = run_identity(record.result)
        previous_identity = identities.get(identity)
        if previous_identity is not None:
            errors.append(
                "duplicate run identity in "
                f"{record.path} and {previous_identity}: {identity[0]}"
            )
        else:
            identities[identity] = record.path

    if errors:
        raise DuplicateResultError("\n".join(errors))


def load_archive_results(results_dir: Path) -> list[ArchiveResult]:
    records: list[ArchiveResult] = []
    errors: list[str] = []
    for path in sorted(results_dir.rglob("*.json")):
        try:
            _, result = load_publishable_result(
                path,
                allow_legacy_missing_model_reference=True,
                allow_legacy_missing_ollama_model_format=True,
                allow_legacy_missing_decode_elapsed=True,
                allow_legacy_missing_monitor_diagnostics=True,
            )
            records.append(ArchiveResult(path=path, result=result))
        except Exception as exc:
            errors.append(f"{path}: {exc}")

    if errors:
        raise ValueError("invalid submitted result file(s):\n" + "\n".join(errors))
    assert_unique_results(records)
    return records


def _headroom_gb(memory_gb: object, peak_gb: object) -> float | None:
    """Return estimated unused RAM at peak as whole-device stress context."""
    if not isinstance(memory_gb, (int, float)) or not isinstance(peak_gb, (int, float)):
        return None
    return round(max(0.0, float(memory_gb) - float(peak_gb)), 3)


def _index_row(result: BenchmarkResult) -> dict[str, object]:
    data = result.model_dump(mode="json", by_alias=True)
    hardware = data["hardware"]
    engine = data["engine"]
    model = data["model"]
    metrics = data["metrics"]
    trials = data["trials"]
    meta = data["meta"]
    decode_stats = metrics.get("decode_tokens_per_second") or {}

    return {
        "chip": hardware["chip"],
        "memory_gb": hardware["memory_gb"],
        "macos_version": hardware["macos_version"],
        "machine_model": hardware["machine_model"],
        "engine": engine["name"],
        "engine_version": engine["version"],
        "engine_serving_config": engine.get("serving_config"),
        "model": model["name"],
        "quantization": model["quantization"],
        "model_format": model.get("format"),
        "model_reference_url": model.get("reference_url"),
        "benchmark_profile": meta["benchmark_profile"],
        "tps": metrics["tokens_per_second"]["mean"],
        "tps_stddev": metrics["tokens_per_second"]["stddev"],
        "decode_tps": decode_stats.get("mean"),
        "decode_timing_source": metrics.get(
            "decode_timing_source",
            "unavailable",
        ),
        "completion_tokens_raw": trials["completion_tokens_raw"],
        "ttft_cold": metrics["ttft_cold"]["mean"],
        "ttft_cached": metrics["ttft_cached"]["mean"],
        "system_ram_peak_gb": metrics["system_ram_peak_gb"],
        "system_ram_peak_percent": metrics["system_ram_peak_percent"],
        "system_ram_baseline_gb": metrics.get("system_ram_baseline_gb"),
        "system_ram_delta_gb": metrics.get("system_ram_delta_gb"),
        "system_ram_headroom_gb": _headroom_gb(
            hardware["memory_gb"],
            metrics["system_ram_peak_gb"],
        ),
        "swap_growth_gb": metrics.get("swap_growth_gb"),
        "memory_pressure_warning": bool(meta.get("memory_pressure_warning")),
        "thermal_state": hardware["thermal_state"],
        "warmup_failures": meta["warmup_failures"],
        "submitted_by": meta.get("submitted_by"),
        "chronos_version": meta["chronos_version"],
        "timestamp": meta["timestamp"],
    }


def build_results_index(results_dir: Path) -> dict[str, object]:
    records = load_archive_results(results_dir)
    return {
        "metadata": {
            "standard_throughput_max_tokens": DEFAULT_THROUGHPUT_MAX_TOKENS,
            "standard_baseline_trials": PUBLIC_BASELINE_TRIALS,
            "standard_sustained_max_tokens": SUSTAINED_THROUGHPUT_MAX_TOKENS,
            "standard_sustained_trials": SUSTAINED_TRIALS,
            "minimum_completion_token_ratio": PUBLIC_MIN_COMPLETION_TOKEN_RATIO,
        },
        "results": [_index_row(record.result) for record in records],
    }


def _serialized_results_index(results_dir: Path) -> tuple[dict[str, object], str]:
    payload = build_results_index(results_dir)
    return payload, json.dumps(payload, indent=2) + "\n"


def write_results_index(results_dir: Path, output: Path) -> int:
    payload, serialized = _serialized_results_index(results_dir)
    output.write_text(serialized, encoding="utf-8")
    results = payload["results"]
    if not isinstance(results, list):
        raise TypeError("generated results index must contain a results list")
    return len(results)


def check_results_index(results_dir: Path, output: Path) -> int:
    """Return the result count when ``output`` is the current generated index."""
    payload, expected = _serialized_results_index(results_dir)
    try:
        actual = output.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"could not read {output}: {exc}") from exc
    if actual != expected:
        raise ValueError(
            f"{output} is stale; run `python -m mlx_chronos.leaderboard` and commit it"
        )
    results = payload["results"]
    if not isinstance(results, list):
        raise TypeError("generated results index must contain a results list")
    return len(results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=Path("results/submitted"))
    parser.add_argument("--output", type=Path, default=Path("docs/results_index.json"))
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when --output differs from the index generated from --results-dir",
    )
    args = parser.parse_args(argv)
    if args.check:
        try:
            count = check_results_index(args.results_dir, args.output)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"Leaderboard index is current ({count} results).")
        return 0
    count = write_results_index(args.results_dir, args.output)
    print(f"Generated index with {count} results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
