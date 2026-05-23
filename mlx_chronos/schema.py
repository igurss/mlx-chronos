from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


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
    size_gb: float = Field(..., description="Model size on disk in GB")


class Metrics(BaseModel):
    ttft_cold: float = Field(..., description="Time to first token, cold start (seconds)")
    ttft_cached: Optional[float] = Field(None, description="Time to first token, cached (seconds)")
    tokens_per_second: float = Field(..., description="Generation throughput (tok/s)")
    tool_calling_rate: Optional[float] = Field(None, description="Tool calling success rate (0.0 to 1.0)")
    ram_peak_gb: float = Field(..., description="Peak RAM usage during inference (GB)")


class Meta(BaseModel):
    chronos_version: str = Field(..., description="mlx-chronos version used")
    timestamp: str = Field(..., description="ISO 8601 timestamp of the benchmark run")
    notes: Optional[str] = Field(None, description="Optional notes from the contributor")


class BenchmarkResult(BaseModel):
    hardware: Hardware
    engine: Engine
    model: Model
    metrics: Metrics
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
        "version": "0.3.8"
    },
    "model": {
        "name": "Qwen3.5-4B",
        "quantization": "4bit",
        "size_gb": 2.4
    },
    "metrics": {
        "ttft_cold": 0.32,
        "ttft_cached": 0.16,
        "tokens_per_second": 98.5,
        "tool_calling_rate": 1.0,
        "ram_peak_gb": 3.1
    },
    "meta": {
        "chronos_version": "0.1.0",
        "timestamp": "2026-05-23T10:00:00Z",
        "notes": "Tested with default oMLX settings"
    }
}


if __name__ == "__main__":
    import json
    # Validate the example result against the schema
    result = BenchmarkResult(**EXAMPLE_RESULT)
    print(json.dumps(result.model_dump(), indent=2))
    print("\nSchema validation: OK")