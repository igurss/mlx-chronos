from datetime import datetime
import math
import statistics

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from typing import Optional, Annotated, Literal

from mlx_chronos.constants import (
    VALID_ENGINE_NAMES,
    MAX_TRIALS,
    P95_MIN_TRIALS,
    PHASE_TIMING_TOLERANCE_SECONDS,
    RAM_MEASUREMENT_PROCESS_RSS,
    RAM_MEASUREMENT_SYSTEM_FALLBACK,
)
from mlx_chronos.integrity import INTEGRITY_DIGEST_HEX_LENGTH
from mlx_chronos.measurements import (
    DECODE_TIMING_CLIENT_STREAM,
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
    "client_stream",
]
RequestMode = Literal[
    "streaming",
    "non_streaming",
]
ConnectionMode = Literal[
    "per_request",
    "persistent",
]
ThermalMonitorSource = Literal[
    "foundation",
    "unavailable",
]
BenchmarkProfile = Literal[
    "baseline",
    "sustained",
]
EngineName = Literal[
    "omlx",
    "rapid-mlx",
    "vllm-mlx",
    "mlx-lm",
    "ollama",
]


class ChronosBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class IntegritySeal(ChronosBaseModel):
    schema_name: Literal["mlx-chronos-integrity-v1"] = Field(
        ...,
        alias="schema",
        description="Integrity seal schema version",
    )
    algorithm: Literal["sha256-canonical-json"] = Field(
        ...,
        description="Hashing algorithm used for the canonical result payload",
    )
    signed_payload: Literal["benchmark-result-without-integrity"] = Field(
        ...,
        description="Payload covered by the digest",
    )
    digest: str = Field(
        ...,
        min_length=INTEGRITY_DIGEST_HEX_LENGTH,
        max_length=INTEGRITY_DIGEST_HEX_LENGTH,
        description="SHA-256 digest of the canonical benchmark result payload",
    )

    @field_validator("digest")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if any(character not in "0123456789abcdef" for character in value):
            raise ValueError("digest must be lowercase hexadecimal")
        return value


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
    power_source: Optional[str] = Field(
        None,
        description="macOS power source during hardware detection (ac_power/battery/unavailable_*)",
    )
    low_power_mode: Optional[str] = Field(
        None,
        description="macOS Low Power Mode state during hardware detection (on/off/unavailable_*)",
    )

    @field_validator("thermal_state")
    @classmethod
    def normalize_thermal_state(cls, value: str | None) -> str:
        if value is None:
            return "unavailable_permission"
        normalized = value.strip()
        if normalized == "unavailable_no_sudo":
            return "unavailable_permission"
        return normalized or "unavailable_unknown"


class Engine(ChronosBaseModel):
    name: EngineName = Field(..., description="Engine name")
    version: str = Field(..., min_length=1, description="Engine version string")

    @field_validator("name", mode="before")
    @classmethod
    def validate_engine_name(cls, value: object) -> str:
        if not isinstance(value, str) or value not in VALID_ENGINE_NAMES:
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
    request_tokens_per_second: TrialStats = Field(
        ...,
        description=(
            "Client-observed total request throughput (tok/s), including request "
            "overhead, prefill, and decode. Current results mirror tokens_per_second here."
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
            "Legacy diagnostic peak RSS of the engine server process after "
            "warmup, or fallback system memory usage when the process cannot "
            "be located (GB)"
        ),
    )
    ram_is_process_rss: bool = Field(
        ..., 
        description=(
            "True if diagnostic RAM was measured from process RSS, False if "
            "system fallback was used"
        )
    )
    ram_measurement_method: RAMMeasurementMethod = Field(
        ...,
        description="Measurement method used for diagnostic ram_peak_gb",
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
        elif self.decode_timing_source not in {
            DECODE_TIMING_CLIENT_STREAM,
        }:
            raise ValueError(
                "decode_timing_source must describe provided decode throughput"
            )
        return self


class ThroughputProgressSample(ChronosBaseModel):
    completion_tokens: PositiveInt = Field(
        ...,
        description="Generated completion tokens or estimated output words at sample time",
    )
    elapsed_seconds: PositiveFloat = Field(
        ...,
        description="Client-observed elapsed seconds at sample time",
    )
    tokens_per_second: NonNegativeFloat = Field(
        ...,
        description="Cumulative completion tokens divided by elapsed seconds",
    )
    token_count_source: Literal["usage.completion_tokens", "word_fallback"] = Field(
        ...,
        description="Token count source used for this progress sample",
    )

    @model_validator(mode="after")
    def validate_progress_tps(self):
        expected_tps = round(self.completion_tokens / self.elapsed_seconds, 2)
        if abs(self.tokens_per_second - expected_tps) > 0.02:
            raise ValueError("tokens_per_second must match completion_tokens / elapsed_seconds")
        return self


class Trials(ChronosBaseModel):
    count: int = Field(..., ge=1, le=MAX_TRIALS, description="Number of trials run")
    ttft_cold_raw: list[NonNegativeFloat] = Field(..., description="Raw cold TTFT values per trial")
    ttft_cached_raw: list[NonNegativeFloat] = Field(..., description="Raw cached TTFT values per trial")
    tokens_per_second_raw: list[NonNegativeFloat] = Field(..., description="Raw tok/s values per trial")
    throughput_elapsed_seconds_raw: list[PositiveFloat] = Field(
        ...,
        description="Client-observed elapsed seconds for each throughput request",
    )
    decode_tokens_per_second_raw: Optional[list[NonNegativeFloat]] = Field(
        None,
        description="Raw decode-only tok/s values per throughput trial when available",
    )
    completion_tokens_raw: list[NonNegativeInt] = Field(
        ...,
        description=(
            "Generated completion token counts per throughput trial when available. "
            "For word_fallback results this is an estimated output word count."
        ),
    )
    throughput_progress_samples_raw: Optional[list[list[ThroughputProgressSample]]] = Field(
        None,
        description=(
            "Per-throughput-trial progress samples for long sustained runs. "
            "Intermediate samples may use word_fallback estimates when streaming "
            "responses do not expose incremental usage tokens."
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
        if self.throughput_progress_samples_raw is not None:
            raw_lists.append(self.throughput_progress_samples_raw)
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
    request_mode: Optional[RequestMode] = Field(
        None,
        description="Whether this phase used streaming or non-streaming requests",
    )
    stream_usage_requested: Optional[bool] = Field(
        None,
        description="Whether stream_options.include_usage was requested for this phase",
    )
    connection_mode: ConnectionMode = Field(
        ...,
        description="Whether HTTP connections were reused across benchmark requests",
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
        if self.stream_usage_requested and self.request_mode != "streaming":
            raise ValueError(
                "stream_usage_requested can only be true for streaming requests"
            )
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
    name: BenchmarkProfile = Field(..., description="Benchmark protocol name")
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
        if self.total_runtime + PHASE_TIMING_TOLERANCE_SECONDS < phase_sum:
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
    benchmark_profile: BenchmarkProfile = Field(
        ...,
        description="Benchmark profile selected for the run",
    )
    ram_sample_interval_seconds: PositiveFloat = Field(
        ...,
        gt=0,
        description="Seconds between diagnostic engine RSS and system RAM samples",
    )
    elapsed_since_last_benchmark_seconds: Optional[NonNegativeFloat] = Field(
        None,
        description="Seconds since the latest prior result JSON in the same output directory",
    )
    cooldown_seconds: Optional[NonNegativeFloat] = Field(
        None,
        description="Requested cooldown delay before this run, if any",
    )
    benchmark_protocol: BenchmarkProtocol = Field(
        ...,
        description="Prompt and token-bound metadata for reproducing the benchmark",
    )
    phase_timings_seconds: PhaseTimings = Field(
        ...,
        description="Elapsed time for each benchmark phase and the total run",
    )
    thermal_monitor: ThermalMonitor = Field(
        ...,
        description="Continuous thermal sampling summary for this run",
    )
    warmup_failures: NonNegativeInt = Field(
        ...,
        description="Number of unrecorded warmup calls that failed before measurement",
    )
    word_fallback_warning: bool = Field(
        ...,
        description="True when throughput token counts include word_fallback estimates",
    )
    engine_version_warning: bool = Field(
        ...,
        description="True when engine.version is unknown",
    )
    sustained_throttling_warning: bool = Field(
        ...,
        description=(
            "True when a sustained run observes a late throughput drop while "
            "thermal state changed or became non-nominal"
        ),
    )
    cached_ttft_warning: bool = Field(
        ...,
        description="True when cached TTFT is close to cold TTFT",
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
    integrity: IntegritySeal

    @model_validator(mode="after")
    def validate_summary_stats_match_raw_trials(self):
        if self.meta.benchmark_protocol.name != self.meta.benchmark_profile:
            raise ValueError("benchmark_protocol.name must match benchmark_profile")
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
        self._assert_request_tps_matches_tokens_and_elapsed()
        self._assert_throughput_token_bounds()
        self._assert_progress_samples_match_final_trials()
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

    def _assert_throughput_token_bounds(self) -> None:
        if self.metrics.token_count_source != "usage.completion_tokens":
            return
        throughput_protocol = self.meta.benchmark_protocol.throughput
        max_tokens = throughput_protocol.requested_max_tokens
        min_tokens = throughput_protocol.requested_min_tokens
        for index, tokens in enumerate(self.trials.completion_tokens_raw, start=1):
            if tokens > max_tokens:
                raise ValueError(
                    "trials.completion_tokens_raw must not exceed requested "
                    f"throughput max_tokens (trial {index}: max {max_tokens}, got {tokens})"
                )
            if min_tokens is not None and tokens < min_tokens:
                raise ValueError(
                    "trials.completion_tokens_raw must respect requested "
                    f"throughput min_tokens (trial {index}: min {min_tokens}, got {tokens})"
                )

    def _assert_progress_samples_match_final_trials(self) -> None:
        if self.trials.throughput_progress_samples_raw is None:
            return
        tolerance = 0.001
        for index, samples in enumerate(
            self.trials.throughput_progress_samples_raw,
            start=1,
        ):
            if not samples:
                continue
            final_sample = samples[-1]
            expected_tokens = self.trials.completion_tokens_raw[index - 1]
            expected_elapsed = self.trials.throughput_elapsed_seconds_raw[index - 1]
            if final_sample.completion_tokens != expected_tokens:
                raise ValueError(
                    "final throughput progress sample must match completion "
                    f"tokens for trial {index}"
                )
            if abs(final_sample.elapsed_seconds - expected_elapsed) > tolerance:
                raise ValueError(
                    "final throughput progress sample must match throughput "
                    f"elapsed seconds for trial {index}"
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
    data = result.model_dump(mode="json", by_alias=True)
    metric_stats_fields = (
        "ttft_cold",
        "ttft_cached",
        "tokens_per_second",
        "request_tokens_per_second",
        "decode_tokens_per_second",
    )
    metrics = data.get("metrics", {})
    for field in metric_stats_fields:
        stats = metrics.get(field)
        if isinstance(stats, dict) and stats.get("p95") is None:
            stats.pop("p95", None)
    return data


if __name__ == "__main__":
    import json
    from mlx_chronos.examples import EXAMPLE_RESULT

    result = BenchmarkResult(**EXAMPLE_RESULT)
    print(json.dumps(dump_benchmark_result(result), indent=2))
    print("\nSchema validation: OK")
