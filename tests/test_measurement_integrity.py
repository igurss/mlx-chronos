"""Cross-field and monitor regressions absent from nominal benchmark fixtures."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import psutil
import pytest

from mlx_chronos.benchmark import run_benchmark
from mlx_chronos.examples import EXAMPLE_RESULT
from mlx_chronos.integrity import seal_result
from mlx_chronos.leaderboard import _index_row, load_archive_results
from mlx_chronos.measurements import ThroughputMeasurement, validate_throughput_measurement
from mlx_chronos.schema import BenchmarkResult
from mlx_chronos.stats import compute_stats
from mlx_chronos.submit import SubmissionError, submit_result_file, validate_publishable_result
from mlx_chronos.trackers import RAMTracker, SystemRAMTracker, ThermalStateTracker
from mlx_chronos.wizard import RunWizardConfig, build_run_command, validate_run_config


def test_unavailable_thermal_samples_are_errors_and_not_valid_samples():
    values = iter(["nominal", None, "nominal", "nominal"])
    tracker = ThermalStateTracker(sampler=lambda: next(values))
    for _ in range(3):
        tracker._record_sample()
    summary = tracker.stop()
    assert summary["samples"] == 3
    assert summary["sampling_errors"] == 1
    data = deepcopy(EXAMPLE_RESULT)
    data["meta"]["thermal_monitor"] = summary
    with pytest.raises(SubmissionError, match="error-free thermal"):
        validate_publishable_result(BenchmarkResult.model_validate(seal_result(data)))


@pytest.mark.parametrize("gap", [None, 10])
def test_current_public_protocol_requires_bounded_thermal_gaps(gap):
    data = deepcopy(EXAMPLE_RESULT)
    data["meta"]["thermal_monitor"]["max_sample_gap_seconds"] = gap
    with pytest.raises(SubmissionError, match="complete thermal"):
        validate_publishable_result(BenchmarkResult.model_validate(seal_result(data)))


def test_access_denied_child_marks_the_rss_sample_incomplete():
    child = SimpleNamespace(memory_info=lambda: (_ for _ in ()).throw(psutil.AccessDenied(123)))
    parent = SimpleNamespace(children=lambda **_: [child], memory_info=lambda: SimpleNamespace(rss=1024))
    with patch("mlx_chronos.trackers.psutil.Process", return_value=parent):
        tracker = RAMTracker()
        assert tracker._sample_rss() == 1024
        assert tracker.sample_errors == 1


def test_access_denied_child_enumeration_is_reported():
    parent = SimpleNamespace(children=lambda **_: (_ for _ in ()).throw(psutil.AccessDenied(123)),
                             memory_info=lambda: SimpleNamespace(rss=1024))
    with patch("mlx_chronos.trackers.psutil.Process", return_value=parent):
        tracker = RAMTracker()
        tracker._sample_rss()
        assert tracker.sample_errors == 1


def test_incomplete_swap_observation_does_not_claim_zero_growth():
    tracker = SystemRAMTracker()
    with patch.object(tracker, "_sample_system_ram", return_value=(100, 10, 1000)), \
         patch.object(tracker, "_sample_swap_used", side_effect=[0, None, 0]):
        for _ in range(3):
            tracker._record_sample()
    assert tracker.occupancy_summary()["swap_growth_gb"] is None


@pytest.mark.parametrize("excess", [0.01, 100])
def test_decode_interval_cannot_exceed_its_request(excess):
    data = deepcopy(EXAMPLE_RESULT)
    elapsed = [e + excess for e in data["trials"]["throughput_elapsed_seconds_raw"]]
    tps = [round((n - 1) / e, 2) for n, e in zip(data["trials"]["completion_tokens_raw"], elapsed)]
    data["trials"]["decode_elapsed_seconds_raw"] = elapsed
    data["trials"]["decode_tokens_per_second_raw"] = tps
    data["metrics"]["decode_tokens_per_second"] = compute_stats(tps)
    with pytest.raises(ValueError, match="cannot exceed request"):
        BenchmarkResult.model_validate(data)


@pytest.mark.parametrize("excess", [0, 0.0009])
def test_decode_interval_accepts_equal_or_millisecond_rounded_durations(excess):
    data = deepcopy(EXAMPLE_RESULT)
    elapsed = [e + excess for e in data["trials"]["throughput_elapsed_seconds_raw"]]
    tokens = data["trials"]["completion_tokens_raw"]
    tps = [round((n - 1) / e, 2) for n, e in zip(tokens, elapsed)]
    data["trials"]["decode_elapsed_seconds_raw"] = elapsed
    data["trials"]["decode_tokens_per_second_raw"] = tps
    data["metrics"]["decode_tokens_per_second"] = compute_stats(tps)
    BenchmarkResult.model_validate(data)
    validate_throughput_measurement(ThroughputMeasurement(
        request_tokens_per_second=data["trials"]["tokens_per_second_raw"][0],
        completion_tokens=tokens[0], token_count_source="usage.completion_tokens",
        elapsed_seconds=data["trials"]["throughput_elapsed_seconds_raw"][0],
        decode_tokens_per_second=tps[0], decode_elapsed_seconds=elapsed[0],
        decode_timing_source="client_stream",
    ))


@pytest.mark.parametrize("change", [
    {"completion_tokens": 100000, "request_tokens_per_second": 100000},
    {"request_tokens_per_second": 99},
    {"token_count_source": "usage"},
    {"token_count_source": []},
    {"decode_tokens_per_second": 2, "decode_elapsed_seconds": 10, "decode_timing_source": "client_stream"},
])
def test_shared_measurement_validation_rejects_inconsistent_data(change):
    value = replace(ThroughputMeasurement(60, 60, "usage.completion_tokens", 1), **change)
    with pytest.raises(RuntimeError):
        validate_throughput_measurement(value, max_tokens=60)


@pytest.mark.parametrize("invalid", [{"submitted_by": "bad/handle"}, {"model_quantization": "  "}])
def test_invalid_static_metadata_causes_zero_engine_requests(invalid):
    kwargs = dict(engine_name="omlx", model_name="fake", model_quantization="4bit")
    kwargs.update(invalid)
    with patch("mlx_chronos.benchmark.get_engine") as engine:
        with pytest.raises(ValueError):
            run_benchmark(**kwargs)
    engine.assert_not_called()


def test_wizard_validates_attribution_and_protects_leading_dash_values():
    assert any("GitHub handle" in e for e in validate_run_config(RunWizardConfig(model="fake", submitted_by="bad/handle")))
    import shlex
    from mlx_chronos.cli import main
    command = build_run_command(RunWizardConfig(model="--model-value", notes="--notes-value"))
    with patch("sys.argv", shlex.split(command)), patch("mlx_chronos.cli.cmd_run") as run:
        main()
    assert run.call_args.args[0].model == "--model-value"
    assert run.call_args.args[0].notes == "--notes-value"


def test_index_retains_worst_thermal_state_and_quality():
    data = deepcopy(EXAMPLE_RESULT)
    data["meta"]["thermal_monitor"].update(end_state="serious", worst_state="serious",
        non_nominal_observed=True, changed_during_run=True, non_nominal_phases=["throughput"])
    row = _index_row(BenchmarkResult.model_validate(data))
    assert row["thermal_state"] == "nominal"
    assert row["thermal_worst_state"] == "serious"
    assert row["thermal_non_nominal_phases"] == ["throughput"]
    assert row["protocol_version"] == "4"


def test_archived_protocol_loads_but_cannot_be_submitted_as_current(tmp_path):
    import json
    data = deepcopy(EXAMPLE_RESULT)
    data["meta"]["benchmark_protocol"]["version"] = "3"
    data["meta"]["thermal_monitor"].pop("max_sample_gap_seconds")
    (tmp_path / "old.json").write_text(json.dumps(seal_result(data)))
    assert len(load_archive_results(tmp_path)) == 1
    with pytest.raises(SubmissionError, match="current internal protocol"):
        validate_publishable_result(BenchmarkResult.model_validate(data))


@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.WriteTimeout, httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError])
def test_ambiguous_post_failure_is_never_retried(failure, tmp_path):
    result = BenchmarkResult.model_validate(EXAMPLE_RESULT)
    with patch("mlx_chronos.submit.httpx.post", side_effect=failure("receipt unknown")) as post:
        with pytest.raises(SubmissionError, match="outcome is unknown"):
            submit_result_file(tmp_path / "fake.json", "https://example.test/form",
                               raw=b"{}", result=result)
    assert post.call_count == 1


def test_legacy_missing_thermal_error_counter_stays_unknown_in_index():
    data = deepcopy(EXAMPLE_RESULT)
    data["meta"]["thermal_monitor"].pop("sampling_errors")
    row = _index_row(BenchmarkResult.model_validate(data))
    assert row["thermal_sampling_errors"] is None
