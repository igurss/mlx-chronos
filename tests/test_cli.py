import pytest
import sys
from pathlib import Path
from unittest.mock import patch
from argparse import Namespace
from mlx_chronos.cli import cmd_run, cmd_validate, main
from mlx_chronos.schema import EXAMPLE_RESULT

def test_cmd_run_invalid_trials(capsys):
    args = Namespace(trials=0, ram_sample_interval=0.1, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_run(args)
    assert exc.value.code == 2
    assert "Error: --trials must be at least 1." in capsys.readouterr().err

def test_cmd_run_invalid_ram_interval(capsys):
    args = Namespace(trials=1, ram_sample_interval=0, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_run(args)
    assert exc.value.code == 2
    assert "Error: --ram-sample-interval must be greater than 0." in capsys.readouterr().err

def test_cmd_run_invalid_model(capsys):
    args = Namespace(trials=1, ram_sample_interval=0.1, model="  ", format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_run(args)
    assert exc.value.code == 2
    assert "Error: --model must not be empty." in capsys.readouterr().err

def test_cmd_validate_invalid_model(capsys):
    args = Namespace(engine="omlx", model="  ")
    with pytest.raises(SystemExit) as exc:
        cmd_validate(args)
    assert exc.value.code == 2
    assert "Error: --model must not be empty." in capsys.readouterr().err

def test_main_engines_command():
    with patch.object(sys, "argv", ["mlx-chronos", "engines"]):
        with patch("mlx_chronos.cli.cmd_engines") as mock_engines:
            main()
            mock_engines.assert_called_once()

def test_main_validate_command():
    with patch.object(sys, "argv", ["mlx-chronos", "validate"]):
        with patch("mlx_chronos.cli.cmd_validate") as mock_validate:
            main()
            mock_validate.assert_called_once()

@patch("mlx_chronos.engines.get_engine")
@patch("mlx_chronos.detect.detect_hardware")
def test_cmd_validate_engine_only(mock_detect, mock_get_engine):
    mock_detect.return_value = {
        "chip": "Apple M2",
        "memory_gb": 8.0,
        "macos_version": "14.0",
    }

    mock_engine = mock_get_engine.return_value
    mock_engine.is_installed.return_value = True
    mock_engine.get_version.return_value = "1.0.0"
    mock_engine.is_server_running.return_value = True
    mock_engine.base_url.return_value = "http://localhost:8000/v1"
    mock_engine.list_model_ids.return_value = ["org/test-model"]

    cmd_validate(Namespace(engine="omlx", model=None))

    mock_engine.list_model_ids.assert_called_once()
    mock_engine.validate_completion_request.assert_not_called()

@patch("mlx_chronos.engines.get_engine")
@patch("mlx_chronos.detect.detect_hardware")
def test_cmd_validate_with_model(mock_detect, mock_get_engine):
    mock_detect.return_value = {
        "chip": "Apple M2",
        "memory_gb": 8.0,
        "macos_version": "14.0",
    }

    mock_engine = mock_get_engine.return_value
    mock_engine.is_installed.return_value = True
    mock_engine.get_version.return_value = "1.0.0"
    mock_engine.is_server_running.return_value = True
    mock_engine.base_url.return_value = "http://localhost:8000/v1"
    mock_engine.list_model_ids.return_value = ["org/test-model"]
    mock_engine.resolve_listed_model_id.return_value = "org/test-model"
    mock_engine.validate_completion_request.return_value = "org/test-model"

    cmd_validate(Namespace(engine="omlx", model="org/test-model"))

    mock_engine.resolve_listed_model_id.assert_called_once_with(
        "org/test-model",
        ["org/test-model"],
    )
    mock_engine.validate_completion_request.assert_called_once_with("org/test-model")

@patch("mlx_chronos.engines.get_engine")
@patch("mlx_chronos.detect.detect_hardware")
def test_cmd_validate_fails_when_server_is_down(mock_detect, mock_get_engine):
    mock_detect.return_value = {
        "chip": "Apple M2",
        "memory_gb": 8.0,
        "macos_version": "14.0",
    }

    mock_engine = mock_get_engine.return_value
    mock_engine.is_installed.return_value = True
    mock_engine.get_version.return_value = "1.0.0"
    mock_engine.is_server_running.return_value = False
    mock_engine.base_url.return_value = "http://localhost:8000/v1"

    with pytest.raises(SystemExit) as exc:
        cmd_validate(Namespace(engine="omlx", model="org/test-model"))

    assert exc.value.code == 1
    mock_engine.list_model_ids.assert_not_called()
    mock_engine.validate_completion_request.assert_not_called()

def test_cmd_run_format_all_calls_reporters():
    args = Namespace(
        engine="omlx",
        model="Qwen3.5-4B-OptiQ-4bit",
        quantization="4bit",
        trials=1,
        notes=None,
        ram_sample_interval=0.1,
        format="all",
        output_dir=None,
    )
    with patch("mlx_chronos.cli.run_benchmark", return_value=EXAMPLE_RESULT) as mock_run, \
         patch("mlx_chronos.cli.JSONReporter") as mock_json, \
         patch("mlx_chronos.cli.MarkdownReporter") as mock_md:
        mock_json.return_value.save.return_value = Path("results/submitted/test.json")
        mock_md.return_value.save.return_value = Path("results/submitted/test.md")

        cmd_run(args)

        mock_run.assert_called_once()
        mock_json.assert_called_once()
        mock_md.assert_called_once()
        expected_dir = Path.cwd() / "results" / "local"
        mock_json.return_value.save.assert_called_once_with(EXAMPLE_RESULT, expected_dir)
        mock_md.return_value.save.assert_called_once_with(EXAMPLE_RESULT, expected_dir)

def test_cmd_run_custom_output_dir():
    output_dir = Path("custom-results")
    args = Namespace(
        engine="omlx",
        model="Qwen3.5-4B-OptiQ-4bit",
        quantization="4bit",
        trials=1,
        notes=None,
        ram_sample_interval=0.1,
        format="json",
        output_dir=output_dir,
    )
    with patch("mlx_chronos.cli.run_benchmark", return_value=EXAMPLE_RESULT), \
         patch("mlx_chronos.cli.JSONReporter") as mock_json:
        mock_json.return_value.save.return_value = output_dir / "test.json"

        cmd_run(args)

        mock_json.return_value.save.assert_called_once_with(EXAMPLE_RESULT, output_dir)

def test_submitted_results_are_not_gitignored():
    gitignore = Path(".gitignore").read_text()
    assert "results/submitted/*.json" not in gitignore
    assert "results/local/" in gitignore
