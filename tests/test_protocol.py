import pytest

from mlx_chronos.protocol import (
    CONNECTION_MODE_PERSISTENT,
    _protocol_phase,
    build_benchmark_protocol,
)


def test_protocol_phase_requires_connection_mode():
    with pytest.raises(TypeError, match="connection_mode"):
        _protocol_phase(["prompt"], 1)


def test_benchmark_protocol_populates_connection_mode_for_every_phase():
    protocol = build_benchmark_protocol(
        trials=1,
        throughput_max_tokens=100,
        throughput_min_tokens=None,
    )

    for phase_name in ("warmup", "ttft_cold", "ttft_cached", "throughput"):
        assert protocol[phase_name]["connection_mode"] == CONNECTION_MODE_PERSISTENT


def test_benchmark_protocol_rejects_input_counts_not_aligned_with_trials():
    with pytest.raises(ValueError, match="must match trials length"):
        build_benchmark_protocol(2, 100, None, throughput_input_tokens=[24])


def test_benchmark_protocol_copies_input_counts():
    counts = [24, None]
    protocol = build_benchmark_protocol(2, 100, None, throughput_input_tokens=counts)
    counts[0] = 99
    assert protocol["throughput"]["input_tokens"] == [24, None]
