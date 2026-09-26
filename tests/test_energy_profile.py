import io
import json
import math
from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest

from mlx_chronos.cli import cmd_energy
from mlx_chronos.energy_profile import (
    MacmonPowerSampler,
    _validate_measurement,
    integrate_power_window,
    run_energy_profile,
    save_energy_report,
)
from mlx_chronos.measurements import ThroughputMeasurement


STAMP = "2026-09-26T07:33:40+00:00"


def points(*pairs):
    return [(float(t), float(power), STAMP) for t, power in pairs]


def test_constant_power_integrates_exact_clipped_window():
    phase = integrate_power_window(
        points((0, 5), (1, 5), (2, 5), (3, 5)), 0.25, 2.75,
        interval_ms=500,
    )
    assert phase["estimated_system_energy_joules"] == 12.5
    assert phase["estimated_mean_system_power_watts"] == 5
    assert phase["duration_seconds"] == 2.5
    assert phase["coverage"] == "full_bracketed_window"


def test_linear_ramp_is_interpolated_at_both_boundaries():
    phase = integrate_power_window(
        points((0, 0), (0.5, 5), (1, 10), (1.5, 15)),
        0.25, 1.25, interval_ms=500,
    )
    assert phase["estimated_system_energy_joules"] == 7.5
    assert phase["estimated_mean_system_power_watts"] == 7.5


@pytest.mark.parametrize("start,end", [(0.1, 3.1), (-0.1, 2), (0, 4)])
def test_incomplete_phase_edges_are_never_extrapolated(start, end):
    with pytest.raises(RuntimeError, match="entire phase"):
        integrate_power_window(points((0, 5), (1, 5), (2, 5), (3, 5)),
                               start, end, interval_ms=500)


def test_large_sampling_gap_is_rejected():
    with pytest.raises(RuntimeError, match="gap"):
        integrate_power_window(points((0, 4), (0.5, 4), (3, 6), (3.5, 6)),
                               0.1, 3.1, interval_ms=500)


def test_non_finite_integrated_energy_is_rejected():
    with pytest.raises(RuntimeError, match="integrated energy"):
        integrate_power_window(points((0, 1e308), (1, 1e308),
                                      (2, 1e308)), 0.1, 1.9,
                               interval_ms=500)


@pytest.mark.parametrize("power", [math.nan, math.inf, -1])
def test_invalid_power_values_are_rejected(power):
    with pytest.raises(RuntimeError, match="non-finite or negative"):
        integrate_power_window(points((0, 4), (1, power), (2, 4)),
                               0.1, 1.9, interval_ms=500)


def test_phase_requires_more_than_one_interval():
    with pytest.raises(RuntimeError, match="too few"):
        integrate_power_window(points((0, 4), (1, 4)),
                               0.1, 0.9, interval_ms=500)


@pytest.mark.parametrize("measurement", [
    ThroughputMeasurement(math.nan, 10, "usage", 1),
    ThroughputMeasurement(10, 0, "usage", 1),
    ThroughputMeasurement(10, 10, "usage", math.inf),
    ThroughputMeasurement(10, 10, "", 1),
])
def test_invalid_engine_measurements_cannot_enter_energy_report(measurement):
    with pytest.raises(RuntimeError, match="invalid throughput"):
        _validate_measurement(measurement)


def test_reader_rejects_boolean_nan_negative_and_invalid_timestamps():
    lines = [
        json.dumps({"timestamp": STAMP, "sys_power": True, "all_power": 1}),
        json.dumps({"timestamp": STAMP, "sys_power": math.nan, "all_power": 1}),
        json.dumps({"timestamp": STAMP, "sys_power": -1, "all_power": 1}),
        json.dumps({"timestamp": "no timezone", "sys_power": 4, "all_power": 1}),
        json.dumps({"timestamp": STAMP, "sys_power": 4.5, "all_power": 1}),
    ]
    sampler = MacmonPowerSampler(500)
    sampler._process = MagicMock(stdout=io.StringIO("\n".join(lines) + "\n"))
    sampler._read()
    assert sampler.invalid_samples == 4
    assert len(sampler.samples()) == 1
    assert sampler.samples()[0][1] == 4.5


def test_reader_rejects_macmon_sys_power_fallback_and_missing_component_field():
    lines = [
        json.dumps({"timestamp": STAMP, "sys_power": 0, "all_power": 0}),
        json.dumps({"timestamp": STAMP, "sys_power": 4, "all_power": 4}),
        json.dumps({"timestamp": STAMP, "sys_power": 4}),
        json.dumps({"timestamp": STAMP, "sys_power": 5, "all_power": 4}),
    ]
    sampler = MacmonPowerSampler(500)
    sampler._process = MagicMock(stdout=io.StringIO("\n".join(lines) + "\n"))
    sampler._read()
    assert sampler.invalid_samples == 3
    assert [sample[1] for sample in sampler.samples()] == [5]


@pytest.mark.parametrize("interval", [0, 99, 1001, 500.5, True])
def test_sampler_rejects_invalid_interval(interval):
    with pytest.raises(ValueError):
        MacmonPowerSampler(interval)


def test_sampler_fails_when_macmon_is_not_installed():
    with patch("mlx_chronos.energy_profile.shutil.which", return_value=None), \
         patch("mlx_chronos.energy_profile.subprocess.Popen") as popen:
        with pytest.raises(RuntimeError, match="not installed"):
            MacmonPowerSampler().start()
    popen.assert_not_called()


def test_profile_uses_separate_idle_and_throughput_windows():
    events = []
    engine = MagicMock()
    engine.is_installed.return_value = True
    engine.is_server_running.return_value = True
    engine.validate_model_backend.return_value = {"format": "mlx", "quantization": "4bit"}
    engine.get_version.return_value = "test"
    engine.measure_throughput.side_effect = lambda *a, **k: (
        events.append("request") or ThroughputMeasurement(10, 100, "usage.completion_tokens", 2)
    )
    sampler = MagicMock()
    sampler.invalid_samples = 0
    sampler.start.side_effect = lambda: events.append("sampler_start")
    sampler.samples.return_value = points(*[
        (index / 2, 5 if index / 2 <= 6 else 10)
        for index in range(27)
    ])
    with patch("mlx_chronos.energy_profile.get_engine", return_value=engine), \
         patch("mlx_chronos.energy_profile.shutil.which", return_value="/fake/macmon"), \
         patch("mlx_chronos.energy_profile.MacmonPowerSampler", return_value=sampler), \
         patch("mlx_chronos.energy_profile._now", side_effect=[0, 1, 6, 6, 12]), \
         patch("mlx_chronos.energy_profile._pause") as pause, \
         patch("mlx_chronos.energy_profile.detect_hardware", return_value={"chip": "test"}), \
         patch("mlx_chronos.energy_profile.get_thermal_state", return_value="nominal"), \
         patch("mlx_chronos.energy_profile._memory_snapshot", return_value={}), \
         patch("mlx_chronos.energy_profile._macmon_version", return_value="macmon test"):
        report = run_energy_profile("ollama", "test-model", model_quantization="4bit")

    assert events[:2] == ["request", "sampler_start"]  # warm-up before idle sampling
    assert events.count("request") == 4  # one warm-up plus three measured trials
    assert [call.args[0] for call in pause.call_args_list] == [5, 5]
    assert report["pre_throughput_no_request"]["duration_seconds"] == 5
    assert report["throughput"]["duration_seconds"] == 6
    assert report["throughput"]["estimated_mean_system_power_watts"] > (
        report["pre_throughput_no_request"]["estimated_mean_system_power_watts"]
    )
    assert report["throughput"]["completion_tokens"] == [100, 100, 100]
    assert "energy_joules_per_token" not in report
    sampler.stop.assert_called_once()


def test_energy_report_is_local_json(tmp_path):
    path = save_energy_report({"kind": "local_energy_diagnostic"}, tmp_path)
    assert path.parent == tmp_path
    assert json.loads(path.read_text())["kind"] == "local_energy_diagnostic"


def test_energy_report_rejects_non_json_finite_values(tmp_path):
    with pytest.raises(ValueError):
        save_energy_report({"power": math.nan}, tmp_path)
    assert not list(tmp_path.iterdir())


def test_profile_rejects_invalid_interval_before_other_preflight():
    with pytest.raises(ValueError, match="sample interval"):
        run_energy_profile("ollama", "model", interval_ms=0)


def test_profile_rejects_short_idle_without_starting_macmon():
    with patch("mlx_chronos.energy_profile.MacmonPowerSampler.start") as start:
        with pytest.raises(ValueError, match="idle_seconds"):
            run_energy_profile("ollama", "model", idle_seconds=3)
    start.assert_not_called()


def test_energy_command_saves_local_only_report(tmp_path):
    args = Namespace(
        engine="ollama", model="test-model", quantization=None, model_url=None,
        trials=1, max_tokens=20, settle_seconds=5.0, idle_seconds=5.0,
        sample_interval_ms=500, output_dir=tmp_path,
    )
    report = {
        "kind": "local_energy_diagnostic",
        "throughput": {"estimated_system_energy_joules": 12.0, "duration_seconds": 3.0},
        "pre_throughput_no_request": {"estimated_mean_system_power_watts": 4.0},
        "warning": "whole-system estimate only",
    }
    with patch("mlx_chronos.cli.run_energy_profile", return_value=report) as run:
        cmd_energy(args)
    assert run.call_args.kwargs["trials"] == 1
    saved = list(tmp_path.glob("energy_*.json"))
    assert len(saved) == 1
    assert json.loads(saved[0].read_text())["kind"] == "local_energy_diagnostic"


def test_energy_command_fails_without_writing_when_sampler_fails(tmp_path):
    args = Namespace(
        engine="ollama", model="test-model", quantization=None, model_url=None,
        trials=1, max_tokens=20, settle_seconds=5.0, idle_seconds=5.0,
        sample_interval_ms=500, output_dir=tmp_path,
    )
    with patch("mlx_chronos.cli.run_energy_profile", side_effect=RuntimeError("no samples")):
        with pytest.raises(SystemExit) as error:
            cmd_energy(args)
    assert error.value.code == 1
    assert not list(tmp_path.iterdir())
