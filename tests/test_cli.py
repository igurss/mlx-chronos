import pytest
import sys
from pathlib import Path
from unittest.mock import patch
from argparse import Namespace
from mlx_chronos.cli import cmd_run, main
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

def test_main_engines_command():
    with patch.object(sys, "argv", ["mlx-chronos", "engines"]):
        with patch("mlx_chronos.cli.cmd_engines") as mock_engines:
            main()
            mock_engines.assert_called_once()

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
