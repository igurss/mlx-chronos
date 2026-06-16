import pytest
import sys
import json
import copy
import logging
import re
from pathlib import Path
from unittest.mock import MagicMock, patch
from argparse import Namespace

import httpx

from mlx_chronos import __version__ as VERSION
from mlx_chronos.cli import (
    _emit_result_warnings,
    _maybe_start_update_check,
    _should_start_update_check,
    cmd_models,
    cmd_run,
    cmd_submit,
    cmd_upgrade,
    cmd_wizard,
    cmd_validate,
    main,
)
from mlx_chronos.constants import (
    MAX_TRIALS,
    PUBLIC_BASELINE_TRIALS,
    SUSTAINED_THROUGHPUT_MAX_TOKENS,
    SUSTAINED_TRIALS,
)
from mlx_chronos.detect import BenchmarkConditionWarning
from mlx_chronos.examples import EXAMPLE_RESULT
from mlx_chronos.integrity import seal_result
from mlx_chronos.protocol import COLD_PROMPTS, THROUGHPUT_PROMPTS
from mlx_chronos.schema import BenchmarkResult
from mlx_chronos.stats import compute_stats
from mlx_chronos.submit import SubmissionError, load_publishable_result, submit_result_file
from mlx_chronos.updates import UpdateCheckResult


class FakeTTY:
    def __init__(self, is_tty=True):
        self._is_tty = is_tty

    def isatty(self):
        return self._is_tty


def test_cmd_run_invalid_trials(capsys):
    args = Namespace(trials=0, ram_sample_interval=0.1, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_run(args)
    assert exc.value.code == 2
    assert "Error: --trials must be at least 1." in capsys.readouterr().err

def test_cmd_run_trials_above_max(capsys):
    args = Namespace(trials=MAX_TRIALS + 1, ram_sample_interval=0.1, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_run(args)
    assert exc.value.code == 2
    assert f"Error: --trials must be <= {MAX_TRIALS}." in capsys.readouterr().err

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

def test_cmd_run_invalid_max_tokens(capsys):
    args = Namespace(
        trials=1,
        ram_sample_interval=0.1,
        max_tokens=0,
        min_tokens=None,
        model="test",
        format="json",
    )
    with pytest.raises(SystemExit) as exc:
        cmd_run(args)
    assert exc.value.code == 2
    assert "Error: --max-tokens must be at least 1." in capsys.readouterr().err

def test_cmd_run_invalid_min_tokens(capsys):
    args = Namespace(
        trials=1,
        ram_sample_interval=0.1,
        max_tokens=100,
        min_tokens=0,
        model="test",
        format="json",
    )
    with pytest.raises(SystemExit) as exc:
        cmd_run(args)
    assert exc.value.code == 2
    assert "Error: --min-tokens must be at least 1." in capsys.readouterr().err

def test_cmd_run_min_tokens_must_not_exceed_max_tokens(capsys):
    args = Namespace(
        trials=1,
        ram_sample_interval=0.1,
        max_tokens=50,
        min_tokens=80,
        model="test",
        format="json",
    )
    with pytest.raises(SystemExit) as exc:
        cmd_run(args)
    assert exc.value.code == 2
    assert "Error: --min-tokens must be <= --max-tokens." in capsys.readouterr().err

def test_cmd_run_invalid_cooldown(capsys):
    args = Namespace(
        trials=1,
        ram_sample_interval=0.1,
        max_tokens=100,
        min_tokens=None,
        cooldown_seconds=-1,
        profile="baseline",
        model="test",
        format="json",
    )
    with pytest.raises(SystemExit) as exc:
        cmd_run(args)
    assert exc.value.code == 2
    assert "Error: --cooldown-seconds must be non-negative." in capsys.readouterr().err

def test_cmd_validate_invalid_model(capsys):
    args = Namespace(engine="omlx", model="  ")
    with pytest.raises(SystemExit) as exc:
        cmd_validate(args)
    assert exc.value.code == 2
    assert "Error: --model must not be empty." in capsys.readouterr().err

def test_main_version_command(capsys):
    with patch.object(sys, "argv", ["mlx-chronos", "--version"]):
        with pytest.raises(SystemExit) as exc:
            main()

    assert exc.value.code == 0
    assert f"mlx-chronos {VERSION}" in capsys.readouterr().out


def test_package_version_matches_pyproject():
    project_root = Path(__file__).resolve().parent.parent
    pyproject = (project_root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)

    assert match is not None
    assert VERSION == match.group(1)

def test_main_engines_command():
    with patch.object(sys, "argv", ["mlx-chronos", "engines"]):
        with patch("mlx_chronos.cli.cmd_engines") as mock_engines:
            main()
            mock_engines.assert_called_once()

def test_main_models_command():
    with patch.object(sys, "argv", ["mlx-chronos", "models"]):
        with patch("mlx_chronos.cli.cmd_models") as mock_models:
            main()
            mock_models.assert_called_once()

def test_main_validate_command():
    with patch.object(sys, "argv", ["mlx-chronos", "validate"]):
        with patch("mlx_chronos.cli.cmd_validate") as mock_validate:
            main()
            mock_validate.assert_called_once()

def test_main_submit_command():
    with patch.object(sys, "argv", ["mlx-chronos", "submit", "--file", "result.json"]):
        with patch("mlx_chronos.cli.cmd_submit") as mock_submit:
            main()
            mock_submit.assert_called_once()


def test_main_upgrade_command():
    with patch.object(sys, "argv", ["mlx-chronos", "upgrade"]):
        with patch("mlx_chronos.cli.cmd_upgrade") as mock_upgrade:
            main()
            mock_upgrade.assert_called_once()


def test_main_wizard_command():
    with patch.object(sys, "argv", ["mlx-chronos", "wizard"]):
        with patch("mlx_chronos.cli.cmd_wizard") as mock_wizard:
            main()
            mock_wizard.assert_called_once()


def test_cmd_wizard_invokes_interactive_runner():
    with patch("mlx_chronos.wizard.run_wizard") as mock_run_wizard:
        cmd_wizard(Namespace())

    mock_run_wizard.assert_called_once()


def test_should_start_update_check_only_for_interactive_commands(monkeypatch):
    monkeypatch.delenv("MLX_CHRONOS_DISABLE_UPDATE_CHECK", raising=False)

    assert _should_start_update_check("engines", stream=FakeTTY(True)) is True
    assert _should_start_update_check("engines", stream=FakeTTY(False)) is False
    assert _should_start_update_check("upgrade", stream=FakeTTY(True)) is False


def test_should_start_update_check_honors_disable_env(monkeypatch):
    monkeypatch.setenv("MLX_CHRONOS_DISABLE_UPDATE_CHECK", "1")

    assert _should_start_update_check("engines", stream=FakeTTY(True)) is False


def test_maybe_start_update_check_starts_background_thread(monkeypatch):
    monkeypatch.delenv("MLX_CHRONOS_DISABLE_UPDATE_CHECK", raising=False)
    with patch("mlx_chronos.cli.sys.stderr", FakeTTY(True)):
        with patch("mlx_chronos.cli.start_background_update_check") as mock_start:
            _maybe_start_update_check("engines")

    mock_start.assert_called_once()


def test_maybe_start_update_check_skips_upgrade(monkeypatch):
    monkeypatch.delenv("MLX_CHRONOS_DISABLE_UPDATE_CHECK", raising=False)
    with patch("mlx_chronos.cli.sys.stderr", FakeTTY(True)):
        with patch("mlx_chronos.cli.start_background_update_check") as mock_start:
            _maybe_start_update_check("upgrade")

    mock_start.assert_not_called()


@patch("mlx_chronos.cli.subprocess.run")
@patch("mlx_chronos.cli.check_for_update")
def test_cmd_upgrade_installs_when_update_is_available(
    mock_check_for_update,
    mock_run,
    caplog,
):
    mock_check_for_update.return_value = UpdateCheckResult(
        current_version="0.2.1",
        latest_version="0.2.2",
        update_available=True,
        error=None,
    )
    mock_run.return_value.returncode = 0
    caplog.set_level(logging.INFO, logger="mlx_chronos")

    cmd_upgrade(Namespace(timeout=0.5))

    mock_check_for_update.assert_called_once_with(timeout=0.5)
    mock_run.assert_called_once_with(
        [sys.executable, "-m", "pip", "install", "--upgrade", "mlx-chronos"],
        check=False,
    )
    assert "Updating mlx-chronos from" in caplog.text
    assert "Upgrade complete" in caplog.text


@patch("mlx_chronos.cli.subprocess.run")
@patch("mlx_chronos.cli.check_for_update")
def test_cmd_upgrade_reports_current_version_when_latest(
    mock_check_for_update,
    mock_run,
    caplog,
):
    mock_check_for_update.return_value = UpdateCheckResult(
        current_version=VERSION,
        latest_version=VERSION,
        update_available=False,
        error=None,
    )
    caplog.set_level(logging.INFO, logger="mlx_chronos")

    cmd_upgrade(Namespace(timeout=0.5))

    mock_run.assert_not_called()
    assert "mlx-chronos is already up to date" in caplog.text


@patch("mlx_chronos.cli.check_for_update")
def test_cmd_upgrade_reports_check_error(mock_check_for_update, capsys):
    mock_check_for_update.return_value = UpdateCheckResult(
        current_version=VERSION,
        latest_version=None,
        update_available=False,
        error="network down",
    )

    with pytest.raises(SystemExit) as exc:
        cmd_upgrade(Namespace(timeout=0.5))

    assert exc.value.code == 1
    assert "could not check for mlx-chronos updates: network down" in capsys.readouterr().err


def test_cmd_upgrade_invalid_timeout(capsys):
    with pytest.raises(SystemExit) as exc:
        cmd_upgrade(Namespace(timeout=0))

    assert exc.value.code == 2
    assert "Error: --timeout must be greater than 0." in capsys.readouterr().err

@patch("mlx_chronos.cli.get_engine")
def test_cmd_models_lists_engine_models(mock_get_engine, caplog):
    mock_engine = mock_get_engine.return_value
    mock_engine.is_installed.return_value = True
    mock_engine.is_server_running.return_value = True
    mock_engine.base_url.return_value = "http://localhost:8000/v1"
    mock_engine.list_model_ids.return_value = ["org/test-model", "org/other-model"]

    caplog.set_level(logging.INFO, logger="mlx_chronos")

    cmd_models(Namespace(engine="omlx"))

    mock_engine.list_model_ids.assert_called_once()
    assert "org/test-model" in caplog.text
    assert "org/other-model" in caplog.text

@patch("mlx_chronos.cli.get_engine")
def test_cmd_models_requires_running_server(mock_get_engine, capsys):
    mock_engine = mock_get_engine.return_value
    mock_engine.is_installed.return_value = True
    mock_engine.is_server_running.return_value = False
    mock_engine.base_url.return_value = "http://localhost:8000/v1"

    with pytest.raises(SystemExit) as exc:
        cmd_models(Namespace(engine="omlx"))

    assert exc.value.code == 1
    assert "server is not running" in capsys.readouterr().err

@patch("mlx_chronos.cli.get_engine")
@patch("mlx_chronos.cli.detect_hardware")
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

@patch("mlx_chronos.cli.get_benchmark_condition_warnings")
@patch("mlx_chronos.cli.get_engine")
@patch("mlx_chronos.cli.detect_hardware")
def test_cmd_validate_emits_condition_warnings(
    mock_detect,
    mock_get_engine,
    mock_warnings,
    caplog,
):
    hardware = {
        "chip": "Apple M2",
        "memory_gb": 8.0,
        "macos_version": "14.0",
        "thermal_state": "unavailable_permission",
    }
    mock_detect.return_value = hardware
    mock_warnings.return_value = [
        BenchmarkConditionWarning(
            "thermal state unavailable",
            "thermal_state=unavailable_permission",
        )
    ]

    mock_engine = mock_get_engine.return_value
    mock_engine.is_installed.return_value = True
    mock_engine.get_version.return_value = "1.0.0"
    mock_engine.is_server_running.return_value = True
    mock_engine.base_url.return_value = "http://localhost:8000/v1"
    mock_engine.list_model_ids.return_value = ["org/test-model"]

    caplog.set_level(logging.INFO, logger="mlx_chronos")

    cmd_validate(Namespace(engine="omlx", model=None))

    mock_warnings.assert_called_once_with(hardware)
    assert "[warn] thermal state unavailable: thermal_state=unavailable_permission" in caplog.text

@patch("mlx_chronos.cli.get_engine")
@patch("mlx_chronos.cli.detect_hardware")
def test_cmd_validate_warns_on_unknown_engine_version(
    mock_detect,
    mock_get_engine,
    caplog,
):
    mock_detect.return_value = {
        "chip": "Apple M2",
        "memory_gb": 8.0,
        "macos_version": "14.0",
    }

    mock_engine = mock_get_engine.return_value
    mock_engine.is_installed.return_value = True
    mock_engine.get_version.return_value = "unknown"
    mock_engine.is_server_running.return_value = True
    mock_engine.base_url.return_value = "http://localhost:8000/v1"
    mock_engine.list_model_ids.return_value = ["org/test-model"]

    caplog.set_level(logging.INFO, logger="mlx_chronos")

    cmd_validate(Namespace(engine="omlx", model=None))

    assert "[warn] engine version: version detection failed" in caplog.text

@patch("mlx_chronos.cli.get_engine")
@patch("mlx_chronos.cli.detect_hardware")
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

@patch("mlx_chronos.cli.get_engine")
@patch("mlx_chronos.cli.detect_hardware")
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
        profile="baseline",
        cooldown_seconds=0.0,
        max_tokens=120,
        min_tokens=80,
        format="all",
        output_dir=None,
    )
    with patch("mlx_chronos.cli.run_benchmark", return_value=EXAMPLE_RESULT) as mock_run, \
         patch("mlx_chronos.cli._elapsed_since_last_result", return_value=None), \
         patch("mlx_chronos.cli.JSONReporter") as mock_json, \
         patch("mlx_chronos.cli.MarkdownReporter") as mock_md:
        mock_json.return_value.save.return_value = Path("results/submitted/test.json")
        mock_md.return_value.save.return_value = Path("results/submitted/test.md")

        cmd_run(args)

        mock_run.assert_called_once_with(
            engine_name="omlx",
            model_name="Qwen3.5-4B-OptiQ-4bit",
            model_quantization="4bit",
            model_reference_url=None,
            trials=1,
            notes=None,
            ram_sample_interval=0.1,
            throughput_max_tokens=120,
            throughput_min_tokens=80,
            benchmark_profile="baseline",
            elapsed_since_last_benchmark_seconds=None,
            cooldown_seconds=0.0,
            progress_sample_interval_tokens=None,
            connection_mode="persistent",
        )
        mock_json.assert_called_once()
        mock_md.assert_called_once()
        expected_dir = Path.cwd() / "results" / "local"
        mock_json.return_value.save.assert_called_once_with(EXAMPLE_RESULT, expected_dir)
        mock_md.return_value.save.assert_called_once_with(EXAMPLE_RESULT, expected_dir)


def test_cmd_run_passes_model_url():
    args = Namespace(
        engine="omlx",
        model="Qwen3.5-4B-OptiQ-4bit",
        quantization="4bit",
        model_url=" https://huggingface.co/mlx-community/Qwen3.5-4B-OptiQ-4bit ",
        trials=1,
        notes=None,
        ram_sample_interval=0.1,
        profile="baseline",
        cooldown_seconds=0.0,
        max_tokens=120,
        min_tokens=80,
        format="json",
        output_dir=None,
        connection_mode="persistent",
    )
    with patch("mlx_chronos.cli.run_benchmark", return_value=EXAMPLE_RESULT) as mock_run, \
         patch("mlx_chronos.cli._elapsed_since_last_result", return_value=None), \
         patch("mlx_chronos.cli.JSONReporter") as mock_json:
        mock_json.return_value.save.return_value = Path("results/local/test.json")

        cmd_run(args)

    assert mock_run.call_args.kwargs["model_reference_url"] == (
        " https://huggingface.co/mlx-community/Qwen3.5-4B-OptiQ-4bit "
    )


def test_cmd_run_preflight_validates_model_before_benchmark():
    args = Namespace(
        engine="omlx",
        model="Qwen3.5-4B-OptiQ-4bit",
        quantization="4bit",
        trials=1,
        notes=None,
        ram_sample_interval=0.1,
        profile="baseline",
        cooldown_seconds=0.0,
        max_tokens=100,
        min_tokens=None,
        format="json",
        output_dir=None,
        connection_mode="persistent",
        preflight=True,
    )
    mock_engine = MagicMock()
    mock_engine.is_installed.return_value = True
    mock_engine.is_server_running.return_value = True
    mock_engine.base_url.return_value = "http://localhost:8000/v1"
    mock_engine.list_model_ids.return_value = ["Qwen3.5-4B-OptiQ-4bit"]
    mock_engine.resolve_listed_model_id.return_value = "Qwen3.5-4B-OptiQ-4bit"
    mock_engine.validate_completion_request.return_value = "Qwen3.5-4B-OptiQ-4bit"

    with patch("mlx_chronos.cli.get_engine", return_value=mock_engine), \
         patch("mlx_chronos.cli.run_benchmark", return_value=EXAMPLE_RESULT) as mock_run, \
         patch("mlx_chronos.cli._elapsed_since_last_result", return_value=None), \
         patch("mlx_chronos.cli.JSONReporter") as mock_json:
        mock_json.return_value.save.return_value = Path("results/local/test.json")

        cmd_run(args)

    mock_engine.validate_completion_request.assert_called_once_with(
        "Qwen3.5-4B-OptiQ-4bit"
    )
    mock_run.assert_called_once()

def test_cmd_run_warns_when_previous_result_is_recent(caplog):
    args = Namespace(
        engine="omlx",
        model="Qwen3.5-4B-OptiQ-4bit",
        quantization="4bit",
        trials=1,
        notes=None,
        ram_sample_interval=0.1,
        profile="baseline",
        cooldown_seconds=0.0,
        max_tokens=100,
        min_tokens=None,
        format="json",
        output_dir=None,
    )
    caplog.set_level(logging.WARNING, logger="mlx_chronos")

    with patch("mlx_chronos.cli.run_benchmark", return_value=EXAMPLE_RESULT) as mock_run, \
         patch("mlx_chronos.cli._elapsed_since_last_result", return_value=120.0), \
         patch("mlx_chronos.cli.JSONReporter") as mock_json:
        mock_json.return_value.save.return_value = Path("results/local/test.json")

        cmd_run(args)

    assert "previous benchmark in this output directory was 120.0 seconds ago" in caplog.text
    assert mock_run.call_args.kwargs["elapsed_since_last_benchmark_seconds"] == 120.0

def test_cmd_run_sleeps_for_requested_cooldown():
    args = Namespace(
        engine="omlx",
        model="Qwen3.5-4B-OptiQ-4bit",
        quantization="4bit",
        trials=1,
        notes=None,
        ram_sample_interval=0.1,
        profile="baseline",
        cooldown_seconds=300.0,
        max_tokens=100,
        min_tokens=None,
        format="json",
        output_dir=None,
    )

    with patch("mlx_chronos.cli.run_benchmark", return_value=EXAMPLE_RESULT) as mock_run, \
         patch("mlx_chronos.cli._elapsed_since_last_result", side_effect=[100.0, 301.0]), \
         patch("mlx_chronos.cli.time.sleep") as mock_sleep, \
         patch("mlx_chronos.cli.JSONReporter") as mock_json:
        mock_json.return_value.save.return_value = Path("results/local/test.json")

        cmd_run(args)

    mock_sleep.assert_called_once_with(200.0)
    assert mock_run.call_args.kwargs["elapsed_since_last_benchmark_seconds"] == 301.0

def test_cmd_run_custom_output_dir():
    output_dir = Path("custom-results")
    args = Namespace(
        engine="omlx",
        model="Qwen3.5-4B-OptiQ-4bit",
        quantization="4bit",
        trials=1,
        notes=None,
        ram_sample_interval=0.1,
        profile="baseline",
        cooldown_seconds=0.0,
        format="json",
        output_dir=output_dir,
    )
    with patch("mlx_chronos.cli.run_benchmark", return_value=EXAMPLE_RESULT), \
         patch("mlx_chronos.cli._elapsed_since_last_result", return_value=None), \
         patch("mlx_chronos.cli.JSONReporter") as mock_json:
        mock_json.return_value.save.return_value = output_dir / "test.json"

        cmd_run(args)

        mock_json.return_value.save.assert_called_once_with(EXAMPLE_RESULT, output_dir)

def test_cmd_run_sustained_profile_defaults():
    args = Namespace(
        engine="omlx",
        model="Qwen3.5-4B-OptiQ-4bit",
        quantization="4bit",
        trials=None,
        notes=None,
        ram_sample_interval=0.1,
        profile="sustained",
        cooldown_seconds=0.0,
        max_tokens=None,
        min_tokens=None,
        format="json",
        output_dir=None,
    )
    with patch("mlx_chronos.cli.run_benchmark", return_value=EXAMPLE_RESULT) as mock_run, \
         patch("mlx_chronos.cli._elapsed_since_last_result", return_value=None), \
         patch("mlx_chronos.cli.JSONReporter") as mock_json:
        mock_json.return_value.save.return_value = Path("results/local/test.json")

        cmd_run(args)

    mock_run.assert_called_once()
    kwargs = mock_run.call_args.kwargs
    assert kwargs["trials"] == 1
    assert kwargs["throughput_max_tokens"] == 1000
    assert kwargs["benchmark_profile"] == "sustained"
    assert kwargs["progress_sample_interval_tokens"] == 100

def test_submitted_results_are_not_gitignored():
    project_root = Path(__file__).resolve().parent.parent
    gitignore = (project_root / ".gitignore").read_text()
    assert "results/submitted/*.json" not in gitignore
    assert "results/local/" in gitignore

def write_result(path: Path, data: dict | None = None) -> Path:
    path.write_text(json.dumps(seal_result(data or EXAMPLE_RESULT)), encoding="utf-8")
    return path

@patch("mlx_chronos.submit.httpx.post")
def test_submit_result_file_reuses_prevalidated_result(mock_post, tmp_path):
    result_path = write_result(tmp_path / "result.json")
    raw = result_path.read_bytes()
    result = BenchmarkResult(**EXAMPLE_RESULT)
    mock_post.return_value.status_code = 200
    mock_post.return_value.text = "ok"

    with patch("mlx_chronos.submit.load_publishable_result") as mock_load:
        submit_result_file(
            result_path,
            "https://example.test/form",
            raw=raw,
            result=result,
        )

    mock_load.assert_not_called()
    filename, content, content_type = mock_post.call_args.kwargs["files"]["result_json"]
    assert filename == "result.json"
    assert content == raw
    assert content_type == "application/json"


@patch("mlx_chronos.submit.httpx.post")
def test_submit_result_file_retries_transient_failure(mock_post, tmp_path):
    result_path = write_result(tmp_path / "result.json")
    mock_success = MagicMock(status_code=200, text="ok")
    mock_post.side_effect = [
        httpx.ConnectError("connection reset"),
        mock_success,
    ]

    with patch("mlx_chronos.http_retry.time.sleep") as mock_sleep:
        submit_result_file(result_path, "https://example.test/form")

    assert mock_post.call_count == 2
    mock_sleep.assert_called_once()

def test_cmd_submit_dry_run_validates_without_endpoint(tmp_path):
    result_path = write_result(tmp_path / "result.json")
    args = Namespace(
        file=result_path,
        endpoint=None,
        email=None,
        timeout=30.0,
        dry_run=True,
    )

    with patch("mlx_chronos.cli.submit_result_file") as mock_submit_file:
        cmd_submit(args)

    mock_submit_file.assert_not_called()

def test_cmd_submit_passes_prevalidated_payload(tmp_path):
    result_path = write_result(tmp_path / "result.json")
    raw = result_path.read_bytes()
    result = BenchmarkResult(**EXAMPLE_RESULT)
    args = Namespace(
        file=result_path,
        endpoint="https://example.test/form",
        email=None,
        timeout=30.0,
        dry_run=False,
    )

    with patch("mlx_chronos.cli.load_publishable_result", return_value=(raw, result)) as mock_load, \
         patch("mlx_chronos.cli.submit_result_file") as mock_submit_file:
        cmd_submit(args)

    mock_load.assert_called_once_with(result_path)
    mock_submit_file.assert_called_once()
    assert mock_submit_file.call_args.kwargs["raw"] == raw
    assert mock_submit_file.call_args.kwargs["result"] is result

def test_cmd_submit_invalid_timeout(capsys):
    args = Namespace(
        file=Path("result.json"),
        endpoint=None,
        email=None,
        timeout=0,
        dry_run=True,
    )
    with pytest.raises(SystemExit) as exc:
        cmd_submit(args)

    assert exc.value.code == 2
    assert "Error: --timeout must be greater than 0." in capsys.readouterr().err

def test_cmd_submit_uses_default_endpoint(tmp_path, monkeypatch):
    monkeypatch.delenv("MLX_CHRONOS_SUBMIT_ENDPOINT", raising=False)
    monkeypatch.delenv("MLX_CHRONOS_SUBMITTER_EMAIL", raising=False)
    result_path = write_result(tmp_path / "result.json")
    args = Namespace(
        file=result_path,
        endpoint=None,
        email=None,
        timeout=30.0,
        dry_run=False,
    )

    with patch("mlx_chronos.submit.httpx.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "ok"
        cmd_submit(args)

    mock_post.assert_called_once()
    endpoint = mock_post.call_args.args[0]
    assert endpoint == "https://usebasin.com/f/29157002c003"
    data = mock_post.call_args.kwargs["data"]
    assert data["email"] == "182094468+igurss@users.noreply.github.com"
    assert data["name"] == "mlx-chronos CLI"
    assert data["subject"] == "mlx-chronos benchmark result: omlx"
    assert "The full benchmark result is attached as result_json." in data["message"]

def test_cmd_submit_rejects_non_publishable_token_source(tmp_path, capsys):
    result = copy.deepcopy(EXAMPLE_RESULT)
    result["metrics"]["token_count_source"] = "word_fallback"
    result_path = write_result(tmp_path / "result.json", result)
    args = Namespace(
        file=result_path,
        endpoint="https://example.test/form",
        email=None,
        timeout=30.0,
        dry_run=False,
    )

    with pytest.raises(SystemExit) as exc:
        cmd_submit(args)

    assert exc.value.code == 1
    assert "usage.completion_tokens" in capsys.readouterr().err


def test_emit_result_warnings_does_not_duplicate_cached_ttft_warning(capsys):
    _emit_result_warnings({"meta": {"cached_ttft_warning": True}})

    assert "cached TTFT" not in capsys.readouterr().err


def test_load_publishable_result_rejects_tampered_integrity(tmp_path):
    result = copy.deepcopy(EXAMPLE_RESULT)
    result["metrics"]["tokens_per_second"]["mean"] = 99.0
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")

    with pytest.raises(SubmissionError, match="integrity"):
        load_publishable_result(result_path)


def test_load_publishable_result_rejects_missing_model_reference(tmp_path):
    result = copy.deepcopy(EXAMPLE_RESULT)
    result["model"].pop("reference_url", None)
    result_path = write_result(tmp_path / "result.json", result)

    with pytest.raises(SubmissionError, match="model.reference_url"):
        load_publishable_result(result_path)


def test_load_publishable_result_allows_legacy_missing_model_reference(tmp_path):
    result = copy.deepcopy(EXAMPLE_RESULT)
    result["model"].pop("reference_url", None)
    result_path = write_result(tmp_path / "result.json", result)

    _, parsed = load_publishable_result(
        result_path,
        allow_legacy_missing_model_reference=True,
    )

    assert parsed.model.reference_url is None


def resize_result_trials(result: dict, count: int) -> None:
    for key in (
        "ttft_cold_raw",
        "ttft_cached_raw",
        "tokens_per_second_raw",
        "throughput_elapsed_seconds_raw",
        "decode_tokens_per_second_raw",
        "completion_tokens_raw",
    ):
        result["trials"][key] = result["trials"][key][:count]
    if result["trials"].get("throughput_progress_samples_raw") is not None:
        result["trials"]["throughput_progress_samples_raw"] = result["trials"][
            "throughput_progress_samples_raw"
        ][:count]
    result["meta"]["benchmark_protocol"]["ttft_cold"]["prompts"] = COLD_PROMPTS[:count]
    result["meta"]["benchmark_protocol"]["throughput"]["prompts"] = (
        THROUGHPUT_PROMPTS[:count]
    )
    result["trials"]["count"] = count
    result["metrics"]["ttft_cold"] = compute_stats(result["trials"]["ttft_cold_raw"])
    result["metrics"]["ttft_cached"] = compute_stats(result["trials"]["ttft_cached_raw"])
    throughput_stats = compute_stats(result["trials"]["tokens_per_second_raw"])
    result["metrics"]["tokens_per_second"] = throughput_stats
    result["metrics"]["request_tokens_per_second"] = throughput_stats
    result["metrics"]["decode_tokens_per_second"] = compute_stats(
        result["trials"]["decode_tokens_per_second_raw"]
    )


def shrink_result_to_four_trials(result: dict) -> None:
    resize_result_trials(result, 4)


def expand_result_to_six_trials(result: dict) -> None:
    for key in (
        "ttft_cold_raw",
        "ttft_cached_raw",
        "tokens_per_second_raw",
        "throughput_elapsed_seconds_raw",
        "decode_tokens_per_second_raw",
        "completion_tokens_raw",
    ):
        result["trials"][key].append(result["trials"][key][-1])
    if result["trials"].get("throughput_progress_samples_raw") is not None:
        result["trials"]["throughput_progress_samples_raw"].append(
            copy.deepcopy(result["trials"]["throughput_progress_samples_raw"][-1])
        )
    result["meta"]["benchmark_protocol"]["ttft_cold"]["prompts"] = (
        COLD_PROMPTS[: PUBLIC_BASELINE_TRIALS + 1]
    )
    result["meta"]["benchmark_protocol"]["throughput"]["prompts"] = (
        THROUGHPUT_PROMPTS[: PUBLIC_BASELINE_TRIALS + 1]
    )
    result["trials"]["count"] = PUBLIC_BASELINE_TRIALS + 1
    result["metrics"]["ttft_cold"] = compute_stats(result["trials"]["ttft_cold_raw"])
    result["metrics"]["ttft_cached"] = compute_stats(result["trials"]["ttft_cached_raw"])
    throughput_stats = compute_stats(result["trials"]["tokens_per_second_raw"])
    result["metrics"]["tokens_per_second"] = throughput_stats
    result["metrics"]["request_tokens_per_second"] = throughput_stats
    result["metrics"]["decode_tokens_per_second"] = compute_stats(
        result["trials"]["decode_tokens_per_second_raw"]
    )
    extra_elapsed = result["trials"]["throughput_elapsed_seconds_raw"][-1]
    result["meta"]["phase_timings_seconds"]["throughput"] += extra_elapsed
    result["meta"]["phase_timings_seconds"]["total_runtime"] += extra_elapsed


def make_standard_sustained_result(result: dict) -> None:
    resize_result_trials(result, SUSTAINED_TRIALS)
    result["meta"]["benchmark_profile"] = "sustained"
    result["meta"]["benchmark_protocol"]["name"] = "sustained"
    result["meta"]["benchmark_protocol"]["throughput"][
        "requested_max_tokens"
    ] = SUSTAINED_THROUGHPUT_MAX_TOKENS
    set_completion_tokens(result, SUSTAINED_THROUGHPUT_MAX_TOKENS)


def set_completion_tokens(result: dict, tokens: int) -> None:
    count = result["trials"]["count"]
    result["trials"]["completion_tokens_raw"] = [tokens] * count
    result["trials"]["tokens_per_second_raw"] = [
        round(tokens / elapsed, 2)
        for elapsed in result["trials"]["throughput_elapsed_seconds_raw"]
    ]
    throughput_stats = compute_stats(result["trials"]["tokens_per_second_raw"])
    result["metrics"]["tokens_per_second"] = throughput_stats
    result["metrics"]["request_tokens_per_second"] = throughput_stats


def make_sustained_with_two_trials(result: dict) -> None:
    resize_result_trials(result, 2)
    result["meta"]["benchmark_profile"] = "sustained"
    result["meta"]["benchmark_protocol"]["name"] = "sustained"
    result["meta"]["benchmark_protocol"]["throughput"][
        "requested_max_tokens"
    ] = SUSTAINED_THROUGHPUT_MAX_TOKENS


def make_sustained_with_baseline_max_tokens(result: dict) -> None:
    resize_result_trials(result, SUSTAINED_TRIALS)
    result["meta"]["benchmark_profile"] = "sustained"
    result["meta"]["benchmark_protocol"]["name"] = "sustained"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            shrink_result_to_four_trials,
            "baseline leaderboard submissions must use the standard baseline trial count",
        ),
        (
            expand_result_to_six_trials,
            "baseline leaderboard submissions must use the standard baseline trial count",
        ),
        (
            lambda result: result["meta"]["benchmark_protocol"]["throughput"].__setitem__(
                "requested_max_tokens",
                1000,
            ),
            "baseline leaderboard submissions must use standard throughput",
        ),
        (
            lambda result: result["meta"]["benchmark_protocol"]["throughput"].__setitem__(
                "requested_min_tokens",
                80,
            ),
            "must not request throughput min_tokens",
        ),
        (
            lambda result: result["meta"]["benchmark_protocol"]["throughput"][
                "generation_parameters"
            ].__setitem__("temperature", 0.7),
            "standard generation parameters",
        ),
        (
            lambda result: result["meta"]["benchmark_protocol"]["throughput"].__setitem__(
                "connection_mode",
                "per_request",
            ),
            "benchmark_protocol.throughput.connection_mode",
        ),
        (
            lambda result: result["meta"]["benchmark_protocol"]["throughput"][
                "prompts"
            ].__setitem__(0, "Altered throughput prompt."),
            "benchmark_protocol.throughput.prompts",
        ),
        (
            lambda result: result["meta"]["benchmark_protocol"]["ttft_cold"].__setitem__(
                "stream_usage_requested",
                True,
            ),
            "benchmark_protocol.ttft_cold.stream_usage_requested",
        ),
        (
            lambda result: set_completion_tokens(result, 79),
            "at least 80% of the standard throughput max_tokens",
        ),
        (
            lambda result: result["hardware"].__setitem__("low_power_mode", "on"),
            "pmset -g custom",
        ),
        (
            lambda result: result["hardware"].__setitem__(
                "low_power_mode",
                "unavailable_pmset_not_found",
            ),
            "pmset -g custom",
        ),
        (
            lambda result: result["meta"].__setitem__("warmup_failures", 1),
            "warmup_failures=1",
        ),
        (
            make_sustained_with_two_trials,
            "sustained leaderboard submissions must use the standard sustained trial count",
        ),
        (
            make_sustained_with_baseline_max_tokens,
            "sustained leaderboard submissions must use standard sustained max_tokens=1000",
        ),
    ],
)
def test_load_publishable_result_rejects_nonstandard_leaderboard_runs(
    tmp_path,
    mutate,
    message,
):
    result = copy.deepcopy(EXAMPLE_RESULT)
    mutate(result)
    result_path = write_result(tmp_path / "result.json", result)

    with pytest.raises(SubmissionError, match=message):
        load_publishable_result(result_path)


def test_load_publishable_result_accepts_standard_sustained_run(tmp_path):
    result = copy.deepcopy(EXAMPLE_RESULT)
    make_standard_sustained_result(result)
    result_path = write_result(tmp_path / "result.json", result)

    _, parsed = load_publishable_result(result_path)

    assert parsed.meta.benchmark_profile == "sustained"
    assert parsed.trials.count == SUSTAINED_TRIALS
    assert (
        parsed.meta.benchmark_protocol.throughput.requested_max_tokens
        == SUSTAINED_THROUGHPUT_MAX_TOKENS
    )

@patch("mlx_chronos.submit.httpx.post")
def test_cmd_submit_env_endpoint_overrides_default(mock_post, tmp_path, monkeypatch):
    monkeypatch.setenv("MLX_CHRONOS_SUBMIT_ENDPOINT", "https://example.test/env-form")
    result_path = write_result(tmp_path / "result.json")
    mock_post.return_value.status_code = 200
    mock_post.return_value.text = "ok"
    args = Namespace(
        file=result_path,
        endpoint=None,
        email=None,
        timeout=30.0,
        dry_run=False,
    )

    cmd_submit(args)

    endpoint = mock_post.call_args.args[0]
    assert endpoint == "https://example.test/env-form"

@patch("mlx_chronos.submit.httpx.post")
def test_cmd_submit_email_overrides_default(mock_post, tmp_path, monkeypatch):
    monkeypatch.setenv("MLX_CHRONOS_SUBMITTER_EMAIL", "env@example.test")
    result_path = write_result(tmp_path / "result.json")
    mock_post.return_value.status_code = 200
    mock_post.return_value.text = "ok"
    args = Namespace(
        file=result_path,
        endpoint="https://example.test/form",
        email="arg@example.test",
        timeout=30.0,
        dry_run=False,
    )

    cmd_submit(args)

    data = mock_post.call_args.kwargs["data"]
    assert data["email"] == "arg@example.test"

@patch("mlx_chronos.submit.httpx.post")
def test_cmd_submit_sends_result_file(mock_post, tmp_path):
    result_path = write_result(tmp_path / "result.json")
    mock_post.return_value.status_code = 200
    mock_post.return_value.text = "ok"
    args = Namespace(
        file=result_path,
        endpoint="https://example.test/form",
        email="submitter@example.test",
        timeout=12.0,
        dry_run=False,
    )

    cmd_submit(args)

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["timeout"] == 12.0
    assert kwargs["follow_redirects"] is True
    assert kwargs["data"]["email"] == "submitter@example.test"
    assert kwargs["data"]["name"] == "mlx-chronos CLI"
    assert "Engine: omlx" in kwargs["data"]["message"]
    filename, content, content_type = kwargs["files"]["result_json"]
    assert filename == "result.json"
    assert json.loads(content.decode("utf-8"))["engine"]["name"] == "omlx"
    assert content_type == "application/json"

@patch("mlx_chronos.submit.httpx.post")
def test_cmd_submit_reports_http_error(mock_post, tmp_path, capsys):
    result_path = write_result(tmp_path / "result.json")
    mock_post.return_value.status_code = 500
    mock_post.return_value.text = "server error"
    args = Namespace(
        file=result_path,
        endpoint="https://example.test/form",
        email=None,
        timeout=30.0,
        dry_run=False,
    )

    with pytest.raises(SystemExit) as exc:
        cmd_submit(args)

    assert exc.value.code == 1
    assert "HTTP 500" in capsys.readouterr().err
