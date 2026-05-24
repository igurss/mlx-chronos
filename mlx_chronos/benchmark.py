import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
import logging

from mlx_chronos.detect import detect_hardware
from mlx_chronos.engines import get_engine
from mlx_chronos.schema import BenchmarkResult

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("mlx_chronos")

# mlx-chronos version
VERSION = "0.1.0"

# Results output directory
RESULTS_DIR = Path(__file__).parent.parent / "results" / "submitted"

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
        return {"mean": None, "stddev": None, "min": None, "max": None}
    mean = statistics.mean(values)
    stddev = statistics.stdev(values) if len(values) > 1 else 0.0
    return {
        "mean": round(mean, 3),
        "stddev": round(stddev, 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }


def run_benchmark(
    engine_name: str,
    model_name: str,
    model_quantization: str,
    model_size_gb: float,
    trials: int = DEFAULT_TRIALS,
    notes: str = None,
) -> dict:
    """
    Run a full benchmark session for a given engine and model.
    Returns a structured result dict with trial statistics.
    """

    if trials > len(COLD_PROMPTS):
        raise ValueError(
            f"Max trials is {len(COLD_PROMPTS)} (one unique cold prompt per trial). "
            f"Requested: {trials}"
        )

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
    version = engine.get_version()
    logger.info(f"Engine version: {version}\n")

    # 4. Warmup phase — 2 calls with the throughput prompt, not recorded
    logger.info("Warming up (2 calls, not recorded)...")
    for _ in range(2):
        try:
            engine.measure_tokens_per_second(THROUGHPUT_PROMPT, model=model_name, max_tokens=30)
        except Exception:
            pass
    logger.info("  Done.\n")

    # 5. Run trials
    ttft_cold_trials = []
    ttft_cached_trials = []
    tps_trials = []

    # Fixed prompt for cached TTFT — same prompt every trial = cache hit
    cached_prompt = "Explain the concept of unified memory in Apple Silicon in one sentence."

    # Priming call — load cached_prompt into engine cache, not recorded
    logger.info("Priming cache for cached TTFT measurement...")
    try:
        engine.measure_ttft(cached_prompt, model=model_name)
    except Exception:
        pass
    logger.info("  Done.\n")

    for i in range(trials):
        logger.info(f"Trial {i + 1}/{trials}")

        # Cold TTFT — unique prompt per trial, never seen before
        cold_prompt = COLD_PROMPTS[i]
        logger.info(f"  Cold TTFT (unique prompt)...")
        ttft_cold_trials.append(engine.measure_ttft(cold_prompt, model=model_name))

        # Cached TTFT — same prompt every trial
        logger.info(f"  Cached TTFT (fixed prompt)...")
        ttft_cached_trials.append(engine.measure_ttft(cached_prompt, model=model_name))

        # Throughput
        logger.info(f"  Throughput...")
        tps_trials.append(
            engine.measure_tokens_per_second(THROUGHPUT_PROMPT, model=model_name)
        )

    logger.info("")

    # 6. Compute statistics
    ttft_cold_stats = compute_stats(ttft_cold_trials)
    ttft_cached_stats = compute_stats(ttft_cached_trials)
    tps_stats = compute_stats(tps_trials)

    # 7. RAM after trials
    logger.info("Measuring RAM...")
    ram, ram_is_fallback = engine.measure_ram_peak()
    if ram_is_fallback:
        logger.warning("  Warning: RAM measured as system fallback, not process RSS.")

    # Normalize model name — strip path if full path was passed
    model_display_name = model_name.split("/")[-1] if "/" in model_name else model_name

    # 8. Build result
    result = {
        "hardware": hw,
        "engine": {
            "name": engine_name,
            "version": version,
        },
        "model": {
            "name": model_display_name,
            "quantization": model_quantization,
            "size_gb": model_size_gb,
        },
        "metrics": {
            "ttft_cold": ttft_cold_stats,
            "ttft_cached": ttft_cached_stats,
            "tokens_per_second": tps_stats,
            "ram_peak_gb": ram,
            "ram_is_process_rss": not ram_is_fallback,
        },
        "trials": {
            "count": trials,
            "ttft_cold_raw": ttft_cold_trials,
            "ttft_cached_raw": ttft_cached_trials,
            "tokens_per_second_raw": tps_trials,
        },
        "meta": {
            "chronos_version": VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "notes": notes,
        }
    }
    # Validate against schema before returning
    BenchmarkResult(**result)
    return result


def save_result(result: dict) -> Path:
    """Save a benchmark result to results/submitted/."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    chip_slug = result["hardware"]["chip"].replace(" ", "_").lower()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    engine_name = result["engine"]["name"]
    filename = f"{engine_name}_{chip_slug}_{ts}.json"

    output_path = RESULTS_DIR / filename

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    logger.info(f"\nResult saved to: {output_path}")
    return output_path


if __name__ == "__main__":
    result = run_benchmark(
        engine_name="omlx",
        model_name="Qwen3.5-4B-OptiQ-4bit",
        model_quantization="4bit",
        model_size_gb=3.2,
        trials=5,
        notes="Test run — unique cold prompts per trial"
    )

    path = save_result(result)

    logger.info("\n--- Result ---")
    logger.info(json.dumps(result, indent=2))