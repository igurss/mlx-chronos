"""Validation and index generation for the public benchmark archive."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
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
        model.source or "",
        model.revision or "",
        model.weight_hash or "",
        model.tokenizer_hash or "",
        model.chat_template_hash or "",
        model.architecture or "",
        model.family or "",
        model.parameter_size or "",
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
        "model": model["name"],
        "quantization": model["quantization"],
        "model_format": model.get("format"),
        "model_reference_url": model.get("reference_url"),
        "model_source": model.get("source"),
        "model_revision": model.get("revision"),
        "model_weight_hash": model.get("weight_hash"),
        "model_tokenizer_hash": model.get("tokenizer_hash"),
        "model_chat_template_hash": model.get("chat_template_hash"),
        "model_architecture": model.get("architecture"),
        "model_family": model.get("family"),
        "model_parameter_size": model.get("parameter_size"),
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
        "thermal_state": hardware["thermal_state"],
        "warmup_failures": meta["warmup_failures"],
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


def write_results_index(results_dir: Path, output: Path) -> int:
    payload = build_results_index(results_dir)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    results = payload["results"]
    if not isinstance(results, list):
        raise TypeError("generated results index must contain a results list")
    return len(results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=Path("results/submitted"))
    parser.add_argument("--output", type=Path, default=Path("docs/results_index.json"))
    args = parser.parse_args(argv)
    count = write_results_index(args.results_dir, args.output)
    print(f"Generated index with {count} results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
