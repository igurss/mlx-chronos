import json
from unittest.mock import patch

import pytest

from mlx_chronos.cli import cmd_run, main, parse_cli_args, resolve_run_settings
from mlx_chronos.protocol import BASELINE_PROTOCOL_VERSION
from mlx_chronos.run_config import (
    MAX_RUN_CONFIG_BYTES, form_values, load_run_configuration, save_run_configuration,
)


def saved_config(tmp_path, *options):
    path = tmp_path / "experiment.json"
    settings = resolve_run_settings(parse_cli_args([
        "run", "--model", "org/model with spaces", *options,
    ]))
    save_run_configuration(path, settings)
    return path


@pytest.mark.parametrize("profile,trials,tokens", [("baseline", 5, 100), ("sustained", 1, 1000)])
def test_save_resolves_defaults_without_updates_hardware_or_inference(tmp_path, monkeypatch, profile, trials, tokens):
    path = tmp_path / "experiment.json"
    monkeypatch.setattr("sys.argv", ["mlx-chronos", "run", "--model", "org/model", "--profile", profile, "--save-config", str(path)])
    with patch("mlx_chronos.cli._run_once", side_effect=AssertionError("no inference")), \
         patch("mlx_chronos.cli.detect_hardware", side_effect=AssertionError("no hardware")), \
         patch("mlx_chronos.cli._maybe_start_update_check", side_effect=AssertionError("no network")):
        main()

    config = load_run_configuration(path)
    assert config.benchmark_protocol_version == BASELINE_PROTOCOL_VERSION
    assert config.run.trials == trials
    assert config.run.max_tokens == tokens
    assert config.run.repeat == 1
    assert config.run.preflight is False
    assert "output_dir" not in config.run.model_dump()
    assert "submitted_by" not in config.run.model_dump()


def test_loaded_values_survive_changed_cli_defaults(tmp_path, monkeypatch):
    path = saved_config(tmp_path)
    monkeypatch.setattr("mlx_chronos.cli.DEFAULT_TRIALS", 13)
    monkeypatch.setattr("mlx_chronos.cli.DEFAULT_THROUGHPUT_MAX_TOKENS", 222)
    loaded = resolve_run_settings(parse_cli_args(["run", "--config", str(path)]))
    assert loaded.trials == 5
    assert loaded.max_tokens == 100
    assert loaded.model == "org/model with spaces"


def test_explicit_overrides_replace_saved_values_and_declarations(tmp_path):
    path = saved_config(tmp_path, "--repeat", "3", "--engine-opt", "cache_policy=off")
    loaded = resolve_run_settings(parse_cli_args([
        "run", "--config", str(path), "--repeat", "2", "--max-tokens", "200",
        "--engine-opt", "allocated_context_length=4096", "--notes=-literal note $(never execute)",
    ]))
    assert loaded.repeat == 2
    assert loaded.max_tokens == 200
    assert loaded.engine_opt == ["allocated_context_length=4096"]
    assert loaded.notes == "-literal note $(never execute)"


def test_loaded_run_uses_existing_execution_and_current_checks(tmp_path):
    path = saved_config(tmp_path, "--preflight", "--cooldown-seconds", "3.5")
    args = parse_cli_args(["run", "--config", str(path), "--output-dir", str(tmp_path / "results")])
    with patch("mlx_chronos.cli._run_once", return_value={}) as run:
        cmd_run(args)
    run.assert_called_once()
    assert run.call_args.args[0].model == "org/model with spaces"
    assert run.call_args.args[0].preflight is True
    assert run.call_args.kwargs["cooldown_seconds"] == 3.5
    assert run.call_args.kwargs["trials"] == 5
    assert run.call_args.kwargs["results_dir"] == tmp_path / "results"


def test_save_publishable_configuration_does_not_probe_the_environment(tmp_path):
    args = parse_cli_args([
        "run", "--model", "org/model", "--model-url", "https://huggingface.co/org/model",
        "--publishable", "--save-config", str(tmp_path / "public.json"),
    ])
    with patch("mlx_chronos.cli._ensure_publishable_environment", side_effect=AssertionError("no hardware")):
        cmd_run(args)
    assert load_run_configuration(tmp_path / "public.json").run.preflight is True
    with patch("mlx_chronos.cli._ensure_publishable_environment", side_effect=SystemExit(2)) as check:
        with pytest.raises(SystemExit):
            cmd_run(parse_cli_args(["run", "--config", str(tmp_path / "public.json")]))
    check.assert_called_once()


@pytest.mark.parametrize("field,value", [
    ("repeat", True), ("repeat", "3"), ("repeat", 2.0), ("trials", 0),
    ("cooldown_seconds", float("nan")), ("ram_sample_interval", -1),
    ("engine", "unimplemented"), ("model", " "), ("connection_mode", "guess"),
    ("min_tokens", 200), ("preflight", "false"), ("engine_opt", ["cache_policy=off\ncache_policy=on"]),
    ("custom_prompt", "different workload"),
])
def test_invalid_or_unknown_saved_settings_fail_before_execution(tmp_path, field, value):
    path = saved_config(tmp_path)
    data = json.loads(path.read_text())
    data["run"][field] = value
    path.write_text(json.dumps(data))
    with patch("mlx_chronos.cli._run_once", side_effect=AssertionError("must not run")):
        with pytest.raises(SystemExit) as stopped:
            parse_cli_args(["run", "--config", str(path)])
    assert stopped.value.code == 2


@pytest.mark.parametrize("field,value", [
    ("schema_version", "mlx-chronos-run-config-v2"),
    ("benchmark_protocol_version", "3"), ("unknown_setting", 1),
])
def test_incompatible_format_or_protocol_is_explicit(tmp_path, field, value):
    path = saved_config(tmp_path)
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_run_configuration(path)


@pytest.mark.parametrize("text", ['{"run":{},"run":{}}', "[]", "null", "not JSON", "[" * 2000 + "]" * 2000])
def test_malformed_files_and_duplicate_keys_are_rejected(tmp_path, text):
    path = tmp_path / "invalid.json"
    path.write_text(text)
    with pytest.raises(ValueError):
        load_run_configuration(path)


def test_file_size_is_bounded(tmp_path):
    path = tmp_path / "large.json"
    path.write_bytes(b" " * (MAX_RUN_CONFIG_BYTES + 1))
    with pytest.raises(ValueError, match="1 MB"):
        load_run_configuration(path)


def test_invalid_save_preserves_existing_file(tmp_path):
    path = tmp_path / "preserved.json"
    path.write_text("preserve this content")
    args = parse_cli_args(["run", "--model", "org/model", "--trials", "0", "--save-config", str(path)])
    with pytest.raises(SystemExit):
        cmd_run(args)
    assert path.read_text() == "preserve this content"


def test_form_values_preserve_resolved_numbers_booleans_and_literal_text(tmp_path):
    path = saved_config(tmp_path, "--engine-opt", "cache_policy=off", "--notes", "a\nb $(literal)")
    values = form_values(load_run_configuration(path).run)
    assert values["trials"] == "5"
    assert values["preflight"] == "false"
    assert values["engine_opt"] == "cache_policy=off"
    assert values["min_tokens"] == ""
    assert values["notes"] == "a\nb $(literal)"
