from pydantic import BaseModel, Field
from typing import Optional


class Hardware(BaseModel):
    chip: str = Field(..., description="Apple Silicon chip model (e.g. 'Apple M3 Ultra')")
    memory_gb: float = Field(..., description="Unified memory in GB")
    macos_version: str = Field(..., description="macOS version (e.g. '15.3.1')")
    python_version: str = Field(..., description="Python version (e.g. '3.11.4')")


class Engine(BaseModel):
    name: str = Field(..., description="Engine name: 'omlx', 'rapid-mlx', 'mlx-lm'")
    version: str = Field(..., description="Engine version string")


class Model(BaseModel):
    name: str = Field(..., description="Model name (e.g. 'Qwen3.5-9B')")
    quantization: str = Field(..., description="Quantization format (e.g. '4bit', '8bit')")


class TrialStats(BaseModel):
    mean: float = Field(..., description="Mean across trials")
    stddev: float = Field(..., description="Standard deviation across trials")
    min: float = Field(..., description="Minimum observed value")
    max: float = Field(..., description="Maximum observed value")


class Metrics(BaseModel):
    ttft_cold: TrialStats = Field(..., description="Time to first token, cold (seconds)")
    ttft_cached: TrialStats = Field(..., description="Time to first token, cached (seconds)")
    tokens_per_second: TrialStats = Field(..., description="Generation throughput (tok/s)")
    ram_peak_gb: float = Field(..., description="Peak RAM usage during inference (GB)")
    ram_is_process_rss: bool = Field(
        ..., 
        description="True if RAM was measured from process RSS, False if system fallback was used"
    )


class Trials(BaseModel):
    count: int = Field(..., description="Number of trials run")
    ttft_cold_raw: list[float] = Field(..., description="Raw cold TTFT values per trial")
    ttft_cached_raw: list[float] = Field(..., description="Raw cached TTFT values per trial")
    tokens_per_second_raw: list[float] = Field(..., description="Raw tok/s values per trial")


class Meta(BaseModel):
    chronos_version: str = Field(..., description="mlx-chronos version used")
    timestamp: str = Field(..., description="ISO 8601 timestamp of the benchmark run")
    notes: Optional[str] = Field(None, description="Optional notes from the contributor")


class BenchmarkResult(BaseModel):
    hardware: Hardware
    engine: Engine
    model: Model
    metrics: Metrics
    trials: Trials
    meta: Meta


# Example valid result — used in tests and documentation
EXAMPLE_RESULT = {
    "hardware": {
        "chip": "Apple M2",
        "memory_gb": 8.0,
        "macos_version": "15.3.1",
        "python_version": "3.11.4"
    },
    "engine": {
        "name": "omlx",
        "version": "0.3.9"
    },
    "model": {
        "name": "Qwen3.5-4B-OptiQ-4bit",
        "quantization": "4bit",
        "size_gb": 3.2
    },
    "metrics": {
        "ttft_cold": {"mean": 0.041, "stddev": 0.015, "min": 0.028, "max": 0.066},
        "ttft_cached": {"mean": 0.010, "stddev": 0.002, "min": 0.007, "max": 0.012},
        "tokens_per_second": {"mean": 18.44, "stddev": 0.097, "min": 18.27, "max": 18.51},
        "ram_peak_gb": 7.22, "ram_is_process_rss": False
    },
    "trials": {
        "count": 5,
        "ttft_cold_raw": [0.044, 0.066, 0.028, 0.039, 0.030],
        "ttft_cached_raw": [0.011, 0.007, 0.008, 0.010, 0.012],
        "tokens_per_second_raw": [18.48, 18.27, 18.51, 18.48, 18.46]
    },
    "meta": {
        "chronos_version": "0.1.0",
        "timestamp": "2026-05-23T15:08:36Z",
        "notes": "Test run"
    }
}


if __name__ == "__main__":
    import json
    result = BenchmarkResult(**EXAMPLE_RESULT)
    print(json.dumps(result.model_dump(), indent=2))
    print("\nSchema validation: OK")