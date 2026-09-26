"""Local TTFT-versus-input-length diagnostic, never a leaderboard result.

Character buckets are approximate. Only a server-provided prompt token count
is recorded as a token count; TTFT is not pure model-prefill time.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
import secrets
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

from mlx_chronos import __version__ as VERSION
from mlx_chronos.detect import detect_hardware
from mlx_chronos.engines import get_engine
from mlx_chronos.matrix import sample_matrix_conditions
from mlx_chronos.measurements import (
    INPUT_TOKEN_COUNT_ENGINE,
    INPUT_TOKEN_COUNT_UNAVAILABLE,
    TTFTMeasurement,
)
from mlx_chronos.model_reference import normalize_model_reference_url
from mlx_chronos.protocol import CONNECTION_MODE_PERSISTENT, VALID_CONNECTION_MODES
from mlx_chronos.reporters import _write_text_atomic
from mlx_chronos.schema import normalize_model_quantization
from mlx_chronos.stats import compute_stats

CONTEXT_PROFILE_VERSION = "1"
MIN_TRIALS_PER_BUCKET = 1
MAX_TRIALS_PER_BUCKET = 10
DEFAULT_TRIALS_PER_BUCKET = 3
DEFAULT_CONTEXT_BUCKETS = ("small", "medium")
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0
CONTEXT_LENGTH_BUCKETS = {
    "small": 2_000,
    "medium": 8_000,
    "large": 32_000,
    "xlarge": 128_000,
}

_FILLER_SENTENCES = (
    "The workshop's north window let in a slow even light through the afternoon.",
    "A ferry crossed the strait twice a day while the bridge was under repair.",
    "Local records described the harvest as ordinary for that particular year.",
    "The committee met each month in the smaller of the two rooms.",
    "Copper pipes replaced the older fittings in the district decades earlier.",
    "The trail climbed gradually before leveling off near a stand of birch trees.",
    "Most correspondence from that period survives only in copied fragments.",
    "The recipe called for a slow simmer stirred over the better part of an hour.",
    "Traffic on the old road thinned after the new crossing opened downstream.",
    "The observatory logged clear skies on roughly a third of winter nights.",
    "Her notebook mixed sketches of hinges with lists and unfinished letters.",
    "The orchard's older trees were kept mainly for shade in the summer.",
    "Repairs to the seawall were postponed first for funding and then for weather.",
    "The library's reading room closed an hour earlier on Saturdays.",
    "A brass plate near the door listed the original architect and the year.",
    "The market stalls were rearranged each spring though never by very much.",
    "Most travelers on that line changed trains twice before reaching the coast.",
    "The foreman kept a tally of spare parts in a ledger by the workshop door.",
    "Rain gauges along the valley recorded consistent totals that autumn.",
    "The choir rehearsed on Thursdays in a hall near the polling station.",
    "Deliveries to the outer islands depended on the local tide tables.",
    "The museum basement held more uncatalogued material than the galleries.",
    "A painted sign still marked the turn toward the old mill.",
    "The apprentice spent his first year sorting scrap metal by weight.",
)


def build_context_prompt(
    bucket_label: str,
    target_chars: int,
    trial_index: int = 0,
    *,
    run_nonce: str = "preview",
) -> str:
    """Start with a pair-specific marker, then fill to the character target."""
    if bucket_label not in CONTEXT_LENGTH_BUCKETS:
        raise ValueError("unknown context bucket")
    if isinstance(target_chars, bool) or not isinstance(target_chars, int) or target_chars < 1:
        raise ValueError("target_chars must be a positive integer")
    if isinstance(trial_index, bool) or not isinstance(trial_index, int) or trial_index < 0:
        raise ValueError("trial_index must be a non-negative integer")
    if not isinstance(run_nonce, str) or not run_nonce:
        raise ValueError("run_nonce must be a non-empty string")
    identity = f"{run_nonce}|{bucket_label}|{trial_index:02d}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    prefix = f"{digest} [{bucket_label}:{trial_index:02d}] "
    parts: list[str] = []
    length = len(prefix)
    offset = list(CONTEXT_LENGTH_BUCKETS).index(bucket_label) * 6 + trial_index
    while length < target_chars:
        sentence = _FILLER_SENTENCES[(offset + len(parts)) % len(_FILLER_SENTENCES)]
        length += len(sentence) + (1 if parts else 0)
        parts.append(sentence)
    return prefix + " ".join(parts)


def _validate_measurement(value: TTFTMeasurement) -> None:
    if (
        not isinstance(value, TTFTMeasurement)
        or isinstance(value.ttft_seconds, bool)
        or not isinstance(value.ttft_seconds, (int, float))
        or not math.isfinite(value.ttft_seconds)
        or value.ttft_seconds <= 0
        or (
            value.input_token_count_source == INPUT_TOKEN_COUNT_ENGINE
            and (isinstance(value.input_tokens, bool)
                 or not isinstance(value.input_tokens, int)
                 or value.input_tokens <= 0)
        )
        or (
            value.input_token_count_source == INPUT_TOKEN_COUNT_UNAVAILABLE
            and value.input_tokens is not None
        )
        or value.input_token_count_source not in {
            INPUT_TOKEN_COUNT_ENGINE, INPUT_TOKEN_COUNT_UNAVAILABLE,
        }
    ):
        raise RuntimeError("engine returned an invalid context TTFT measurement")


def run_context_profile(
    engine_name: str,
    model_name: str,
    *,
    model_quantization: str | None = None,
    model_reference_url: str | None = None,
    buckets: list[str] | None = None,
    trials_per_bucket: int = DEFAULT_TRIALS_PER_BUCKET,
    connection_mode: str = CONNECTION_MODE_PERSISTENT,
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> dict:
    selected = list(DEFAULT_CONTEXT_BUCKETS if buckets is None else buckets)
    if not selected or any(bucket not in CONTEXT_LENGTH_BUCKETS for bucket in selected):
        raise ValueError(f"select context buckets from {list(CONTEXT_LENGTH_BUCKETS)}")
    if len(set(selected)) != len(selected):
        raise ValueError("context buckets must not be repeated")
    if (isinstance(trials_per_bucket, bool) or not isinstance(trials_per_bucket, int)
            or not MIN_TRIALS_PER_BUCKET <= trials_per_bucket <= MAX_TRIALS_PER_BUCKET):
        raise ValueError("trials_per_bucket must be between 1 and 10")
    if connection_mode not in VALID_CONNECTION_MODES:
        raise ValueError(f"connection_mode must be one of {sorted(VALID_CONNECTION_MODES)}")
    if (isinstance(request_timeout_seconds, bool)
            or not isinstance(request_timeout_seconds, (int, float))
            or not math.isfinite(request_timeout_seconds)
            or not 1 <= request_timeout_seconds <= 600):
        raise ValueError("request_timeout_seconds must be finite and between 1 and 600")
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("model name must not be empty")
    model_name = model_name.strip()
    model_reference_url = normalize_model_reference_url(model_reference_url)
    if model_quantization is not None:
        model_quantization = normalize_model_quantization(model_quantization)

    engine = get_engine(engine_name)
    if not engine.is_installed():
        raise RuntimeError(f"Engine '{engine_name}' is not installed")
    if not engine.is_server_running():
        raise RuntimeError(f"Engine '{engine_name}' server is not running")
    backend = engine.validate_model_backend(model_name)
    if not isinstance(backend, dict):
        backend = {}
    reported_quantization = backend.get("quantization")
    if reported_quantization:
        reported = normalize_model_quantization(reported_quantization)
        if model_quantization is not None and model_quantization != reported:
            raise RuntimeError("declared quantization differs from engine metadata")
        model_quantization = reported
    engine.validate_completion_request(model_name)

    nonce = secrets.token_hex(8)
    bucket_reports: list[dict] = []
    with (
        engine.http_client() if connection_mode == CONNECTION_MODE_PERSISTENT
        else nullcontext(None)
    ) as client:
        engine.measure_throughput(
            f"Context diagnostic warm-up {nonce}.",
            model=model_name, max_tokens=16, client=client,
        )
        for bucket_label in selected:
            target_chars = CONTEXT_LENGTH_BUCKETS[bucket_label]
            conditions_before = sample_matrix_conditions()
            ttft_raw: list[float] = []
            input_tokens_raw: list[int | None] = []
            prompt_chars_raw: list[int] = []
            prompt_sha256: list[str] = []
            for trial_index in range(trials_per_bucket):
                prompt = build_context_prompt(
                    bucket_label, target_chars, trial_index, run_nonce=nonce,
                )
                measurement = engine.measure_ttft_with_input_tokens(
                    prompt, model=model_name, client=client,
                    timeout_seconds=request_timeout_seconds,
                )
                _validate_measurement(measurement)
                ttft_raw.append(measurement.ttft_seconds)
                input_tokens_raw.append(measurement.input_tokens)
                prompt_chars_raw.append(len(prompt))
                prompt_sha256.append(hashlib.sha256(prompt.encode("utf-8")).hexdigest())
            conditions_after = sample_matrix_conditions()
            all_counts = all(count is not None for count in input_tokens_raw)
            any_counts = any(count is not None for count in input_tokens_raw)
            bucket_reports.append({
                "label": bucket_label,
                "target_chars": target_chars,
                "trials": trials_per_bucket,
                "prompt_chars_raw": prompt_chars_raw,
                "prompt_sha256": prompt_sha256,
                "ttft_seconds_raw": ttft_raw,
                "ttft_seconds": compute_stats(ttft_raw),
                "input_tokens_raw": input_tokens_raw,
                "input_tokens_mean": (
                    round(sum(count for count in input_tokens_raw if count is not None)
                          / len(input_tokens_raw), 1)
                    if all_counts else None
                ),
                "input_token_count_source": (
                    "engine" if all_counts else "partial_engine" if any_counts
                    else "unavailable"
                ),
                "conditions_before": conditions_before,
                "conditions_after": conditions_after,
            })

    return {
        "kind": "local_context_diagnostic",
        "version": CONTEXT_PROFILE_VERSION,
        "chronos_version": VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hardware": detect_hardware(),
        "engine": {"name": engine_name, "version": engine.get_version()},
        "model": {
            "name": model_name, "quantization": model_quantization,
            "reference_url": model_reference_url, "format": backend.get("format"),
        },
        "protocol": {
            "bucket_order": selected,
            "trials_per_bucket": trials_per_bucket,
            "connection_mode": connection_mode,
            "request_timeout_seconds": request_timeout_seconds,
            "prompt_strategy": "unique_run_bucket_trial_prefix_before_rotating_filler",
            "run_nonce": nonce,
            "input_length_unit": "characters_not_tokens",
        },
        "buckets": bucket_reports,
        "warning": (
            "TTFT includes HTTP, queueing and first-token overhead; it is not "
            "pure prefill time. Character buckets are approximate; server "
            "truncation and cache state cannot be ruled out. Local only."
        ),
    }


def _markdown_text(value: object) -> str:
    escaped = html.escape(str(value).replace("\r", " ").replace("\n", " "), quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", escaped)


def save_context_reports(report: dict, output_dir: Path, format_name: str = "all") -> list[Path]:
    if format_name not in {"json", "markdown", "all"}:
        raise ValueError("format must be json, markdown or all")
    stem = "context_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    stem += "_" + secrets.token_hex(4)
    output: list[tuple[Path, str]] = []
    if format_name in {"json", "all"}:
        output.append((output_dir / f"{stem}.json", json.dumps(
            report, indent=2, ensure_ascii=False, allow_nan=False,
        ) + "\n"))
    if format_name in {"markdown", "all"}:
        lines = [
            "# mlx-Chronos context diagnostic", "",
            f"- Engine: {_markdown_text(report['engine']['name'])}",
            f"- Model: {_markdown_text(report['model']['name'])}",
            f"- Hardware: {_markdown_text(report['hardware']['chip'])}",
            "- Scope: local diagnostic; not a leaderboard result", "",
            "Character buckets are approximate. TTFT is not pure prefill time.", "",
            "| Bucket | Mean chars | Trials | TTFT mean (s) | Stddev (s) | Mean input tokens |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for bucket in report["buckets"]:
            tokens = bucket["input_tokens_mean"]
            lines.append(
                f"| {_markdown_text(bucket['label'])} | "
                f"{sum(bucket['prompt_chars_raw']) / bucket['trials']:.0f} | "
                f"{bucket['trials']} | {bucket['ttft_seconds']['mean']:.3f} | "
                f"{bucket['ttft_seconds']['stddev']:.3f} | "
                f"{'-' if tokens is None else f'{tokens:.1f}'} |"
            )
        lines.extend(["", _markdown_text(report["warning"]), ""])
        output.append((output_dir / f"{stem}.md", "\n".join(lines)))
    output_dir.mkdir(parents=True, exist_ok=True)
    for path, content in output:
        _write_text_atomic(path, content)
    return [path for path, _ in output]
