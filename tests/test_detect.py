import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mlx_chronos.detect import (
    _resolve_condition_field,
    clear_hardware_detection_caches,
    get_benchmark_condition_warnings,
    get_architecture,
    get_chip_model,
    get_low_power_mode,
    get_machine_model,
    get_power_source,
    get_thermal_state,
    get_thermal_state_from_foundation,
)


@pytest.fixture(autouse=True)
def clear_detect_caches():
    clear_hardware_detection_caches()
    yield
    clear_hardware_detection_caches()


def test_thermal_state_uses_foundation_when_available(monkeypatch):
    process_info = SimpleNamespace(thermalState=lambda: 1)
    foundation = SimpleNamespace(
        NSProcessInfo=SimpleNamespace(processInfo=lambda: process_info)
    )
    monkeypatch.setitem(sys.modules, "Foundation", foundation)

    assert get_thermal_state() == "fair"


def test_thermal_state_reports_unavailable_when_foundation_is_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "Foundation", None)
    monkeypatch.setattr("os.geteuid", lambda: 501)

    assert get_thermal_state() == "unavailable_permission"


def test_foundation_thermal_state_handles_import_error(monkeypatch):
    def raise_import_error(_name):
        raise ImportError("Foundation unavailable")

    monkeypatch.setattr(
        "mlx_chronos.detect.importlib.import_module",
        raise_import_error,
    )

    assert get_thermal_state_from_foundation() is None


def test_get_architecture(monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "arm64")
    assert get_architecture() == "arm64"


def test_chip_and_machine_model_fallback_to_system_profiler(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "sysctl":
            return MagicMock(stdout="", returncode=0)
        return MagicMock(
            returncode=0,
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


def test_chip_and_machine_model_are_cached(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd == ["sysctl", "-n", "machdep.cpu.brand_string"]:
            return MagicMock(stdout="Apple M2\n", returncode=0)
        if cmd == ["sysctl", "-n", "hw.model"]:
            return MagicMock(stdout="Mac14,2\n", returncode=0)
        return MagicMock(stdout="", returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    assert get_chip_model() == "Apple M2"
    assert get_chip_model() == "Apple M2"
    assert get_machine_model() == "Mac14,2"
    assert get_machine_model() == "Mac14,2"
    assert calls.count(["sysctl", "-n", "machdep.cpu.brand_string"]) == 1
    assert calls.count(["sysctl", "-n", "hw.model"]) == 1


def test_failed_hardware_detection_is_not_cached(monkeypatch):
    profiler_calls = 0

    def fake_run(cmd, **kwargs):
        nonlocal profiler_calls
        if cmd[0] == "sysctl":
            return MagicMock(stdout="", returncode=0)
        profiler_calls += 1
        if profiler_calls == 1:
            return MagicMock(stdout="", returncode=1)
        return MagicMock(stdout="Chip: Apple M2\n", returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    assert get_chip_model() == "unknown"
    assert get_chip_model() == "Apple M2"
    assert profiler_calls == 2


def test_benchmark_condition_warnings_for_non_nominal_conditions():
    warnings = get_benchmark_condition_warnings(
        {"thermal_state": "fair"},
        power_source="battery",
        low_power_mode="on",
    )

    labels = [warning.label for warning in warnings]
    assert labels == ["thermal state", "power source", "low power mode"]
    assert "thermal_state=fair" in warnings[0].detail


def test_benchmark_condition_warnings_reuse_hardware_power_fields(monkeypatch):
    def fail_if_called():
        raise AssertionError("should not call pmset")

    monkeypatch.setattr(
        "mlx_chronos.detect.get_power_source",
        fail_if_called,
    )
    monkeypatch.setattr(
        "mlx_chronos.detect.get_low_power_mode",
        fail_if_called,
    )

    warnings = get_benchmark_condition_warnings(
        {
            "thermal_state": "nominal",
            "power_source": "battery",
            "low_power_mode": "on",
        },
    )

    labels = [warning.label for warning in warnings]
    assert labels == ["power source", "low power mode"]


def test_benchmark_condition_warnings_for_unavailable_thermal_state():
    warnings = get_benchmark_condition_warnings(
        {"thermal_state": "unavailable_permission"},
        power_source="ac_power",
        low_power_mode="off",
    )

    assert len(warnings) == 1
    assert warnings[0].label == "thermal state unavailable"
    assert "unavailable_permission" in warnings[0].detail


def test_condition_field_resolution_prefers_explicit_then_hardware():
    def fallback():
        raise AssertionError("fallback should not be called")

    assert (
        _resolve_condition_field(
            "battery",
            {"power_source": "ac_power"},
            "power_source",
            fallback,
        )
        == "battery"
    )
    assert (
        _resolve_condition_field(
            None,
            {"power_source": "ac_power"},
            "power_source",
            fallback,
        )
        == "ac_power"
    )


def test_condition_field_resolution_uses_fallback_for_missing_or_none_hardware():
    assert (
        _resolve_condition_field(None, {}, "power_source", lambda: "unavailable")
        == "unavailable"
    )
    assert (
        _resolve_condition_field(
            None,
            {"power_source": None},
            "power_source",
            lambda: "unavailable",
        )
        == "unavailable"
    )


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


def test_low_power_mode_detects_disabled(monkeypatch):
    def fake_run(cmd, **kwargs):
        return MagicMock(stdout=" lowpowermode         0\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    assert get_low_power_mode() == "off"


def test_low_power_mode_falls_back_to_powermode_when_low_active(monkeypatch):
    def fake_run(cmd, **kwargs):
        return MagicMock(stdout=" powermode            1\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    assert get_low_power_mode() == "on"


@pytest.mark.parametrize("value", ["0", "2"])
def test_low_power_mode_falls_back_to_powermode_when_not_low(monkeypatch, value):
    def fake_run(cmd, **kwargs):
        return MagicMock(stdout=f" powermode            {value}\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    assert get_low_power_mode() == "off"


def test_low_power_mode_prefers_legacy_key_when_both_present(monkeypatch):
    def fake_run(cmd, **kwargs):
        return MagicMock(
            stdout=" powermode            2\n lowpowermode         1\n", stderr=""
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    assert get_low_power_mode() == "on"


def test_low_power_mode_unavailable_when_neither_key_present(monkeypatch):
    def fake_run(cmd, **kwargs):
        return MagicMock(stdout=" sleep                10\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    assert get_low_power_mode() == "unavailable_parse_error"
