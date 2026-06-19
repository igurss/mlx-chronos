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
