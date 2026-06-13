import json

from mlx_chronos.updates import (
    UpdateCheckResult,
    check_for_update,
    fetch_latest_version,
    is_newer_version,
    start_background_update_check,
    update_check_disabled,
)


class FakePyPIResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def test_is_newer_version_compares_numeric_releases():
    assert is_newer_version("0.2.10", "0.2.9") is True
    assert is_newer_version("0.3.0", "0.2.10") is True
    assert is_newer_version("0.2.1", "0.2.1") is False
    assert is_newer_version("0.2.1", "0.2.1.post1") is False


def test_fetch_latest_version_reads_pypi_json(monkeypatch):
    def fake_urlopen(request, timeout):
        assert request.full_url == "https://example.test/pypi.json"
        assert timeout == 0.5
        return FakePyPIResponse({"info": {"version": "0.2.2"}})

    monkeypatch.setattr("mlx_chronos.updates.urlopen", fake_urlopen)

    assert fetch_latest_version(timeout=0.5, url="https://example.test/pypi.json") == "0.2.2"


def test_fetch_latest_version_rejects_malformed_pypi_json(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakePyPIResponse({"info": None})

    monkeypatch.setattr("mlx_chronos.updates.urlopen", fake_urlopen)

    result = check_for_update(current_version="0.2.1", url="https://example.test/pypi.json")

    assert result.latest_version is None
    assert result.update_available is False
    assert "info.version" in result.error


def test_check_for_update_reports_available_release(monkeypatch):
    monkeypatch.setattr("mlx_chronos.updates.fetch_latest_version", lambda **kwargs: "0.2.2")

    result = check_for_update(current_version="0.2.1")

    assert result == UpdateCheckResult(
        current_version="0.2.1",
        latest_version="0.2.2",
        update_available=True,
        error=None,
    )


def test_check_for_update_suppresses_fetch_errors(monkeypatch):
    def fail_fetch(**kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("mlx_chronos.updates.fetch_latest_version", fail_fetch)

    result = check_for_update(current_version="0.2.1")

    assert result.current_version == "0.2.1"
    assert result.latest_version is None
    assert result.update_available is False
    assert result.error == "network down"


def test_update_check_disabled_env_var():
    assert update_check_disabled({"MLX_CHRONOS_DISABLE_UPDATE_CHECK": "1"}) is True
    assert update_check_disabled({"MLX_CHRONOS_DISABLE_UPDATE_CHECK": "true"}) is True
    assert update_check_disabled({"MLX_CHRONOS_DISABLE_UPDATE_CHECK": "0"}) is False


def test_background_update_check_notifies_when_update_available(monkeypatch, capsys):
    result = UpdateCheckResult(
        current_version="0.2.1",
        latest_version="0.2.2",
        update_available=True,
        error=None,
    )
    monkeypatch.setattr("mlx_chronos.updates.check_for_update", lambda **kwargs: result)

    thread = start_background_update_check(current_version="0.2.1")
    thread.join(timeout=1.0)

    captured = capsys.readouterr()
    assert "Update available: mlx-chronos 0.2.2" in captured.err
    assert "mlx-chronos upgrade" in captured.err
