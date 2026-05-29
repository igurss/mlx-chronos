import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
import logging
import threading
import time
import os
import psutil

from mlx_chronos.constants import (
    MAX_TRIALS,
    RAM_MEASUREMENT_PROCESS_RSS,
    RAM_MEASUREMENT_SYSTEM_FALLBACK,
    TOKEN_COUNT_SOURCE_MIXED,
    TOKEN_COUNT_SOURCE_USAGE,
    TOKEN_COUNT_SOURCE_WORD_FALLBACK,
    TOKEN_COUNT_SOURCES,
)
from mlx_chronos import __version__ as VERSION
from mlx_chronos.detect import detect_hardware
from mlx_chronos.engines import get_engine
from mlx_chronos.schema import BenchmarkResult

class RAMTracker:
    """
    Continuously samples the RAM (RSS) of the target process in a separate thread.
    Solves the issue of missing a memory peak between the start and end of inference.
    """
    def __init__(self, interval: float = 0.05, target_pid: int = None):
        self.pid = target_pid or os.getpid()
        self.interval = interval
        self._process = psutil.Process(self.pid)
        self.peak_ram_bytes = 0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None

    def _sample_rss(self) -> int:
        rss_bytes = self._process.memory_info().rss
        try:
            for child in self._process.children(recursive=True):
                try:
                    rss_bytes += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return rss_bytes

    def _monitor(self):
        while not self._stop_event.is_set():
            try:
                current_ram = self._sample_rss()
                with self._lock:
                    if current_ram > self.peak_ram_bytes:
                        self.peak_ram_bytes = current_ram
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                try:
                    is_running = self._process.is_running()
                except psutil.Error:
                    break
                if not is_running:
                    break
                time.sleep(self.interval)
                continue
            time.sleep(self.interval)

    def start(self):
        """Run the sampling."""
        self.peak_ram_bytes = self._sample_rss()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()

    def stop(self) -> float:
        """Stop sampling and return the peak RAM in GB."""
        self._stop_event.set()
        if self._thread:
            self._thread.join()

        # Byte conversion to GB
        with self._lock:
            peak = self.peak_ram_bytes
        return peak / (1024 ** 3)


class SystemRAMTracker:
    """Continuously samples total system RAM usage during the benchmark."""

    def __init__(self, interval: float = 0.05):
        self.interval = interval
        self.peak_used_bytes = 0
        self.peak_percent = 0.0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None

    def _sample_system_ram(self) -> tuple[int, float]:
        mem = psutil.virtual_memory()
        used_bytes = max(0, mem.total - mem.available)
        percent = (used_bytes / mem.total * 100) if mem.total else 0.0
        return used_bytes, percent

    def _monitor(self):
        while not self._stop_event.is_set():
            used_bytes, percent = self._sample_system_ram()
            with self._lock:
                if used_bytes > self.peak_used_bytes:
                    self.peak_used_bytes = used_bytes
                    self.peak_percent = percent
            time.sleep(self.interval)

    def start(self):
        self.peak_used_bytes, self.peak_percent = self._sample_system_ram()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()

    def stop(self) -> tuple[float, float]:
        self._stop_event.set()
        if self._thread:
            self._thread.join()
        with self._lock:
            peak_used = self.peak_used_bytes
            peak_pct = self.peak_percent
        return peak_used / (1024 ** 3), peak_pct


logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("mlx_chronos")

# Default RAM sampling interval in seconds
DEFAULT_RAM_SAMPLE_INTERVAL = 0.05

# Default number of trials
DEFAULT_TRIALS = 5

# Prompt pool for cold TTFT — each trial uses a different prompt
# to avoid cache hits between trials
COLD_PROMPTS = [
    "What is the capital of Australia?",
    "Explain what a transformer neural network is in one sentence.",
    "What does RAM stand for in computing?",
    "Describe the difference between a CPU and a GPU briefly.",
    "What is the boiling point of water in Celsius?",
    "Name the three laws of thermodynamics in one sentence each.",
    "What is gradient descent in machine learning?",
    "Explain what an operating system does in simple terms.",
]

# Fixed prompt used for cached TTFT trials.
CACHED_TTFT_PROMPT = (
    "Explain the concept of unified memory in Apple Silicon in one sentence."
)

# Standard throughput prompt — fixed across all engines and versions
# Do not change this without bumping chronos_version
THROUGHPUT_PROMPT = (
    "Explain in detail how the attention mechanism works in transformer "
    "neural networks, including the role of queries, keys, and values."
)


def compute_stats(values: list[float]) -> dict:
    """Compute mean, stddev, min, max from a list of float values.
    p95 is only meaningful with 20+ trials — use min/max for small samples.
    """
    if not values:
        raise ValueError("values must contain at least one measurement")
    mean = statistics.mean(values)
    stddev = statistics.stdev(values) if len(values) > 1 else 0.0
    return {
        "mean": round(mean, 3),
        "stddev": round(stddev, 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }


def _normalize_token_count_source(source: object) -> str:
    if isinstance(source, str) and source in TOKEN_COUNT_SOURCES:
        return source
    return TOKEN_COUNT_SOURCE_WORD_FALLBACK


def _summarize_token_count_sources(sources: list[str]) -> str:
    unique_sources = set(sources)
    if unique_sources == {TOKEN_COUNT_SOURCE_USAGE}:
        return TOKEN_COUNT_SOURCE_USAGE
    if unique_sources == {TOKEN_COUNT_SOURCE_WORD_FALLBACK}:
        return TOKEN_COUNT_SOURCE_WORD_FALLBACK
    return TOKEN_COUNT_SOURCE_MIXED


def run_benchmark(
    engine_name: str,
    model_name: str,
    model_quantization: str,
    trials: int = DEFAULT_TRIALS,
    notes: str = None,
    ram_sample_interval: float = DEFAULT_RAM_SAMPLE_INTERVAL,
) -> dict:
    """
    Run a full benchmark session for a given engine and model.
    Returns a structured result dict with trial statistics.
    """

    if trials > MAX_TRIALS:
        raise ValueError(
            f"Max trials is {MAX_TRIALS} (one unique cold prompt per trial). "
            f"Requested: {trials}"
        )
    if trials < 1:
        raise ValueError("trials must be at least 1")
    if ram_sample_interval <= 0:
        raise ValueError("ram_sample_interval must be greater than 0")
    model_name = model_name.strip()
    if not model_name:
        raise ValueError("model name must not be empty")

    logger.info(f"\n{'='*50}")
    logger.info(f"  mlx-Chronos Benchmark")
    logger.info(f"  Engine : {engine_name}")
    logger.info(f"  Model  : {model_name} ({model_quantization})")
    logger.info(f"  Trials : {trials}")
    logger.info(f"{'='*50}\n")

    # 1. Detect hardware
    logger.info("Detecting hardware...")
    hw = detect_hardware()
    logger.info(f"  {hw['chip']} — {hw['memory_gb']}GB — macOS {hw['macos_version']}\n")

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

    # 4. Start system memory sampling before warmup so load/cache pressure is captured.
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
    token_count_sources = []

    peak_ram_gb = None
    system_ram_peak_gb = None
    system_ram_peak_percent = None
    ram_tracker = None
    ram_is_process_rss = False

    try:
        # Warmup phase — 2 calls with the throughput prompt, not recorded
        logger.info("Warming up (2 calls, not recorded)...")
        for _ in range(2):
            try:
                engine.measure_tokens_per_second(
                    THROUGHPUT_PROMPT,
                    model=model_name,
                    max_tokens=30,
                )
            except Exception as exc:
                logger.warning(f"  Warmup call failed and was skipped: {exc}")
        logger.info("  Done.\n")

        logger.info(
            f"Starting continuous background engine RSS sampling "
            f"({ram_sample_interval:.3f}s interval)..."
        )
        target_pid = engine.get_server_pid()
        if target_pid is None:
            logger.warning(
                "Engine PID not found; engine RSS will use system RAM peak fallback."
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
                    f"Could not start engine RSS sampling for PID {target_pid}: {exc}"
                )
                ram_tracker = None

        logger.info("Running cold TTFT trials...")
        for i in range(trials):
            cold_prompt = COLD_PROMPTS[i]
            logger.info(f"  Cold trial {i + 1}/{trials} (unique prompt)...")
            ttft_cold_trials.append(engine.measure_ttft(cold_prompt, model=model_name))

        logger.info("\nPriming cache for cached TTFT measurement...")
        try:
            engine.measure_ttft(CACHED_TTFT_PROMPT, model=model_name)
        except Exception as exc:
            logger.warning(f"  Cache priming failed; cached TTFT may be cold: {exc}")
        logger.info("  Done.\n")

        logger.info("Running cached TTFT trials...")
        for i in range(trials):
            logger.info(f"  Cached trial {i + 1}/{trials} (fixed prompt)...")
            ttft_cached_trials.append(
                engine.measure_ttft(CACHED_TTFT_PROMPT, model=model_name)
            )

        logger.info("\nRunning throughput trials...")
        for i in range(trials):
            logger.info(f"  Throughput trial {i + 1}/{trials}...")
            tps_trials.append(
                engine.measure_tokens_per_second(THROUGHPUT_PROMPT, model=model_name)
            )
            token_count_sources.append(
                _normalize_token_count_source(
                    getattr(engine, "last_token_count_source", None)
                )
            )
    finally:
        if ram_tracker:
            peak_ram_gb = ram_tracker.stop()
            logger.info(
                f"Engine RSS sampling finished. Peak detected: {peak_ram_gb:.2f} GB"
            )
        else:
            ram_is_process_rss = False

        system_ram_peak_gb, system_ram_peak_percent = system_ram_tracker.stop()
        logger.info(
            "System RAM sampling finished. Peak detected: "
            f"{system_ram_peak_gb:.2f} GB ({system_ram_peak_percent:.1f}%)\n"
        )

        if peak_ram_gb is None:
            peak_ram_gb = system_ram_peak_gb

    logger.info("")

    # 6. Compute statistics
    ttft_cold_stats = compute_stats(ttft_cold_trials)
    ttft_cached_stats = compute_stats(ttft_cached_trials)
    tps_stats = compute_stats(tps_trials)
    token_count_source = _summarize_token_count_sources(token_count_sources)


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
        },
        "meta": {
            "chronos_version": VERSION,
            "timestamp": datetime.now(timezone.utc),
            "ram_sample_interval_seconds": ram_sample_interval,
            "notes": notes,
        }
    }
    # Validate against schema before returning
    return BenchmarkResult(**result).model_dump(mode="json")


if __name__ == "__main__":
    from mlx_chronos.reporters import JSONReporter
    
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
