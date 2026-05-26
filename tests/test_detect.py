import sys
from types import SimpleNamespace

from mlx_chronos.detect import get_thermal_state


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
