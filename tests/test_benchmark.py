import pytest
from unittest.mock import MagicMock, patch
from mlx_chronos.benchmark import compute_stats, RAMTracker, run_benchmark

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
    assert stats["mean"] == 10.346
    assert stats["min"] == 10.123
    assert stats["max"] == 10.568

def test_ram_tracker():
    with patch("mlx_chronos.benchmark.psutil.Process") as mock_process_cls:
        mock_process = MagicMock()
        mem_info = MagicMock()
        mem_info.rss = 1024 ** 3
        mock_process.memory_info.return_value = mem_info
        mock_process.children.return_value = []
        mock_process_cls.return_value = mock_process
        
        tracker = RAMTracker(interval=0.1, target_pid=12345)
        tracker.peak_ram_bytes = tracker._sample_rss()
        
    assert tracker.peak_ram_bytes == 1024 ** 3

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
        "system_ram_usage_percent": 50.0
    }
    
    mock_engine = MagicMock()
    mock_engine.name = "omlx"
    mock_engine.measure_ttft.return_value = 0.5
    mock_engine.measure_tokens_per_second.return_value = 20.0
    mock_engine.last_token_count_source = "usage.completion_tokens"
    mock_engine.get_version.return_value = "1.0.0"
    mock_engine.get_server_pid.return_value = 12345
    mock_get_engine.return_value = mock_engine
    
    with patch("mlx_chronos.benchmark.psutil.Process") as mock_process_cls:
        mock_process = MagicMock()
        mem_info = MagicMock()
        mem_info.rss = int(1.5 * (1024 ** 3))
        mock_process.memory_info.return_value = mem_info
        mock_process.children.return_value = []
        mock_process_cls.return_value = mock_process
        
        result = run_benchmark(
            engine_name="omlx",
            model_name="test-model",
            model_quantization="4bit",
            trials=2,
            notes="test run",
            ram_sample_interval=0.1
        )
    
    assert result["engine"]["name"] == "omlx"
    assert result["engine"]["version"] == "1.0.0"
    assert result["model"]["name"] == "test-model"
    assert result["metrics"]["tokens_per_second"]["mean"] == 20.0
    assert result["metrics"]["ttft_cold"]["mean"] == 0.5
    assert result["metrics"]["token_count_source"] == "usage.completion_tokens"
    assert result["metrics"]["ram_measurement_method"] == "process_rss"
