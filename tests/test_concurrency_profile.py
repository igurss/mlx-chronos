from unittest.mock import MagicMock, patch

import pytest

from mlx_chronos.concurrency_profile import run_concurrency_profile
from mlx_chronos.measurements import ThroughputMeasurement


def _measurement(source="usage.completion_tokens", tokens=50):
    return ThroughputMeasurement(
        request_tokens_per_second=50.0,
        completion_tokens=tokens,
        token_count_source=source,
        elapsed_seconds=1.0,
    )


def _engine():
    engine = MagicMock()
    engine.is_installed.return_value = True
    engine.is_server_running.return_value = True
    engine.validate_model_backend.return_value = {
        "format": "mlx",
        "quantization": "4bit",
    }
    engine.get_version.return_value = "1.2.3"
    engine.http_client.return_value.__enter__.return_value = MagicMock()
    engine.measure_throughput.return_value = _measurement()
    engine.clear_cache_for_benchmark.return_value = False
    engine.prefix_cache_hit_count.return_value = None
    return engine


def _run(engine, **kwargs):
    with (
        patch("mlx_chronos.concurrency_profile.get_engine", return_value=engine),
        patch(
            "mlx_chronos.concurrency_profile.detect_hardware",
            return_value={
                "chip": "Apple M4 Max",
                "memory_gb": 64,
                "macos_version": "15.1",
            },
        ),
        patch(
            "mlx_chronos.concurrency_profile.secrets.token_hex", return_value="abcd1234"
        ),
        patch(
            "mlx_chronos.concurrency_profile.get_thermal_state", return_value="nominal"
        ),
    ):
        return run_concurrency_profile("vllm-mlx", "example", **kwargs)


def test_default_run_never_reuses_a_prompt_across_warmup_or_measured_waves():
    engine = _engine()
    report = _run(engine)

    assert [level["concurrency"] for level in report["levels"]] == [1, 2, 4, 8]
    prompts = [
        prompt
        for level in report["levels"]
        for wave in level["waves"]
        for phase in [wave["warmup"], wave]
        for prompt in phase["prompts"]
    ]
    assert len(prompts) == 90  # 45 warm-up + 45 measured requests
    assert len(set(prompts)) == len(prompts)
    assert all(prompt.startswith("Benchmark request abcd1234-") for prompt in prompts)
    assert engine.measure_throughput.call_count == 90
    assert engine.clear_cache_for_benchmark.call_count == 12
    assert report["protocol"]["exact_completion_usage_required"] is True
    assert any("not verified cold-cache" in warning for warning in report["warnings"])
    assert report["protocol"]["execution_order"][4:8] == [
        {"round": 2, "concurrency": level} for level in (2, 4, 8, 1)
    ]
    assert "canonical_id" not in report["model"]


def test_level_32_has_distinct_prompts_inside_the_same_wave():
    engine = _engine()
    report = _run(engine, levels=[32], trials_per_level=1)
    measured_wave = report["levels"][0]["waves"][0]
    warmup = measured_wave["warmup"]["prompts"]
    measured = measured_wave["prompts"]
    assert len(set(warmup + measured)) == 64
    assert report["levels"][0]["waves"][0]["total_completion_tokens"] == 1600
    engine.http_client.assert_called_once_with(max_keepalive_connections=32)


def test_warmup_is_separate_and_exact_usage_is_required_only_for_measurement():
    engine = _engine()

    def measurement(*_args, **kwargs):
        return _measurement(
            source="usage.completion_tokens"
            if kwargs["request_stream_usage"]
            else "word_fallback"
        )

    engine.measure_throughput.side_effect = measurement
    report = _run(engine, levels=[2], trials_per_level=1)
    assert report["levels"][0]["waves"][0]["warmup"]["total_completion_tokens"] == 100
    assert report["levels"][0]["waves"][0]["total_completion_tokens"] == 100
    assert all(
        call.kwargs["allow_stream_usage_fallback"] is False
        for call in engine.measure_throughput.call_args_list
    )


def test_estimated_tokens_abort_the_diagnostic():
    engine = _engine()
    engine.measure_throughput.return_value = _measurement("word_fallback")
    with pytest.raises(RuntimeError, match="exact completion token usage"):
        _run(engine, levels=[1], trials_per_level=1)


def test_short_completion_aborts_instead_of_changing_the_workload():
    engine = _engine()
    engine.measure_throughput.return_value = _measurement(tokens=5)
    with pytest.raises(RuntimeError, match="ended too early"):
        _run(engine, levels=[1], trials_per_level=1)


def test_cache_evidence_is_recorded_without_claiming_unverified_coldness():
    engine = _engine()
    engine.clear_cache_for_benchmark.side_effect = [True, False]
    engine.prefix_cache_hit_count.side_effect = [7, 8, None, None]
    report = _run(engine, levels=[1], trials_per_level=2)
    first, second = report["levels"][0]["waves"]
    assert first["cache_clear_confirmed"] is True
    assert first["prefix_cache_hits_delta"] == 1
    assert second["cache_clear_confirmed"] is False
    assert second["prefix_cache_hits_delta"] is None
    assert any("counter increased" in warning for warning in report["warnings"])


@pytest.mark.parametrize("levels", [[], [0], [33], [2, 2], [True], [[1]]])
def test_invalid_levels_are_rejected_before_engine_use(levels):
    with pytest.raises(ValueError, match="concurrency level|at least one"):
        run_concurrency_profile("vllm-mlx", "example", levels=levels)


@pytest.mark.parametrize("trials", [0, 11, True])
def test_invalid_trial_counts_are_rejected(trials):
    with pytest.raises(ValueError, match="trials_per_level"):
        run_concurrency_profile("vllm-mlx", "example", trials_per_level=trials)
