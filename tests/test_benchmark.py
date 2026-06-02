import pytest
import logging
from unittest.mock import MagicMock, patch
from mlx_chronos.benchmark import (
    CACHED_TTFT_PROMPT,
    COLD_PROMPTS,
    DEFAULT_THROUGHPUT_MAX_TOKENS,
    RAMTracker,
    SystemRAMTracker,
    THROUGHPUT_PROMPT,
    TTFT_MAX_TOKENS,
    WARMUP_MAX_TOKENS,
    compute_stats,
    run_benchmark,
)
from mlx_chronos.constants import MAX_TRIALS
from mlx_chronos.detect import BenchmarkConditionWarning
from mlx_chronos.measurements import ThroughputMeasurement


def throughput_measurement(
    tps: float = 20.0,
    tokens: int = 100,
    source: str = "usage.completion_tokens",
    elapsed: float = 5.0,
    decode_tps: float | None = None,
) -> ThroughputMeasurement:
    return ThroughputMeasurement(
        request_tokens_per_second=tps,
        completion_tokens=tokens,
        token_count_source=source,
        elapsed_seconds=elapsed,
        decode_tokens_per_second=decode_tps,
        decode_timing_source="engine_response" if decode_tps is not None else "unavailable",
    )

def test_compute_stats_normal():
    values = [10.0, 12.0, 14.0, 16.0, 18.0]
    stats = compute_stats(values)
    assert stats["mean"] == 14.0
    assert stats["stddev"] == pytest.approx(3.162, 0.01)
    assert stats["min"] == 10.0
    assert stats["max"] == 18.0

def test_compute_stats_empty():
    with pytest.raises(ValueError, match="at least one measurement"):
        compute_stats([])

def test_compute_stats_single():
    values = [10.0]
    stats = compute_stats(values)
    assert stats["mean"] == 10.0
    assert stats["stddev"] == 0.0
    assert stats["min"] == 10.0
    assert stats["max"] == 10.0

def test_compute_stats_rounding():
    values = [10.1234, 10.5678]
    stats = compute_stats(values)
    assert stats["mean"] == pytest.approx(10.346, abs=0.001)
    assert stats["min"] == pytest.approx(10.123, abs=0.001)
    assert stats["max"] == pytest.approx(10.568, abs=0.001)

def test_compute_stats_adds_p95_for_large_samples():
    stats = compute_stats([float(value) for value in range(1, 21)])
    assert stats["p95"] == 19.0

def test_cold_prompt_count_matches_max_trials():
    assert len(COLD_PROMPTS) == MAX_TRIALS

def test_run_benchmark_rejects_trials_above_max():
    with pytest.raises(ValueError, match=f"Max trials is {MAX_TRIALS}"):
        run_benchmark(
            engine_name="omlx",
            model_name="Qwen3.5-4B-OptiQ-4bit",
            model_quantization="4bit",
            trials=MAX_TRIALS + 1,
        )

def test_ram_tracker():
    with patch("mlx_chronos.trackers.psutil.Process") as mock_process_cls:
        mock_process = MagicMock()
        mem_info = MagicMock()
        mem_info.rss = 1024 ** 3
        mock_process.memory_info.return_value = mem_info
        mock_process.children.return_value = []
        mock_process_cls.return_value = mock_process
        
        tracker = RAMTracker(interval=0.1, target_pid=12345)
        tracker.peak_ram_bytes = tracker._sample_rss()
        
    assert tracker.peak_ram_bytes == 1024 ** 3

def test_system_ram_tracker():
    with patch("mlx_chronos.trackers.psutil.virtual_memory") as mock_virtual_memory:
        mem_info = MagicMock()
        mem_info.total = 8 * (1024 ** 3)
        mem_info.available = 2 * (1024 ** 3)
        mock_virtual_memory.return_value = mem_info

        tracker = SystemRAMTracker(interval=0.1)
        used_bytes, percent = tracker._sample_system_ram()

    assert used_bytes == 6 * (1024 ** 3)
    assert percent == 75.0

@patch("mlx_chronos.benchmark.get_engine")
@patch("mlx_chronos.benchmark.detect_hardware")
def test_run_benchmark(mock_detect, mock_get_engine):
    mock_detect.return_value = {
        "chip": "Apple M2",
        "machine_model": "Mac14,2",
        "memory_gb": 8.0,
        "macos_version": "14.0",
        "python_version": "3.11",
        "architecture": "arm64",
        "thermal_state": "nominal",
    }
    
    mock_engine = MagicMock()
    mock_engine.name = "omlx"
    mock_engine.measure_ttft.return_value = 0.5
    mock_engine.measure_tokens_per_second.return_value = 20.0
    mock_engine.measure_throughput.return_value = throughput_measurement(
        tps=20.0,
        tokens=100,
        elapsed=5.0,
    )
    mock_engine.get_version.return_value = "1.0.0"
    mock_engine.get_server_pid.return_value = 12345
    mock_get_engine.return_value = mock_engine
    
    with patch("mlx_chronos.trackers.psutil.Process") as mock_process_cls, \
         patch("mlx_chronos.trackers.psutil.virtual_memory") as mock_virtual_memory:
        mock_process = MagicMock()
        mem_info = MagicMock()
        mem_info.rss = int(1.5 * (1024 ** 3))
        mock_process.memory_info.return_value = mem_info
        mock_process.children.return_value = []
        mock_process_cls.return_value = mock_process
        system_mem_info = MagicMock()
        system_mem_info.total = 8 * (1024 ** 3)
        system_mem_info.available = 2 * (1024 ** 3)
        mock_virtual_memory.return_value = system_mem_info
        
        result = run_benchmark(
            engine_name="omlx",
            model_name="org/test-model",
            model_quantization="4bit",
            trials=2,
            notes="test run",
            ram_sample_interval=0.1
        )
    
    assert result["engine"]["name"] == "omlx"
    assert result["engine"]["version"] == "1.0.0"
    assert result["model"]["name"] == "org/test-model"
    assert result["metrics"]["tokens_per_second"]["mean"] == 20.0
    assert "p95" not in result["metrics"]["tokens_per_second"]
    assert result["metrics"]["request_tokens_per_second"]["mean"] == 20.0
    assert result["metrics"]["decode_tokens_per_second"] is None
    assert result["metrics"]["decode_timing_source"] == "unavailable"
    assert result["metrics"]["ttft_cold"]["mean"] == 0.5
    assert result["metrics"]["token_count_source"] == "usage.completion_tokens"
    assert result["metrics"]["ram_measurement_method"] == "process_rss"
    assert result["metrics"]["system_ram_peak_gb"] == 6.0
    assert result["metrics"]["system_ram_peak_percent"] == 75.0
    assert result["trials"]["completion_tokens_raw"] == [100, 100]
    assert result["trials"]["throughput_elapsed_seconds_raw"] == [5.0, 5.0]
    protocol = result["meta"]["benchmark_protocol"]
    assert protocol["name"] == "baseline"
    assert protocol["ttft_cold"]["prompts"] == COLD_PROMPTS[:2]
    assert protocol["ttft_cold"]["requested_max_tokens"] == TTFT_MAX_TOKENS
    assert protocol["throughput"]["prompts"] == [THROUGHPUT_PROMPT]
    assert protocol["throughput"]["requested_max_tokens"] == DEFAULT_THROUGHPUT_MAX_TOKENS
    assert protocol["throughput"]["requested_min_tokens"] is None
    assert protocol["throughput"]["input_token_count_source"] == "unavailable"

    ttft_prompts = [call.args[0] for call in mock_engine.measure_ttft.call_args_list]
    assert ttft_prompts == [
        COLD_PROMPTS[0],
        COLD_PROMPTS[1],
        CACHED_TTFT_PROMPT,
        CACHED_TTFT_PROMPT,
        CACHED_TTFT_PROMPT,
    ]
    warmup_prompts = [
        call.args[0] for call in mock_engine.measure_tokens_per_second.call_args_list
    ]
    assert warmup_prompts == [THROUGHPUT_PROMPT] * 2
    throughput_prompts = [
        call.args[0] for call in mock_engine.measure_throughput.call_args_list
    ]
    assert throughput_prompts == [THROUGHPUT_PROMPT] * 2
    assert [
        call.kwargs.get("max_tokens")
        for call in mock_engine.measure_tokens_per_second.call_args_list
    ] == [WARMUP_MAX_TOKENS, WARMUP_MAX_TOKENS]
    assert [
        call.kwargs.get("max_tokens")
        for call in mock_engine.measure_throughput.call_args_list
    ] == [DEFAULT_THROUGHPUT_MAX_TOKENS, DEFAULT_THROUGHPUT_MAX_TOKENS]
    assert [
        call.kwargs.get("min_tokens")
        for call in mock_engine.measure_tokens_per_second.call_args_list
    ] == [None, None]
    assert [
        call.kwargs.get("min_tokens")
        for call in mock_engine.measure_throughput.call_args_list
    ] == [None, None]

    for call in mock_engine.measure_ttft.call_args_list:
        assert call.kwargs["model"] == "org/test-model"
    for call in mock_engine.measure_tokens_per_second.call_args_list:
        assert call.kwargs["model"] == "org/test-model"
    for call in mock_engine.measure_throughput.call_args_list:
        assert call.kwargs["model"] == "org/test-model"


@patch("mlx_chronos.benchmark.get_benchmark_condition_warnings")
@patch("mlx_chronos.benchmark.get_engine")
@patch("mlx_chronos.benchmark.detect_hardware")
def test_run_benchmark_emits_condition_warnings(
    mock_detect,
    mock_get_engine,
    mock_warnings,
    caplog,
):
    mock_detect.return_value = {
        "chip": "Apple M2",
        "machine_model": "Mac14,2",
        "memory_gb": 8.0,
        "macos_version": "14.0",
        "python_version": "3.11",
        "architecture": "arm64",
        "thermal_state": "serious",
    }
    mock_warnings.return_value = [
        BenchmarkConditionWarning(
            "thermal state",
            "thermal_state=serious; thermal pressure can reduce performance.",
        )
    ]

    mock_engine = MagicMock()
    mock_engine.name = "omlx"
    mock_engine.is_installed.return_value = True
    mock_engine.is_server_running.return_value = True
    mock_engine.measure_ttft.return_value = 0.5
    mock_engine.measure_tokens_per_second.return_value = 20.0
    mock_engine.measure_throughput.return_value = throughput_measurement()
    mock_engine.get_version.return_value = "1.0.0"
    mock_engine.get_server_pid.return_value = None
    mock_get_engine.return_value = mock_engine

    caplog.set_level(logging.WARNING, logger="mlx_chronos")

    with patch("mlx_chronos.trackers.psutil.virtual_memory") as mock_virtual_memory:
        system_mem_info = MagicMock()
        system_mem_info.total = 8 * (1024 ** 3)
        system_mem_info.available = 2 * (1024 ** 3)
        mock_virtual_memory.return_value = system_mem_info

        run_benchmark(
            engine_name="omlx",
            model_name="org/test-model",
            model_quantization="4bit",
            trials=1,
            ram_sample_interval=0.01,
        )

    mock_warnings.assert_called_once_with(mock_detect.return_value)
    assert "Warning: thermal state: thermal_state=serious" in caplog.text


@patch("mlx_chronos.benchmark.get_engine")
@patch("mlx_chronos.benchmark.detect_hardware")
def test_run_benchmark_rejects_missing_token_count_source(mock_detect, mock_get_engine):
    mock_detect.return_value = {
        "chip": "Apple M2",
        "machine_model": "Mac14,2",
        "memory_gb": 8.0,
        "macos_version": "14.0",
        "python_version": "3.11",
        "architecture": "arm64",
        "thermal_state": "nominal",
    }

    mock_engine = MagicMock()
    mock_engine.name = "omlx"
    mock_engine.measure_ttft.return_value = 0.5
    mock_engine.measure_tokens_per_second.return_value = 20.0
    mock_engine.measure_throughput.return_value = throughput_measurement(
        source="invalid",
    )
    mock_engine.get_version.return_value = "1.0.0"
    mock_engine.get_server_pid.return_value = None
    mock_get_engine.return_value = mock_engine

    with patch("mlx_chronos.trackers.psutil.virtual_memory") as mock_virtual_memory:
        system_mem_info = MagicMock()
        system_mem_info.total = 8 * (1024 ** 3)
        system_mem_info.available = 2 * (1024 ** 3)
        mock_virtual_memory.return_value = system_mem_info

        with pytest.raises(RuntimeError, match="valid token count source"):
            run_benchmark(
                engine_name="omlx",
                model_name="org/test-model",
                model_quantization="4bit",
                trials=1,
                ram_sample_interval=0.01,
            )


@patch("mlx_chronos.benchmark.get_engine")
@patch("mlx_chronos.benchmark.detect_hardware")
def test_run_benchmark_passes_throughput_token_bounds(mock_detect, mock_get_engine):
    mock_detect.return_value = {
        "chip": "Apple M2",
        "machine_model": "Mac14,2",
        "memory_gb": 8.0,
        "macos_version": "14.0",
        "python_version": "3.11",
        "architecture": "arm64",
        "thermal_state": "nominal",
    }

    mock_engine = MagicMock()
    mock_engine.name = "omlx"
    mock_engine.measure_ttft.return_value = 0.5
    mock_engine.measure_tokens_per_second.return_value = 20.0
    mock_engine.measure_throughput.return_value = throughput_measurement(
        tps=20.0,
        tokens=90,
    )
    mock_engine.get_version.return_value = "1.0.0"
    mock_engine.get_server_pid.return_value = None
    mock_get_engine.return_value = mock_engine

    with patch("mlx_chronos.trackers.psutil.virtual_memory") as mock_virtual_memory:
        system_mem_info = MagicMock()
        system_mem_info.total = 8 * (1024 ** 3)
        system_mem_info.available = 2 * (1024 ** 3)
        mock_virtual_memory.return_value = system_mem_info

        result = run_benchmark(
            engine_name="omlx",
            model_name="org/test-model",
            model_quantization="4bit",
            trials=1,
            ram_sample_interval=0.01,
            throughput_max_tokens=100,
            throughput_min_tokens=80,
        )

    throughput_calls = mock_engine.measure_throughput.call_args_list
    assert [call.kwargs["max_tokens"] for call in throughput_calls] == [100]
    assert [call.kwargs["min_tokens"] for call in throughput_calls] == [80]
    assert result["meta"]["benchmark_protocol"]["throughput"][
        "requested_min_tokens"
    ] == 80


@patch("mlx_chronos.benchmark.get_engine")
@patch("mlx_chronos.benchmark.detect_hardware")
def test_run_benchmark_records_decode_throughput_when_available(
    mock_detect,
    mock_get_engine,
):
    mock_detect.return_value = {
        "chip": "Apple M2",
        "machine_model": "Mac14,2",
        "memory_gb": 8.0,
        "macos_version": "14.0",
        "python_version": "3.11",
        "architecture": "arm64",
        "thermal_state": "nominal",
    }

    mock_engine = MagicMock()
    mock_engine.name = "omlx"
    mock_engine.measure_ttft.return_value = 0.5
    mock_engine.measure_tokens_per_second.return_value = 20.0
    mock_engine.measure_throughput.return_value = throughput_measurement(
        tps=18.0,
        tokens=100,
        elapsed=5.5,
        decode_tps=21.0,
    )
    mock_engine.get_version.return_value = "1.0.0"
    mock_engine.get_server_pid.return_value = None
    mock_get_engine.return_value = mock_engine

    with patch("mlx_chronos.trackers.psutil.virtual_memory") as mock_virtual_memory:
        system_mem_info = MagicMock()
        system_mem_info.total = 8 * (1024 ** 3)
        system_mem_info.available = 2 * (1024 ** 3)
        mock_virtual_memory.return_value = system_mem_info

        result = run_benchmark(
            engine_name="omlx",
            model_name="org/test-model",
            model_quantization="4bit",
            trials=2,
            ram_sample_interval=0.01,
        )

    assert result["metrics"]["decode_tokens_per_second"]["mean"] == 21.0
    assert result["metrics"]["decode_timing_source"] == "engine_response"
    assert result["trials"]["decode_tokens_per_second_raw"] == [21.0, 21.0]


@patch("mlx_chronos.benchmark.get_engine")
@patch("mlx_chronos.benchmark.detect_hardware")
def test_run_benchmark_rejects_usage_tokens_below_requested_min(
    mock_detect,
    mock_get_engine,
):
    mock_detect.return_value = {
        "chip": "Apple M2",
        "machine_model": "Mac14,2",
        "memory_gb": 8.0,
        "macos_version": "14.0",
        "python_version": "3.11",
        "architecture": "arm64",
        "thermal_state": "nominal",
    }

    mock_engine = MagicMock()
    mock_engine.name = "omlx"
    mock_engine.measure_ttft.return_value = 0.5
    mock_engine.measure_tokens_per_second.return_value = 20.0
    mock_engine.measure_throughput.return_value = throughput_measurement(
        tps=20.0,
        tokens=20,
    )
    mock_engine.get_version.return_value = "1.0.0"
    mock_engine.get_server_pid.return_value = None
    mock_get_engine.return_value = mock_engine

    with patch("mlx_chronos.trackers.psutil.virtual_memory") as mock_virtual_memory:
        system_mem_info = MagicMock()
        system_mem_info.total = 8 * (1024 ** 3)
        system_mem_info.available = 2 * (1024 ** 3)
        mock_virtual_memory.return_value = system_mem_info

        with pytest.raises(RuntimeError, match="below requested min_tokens"):
            run_benchmark(
                engine_name="omlx",
                model_name="org/test-model",
                model_quantization="4bit",
                trials=1,
                ram_sample_interval=0.01,
                throughput_max_tokens=100,
                throughput_min_tokens=80,
            )


@patch("mlx_chronos.benchmark.get_engine")
@patch("mlx_chronos.benchmark.detect_hardware")
def test_run_benchmark_uses_all_cold_prompts_at_max_trials(mock_detect, mock_get_engine):
    mock_detect.return_value = {
        "chip": "Apple M2",
        "machine_model": "Mac14,2",
        "memory_gb": 8.0,
        "macos_version": "14.0",
        "python_version": "3.11",
        "architecture": "arm64",
        "thermal_state": "nominal",
    }

    mock_engine = MagicMock()
    mock_engine.name = "omlx"
    mock_engine.measure_ttft.return_value = 0.5
    mock_engine.measure_tokens_per_second.return_value = 20.0
    mock_engine.measure_throughput.return_value = throughput_measurement()
    mock_engine.get_version.return_value = "1.0.0"
    mock_engine.get_server_pid.return_value = None
    mock_get_engine.return_value = mock_engine

    with patch("mlx_chronos.trackers.psutil.virtual_memory") as mock_virtual_memory:
        system_mem_info = MagicMock()
        system_mem_info.total = 8 * (1024 ** 3)
        system_mem_info.available = 2 * (1024 ** 3)
        mock_virtual_memory.return_value = system_mem_info

        run_benchmark(
            engine_name="omlx",
            model_name="org/test-model",
            model_quantization="4bit",
            trials=MAX_TRIALS,
            ram_sample_interval=0.01,
        )

    ttft_prompts = [call.args[0] for call in mock_engine.measure_ttft.call_args_list]
    assert ttft_prompts[:MAX_TRIALS] == COLD_PROMPTS


def test_run_benchmark_rejects_empty_model_name():
    with pytest.raises(ValueError, match="model name must not be empty"):
        run_benchmark(
            engine_name="omlx",
            model_name="  ",
            model_quantization="4bit",
            trials=1,
        )


def test_run_benchmark_rejects_invalid_throughput_token_bounds():
    with pytest.raises(ValueError, match="throughput_min_tokens"):
        run_benchmark(
            engine_name="omlx",
            model_name="org/test-model",
            model_quantization="4bit",
            trials=1,
            throughput_max_tokens=20,
            throughput_min_tokens=30,
        )
