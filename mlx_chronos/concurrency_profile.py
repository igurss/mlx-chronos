"""Local, cache-minimizing concurrent-request throughput diagnostic.

This is not a public BenchmarkResult: server cache state and scheduling are
engine-dependent, and completion-token counts must be exact for aggregate
tokens/second to have a defensible meaning.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
import logging
import math
import secrets
from threading import Barrier, BrokenBarrierError
import time

from mlx_chronos import __version__ as VERSION
from mlx_chronos.constants import (
    PUBLIC_MIN_COMPLETION_TOKEN_RATIO,
    TOKEN_COUNT_SOURCE_USAGE,
)
from mlx_chronos.detect import detect_hardware, get_thermal_state
from mlx_chronos.engines import get_engine
from mlx_chronos.model_reference import normalize_model_reference_url
from mlx_chronos.protocol import THROUGHPUT_PROMPTS
from mlx_chronos.schema import normalize_model_quantization
from mlx_chronos.stats import compute_stats

logger = logging.getLogger("mlx_chronos")

CONCURRENCY_PROFILE_VERSION = "1"
DEFAULT_CONCURRENCY_LEVELS = (1, 2, 4, 8)
MAX_CONCURRENCY_LEVEL = 32
DEFAULT_TRIALS_PER_LEVEL = 3
MIN_TRIALS_PER_LEVEL = 1
MAX_TRIALS_PER_LEVEL = 10
DEFAULT_REQUEST_MAX_TOKENS = 60
_BARRIER_TIMEOUT_SECONDS = 60
_BASE_PROMPT = THROUGHPUT_PROMPTS[0]


def _prompt(run_nonce: str, sequence: int) -> str:
    # A run-specific nonce also avoids exact reuse from a previous process.
    # Put it before the substantial prompt, not at the end: a suffix would
    # still let a prefix cache reuse almost the entire prefill.
    return f"Benchmark request {run_nonce}-{sequence:06d}. {_BASE_PROMPT}"


def _wave(
    engine,
    client,
    executor,
    model: str,
    prompts: list[str],
    max_tokens: int,
    *,
    require_exact_tokens: bool,
) -> dict:
    """Launch a wave from one barrier and wait for every worker before returning.

    The barrier action timestamps release, excluding worker creation and queue
    setup from the measured wall time. Individual start times reveal whether
    client scheduling meaningfully staggered the requests.
    """
    level = len(prompts)
    released_at = [0.0]
    gate = Barrier(
        level + 1, action=lambda: released_at.__setitem__(0, time.perf_counter())
    )

    def measure(prompt: str):
        gate.wait(timeout=_BARRIER_TIMEOUT_SECONDS)
        started = time.perf_counter()
        measurement = engine.measure_throughput(
            prompt,
            model=model,
            max_tokens=max_tokens,
            client=client,
            request_stream_usage=require_exact_tokens,
            allow_stream_usage_fallback=False,
        )
        return started, time.perf_counter(), measurement

    futures = []
    try:
        futures = [executor.submit(measure, prompt) for prompt in prompts]
        gate.wait(timeout=_BARRIER_TIMEOUT_SECONDS)
    except BrokenBarrierError as exc:
        raise RuntimeError("concurrent request start barrier timed out") from exc
    except Exception:
        gate.abort()
        raise

    # Do not return or close the shared client while any request remains active.
    wait(futures)
    observations = [future.result() for future in futures]
    if require_exact_tokens:
        for _, _, measurement in observations:
            if measurement.token_count_source != TOKEN_COUNT_SOURCE_USAGE:
                raise RuntimeError(
                    "concurrency requires exact completion token usage from every "
                    "request; the engine returned an estimate instead"
                )

    tokens = [observation[2].completion_tokens for observation in observations]
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in tokens
    ):
        raise RuntimeError(
            "concurrent request returned an invalid completion-token count"
        )
    if require_exact_tokens:
        minimum = math.ceil(max_tokens * PUBLIC_MIN_COMPLETION_TOKEN_RATIO)
        if any(value < minimum for value in tokens):
            raise RuntimeError(
                "concurrent request ended too early for a comparable workload: "
                f"each request must complete at least {minimum} of the "
                f"requested {max_tokens} tokens"
            )
    elapsed = max(observation[1] for observation in observations) - released_at[0]
    if elapsed <= 0:
        raise RuntimeError("concurrent wave had no measurable elapsed time")
    per_request_elapsed = [
        observation[1] - observation[0] for observation in observations
    ]
    start_spread = max(observation[0] for observation in observations) - min(
        observation[0] for observation in observations
    )
    return {
        "prompts": prompts,
        "prompt_chars": [len(prompt) for prompt in prompts],
        "completion_tokens": tokens,
        "total_completion_tokens": sum(tokens),
        "elapsed_seconds": round(elapsed, 6),
        "aggregate_tokens_per_second": round(sum(tokens) / elapsed, 3),
        "per_request_elapsed_seconds": [
            round(value, 6) for value in per_request_elapsed
        ],
        "request_start_spread_seconds": round(start_spread, 6),
    }


def _cache_hit_delta(before: int | None, after: int | None) -> int | None:
    if (
        isinstance(before, int)
        and not isinstance(before, bool)
        and isinstance(after, int)
        and not isinstance(after, bool)
        and after >= before >= 0
    ):
        return after - before
    return None


def run_concurrency_profile(
    engine_name: str,
    model_name: str,
    model_quantization: str | None = None,
    model_reference_url: str | None = None,
    levels: list[int] | None = None,
    trials_per_level: int = DEFAULT_TRIALS_PER_LEVEL,
    request_max_tokens: int = DEFAULT_REQUEST_MAX_TOKENS,
) -> dict:
    """Measure aggregate throughput at each requested concurrent load level.

    One unmeasured warm-up wave per measured wave primes the server and client.
    Each measured wave gets unique early-nonce prompts and a best-effort
    engine-confirmed prefix-cache clear. This minimizes cache contamination; it
    does not prove a cold cache where the engine exposes no usable evidence.
    """
    selected_levels = list(DEFAULT_CONCURRENCY_LEVELS if levels is None else levels)
    if not selected_levels:
        raise ValueError("at least one concurrency level must be selected")
    if any(
        isinstance(level, bool)
        or not isinstance(level, int)
        or not 1 <= level <= MAX_CONCURRENCY_LEVEL
        for level in selected_levels
    ):
        raise ValueError(
            f"concurrency levels must be integers from 1 to {MAX_CONCURRENCY_LEVEL}"
        )
    if len(selected_levels) != len(set(selected_levels)):
        raise ValueError("concurrency levels must not repeat")
    if (
        isinstance(trials_per_level, bool)
        or not isinstance(trials_per_level, int)
        or not MIN_TRIALS_PER_LEVEL <= trials_per_level <= MAX_TRIALS_PER_LEVEL
    ):
        raise ValueError(
            f"trials_per_level must be between {MIN_TRIALS_PER_LEVEL} "
            f"and {MAX_TRIALS_PER_LEVEL}"
        )
    if (
        isinstance(request_max_tokens, bool)
        or not isinstance(request_max_tokens, int)
        or request_max_tokens < 1
    ):
        raise ValueError("request_max_tokens must be a positive integer")
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("model name must not be empty")
    model_name = model_name.strip()
    model_reference_url = normalize_model_reference_url(model_reference_url)

    engine = get_engine(engine_name)
    if not engine.is_installed():
        raise RuntimeError(f"Engine '{engine_name}' is not installed.")
    if not engine.is_server_running():
        raise RuntimeError(f"Engine '{engine_name}' server is not running.")
    backend_metadata = engine.validate_model_backend(model_name)
    if not isinstance(backend_metadata, dict):
        backend_metadata = {}
    reported_quantization = backend_metadata.get("quantization")
    if reported_quantization and model_quantization:
        declared = normalize_model_quantization(model_quantization)
        actual = normalize_model_quantization(reported_quantization)
        if declared != actual:
            raise RuntimeError(
                "declared model quantization does not match engine metadata: "
                f"{declared!r} vs {actual!r}"
            )
        model_quantization = actual
    elif reported_quantization:
        model_quantization = normalize_model_quantization(reported_quantization)
    elif model_quantization:
        model_quantization = normalize_model_quantization(model_quantization)

    hardware = detect_hardware()
    started_at = datetime.now(timezone.utc).isoformat()
    run_nonce = secrets.token_hex(8)
    sequence = 0

    def prompts_for(count: int) -> list[str]:
        nonlocal sequence
        values = [_prompt(run_nonce, sequence + offset) for offset in range(count)]
        sequence += count
        return values

    wave_reports_by_level: dict[int, list[dict]] = {
        level: [] for level in selected_levels
    }
    execution_order = []
    # httpx normally retains only 20 idle connections. At level 32 that
    # would silently force new TCP connections between warm-up and measurement.
    with engine.http_client(
        max_keepalive_connections=max(20, max(selected_levels))
    ) as client:
        for trial_index in range(trials_per_level):
            offset = trial_index % len(selected_levels)
            round_order = selected_levels[offset:] + selected_levels[:offset]
            for level in round_order:
                logger.info(
                    "Concurrency %d, wave %d/%d: warm-up then measurement",
                    level,
                    trial_index + 1,
                    trials_per_level,
                )
                execution_order.append({"round": trial_index + 1, "concurrency": level})
                with ThreadPoolExecutor(max_workers=level) as executor:
                    warmup = _wave(
                        engine,
                        client,
                        executor,
                        model_name,
                        prompts_for(level),
                        request_max_tokens,
                        require_exact_tokens=False,
                    )
                    cache_cleared = (
                        engine.clear_cache_for_benchmark(client=client) is True
                    )
                    hits_before = engine.prefix_cache_hit_count(client=client)
                    thermal_before = get_thermal_state()
                    wave = _wave(
                        engine,
                        client,
                        executor,
                        model_name,
                        prompts_for(level),
                        request_max_tokens,
                        require_exact_tokens=True,
                    )
                    thermal_after = get_thermal_state()
                    hits_after = engine.prefix_cache_hit_count(client=client)
                    wave.update(
                        {
                            "wave": trial_index + 1,
                            "warmup": warmup,
                            "cache_clear_confirmed": cache_cleared,
                            "prefix_cache_hits_before": hits_before,
                            "prefix_cache_hits_after": hits_after,
                            "prefix_cache_hits_delta": _cache_hit_delta(
                                hits_before, hits_after
                            ),
                            "thermal_state_before": thermal_before,
                            "thermal_state_after": thermal_after,
                        }
                    )
                    wave_reports_by_level[level].append(wave)

    reports: list[dict] = []
    for level in selected_levels:
        wave_reports = wave_reports_by_level[level]
        aggregate_raw = [wave["aggregate_tokens_per_second"] for wave in wave_reports]
        request_elapsed_raw = [
            elapsed
            for wave in wave_reports
            for elapsed in wave["per_request_elapsed_seconds"]
        ]
        reports.append(
            {
                "concurrency": level,
                "trials": trials_per_level,
                "aggregate_tokens_per_second": compute_stats(aggregate_raw),
                "aggregate_tokens_per_second_raw": aggregate_raw,
                "per_request_elapsed_seconds": compute_stats(request_elapsed_raw),
                "waves": wave_reports,
            }
        )

    all_waves = [wave for report in reports for wave in report["waves"]]
    warnings = []
    if any(not wave["cache_clear_confirmed"] for wave in all_waves):
        warnings.append(
            "Prefix-cache clearing was not confirmed for every measured wave; "
            "these results are not verified cold-cache measurements."
        )
    if any(wave["prefix_cache_hits_delta"] is None for wave in all_waves):
        warnings.append(
            "Prefix-cache hit evidence was unavailable for at least one wave; "
            "unknown does not mean zero hits."
        )
    if any((wave["prefix_cache_hits_delta"] or 0) > 0 for wave in all_waves):
        warnings.append(
            "A prefix-cache hit counter increased during at least one wave; "
            "other clients may also contribute to that counter."
        )
    if any(
        state not in {"nominal", "unavailable_unknown"}
        and not state.startswith("unavailable")
        for wave in all_waves
        for state in (wave["thermal_state_before"], wave["thermal_state_after"])
    ):
        warnings.append(
            "Thermal pressure was observed during the run; level comparisons "
            "may include thermal effects."
        )

    return {
        "concurrency_profile_version": CONCURRENCY_PROFILE_VERSION,
        "chronos_version": VERSION,
        "timestamp": started_at,
        "hardware": hardware,
        "engine": {"name": engine_name, "version": engine.get_version()},
        "model": {
            "name": model_name,
            "quantization": model_quantization,
            "reference_url": model_reference_url,
            "format": backend_metadata.get("format"),
        },
        "protocol": {
            "name": "cache_minimized_concurrency",
            "version": CONCURRENCY_PROFILE_VERSION,
            "selected_levels": selected_levels,
            "execution_order": execution_order,
            "warmup_waves_per_measured_wave": 1,
            "prompt_strategy": "fixed_template_early_run_nonce_and_sequence",
            "run_nonce": run_nonce,
            "cache_clear_policy": "best_effort_before_each_measured_wave",
            "exact_completion_usage_required": True,
            "minimum_completion_token_ratio": PUBLIC_MIN_COMPLETION_TOKEN_RATIO,
            "request_start": "thread_barrier",
        },
        "request_max_tokens": request_max_tokens,
        "levels": reports,
        "warnings": warnings,
    }
