from datetime import datetime
import math
import statistics

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from typing import Optional, Annotated, Literal

from mlx_chronos.constants import (
    VALID_ENGINE_NAMES,
    MAX_TRIALS,
    P95_MIN_TRIALS,
    RAM_MEASUREMENT_PROCESS_RSS,
    RAM_MEASUREMENT_SYSTEM_FALLBACK,
)
from mlx_chronos.measurements import (
    DECODE_TIMING_ENGINE_RESPONSE,
    DECODE_TIMING_UNAVAILABLE,
)


NonNegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]
PositiveInt = Annotated[int, Field(gt=0)]
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
InputTokenCountSource = Literal[
    "unavailable",
    "estimated",
    "tokenizer",
    "engine",
]
DecodeTimingSource = Literal[
    "unavailable",
    "engine_response",
]
ThermalMonitorSource = Literal[
    "foundation",
    "unavailable",
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
        "unavailable_permission",
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

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("model name must not be empty")
        return normalized

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
    p95: Optional[NonNegativeFloat] = Field(
        None,
        description=f"Nearest-rank p95 when at least {P95_MIN_TRIALS} trials are available",
    )

    @model_validator(mode="after")
    def validate_range(self):
        if self.min > self.max:
            raise ValueError("min must be less than or equal to max")
        if not self.min <= self.mean <= self.max:
            raise ValueError("mean must be between min and max")
        if self.min == self.max and self.stddev != 0:
            raise ValueError("stddev must be 0 when min and max are equal")
        if self.p95 is not None and not self.min <= self.p95 <= self.max:
            raise ValueError("p95 must be between min and max")
        return self


class Metrics(ChronosBaseModel):
    ttft_cold: TrialStats = Field(..., description="Time to first token, cold (seconds)")
    ttft_cached: TrialStats = Field(..., description="Time to first token, cached (seconds)")
    tokens_per_second: TrialStats = Field(
        ...,
        description=(
            "Legacy throughput field: client-observed total request throughput (tok/s), "
            "including request overhead, prefill, and decode"
        ),
    )
    request_tokens_per_second: Optional[TrialStats] = Field(
        None,
        description=(
            "Client-observed total request throughput (tok/s), including request "
            "overhead, prefill, and decode. New results mirror tokens_per_second here."
        ),
    )
    decode_tokens_per_second: Optional[TrialStats] = Field(
        None,
        description="Decode-only throughput (tok/s) when reliable engine timing is available",
    )
    decode_timing_source: DecodeTimingSource = Field(
        DECODE_TIMING_UNAVAILABLE,
        description="Source used for decode-only throughput timing",
    )
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
        if self.decode_tokens_per_second is None:
            if self.decode_timing_source != DECODE_TIMING_UNAVAILABLE:
                raise ValueError(
                    "decode_timing_source must be unavailable when decode throughput is missing"
                )
        elif self.decode_timing_source != DECODE_TIMING_ENGINE_RESPONSE:
            raise ValueError(
                "decode_timing_source must describe provided decode throughput"
            )
        return self


class Trials(ChronosBaseModel):
    count: int = Field(..., ge=1, le=MAX_TRIALS, description="Number of trials run")
    ttft_cold_raw: list[NonNegativeFloat] = Field(..., description="Raw cold TTFT values per trial")
    ttft_cached_raw: list[NonNegativeFloat] = Field(..., description="Raw cached TTFT values per trial")
    tokens_per_second_raw: list[NonNegativeFloat] = Field(..., description="Raw tok/s values per trial")
    throughput_elapsed_seconds_raw: Optional[list[PositiveFloat]] = Field(
        None,
        description="Client-observed elapsed seconds for each throughput request",
    )
    decode_tokens_per_second_raw: Optional[list[NonNegativeFloat]] = Field(
        None,
        description="Raw decode-only tok/s values per throughput trial when available",
    )
    completion_tokens_raw: Optional[list[NonNegativeInt]] = Field(
        None,
        description=(
            "Generated completion token counts per throughput trial when available. "
            "For word_fallback results this is an estimated output word count."
        ),
    )

    @model_validator(mode="after")
    def validate_raw_lengths(self):
        raw_lists = [
            self.ttft_cold_raw,
            self.ttft_cached_raw,
            self.tokens_per_second_raw,
        ]
        if self.throughput_elapsed_seconds_raw is not None:
            raw_lists.append(self.throughput_elapsed_seconds_raw)
        if self.decode_tokens_per_second_raw is not None:
            raw_lists.append(self.decode_tokens_per_second_raw)
        if self.completion_tokens_raw is not None:
            raw_lists.append(self.completion_tokens_raw)
        lengths = {
            len(raw_values)
            for raw_values in raw_lists
        }
        if lengths != {self.count}:
            raise ValueError("trials.count must match all raw metric list lengths")
        return self


class BenchmarkProtocolPhase(ChronosBaseModel):
    prompts: list[str] = Field(
        ...,
        min_length=1,
        description="Prompt text used by this benchmark phase",
    )
    requested_max_tokens: PositiveInt = Field(
        ...,
        description="max_tokens requested from the engine for this phase",
    )
    requested_min_tokens: Optional[PositiveInt] = Field(
        None,
        description="min_tokens requested from the engine for this phase when used",
    )
    input_tokens: Optional[list[NonNegativeInt]] = Field(
        None,
        description="Input token counts aligned with prompts when available",
    )
    input_token_count_source: InputTokenCountSource = Field(
        "unavailable",
        description="How input token counts were obtained",
    )

    @model_validator(mode="after")
    def validate_protocol_phase(self):
        if any(not prompt.strip() for prompt in self.prompts):
            raise ValueError("protocol prompts must not be empty")
        if (
            self.requested_min_tokens is not None
            and self.requested_min_tokens > self.requested_max_tokens
        ):
            raise ValueError("requested_min_tokens must be <= requested_max_tokens")
        if self.input_tokens is None:
            if self.input_token_count_source != "unavailable":
                raise ValueError(
                    "input_token_count_source must be unavailable when input_tokens is missing"
                )
        else:
            if len(self.input_tokens) != len(self.prompts):
                raise ValueError("input_tokens must match prompts length")
            if self.input_token_count_source == "unavailable":
                raise ValueError(
                    "input_token_count_source must describe provided input_tokens"
                )
        return self


class BenchmarkProtocol(ChronosBaseModel):
    name: str = Field(..., min_length=1, description="Benchmark protocol name")
    version: str = Field(..., min_length=1, description="Benchmark protocol version")
    warmup: BenchmarkProtocolPhase
    ttft_cold: BenchmarkProtocolPhase
    ttft_cached: BenchmarkProtocolPhase
    throughput: BenchmarkProtocolPhase


class PhaseTimings(ChronosBaseModel):
    warmup: NonNegativeFloat = Field(..., description="Warmup phase duration in seconds")
    ttft_cold: NonNegativeFloat = Field(..., description="Cold TTFT phase duration in seconds")
    cache_priming: NonNegativeFloat = Field(..., description="Cached TTFT priming duration in seconds")
    ttft_cached: NonNegativeFloat = Field(..., description="Cached TTFT phase duration in seconds")
    throughput: NonNegativeFloat = Field(..., description="Throughput phase duration in seconds")
    total_runtime: NonNegativeFloat = Field(..., description="Total measured benchmark runtime in seconds")

    @model_validator(mode="after")
    def validate_total_runtime(self):
        phase_sum = (
            self.warmup
            + self.ttft_cold
            + self.cache_priming
            + self.ttft_cached
            + self.throughput
        )
        # Individual phase timings and total runtime are rounded independently.
        if self.total_runtime + 0.05 < phase_sum:
            raise ValueError("total_runtime must cover the sum of benchmark phases")
        return self


class ThermalMonitor(ChronosBaseModel):
    sample_interval_seconds: PositiveFloat = Field(
        ...,
        description="Seconds between thermal monitor samples",
    )
    source: ThermalMonitorSource = Field(
        ...,
        description="Source used for continuous thermal monitoring",
    )
    start_state: str = Field(..., min_length=1, description="First observed thermal state")
    end_state: str = Field(..., min_length=1, description="Last observed thermal state")
    worst_state: str = Field(..., min_length=1, description="Worst observed thermal state")
    samples: PositiveInt = Field(..., description="Number of thermal samples collected")
    changed_during_run: bool = Field(..., description="Whether thermal state changed during the run")
    non_nominal_observed: bool = Field(..., description="Whether a known non-nominal state was observed")
    non_nominal_phases: list[str] = Field(
        default_factory=list,
        description="Benchmark phases where a known non-nominal state was observed",
    )

    @model_validator(mode="after")
    def validate_thermal_monitor(self):
        if self.start_state != self.end_state and not self.changed_during_run:
            raise ValueError("changed_during_run must be true when start and end differ")
        if self.non_nominal_phases and not self.non_nominal_observed:
            raise ValueError(
                "non_nominal_observed must be true when non_nominal_phases is non-empty"
            )
        if any(not phase.strip() for phase in self.non_nominal_phases):
            raise ValueError("non_nominal_phases must not contain blank phase names")
        return self


class Meta(ChronosBaseModel):
    chronos_version: str = Field(..., min_length=1, description="mlx-chronos version used")
    timestamp: datetime = Field(..., description="Timestamp of the benchmark run")
    ram_sample_interval_seconds: Optional[float] = Field(
        None,
        gt=0,
        description="Seconds between engine RSS and system RAM samples",
    )
    benchmark_protocol: Optional[BenchmarkProtocol] = Field(
        None,
        description="Prompt and token-bound metadata for reproducing the benchmark",
    )
    phase_timings_seconds: Optional[PhaseTimings] = Field(
        None,
        description="Elapsed time for each benchmark phase and the total run",
    )
    thermal_monitor: Optional[ThermalMonitor] = Field(
        None,
        description="Continuous thermal sampling summary for this run",
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
        if self.metrics.request_tokens_per_second is not None:
            self._assert_stats_match_raw(
                self.metrics.request_tokens_per_second,
                self.trials.tokens_per_second_raw,
                "metrics.request_tokens_per_second",
            )
        if self.trials.decode_tokens_per_second_raw is None:
            if self.metrics.decode_tokens_per_second is not None:
                raise ValueError(
                    "metrics.decode_tokens_per_second requires raw decode trials"
                )
        else:
            if self.metrics.decode_tokens_per_second is None:
                raise ValueError(
                    "metrics.decode_tokens_per_second is required when raw decode trials exist"
                )
            self._assert_stats_match_raw(
                self.metrics.decode_tokens_per_second,
                self.trials.decode_tokens_per_second_raw,
                "metrics.decode_tokens_per_second",
            )
        if (
            self.trials.completion_tokens_raw is not None
            and self.trials.throughput_elapsed_seconds_raw is not None
        ):
            self._assert_request_tps_matches_tokens_and_elapsed()
        return self

    def _assert_request_tps_matches_tokens_and_elapsed(self) -> None:
        tolerance = 0.02
        for index, (tps, tokens, elapsed) in enumerate(
            zip(
                self.trials.tokens_per_second_raw,
                self.trials.completion_tokens_raw,
                self.trials.throughput_elapsed_seconds_raw,
            ),
            start=1,
        ):
            expected_tps = round(tokens / elapsed, 2)
            if abs(tps - expected_tps) > tolerance:
                raise ValueError(
                    "trials.tokens_per_second_raw must match completion token "
                    "counts divided by throughput elapsed seconds "
                    f"(trial {index}: expected {expected_tps}, got {tps})"
                )

    @staticmethod
    def _assert_stats_match_raw(stats: TrialStats, raw_values: list[float], label: str) -> None:
        expected = {
            "mean": round(statistics.mean(raw_values), 3),
            "stddev": round(statistics.stdev(raw_values), 3) if len(raw_values) > 1 else 0.0,
            "min": round(min(raw_values), 3),
            "max": round(max(raw_values), 3),
        }
        if len(raw_values) >= P95_MIN_TRIALS:
            sorted_values = sorted(raw_values)
            # Nearest-rank p95, matching mlx_chronos.stats.compute_stats.
            index = math.ceil(0.95 * len(sorted_values)) - 1
            expected["p95"] = round(sorted_values[index], 3)
        actual = {
            "mean": stats.mean,
            "stddev": stats.stddev,
            "min": stats.min,
            "max": stats.max,
        }
        if stats.p95 is not None:
            actual["p95"] = stats.p95
        elif "p95" in expected:
            raise ValueError(f"{label}.p95 must be present for {len(raw_values)} trials")
        if len(raw_values) < P95_MIN_TRIALS and stats.p95 is not None:
            raise ValueError(
                f"{label}.p95 must be omitted for fewer than {P95_MIN_TRIALS} trials"
            )
        tolerance = 0.001
        for key, expected_value in expected.items():
            if abs(actual[key] - expected_value) > tolerance:
                raise ValueError(
                    f"{label}.{key} must match raw trials "
                    f"(expected {expected_value}, got {actual[key]})"
                )


def dump_benchmark_result(result: BenchmarkResult) -> dict:
    data = result.model_dump(mode="json")
    for stats in data.get("metrics", {}).values():
        if isinstance(stats, dict) and stats.get("p95") is None:
            stats.pop("p95", None)
    return data


# Example valid result — used in tests and documentation
EXAMPLE_RESULT = {
    "hardware": {
        "chip": "Apple M2",
        "machine_model": "Mac14,2",
        "memory_gb": 8.0,
        "macos_version": "15.3.1",
        "python_version": "3.11.4",
        "architecture": "arm64",
        "thermal_state": "unavailable_permission"
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
        "request_tokens_per_second": {"mean": 18.44, "stddev": 0.097, "min": 18.27, "max": 18.51},
        "decode_tokens_per_second": None,
        "decode_timing_source": "unavailable",
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
        "tokens_per_second_raw": [18.48, 18.27, 18.51, 18.48, 18.46],
        "throughput_elapsed_seconds_raw": [5.411, 5.473, 5.402, 5.411, 5.417],
        "decode_tokens_per_second_raw": None,
        "completion_tokens_raw": [100, 100, 100, 100, 100]
    },
    "meta": {
        "chronos_version": "0.1.1",
        "timestamp": "2026-05-23T15:08:36Z",
        "ram_sample_interval_seconds": 0.05,
        "phase_timings_seconds": {
            "warmup": 10.512,
            "ttft_cold": 0.208,
            "cache_priming": 0.010,
            "ttft_cached": 0.050,
            "throughput": 27.104,
            "total_runtime": 38.100,
        },
        "thermal_monitor": {
            "sample_interval_seconds": 1.0,
            "source": "unavailable",
            "start_state": "unavailable_foundation",
            "end_state": "unavailable_foundation",
            "worst_state": "unavailable_foundation",
            "samples": 2,
            "changed_during_run": False,
            "non_nominal_observed": False,
            "non_nominal_phases": [],
        },
        "benchmark_protocol": {
            "name": "baseline",
            "version": "1",
            "warmup": {
                "prompts": [
                    "Explain in detail how the attention mechanism works in transformer "
                    "neural networks, including the role of queries, keys, and values."
                ],
                "requested_max_tokens": 30,
                "requested_min_tokens": None,
                "input_tokens": None,
                "input_token_count_source": "unavailable",
            },
            "ttft_cold": {
                "prompts": [
                    "What is the capital of Australia?",
                    "Explain what a transformer neural network is in one sentence.",
                    "What does RAM stand for in computing?",
                    "Describe the difference between a CPU and a GPU briefly.",
                    "What is the boiling point of water in Celsius?",
                ],
                "requested_max_tokens": 1,
                "requested_min_tokens": None,
                "input_tokens": None,
                "input_token_count_source": "unavailable",
            },
            "ttft_cached": {
                "prompts": [
                    "Explain the concept of unified memory in Apple Silicon in one sentence."
                ],
                "requested_max_tokens": 1,
                "requested_min_tokens": None,
                "input_tokens": None,
                "input_token_count_source": "unavailable",
            },
            "throughput": {
                "prompts": [
                    "Explain in detail how the attention mechanism works in transformer "
                    "neural networks, including the role of queries, keys, and values."
                ],
                "requested_max_tokens": 100,
                "requested_min_tokens": None,
                "input_tokens": None,
                "input_token_count_source": "unavailable",
            },
        },
        "notes": "Test run"
    }
}


if __name__ == "__main__":
    import json
    result = BenchmarkResult(**EXAMPLE_RESULT)
    print(json.dumps(dump_benchmark_result(result), indent=2))
    print("\nSchema validation: OK")
