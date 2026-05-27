from datetime import datetime
import statistics

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from typing import Optional, Annotated, Literal

from mlx_chronos.constants import (
    VALID_ENGINE_NAMES,
    MAX_TRIALS,
    RAM_MEASUREMENT_PROCESS_RSS,
    RAM_MEASUREMENT_SYSTEM_FALLBACK,
)


NonNegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
PercentFloat = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
TokenCountSource = Literal[
    "usage.completion_tokens",
    "word_fallback",
    "mixed",
]
RAMMeasurementMethod = Literal[
    "process_rss",
    "system_fallback",
]


class ChronosBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Hardware(ChronosBaseModel):
    chip: str = Field(..., description="Apple Silicon chip model (e.g. 'Apple M2')")
    machine_model: str = Field(..., description="Mac machine identifier (e.g. 'Mac14,2')")
    memory_gb: NonNegativeFloat = Field(..., description="Unified memory in GB")
    macos_version: str = Field(..., description="macOS version (e.g. '15.3.1')")
    python_version: str = Field(..., description="Python version (e.g. '3.11.4')")
    architecture: str = Field(..., min_length=1, description="CPU architecture (e.g. 'arm64')")
    thermal_state: Optional[str] = Field(
        "unavailable_no_sudo",
        description="Thermal pressure level (nominal/fair/serious/critical or unavailable_*)",
    )


class Engine(ChronosBaseModel):
    name: str = Field(..., description="Engine name")
    version: str = Field(..., min_length=1, description="Engine version string")

    @field_validator("name")
    @classmethod
    def validate_engine_name(cls, value: str) -> str:
        if value not in VALID_ENGINE_NAMES:
            raise ValueError(
                f"Unknown engine: '{value}'. Available: {sorted(VALID_ENGINE_NAMES)}"
            )
        return value


class Model(ChronosBaseModel):
    name: str = Field(..., description="Model name (e.g. 'Qwen3.5-9B')")
    quantization: str = Field(..., description="Quantization format (e.g. '4bit', '8bit')")

    @field_validator("quantization")
    @classmethod
    def normalize_quantization(cls, value: str) -> str:
        normalized = value.strip().lower().replace("-", "").replace("_", "").replace(" ", "")
        if not normalized:
            raise ValueError("quantization must not be empty")
        aliases = {
            "4bits": "4bit",
            "int4": "4bit",
            "q4": "4bit",
            "8bits": "8bit",
            "int8": "8bit",
            "q8": "8bit",
            "float16": "fp16",
            "f16": "fp16",
            "bfloat16": "bf16",
        }
        return aliases.get(normalized, normalized)


class TrialStats(ChronosBaseModel):
    mean: NonNegativeFloat = Field(..., description="Mean across trials")
    stddev: NonNegativeFloat = Field(..., description="Standard deviation across trials")
    min: NonNegativeFloat = Field(..., description="Minimum observed value")
    max: NonNegativeFloat = Field(..., description="Maximum observed value")

    @model_validator(mode="after")
    def validate_range(self):
        if self.min > self.max:
            raise ValueError("min must be less than or equal to max")
        if not self.min <= self.mean <= self.max:
            raise ValueError("mean must be between min and max")
        return self


class Metrics(ChronosBaseModel):
    ttft_cold: TrialStats = Field(..., description="Time to first token, cold (seconds)")
    ttft_cached: TrialStats = Field(..., description="Time to first token, cached (seconds)")
    tokens_per_second: TrialStats = Field(..., description="Generation throughput (tok/s)")
    ram_peak_gb: NonNegativeFloat = Field(
        ...,
        description=(
            "Peak RSS of the engine server process after warmup during the benchmark, or "
            "fallback system memory usage when the process cannot be located (GB)"
        ),
    )
    ram_is_process_rss: bool = Field(
        ..., 
        description="True if RAM was measured from process RSS, False if system fallback was used"
    )
    ram_measurement_method: RAMMeasurementMethod = Field(
        ...,
        description="Measurement method used for ram_peak_gb",
    )
    system_ram_peak_gb: NonNegativeFloat = Field(
        ...,
        description="Peak total Mac RAM in use during the benchmark (GB)",
    )
    system_ram_peak_percent: PercentFloat = Field(
        ...,
        description="Peak total Mac RAM usage percentage during the benchmark",
    )
    token_count_source: TokenCountSource = Field(
        ...,
        description="Source used to count generated tokens for throughput",
    )

    @model_validator(mode="after")
    def validate_ram_method_matches_boolean(self):
        expected = (
            RAM_MEASUREMENT_PROCESS_RSS
            if self.ram_is_process_rss
            else RAM_MEASUREMENT_SYSTEM_FALLBACK
        )
        if self.ram_measurement_method != expected:
            raise ValueError("ram_measurement_method must match ram_is_process_rss")
        return self


class Trials(ChronosBaseModel):
    count: int = Field(..., ge=1, le=MAX_TRIALS, description="Number of trials run")
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


class Meta(ChronosBaseModel):
    chronos_version: str = Field(..., min_length=1, description="mlx-chronos version used")
    timestamp: datetime = Field(..., description="Timestamp of the benchmark run")
    ram_sample_interval_seconds: Optional[float] = Field(
        None,
        gt=0,
        description="Seconds between engine RSS and system RAM samples",
    )
    notes: Optional[str] = Field(None, description="Optional notes from the contributor")

    @field_validator("timestamp")
    @classmethod
    def validate_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class BenchmarkResult(ChronosBaseModel):
    hardware: Hardware
    engine: Engine
    model: Model
    metrics: Metrics
    trials: Trials
    meta: Meta

    @model_validator(mode="after")
    def validate_summary_stats_match_raw_trials(self):
        self._assert_stats_match_raw(
            self.metrics.ttft_cold,
            self.trials.ttft_cold_raw,
            "metrics.ttft_cold",
        )
        self._assert_stats_match_raw(
            self.metrics.ttft_cached,
            self.trials.ttft_cached_raw,
            "metrics.ttft_cached",
        )
        self._assert_stats_match_raw(
            self.metrics.tokens_per_second,
            self.trials.tokens_per_second_raw,
            "metrics.tokens_per_second",
        )
        return self

    @staticmethod
    def _assert_stats_match_raw(stats: TrialStats, raw_values: list[float], label: str) -> None:
        expected = {
            "mean": round(statistics.mean(raw_values), 3),
            "stddev": round(statistics.stdev(raw_values), 3) if len(raw_values) > 1 else 0.0,
            "min": round(min(raw_values), 3),
            "max": round(max(raw_values), 3),
        }
        actual = {
            "mean": stats.mean,
            "stddev": stats.stddev,
            "min": stats.min,
            "max": stats.max,
        }
        tolerance = 0.001
        for key, expected_value in expected.items():
            if abs(actual[key] - expected_value) > tolerance:
                raise ValueError(
                    f"{label}.{key} must match raw trials "
                    f"(expected {expected_value}, got {actual[key]})"
                )


# Example valid result — used in tests and documentation
EXAMPLE_RESULT = {
    "hardware": {
        "chip": "Apple M2",
        "machine_model": "Mac14,2",
        "memory_gb": 8.0,
        "macos_version": "15.3.1",
        "python_version": "3.11.4",
        "architecture": "arm64",
        "thermal_state": "unavailable_no_sudo"
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
        "ram_peak_gb": 7.22,
        "ram_is_process_rss": False,
        "ram_measurement_method": "system_fallback",
        "system_ram_peak_gb": 7.22,
        "system_ram_peak_percent": 90.2,
        "token_count_source": "usage.completion_tokens"
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
