import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from mlx_chronos.detect import (
    get_benchmark_condition_warnings,
    get_architecture,
    get_chip_model,
    get_low_power_mode,
    get_machine_model,
    get_power_source,
    get_system_profiler_hardware,
    get_thermal_state,
)


def test_thermal_state_uses_foundation_when_available(monkeypatch):
    process_info = SimpleNamespace(thermalState=lambda: 1)
    foundation = SimpleNamespace(
        NSProcessInfo=SimpleNamespace(processInfo=lambda: process_info)
    )
    monkeypatch.setitem(sys.modules, "Foundation", foundation)

    assert get_thermal_state() == "fair"


def test_thermal_state_falls_back_without_sudo(monkeypatch):
    monkeypatch.setitem(sys.modules, "Foundation", None)
    monkeypatch.setattr("os.geteuid", lambda: 501)

    assert get_thermal_state() == "unavailable_no_sudo"


def test_get_architecture(monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "arm64")
    assert get_architecture() == "arm64"


def test_chip_and_machine_model_fallback_to_system_profiler(monkeypatch):
    get_system_profiler_hardware.cache_clear()

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "sysctl":
            return MagicMock(stdout="")
        return MagicMock(
            stdout=(
                "Hardware:\n"
                "    Hardware Overview:\n"
                "      Model Identifier: Mac14,2\n"
                "      Chip: Apple M2\n"
            )
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    assert get_chip_model() == "Apple M2"
    assert get_machine_model() == "Mac14,2"
    assert calls.count(["system_profiler", "SPHardwareDataType"]) == 1

    get_system_profiler_hardware.cache_clear()


def test_benchmark_condition_warnings_for_non_nominal_conditions():
    warnings = get_benchmark_condition_warnings(
        {"thermal_state": "fair"},
        power_source="battery",
        low_power_mode="on",
    )

    labels = [warning.label for warning in warnings]
    assert labels == ["thermal state", "power source", "low power mode"]
    assert "thermal_state=fair" in warnings[0].detail


def test_benchmark_condition_warnings_for_unavailable_thermal_state():
    warnings = get_benchmark_condition_warnings(
        {"thermal_state": "unavailable_no_sudo"},
        power_source="ac_power",
        low_power_mode="off",
    )

    assert len(warnings) == 1
    assert warnings[0].label == "thermal state unavailable"
    assert "unavailable_no_sudo" in warnings[0].detail


def test_benchmark_condition_warning_detection_failures_are_ignored():
    warnings = get_benchmark_condition_warnings(
        {"thermal_state": "nominal"},
        power_source="unavailable_pmset_not_found",
        low_power_mode="unavailable_parse_error",
    )

    assert warnings == []


def test_power_source_detects_battery(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd == ["pmset", "-g", "batt"]
        return MagicMock(stdout="Now drawing from 'Battery Power'\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    assert get_power_source() == "battery"


def test_low_power_mode_detects_enabled(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd == ["pmset", "-g"]
        return MagicMock(stdout=" lowpowermode         1\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    assert get_low_power_mode() == "on"
