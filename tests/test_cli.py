import pytest
import sys
import json
import copy
from pathlib import Path
from unittest.mock import patch
from argparse import Namespace
from mlx_chronos.cli import cmd_run, cmd_submit, cmd_validate, main
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

def test_main_submit_command():
    with patch.object(sys, "argv", ["mlx-chronos", "submit", "--file", "result.json"]):
        with patch("mlx_chronos.cli.cmd_submit") as mock_submit:
            main()
            mock_submit.assert_called_once()

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
    project_root = Path(__file__).resolve().parent.parent
    gitignore = (project_root / ".gitignore").read_text()
    assert "results/submitted/*.json" not in gitignore
    assert "results/local/" in gitignore

def write_result(path: Path, data: dict | None = None) -> Path:
    path.write_text(json.dumps(data or EXAMPLE_RESULT), encoding="utf-8")
    return path

def test_cmd_submit_dry_run_validates_without_endpoint(tmp_path):
    result_path = write_result(tmp_path / "result.json")
    args = Namespace(file=result_path, endpoint=None, timeout=30.0, dry_run=True)

    with patch("mlx_chronos.cli.submit_result_file") as mock_submit_file:
        cmd_submit(args)

    mock_submit_file.assert_not_called()

def test_cmd_submit_invalid_timeout(capsys):
    args = Namespace(file=Path("result.json"), endpoint=None, timeout=0, dry_run=True)
    with pytest.raises(SystemExit) as exc:
        cmd_submit(args)

    assert exc.value.code == 2
    assert "Error: --timeout must be greater than 0." in capsys.readouterr().err

def test_cmd_submit_uses_default_endpoint(tmp_path, monkeypatch):
    monkeypatch.delenv("MLX_CHRONOS_SUBMIT_ENDPOINT", raising=False)
    result_path = write_result(tmp_path / "result.json")
    args = Namespace(file=result_path, endpoint=None, timeout=30.0, dry_run=False)

    with patch("mlx_chronos.submit.httpx.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "ok"
        cmd_submit(args)

    mock_post.assert_called_once()
    endpoint = mock_post.call_args.args[0]
    assert endpoint == "https://usebasin.com/f/29157002c003"

def test_cmd_submit_rejects_non_publishable_token_source(tmp_path, capsys):
    result = copy.deepcopy(EXAMPLE_RESULT)
    result["metrics"]["token_count_source"] = "word_fallback"
    result_path = write_result(tmp_path / "result.json", result)
    args = Namespace(file=result_path, endpoint="https://example.test/form", timeout=30.0, dry_run=False)

    with pytest.raises(SystemExit) as exc:
        cmd_submit(args)

    assert exc.value.code == 1
    assert "usage.completion_tokens" in capsys.readouterr().err

@patch("mlx_chronos.submit.httpx.post")
def test_cmd_submit_env_endpoint_overrides_default(mock_post, tmp_path, monkeypatch):
    monkeypatch.setenv("MLX_CHRONOS_SUBMIT_ENDPOINT", "https://example.test/env-form")
    result_path = write_result(tmp_path / "result.json")
    mock_post.return_value.status_code = 200
    mock_post.return_value.text = "ok"
    args = Namespace(file=result_path, endpoint=None, timeout=30.0, dry_run=False)

    cmd_submit(args)

    endpoint = mock_post.call_args.args[0]
    assert endpoint == "https://example.test/env-form"

@patch("mlx_chronos.submit.httpx.post")
def test_cmd_submit_sends_result_file(mock_post, tmp_path):
    result_path = write_result(tmp_path / "result.json")
    mock_post.return_value.status_code = 200
    mock_post.return_value.text = "ok"
    args = Namespace(file=result_path, endpoint="https://example.test/form", timeout=12.0, dry_run=False)

    cmd_submit(args)

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["timeout"] == 12.0
    assert kwargs["follow_redirects"] is True
    filename, content, content_type = kwargs["files"]["result_json"]
    assert filename == "result.json"
    assert json.loads(content.decode("utf-8"))["engine"]["name"] == "omlx"
    assert content_type == "application/json"

@patch("mlx_chronos.submit.httpx.post")
def test_cmd_submit_reports_http_error(mock_post, tmp_path, capsys):
    result_path = write_result(tmp_path / "result.json")
    mock_post.return_value.status_code = 500
    mock_post.return_value.text = "server error"
    args = Namespace(file=result_path, endpoint="https://example.test/form", timeout=30.0, dry_run=False)

    with pytest.raises(SystemExit) as exc:
        cmd_submit(args)

    assert exc.value.code == 1
    assert "HTTP 500" in capsys.readouterr().err
