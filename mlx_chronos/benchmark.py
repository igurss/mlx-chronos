import json
import time
from datetime import datetime, timezone
from pathlib import Path

from mlx_chronos.detect import detect_hardware
from mlx_chronos.engines import get_engine
from mlx_chronos.schema import BenchmarkResult, Hardware, Engine, Model, Metrics, Meta

# mlx-chronos version
VERSION = "0.1.0"

# Results output directory
RESULTS_DIR = Path(__file__).parent.parent / "results" / "submitted"


def run_benchmark(engine_name: str, model_name: str, model_quantization: str, model_size_gb: float, notes: str = None) -> BenchmarkResult:
    """
    Run a full benchmark session for a given engine and model.
    Returns a validated BenchmarkResult ready to be saved and submitted.
    """

    print(f"\n{'='*50}")
    print(f"  mlx-Chronos Benchmark")
    print(f"  Engine : {engine_name}")
    print(f"  Model  : {model_name} ({model_quantization})")
    print(f"{'='*50}\n")

    # 1. Detect hardware
    print("Detecting hardware...")
    hw = detect_hardware()
    print(f"  {hw['chip']} — {hw['memory_gb']}GB — macOS {hw['macos_version']}\n")

    # 2. Get engine
    engine = get_engine(engine_name)

    if not engine.is_installed():
        raise RuntimeError(f"Engine '{engine_name}' is not installed on this system.")

    if not engine.is_server_running():
        raise RuntimeError(
            f"Engine '{engine_name}' server is not running. "
            f"Please start it before running mlx-chronos."
        )

    # 3. Get engine version
    version = engine.get_version()
    print(f"Engine version: {version}\n")

    # 4. Run metrics
    print("Running benchmark...\n")
    metrics = engine.run_benchmark(model=model_name)

    # 5. Build result
    result = BenchmarkResult(
        hardware=Hardware(**hw),
        engine=Engine(name=engine_name, version=version),
        model=Model(
            name=model_name,
            quantization=model_quantization,
            size_gb=model_size_gb,
        ),
        metrics=Metrics(**metrics),
        meta=Meta(
            chronos_version=VERSION,
            timestamp=datetime.now(timezone.utc).isoformat(),
            notes=notes,
        )
    )

    return result


def save_result(result: BenchmarkResult) -> Path:
    """Save a BenchmarkResult to the results/submitted directory."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Filename: engine_chip_timestamp.json
    chip_slug = result.hardware.chip.replace(" ", "_").lower()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{result.engine.name}_{chip_slug}_{ts}.json"

    output_path = RESULTS_DIR / filename

    with open(output_path, "w") as f:
        json.dump(result.model_dump(), f, indent=2)

    print(f"\nResult saved to: {output_path}")
    return output_path


if __name__ == "__main__":
    # Quick test — runs only if oMLX server is already running
    result = run_benchmark(
        engine_name="omlx",
        model_name="Qwen3.5-4B",
        model_quantization="4bit",
        model_size_gb=2.4,
        notes="Test run from mlx-chronos development"
    )

    path = save_result(result)

    print("\n--- Result ---")
    print(json.dumps(result.model_dump(), indent=2))