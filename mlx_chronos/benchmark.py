import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import logging
import psutil
import time
from typing import get_args

from mlx_chronos.constants import (
    DEFAULT_RAM_SAMPLE_INTERVAL,
    DEFAULT_THERMAL_SAMPLE_INTERVAL,
    MAX_TRIALS,
    RAM_MEASUREMENT_PROCESS_RSS,
    RAM_MEASUREMENT_SYSTEM_FALLBACK,
    TOKEN_COUNT_SOURCE_MIXED,
    TOKEN_COUNT_SOURCE_USAGE,
    TOKEN_COUNT_SOURCE_WORD_FALLBACK,
)
from mlx_chronos import __version__ as VERSION
from mlx_chronos.detect import detect_hardware, get_benchmark_condition_warnings
from mlx_chronos.engines import get_engine
from mlx_chronos.measurements import (
    DECODE_TIMING_CLIENT_STREAM,
    DECODE_TIMING_UNAVAILABLE,
    ThroughputMeasurement,
)
from mlx_chronos.protocol import (
    CACHED_TTFT_PROMPT,
    COLD_PROMPTS,
    DEFAULT_THROUGHPUT_MAX_TOKENS,
    THROUGHPUT_PROMPT,
    WARMUP_MAX_TOKENS,
    build_benchmark_protocol,
)
from mlx_chronos.schema import BenchmarkProfile, BenchmarkResult, dump_benchmark_result
from mlx_chronos.stats import compute_stats
from mlx_chronos.trackers import RAMTracker, SystemRAMTracker, ThermalStateTracker


logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("mlx_chronos")

DEFAULT_TRIALS = 5
_BENCHMARK_PROFILE_VALUES = get_args(BenchmarkProfile)
BENCHMARK_PROFILE_BASELINE = _BENCHMARK_PROFILE_VALUES[0]
BENCHMARK_PROFILE_SUSTAINED = _BENCHMARK_PROFILE_VALUES[1]
VALID_BENCHMARK_PROFILES = set(_BENCHMARK_PROFILE_VALUES)
SUSTAINED_THROUGHPUT_MAX_TOKENS = 1000
SUSTAINED_TRIALS = 1
SUSTAINED_PROGRESS_SAMPLE_INTERVAL_TOKENS = 100
SUSTAINED_THROTTLING_DROP_RATIO = 0.85
SUSTAINED_THROTTLING_MIN_INTERVALS = 4
SUSTAINED_THROTTLING_EDGE_INTERVALS = 2
CACHED_TTFT_WARNING_RATIO = 0.8


def _normalize_token_count_source(source: object) -> str:
    valid_trial_sources = {
        TOKEN_COUNT_SOURCE_USAGE,
        TOKEN_COUNT_SOURCE_WORD_FALLBACK,
    }
    if isinstance(source, str) and source in valid_trial_sources:
        return source
    raise RuntimeError(
        "engine did not report a valid token count source after throughput "
        f"measurement; expected one of {sorted(valid_trial_sources)}, got {source!r}"
    )


def _normalize_completion_tokens(tokens: object) -> int:
    if isinstance(tokens, int) and tokens >= 0:
        return tokens
    raise RuntimeError(
        "engine did not report a valid completion token count after throughput "
        f"measurement; expected non-negative int, got {tokens!r}"
    )


def _summarize_token_count_sources(sources: list[str]) -> str:
    unique_sources = set(sources)
    if unique_sources == {TOKEN_COUNT_SOURCE_USAGE}:
        return TOKEN_COUNT_SOURCE_USAGE
    if unique_sources == {TOKEN_COUNT_SOURCE_WORD_FALLBACK}:
        return TOKEN_COUNT_SOURCE_WORD_FALLBACK
    return TOKEN_COUNT_SOURCE_MIXED


def _validate_token_bounds(
    tokens: int,
    source: str,
    min_tokens: int | None,
    max_tokens: int,
) -> None:
    if source != TOKEN_COUNT_SOURCE_USAGE:
        return
    if tokens > max_tokens:
        raise RuntimeError(
            "throughput completion token count exceeded requested max_tokens; "
            f"requested <= {max_tokens}, got {tokens}"
        )
    if min_tokens is not None and tokens < min_tokens:
        raise RuntimeError(
            "throughput completion token count was below requested min_tokens; "
            f"requested >= {min_tokens}, got {tokens}"
        )


def _validate_throughput_measurement(value: object) -> ThroughputMeasurement:
    if isinstance(value, ThroughputMeasurement):
        return value
    raise RuntimeError(
        "engine returned an invalid throughput measurement; expected "
        f"ThroughputMeasurement, got {type(value).__name__}"
    )


@contextmanager
def _record_phase_duration(
    phase_timings: dict[str, float],
    name: str,
):
    start = time.perf_counter()
    try:
        yield
    finally:
        phase_timings[name] = round(time.perf_counter() - start, 3)


def _log_thermal_monitor_warnings(summary: dict) -> None:
    source = summary.get("source")
    if source == "unavailable":
        logger.warning(
            "  Warning: thermal monitoring unavailable during run; "
            "continuous thermal context is missing. Install mlx-chronos[thermal] "
            "to enable Foundation/PyObjC sampling without powermetrics overhead."
        )
        return

    if summary.get("changed_during_run"):
        logger.warning(
            "  Warning: thermal state changed during run "
            f"({summary.get('start_state')} -> {summary.get('end_state')})."
        )
    if summary.get("non_nominal_observed"):
        phases = ", ".join(summary.get("non_nominal_phases") or ["unknown"])
        logger.warning(
            "  Warning: non-nominal thermal state observed during benchmark "
            f"(worst={summary.get('worst_state')}; phases={phases})."
        )


def _throughput_interval_rates(samples: list[dict]) -> list[float]:
    rates = []
    previous_tokens = 0
    previous_elapsed = 0.0
    previous_source = None
    for sample in samples:
        tokens = sample.get("completion_tokens")
        elapsed = sample.get("elapsed_seconds")
        source = sample.get("token_count_source")
        if not isinstance(tokens, int) or not isinstance(elapsed, (int, float)):
            continue
        token_delta = tokens - previous_tokens
        elapsed_delta = float(elapsed) - previous_elapsed
        same_source = source == previous_source or previous_source is None
        if token_delta > 0 and elapsed_delta > 0 and same_source:
            rates.append(token_delta / elapsed_delta)
        previous_tokens = tokens
        previous_elapsed = float(elapsed)
        previous_source = source
    return rates


def _edge_average(values: list[float], from_end: bool = False) -> float:
    window = min(SUSTAINED_THROTTLING_EDGE_INTERVALS, len(values) // 2)
    selected = values[-window:] if from_end else values[:window]
    return sum(selected) / len(selected)


def _detect_sustained_throttling(
    progress_samples_trials: list[list[dict]],
    thermal_summary: dict | None,
) -> bool:
    """Flag clear sustained degradation when it aligns with thermal pressure."""
    if not thermal_summary:
        return False
    thermal_signal = (
        thermal_summary.get("changed_during_run")
        or thermal_summary.get("non_nominal_observed")
    )
    if not thermal_signal:
        return False

    for samples in progress_samples_trials:
        rates = _throughput_interval_rates(samples)
        if len(rates) < SUSTAINED_THROTTLING_MIN_INTERVALS:
            continue
        early_rate = _edge_average(rates)
        late_rate = _edge_average(rates, from_end=True)
        if early_rate > 0 and late_rate <= early_rate * SUSTAINED_THROTTLING_DROP_RATIO:
            return True
    return False


def run_benchmark(
    engine_name: str,
    model_name: str,
    model_quantization: str,
    trials: int = DEFAULT_TRIALS,
    notes: str | None = None,
    ram_sample_interval: float = DEFAULT_RAM_SAMPLE_INTERVAL,
    throughput_max_tokens: int = DEFAULT_THROUGHPUT_MAX_TOKENS,
    throughput_min_tokens: int | None = None,
    benchmark_profile: str = BENCHMARK_PROFILE_BASELINE,
    elapsed_since_last_benchmark_seconds: float | None = None,
    cooldown_seconds: float | None = None,
    progress_sample_interval_tokens: int | None = None,
) -> dict:
    """
    Run a full benchmark session for a given engine and model.
    Returns a structured result dict with trial statistics.
    """

    if benchmark_profile not in VALID_BENCHMARK_PROFILES:
        raise ValueError(
            f"benchmark_profile must be one of {sorted(VALID_BENCHMARK_PROFILES)}"
        )
    if trials > MAX_TRIALS:
        raise ValueError(
            f"Max trials is {MAX_TRIALS} (one unique cold prompt per trial). "
            f"Requested: {trials}"
        )
    if trials < 1:
        raise ValueError("trials must be at least 1")
    if ram_sample_interval <= 0:
        raise ValueError("ram_sample_interval must be greater than 0")
    if throughput_max_tokens < 1:
        raise ValueError("throughput_max_tokens must be at least 1")
    if throughput_min_tokens is not None and throughput_min_tokens < 1:
        raise ValueError("throughput_min_tokens must be at least 1 when set")
    if (
        throughput_min_tokens is not None
        and throughput_min_tokens > throughput_max_tokens
    ):
        raise ValueError("throughput_min_tokens must be <= throughput_max_tokens")
    if (
        elapsed_since_last_benchmark_seconds is not None
        and elapsed_since_last_benchmark_seconds < 0
    ):
        raise ValueError("elapsed_since_last_benchmark_seconds must be non-negative")
    if cooldown_seconds is not None and cooldown_seconds < 0:
        raise ValueError("cooldown_seconds must be non-negative")
    if (
        progress_sample_interval_tokens is not None
        and progress_sample_interval_tokens < 1
    ):
        raise ValueError("progress_sample_interval_tokens must be at least 1")
    model_name = model_name.strip()
    if not model_name:
        raise ValueError("model name must not be empty")

    if trials < 3:
        logger.warning(
            "  Warning: only %s trial(s) requested; stddev is low-confidence "
            "and will be 0.0 for a single trial.",
            trials,
        )

    logger.info(f"\n{'='*50}")
    logger.info(f"  mlx-Chronos Benchmark")
    logger.info(f"  Engine : {engine_name}")
    logger.info(f"  Model  : {model_name} ({model_quantization})")
    logger.info(f"  Profile: {benchmark_profile}")
    logger.info(f"  Trials : {trials}")
    token_range = (
        f"{throughput_min_tokens}-{throughput_max_tokens}"
        if throughput_min_tokens is not None
        else f"<= {throughput_max_tokens}"
    )
    logger.info(f"  Output : throughput tokens {token_range}")
    logger.info(f"{'='*50}\n")

    # 1. Detect hardware
    logger.info("Detecting hardware...")
    hw = detect_hardware()
    logger.info(f"  {hw['chip']} — {hw['memory_gb']}GB — macOS {hw['macos_version']}\n")
    condition_warnings = get_benchmark_condition_warnings(hw)
    for warning in condition_warnings:
        logger.warning(f"  Warning: {warning.label}: {warning.detail}")
    if condition_warnings:
        logger.info("")

    # 2. Get engine
    engine = get_engine(engine_name)

    if not engine.is_installed():
        raise RuntimeError(f"Engine '{engine_name}' is not installed.")

    if not engine.is_server_running():
        raise RuntimeError(
            f"Engine '{engine_name}' server is not running. "
            f"Please start it before running mlx-chronos."
        )

    # 3. Engine version
    engine_version = engine.get_version()
    logger.info(f"Engine version: {engine_version}\n")
    engine_version_warning = engine_version == "unknown"
    if engine_version_warning:
        logger.warning(
            "  Warning: engine version could not be detected; "
            "engine.version will be saved as 'unknown'."
        )
        logger.warning(
            "  Engine versions affect comparability. Try restarting the engine "
            "server or updating the engine CLI if this persists.\n"
        )

    # 4. Start background sampling before warmup so load/cache pressure is captured.
    phase_timings = {}
    total_runtime_start = time.perf_counter()
    logger.info(
        f"Starting continuous background thermal sampling "
        f"({DEFAULT_THERMAL_SAMPLE_INTERVAL:.3f}s interval)..."
    )
    thermal_tracker = ThermalStateTracker(interval=DEFAULT_THERMAL_SAMPLE_INTERVAL)
    thermal_tracker.start()

    logger.info(
        f"Starting continuous background system RAM sampling "
        f"({ram_sample_interval:.3f}s interval)..."
    )
    system_ram_tracker = SystemRAMTracker(interval=ram_sample_interval)
    system_ram_tracker.start()

    # 5. Run warmup and trials
    ttft_cold_trials = []
    ttft_cached_trials = []
    tps_trials = []
    throughput_elapsed_trials = []
    decode_tps_trials = []
    decode_timing_sources = []
    token_count_sources = []
    completion_tokens_trials = []
    throughput_progress_samples_trials = []
    warmup_calls = 2
    warmup_failures = 0

    peak_ram_gb = None
    system_ram_peak_gb = None
    system_ram_peak_percent = None
    thermal_summary = None
    ram_tracker = None
    ram_is_process_rss = False

    try:
        # Warmup phase — 2 calls with the throughput prompt, not recorded
        thermal_tracker.set_phase("warmup")
        with _record_phase_duration(phase_timings, "warmup"):
            logger.info("Warming up (2 calls, not recorded)...")
            for _ in range(warmup_calls):
                try:
                    engine.measure_tokens_per_second(
                        THROUGHPUT_PROMPT,
                        model=model_name,
                        max_tokens=WARMUP_MAX_TOKENS,
                    )
                except Exception as exc:
                    warmup_failures += 1
                    logger.warning(f"  Warmup call failed and was skipped: {exc}")
            if warmup_failures == warmup_calls:
                raise RuntimeError(
                    "all warmup calls failed; benchmark did not reach a warmed state"
                )
            logger.info("  Done.\n")

        logger.info(
            f"Starting diagnostic post-warmup engine RSS sampling "
            f"({ram_sample_interval:.3f}s interval)..."
        )
        # Diagnostic engine RSS intentionally starts after warmup, while system
        # RAM started before warmup to include model loading and cache pressure.
        target_pid = engine.get_server_pid()
        if target_pid is None:
            logger.warning(
                "Engine PID not found; diagnostic engine RSS will use system "
                "RAM peak fallback."
            )
        else:
            try:
                ram_tracker = RAMTracker(
                    interval=ram_sample_interval,
                    target_pid=target_pid,
                )
                ram_tracker.start()
                ram_is_process_rss = True
            except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                logger.warning(
                    "Could not start diagnostic engine RSS sampling for PID "
                    f"{target_pid}: {exc}"
                )
                ram_tracker = None

        thermal_tracker.set_phase("ttft_cold")
        with _record_phase_duration(phase_timings, "ttft_cold"):
            logger.info("Running cold TTFT trials...")
            for i in range(trials):
                cold_prompt = COLD_PROMPTS[i]
                logger.info(f"  Cold trial {i + 1}/{trials} (unique prompt)...")
                ttft_cold_trials.append(
                    engine.measure_ttft(cold_prompt, model=model_name)
                )

        thermal_tracker.set_phase("cache_priming")
        with _record_phase_duration(phase_timings, "cache_priming"):
            logger.info("\nPriming cache for cached TTFT measurement...")
            try:
                engine.measure_ttft(CACHED_TTFT_PROMPT, model=model_name)
            except Exception as exc:
                logger.warning(f"  Cache priming failed; cached TTFT may be cold: {exc}")
            logger.info("  Done.\n")

        thermal_tracker.set_phase("ttft_cached")
        with _record_phase_duration(phase_timings, "ttft_cached"):
            logger.info("Running cached TTFT trials...")
            for i in range(trials):
                logger.info(f"  Cached trial {i + 1}/{trials} (fixed prompt)...")
                ttft_cached_trials.append(
                    engine.measure_ttft(CACHED_TTFT_PROMPT, model=model_name)
                )

        thermal_tracker.set_phase("throughput")
        with _record_phase_duration(phase_timings, "throughput"):
            logger.info("\nRunning throughput trials...")
            for i in range(trials):
                logger.info(f"  Throughput trial {i + 1}/{trials}...")
                measurement = _validate_throughput_measurement(
                    engine.measure_throughput(
                        THROUGHPUT_PROMPT,
                        model=model_name,
                        max_tokens=throughput_max_tokens,
                        min_tokens=throughput_min_tokens,
                        progress_sample_interval_tokens=(
                            progress_sample_interval_tokens
                        ),
                    )
                )
                tps_trials.append(measurement.request_tokens_per_second)
                throughput_elapsed_trials.append(measurement.elapsed_seconds)
                token_source = _normalize_token_count_source(
                    measurement.token_count_source
                )
                completion_tokens = _normalize_completion_tokens(
                    measurement.completion_tokens
                )
                _validate_token_bounds(
                    completion_tokens,
                    token_source,
                    throughput_min_tokens,
                    throughput_max_tokens,
                )
                token_count_sources.append(token_source)
                completion_tokens_trials.append(completion_tokens)
                throughput_progress_samples_trials.append(
                    list(measurement.progress_samples)
                )
                if measurement.decode_tokens_per_second is not None:
                    decode_tps_trials.append(measurement.decode_tokens_per_second)
                    decode_timing_sources.append(measurement.decode_timing_source)
    finally:
        thermal_tracker.set_phase("teardown")
        if ram_tracker:
            peak_ram_gb = ram_tracker.stop()
            logger.info(
                "Diagnostic engine RSS sampling finished. Peak detected: "
                f"{peak_ram_gb:.2f} GB"
            )
        else:
            ram_is_process_rss = False

        system_ram_peak_gb, system_ram_peak_percent = system_ram_tracker.stop()
        logger.info(
            "System RAM sampling finished. Peak detected: "
            f"{system_ram_peak_gb:.2f} GB ({system_ram_peak_percent:.1f}%)\n"
        )
        thermal_summary = thermal_tracker.stop()
        phase_timings["total_runtime"] = round(
            time.perf_counter() - total_runtime_start,
            3,
        )
        logger.info(
            "Thermal sampling finished. "
            f"Start: {thermal_summary['start_state']}; "
            f"end: {thermal_summary['end_state']}; "
            f"worst: {thermal_summary['worst_state']}\n"
        )
        _log_thermal_monitor_warnings(thermal_summary)

        if peak_ram_gb is None:
            peak_ram_gb = system_ram_peak_gb

    logger.info("")

    # 6. Compute statistics
    ttft_cold_stats = compute_stats(ttft_cold_trials)
    ttft_cached_stats = compute_stats(ttft_cached_trials)
    tps_stats = compute_stats(tps_trials)
    cached_ttft_warning = (
        ttft_cold_stats["mean"] > 0
        and ttft_cached_stats["mean"]
        >= ttft_cold_stats["mean"] * CACHED_TTFT_WARNING_RATIO
    )
    if cached_ttft_warning:
        logger.warning(
            "  Warning: cached TTFT is close to cold TTFT. The engine may not "
            "have reused a prompt/KV cache for this run."
        )
    token_count_source = _summarize_token_count_sources(token_count_sources)
    word_fallback_warning = token_count_source in {
        TOKEN_COUNT_SOURCE_WORD_FALLBACK,
        TOKEN_COUNT_SOURCE_MIXED,
    }
    if word_fallback_warning:
        logger.warning(
            "  Warning: throughput token counts used word_fallback for at least "
            "one trial. Local tok/s results are estimates and are not "
            "leaderboard-comparable."
        )
        logger.warning(
            "  Use an engine/server that returns usage.completion_tokens in the "
            "streaming response for comparable results."
        )

    sustained_throttling_warning = (
        benchmark_profile == BENCHMARK_PROFILE_SUSTAINED
        and _detect_sustained_throttling(
            throughput_progress_samples_trials,
            thermal_summary,
        )
    )
    if sustained_throttling_warning:
        logger.warning(
            "  Warning: sustained profile observed a late-run throughput drop "
            "while thermal state changed or became non-nominal."
        )

    decode_tps_stats = None
    decode_timing_source = DECODE_TIMING_UNAVAILABLE
    if decode_tps_trials and len(decode_tps_trials) == len(tps_trials):
        unique_decode_sources = set(decode_timing_sources)
        if len(unique_decode_sources) == 1 and unique_decode_sources <= {
            DECODE_TIMING_CLIENT_STREAM,
        }:
            decode_tps_stats = compute_stats(decode_tps_trials)
            decode_timing_source = unique_decode_sources.pop()
        else:
            logger.warning(
                "Decode throughput sources were mixed or unavailable; "
                "decode_tokens_per_second will be omitted."
            )
    elif decode_tps_trials:
        logger.warning(
            "Decode throughput was available for only some throughput trials; "
            "decode_tokens_per_second will be omitted."
        )

    # 7. Build result
    result = {
        "hardware": hw,
        "engine": {
            "name": engine_name,
            "version": engine_version,
        },
        "model": {
            "name": model_name,
            "quantization": model_quantization,
        },
        "metrics": {
            "ttft_cold": ttft_cold_stats,
            "ttft_cached": ttft_cached_stats,
            "tokens_per_second": tps_stats,
            "request_tokens_per_second": tps_stats,
            "decode_tokens_per_second": decode_tps_stats,
            "decode_timing_source": decode_timing_source,
            "ram_peak_gb": round(peak_ram_gb, 3),
            "ram_is_process_rss": ram_is_process_rss,
            "ram_measurement_method": (
                RAM_MEASUREMENT_PROCESS_RSS
                if ram_is_process_rss
                else RAM_MEASUREMENT_SYSTEM_FALLBACK
            ),
            "system_ram_peak_gb": round(system_ram_peak_gb, 3),
            "system_ram_peak_percent": round(system_ram_peak_percent, 1),
            "token_count_source": token_count_source,
        },
        "trials": {
            "count": trials,
            "ttft_cold_raw": ttft_cold_trials,
            "ttft_cached_raw": ttft_cached_trials,
            "tokens_per_second_raw": tps_trials,
            "throughput_elapsed_seconds_raw": throughput_elapsed_trials,
            "decode_tokens_per_second_raw": (
                decode_tps_trials if len(decode_tps_trials) == len(tps_trials) else None
            ),
            "completion_tokens_raw": completion_tokens_trials,
            "throughput_progress_samples_raw": (
                throughput_progress_samples_trials
                if any(throughput_progress_samples_trials)
                else None
            ),
        },
        "meta": {
            "chronos_version": VERSION,
            "timestamp": datetime.now(timezone.utc),
            "benchmark_profile": benchmark_profile,
            "ram_sample_interval_seconds": ram_sample_interval,
            "elapsed_since_last_benchmark_seconds": (
                round(elapsed_since_last_benchmark_seconds, 3)
                if elapsed_since_last_benchmark_seconds is not None
                else None
            ),
            "cooldown_seconds": cooldown_seconds,
            "phase_timings_seconds": phase_timings,
            "thermal_monitor": thermal_summary,
            "warmup_failures": warmup_failures,
            "word_fallback_warning": word_fallback_warning,
            "engine_version_warning": engine_version_warning,
            "sustained_throttling_warning": sustained_throttling_warning,
            "cached_ttft_warning": cached_ttft_warning,
            "benchmark_protocol": build_benchmark_protocol(
                trials,
                throughput_max_tokens,
                throughput_min_tokens,
                name=benchmark_profile,
            ),
            "notes": notes,
        }
    }
    # Validate against schema before returning
    return dump_benchmark_result(BenchmarkResult(**result))


if __name__ == "__main__":
    from mlx_chronos.reporters import JSONReporter

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    result = run_benchmark(
        engine_name="omlx",
        model_name="Qwen3.5-4B-OptiQ-4bit",
        model_quantization="4bit",
        trials=5,
        notes="Test run — unique cold prompts per trial"
    )

    reporter = JSONReporter()
    path = reporter.save(result, Path.cwd() / "results" / "local")

    logger.info("\n--- Result ---")
    logger.info(json.dumps(result, indent=2))
