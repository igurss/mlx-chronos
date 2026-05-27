from datetime import datetime

from pydantic import BaseModel, Field, model_validator, field_validator
from typing import Optional, Annotated


NonNegativeFloat = Annotated[float, Field(ge=0)]


class Hardware(BaseModel):
    chip: str = Field(..., description="Apple Silicon chip model (e.g. 'Apple M2')")
    machine_model: str = Field(..., description="Mac machine identifier (e.g. 'Mac14,2')")
    memory_gb: float = Field(..., ge=0, description="Unified memory in GB")
    macos_version: str = Field(..., description="macOS version (e.g. '15.3.1')")
    python_version: str = Field(..., description="Python version (e.g. '3.11.4')")
    thermal_state: Optional[str] = Field(
        "unavailable_no_sudo",
        description="Thermal pressure level (nominal/fair/serious/critical or unavailable_*)",
    )
    system_ram_usage_percent: float = Field(
        ...,
        ge=0, le=100,
        description="System RAM usage percentage before benchmark starts",
    )


class Engine(BaseModel):
    name: str = Field(..., description="Engine name")
    version: str = Field(..., description="Engine version string")

    @field_validator("name")
    @classmethod
    def validate_engine_name(cls, value: str) -> str:
        from mlx_chronos.engines import ENGINES
        if value not in ENGINES:
            raise ValueError(f"Unknown engine: '{value}'. Available: {list(ENGINES.keys())}")
        return value


class Model(BaseModel):
    name: str = Field(..., description="Model name (e.g. 'Qwen3.5-9B')")
    quantization: str = Field(..., description="Quantization format (e.g. '4bit', '8bit')")


class TrialStats(BaseModel):
    mean: float = Field(..., ge=0, description="Mean across trials")
    stddev: float = Field(..., ge=0, description="Standard deviation across trials")
    min: float = Field(..., ge=0, description="Minimum observed value")
    max: float = Field(..., ge=0, description="Maximum observed value")

    @model_validator(mode="after")
    def validate_range(self):
        if self.min > self.max:
            raise ValueError("min must be less than or equal to max")
        if not self.min <= self.mean <= self.max:
            raise ValueError("mean must be between min and max")
        return self


class Metrics(BaseModel):
    ttft_cold: TrialStats = Field(..., description="Time to first token, cold (seconds)")
    ttft_cached: TrialStats = Field(..., description="Time to first token, cached (seconds)")
    tokens_per_second: TrialStats = Field(..., description="Generation throughput (tok/s)")
    ram_peak_gb: float = Field(..., ge=0, description="Peak engine process RSS or fallback system RAM usage (GB)")
    ram_is_process_rss: bool = Field(
        ..., 
        description="True if RAM was measured from process RSS, False if system fallback was used"
    )


class Trials(BaseModel):
    count: int = Field(..., ge=1, description="Number of trials run")
    ttft_cold_raw: list[NonNegativeFloat] = Field(..., description="Raw cold TTFT values per trial")
    ttft_cached_raw: list[NonNegativeFloat] = Field(..., description="Raw cached TTFT values per trial")
    tokens_per_second_raw: list[NonNegativeFloat] = Field(..., description="Raw tok/s values per trial")

    @model_validator(mode="after")
    def validate_raw_lengths(self):
        lengths = {
            len(self.ttft_cold_raw),
            len(self.ttft_cached_raw),
            len(self.tokens_per_second_raw),
        }
        if lengths != {self.count}:
            raise ValueError("trials.count must match all raw metric list lengths")
        return self


class Meta(BaseModel):
    chronos_version: str = Field(..., description="mlx-chronos version used")
    timestamp: datetime = Field(..., description="Timestamp of the benchmark run")
    ram_sample_interval_seconds: Optional[float] = Field(
        None,
        gt=0,
        description="Seconds between process RSS samples during RAM tracking",
    )
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
        "machine_model": "Mac14,2",
        "memory_gb": 8.0,
        "macos_version": "15.3.1",
        "python_version": "3.11.4",
        "thermal_state": "unavailable_no_sudo",
        "system_ram_usage_percent": 50.0
    },
    "engine": {
        "name": "omlx",
        "version": "0.3.9"
    },
    "model": {
        "name": "Qwen3.5-4B-OptiQ-4bit",
        "quantization": "4bit"
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
        "ram_sample_interval_seconds": 0.05,
        "notes": "Test run"
    }
}


if __name__ == "__main__":
    import json
    result = BenchmarkResult(**EXAMPLE_RESULT)
    print(json.dumps(result.model_dump(mode="json"), indent=2))
    print("\nSchema validation: OK")
