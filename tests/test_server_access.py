"""A reachable, identified HTTP server may live outside Chronos' Python."""

import importlib
from unittest.mock import MagicMock, patch

import pytest

from mlx_chronos.cli import (
    _run_model_preflight, cmd_doctor, cmd_engines, cmd_models, cmd_validate, parse_cli_args,
)
from mlx_chronos.examples import EXAMPLE_RESULT
from mlx_chronos.wizard import WizardSession


def test_engine_inventory_reports_an_external_running_server(caplog):
    engine = MagicMock()
    engine.is_installed.return_value = False
    engine.is_server_running.return_value = True
    engine.base_url.return_value = "http://localhost:8000/v1"
    with patch("mlx_chronos.cli.ENGINES", {"omlx": engine}), \
         patch("mlx_chronos.cli.get_engine", return_value=engine), \
         caplog.at_level("INFO", logger="mlx_chronos"):
        cmd_engines(parse_cli_args(["engines"]))
    assert "running" in caplog.text
    assert "not installed" not in caplog.text
    engine.is_server_running.assert_called_once()


@pytest.mark.parametrize("command", ["models", "doctor", "validate", "preflight", "wizard"])
def test_diagnostics_and_preflight_accept_an_external_engine(command):
    engine = MagicMock()
    engine.is_installed.return_value = False
    engine.is_server_running.return_value = True
    engine.get_version.return_value = "1.2.3"
    engine.list_model_ids.return_value = ["org/model"]
    engine.resolve_listed_model_id.return_value = "org/model"
    engine.validate_model_backend.return_value = {"format": "safetensors"}
    with patch("mlx_chronos.cli.get_engine", return_value=engine), \
         patch("mlx_chronos.wizard.get_engine", return_value=engine), \
         patch("mlx_chronos.cli.detect_hardware", return_value=EXAMPLE_RESULT["hardware"]):
        if command == "preflight":
            _run_model_preflight("omlx", "org/model")
        elif command == "wizard":
            models, error = object.__new__(WizardSession)._load_model_ids("omlx")
            assert models == ["org/model"] and error is None
        else:
            arguments = [command, "--engine", "omlx"]
            if command != "models":
                arguments += ["--model", "org/model"]
            {"models": cmd_models, "doctor": cmd_doctor, "validate": cmd_validate}[command](
                parse_cli_args(arguments)
            )
    engine.list_model_ids.assert_called_once()
    if command not in {"models", "wizard"}:
        engine.validate_completion_request.assert_called_once_with("org/model")


@pytest.mark.parametrize("profile,function", [
    ("benchmark", "run_benchmark"), ("context_profile", "run_context_profile"),
    ("concurrency_profile", "run_concurrency_profile"), ("energy_profile", "run_energy_profile"),
])
@pytest.mark.parametrize("running", [False, True])
def test_external_engine_still_requires_a_server_and_valid_backend(profile, function, running):
    module = importlib.import_module(f"mlx_chronos.{profile}")
    engine = MagicMock()
    engine.is_installed.return_value = False
    engine.is_server_running.return_value = running
    engine.validate_model_backend.side_effect = RuntimeError("backend rejected")
    with patch.object(module, "get_engine", return_value=engine), \
         patch.object(module, "detect_hardware", return_value=EXAMPLE_RESULT["hardware"]), \
         patch("mlx_chronos.energy_profile.shutil.which", return_value="/fake/macmon"):
        with pytest.raises(RuntimeError, match="backend rejected" if running else "server is not running"):
            getattr(module, function)("omlx", "org/model", model_quantization="4bit")
    if running:
        engine.validate_model_backend.assert_called_once_with("org/model")
    else:
        engine.validate_model_backend.assert_not_called()
    engine.measure_throughput.assert_not_called()
