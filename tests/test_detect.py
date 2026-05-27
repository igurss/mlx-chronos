import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from mlx_chronos.detect import (
    get_architecture,
    get_chip_model,
    get_machine_model,
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
