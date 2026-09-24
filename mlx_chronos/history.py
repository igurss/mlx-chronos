"""List local benchmark result files, newest first.

Only the directory's own JSON files are listed (not context/concurrency
subdirectories under it): those hold a different, non-BenchmarkResult report
shape by design, and mixing them in would either need silently skipping most
of them or misrepresenting them as benchmark runs.
"""

from __future__ import annotations

from pathlib import Path

from mlx_chronos.compare import CompareError, load_result_for_compare


def list_history(
    results_dir: Path, limit: int | None = None
) -> tuple[list[dict], list[tuple[Path, str]]]:
    """Return (entries, skipped) for every JSON file directly under results_dir.

    entries are sorted newest first. skipped lists (path, reason) for any file
    that failed to parse as a BenchmarkResult, so a caller can report them
    rather than have a broken file silently vanish from the listing.
    """
    entries: list[dict] = []
    skipped: list[tuple[Path, str]] = []
    if limit is not None and limit < 1:
        raise ValueError("--limit must be at least 1")
    if not results_dir.exists():
        return entries, skipped

    for path in sorted(results_dir.glob("*.json")):
        try:
            result = load_result_for_compare(path)
        except CompareError as exc:
            skipped.append((path, str(exc)))
            continue
        entries.append(
            {
                "path": str(path),
                "timestamp": result.meta.timestamp,
                "engine": result.engine.name,
                "model": result.model.name,
                "quantization": result.model.quantization,
                "benchmark_profile": result.meta.benchmark_profile,
                "request_tokens_per_second": result.metrics.request_tokens_per_second.mean,
            }
        )

    entries.sort(key=lambda entry: entry["timestamp"], reverse=True)
    if limit is not None:
        entries = entries[:limit]
    return entries, skipped
