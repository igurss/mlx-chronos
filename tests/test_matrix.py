import json
import time
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mlx_chronos.cli import _run_model_preflight, _run_once, cmd_matrix
from mlx_chronos.constants import MAX_REPEATS
from mlx_chronos.examples import EXAMPLE_RESULT
from mlx_chronos.matrix import (
    parse_engine_models,
    rotation_schedule,
    sample_matrix_conditions,
    save_matrix_manifest,
)


def _args(tmp_path: Path, **changes) -> Namespace:
    values = dict(
        engine_model=["omlx=org/model-a", "ollama=alias:model-b"],
        rounds=None, seed=17, cooldown_seconds=0.0,
        quantization="4bit", model_url=None, profile="baseline",
        trials=3, max_tokens=100, min_tokens=None,
        ram_sample_interval=0.1, connection_mode="persistent",
        format="json", notes=None, submitted_by=None, output_dir=tmp_path,
    )
    values.update(changes)
    return Namespace(**values)


@pytest.mark.parametrize("assignments", [
    [], ["omlx"], ["omlx="], ["unknown=model"],
    ["omlx=one", "omlx=two"],
])
def test_matrix_model_mapping_rejects_incomplete_or_ambiguous_input(assignments):
    with pytest.raises(ValueError):
        parse_engine_models(assignments, {"omlx", "ollama"})


def test_matrix_model_mapping_preserves_exact_engine_aliases():
    assert parse_engine_models(
        ["omlx=org/model", "ollama=alias:4b=mlx"], {"omlx", "ollama"}
    ) == {"omlx": "org/model", "ollama": "alias:4b=mlx"}


def test_rotation_schedule_is_reproducible_and_balances_each_position():
    names = ["omlx", "ollama", "mlx-lm"]
    schedule = rotation_schedule(names, 6, 17)
    assert schedule == rotation_schedule(names, 6, 17)
    assert all(set(round_) == set(names) for round_ in schedule)
    for engine in names:
        assert [round_.index(engine) for round_ in schedule].count(0) == 2
        assert sorted(round_.index(engine) for round_ in schedule[:3]) == [0, 1, 2]


def test_matrix_conditions_keep_unavailable_samples_unknown():
    with patch("mlx_chronos.matrix.get_thermal_state", side_effect=RuntimeError), \
         patch("mlx_chronos.matrix.get_power_source", return_value="ac"), \
         patch("mlx_chronos.matrix.get_low_power_mode", return_value="off"), \
         patch("mlx_chronos.matrix.psutil.virtual_memory", side_effect=OSError), \
         patch("mlx_chronos.matrix.psutil.swap_memory", side_effect=OSError):
        conditions = sample_matrix_conditions()
    assert conditions["thermal_state"] == "unavailable_error"
    assert conditions["ram_available_gb"] is None
    assert conditions["swap_used_gb"] is None


def test_matrix_manifest_write_is_json_and_replaceable(tmp_path):
    path = tmp_path / "matrix.json"
    save_matrix_manifest(path, {"status": "running"})
    save_matrix_manifest(path, {"status": "completed"})
    assert json.loads(path.read_text())["status"] == "completed"
    assert not list(tmp_path.glob("*.tmp"))


def test_matrix_preflights_every_model_before_any_measurement(tmp_path):
    events = []

    def preflight(engine, model, **_kwargs):
        events.append(("preflight", engine, model))
        return model

    def run_once(args, **kwargs):
        events.append(("run", args.engine, args.model))
        assert args.preflight is False
        kwargs["pre_run_hook"]()
        kwargs["saved_paths"]["json"] = tmp_path / f"{args.engine}.json"
        return EXAMPLE_RESULT

    with patch("mlx_chronos.cli._run_model_preflight", side_effect=preflight), \
         patch("mlx_chronos.cli._run_once", side_effect=run_once), \
         patch("mlx_chronos.cli.sample_matrix_conditions", return_value={"thermal_state": "nominal"}):
        cmd_matrix(_args(tmp_path))

    assert events[:2] == [
        ("preflight", "omlx", "org/model-a"),
        ("preflight", "ollama", "alias:model-b"),
    ]
    assert len(events) == 6  # two engines x two balanced rounds
    manifest = json.loads(next(tmp_path.glob("matrix_*.json")).read_text())
    assert manifest["status"] == "completed"
    assert manifest["position_balanced"] is True
    assert [entry["engine"] for entry in manifest["runs"]] == [
        engine for ordered in manifest["schedule"] for engine in ordered
    ]
    assert all(entry["before"] and entry["after"] for entry in manifest["runs"])
    assert all(entry["result_files"]["json"] for entry in manifest["runs"])


def test_matrix_failed_preflight_stops_all_measurements_and_records_every_probe(tmp_path):
    def preflight(engine, model, **_kwargs):
        if engine == "omlx":
            raise RuntimeError("server unavailable")
        return model

    with patch("mlx_chronos.cli._run_model_preflight", side_effect=preflight) as check, \
         patch("mlx_chronos.cli._run_once") as run:
        with pytest.raises(SystemExit) as error:
            cmd_matrix(_args(tmp_path))

    assert error.value.code == 1
    assert check.call_count == 2
    run.assert_not_called()
    manifest = json.loads(next(tmp_path.glob("matrix_*.json")).read_text())
    assert manifest["status"] == "preflight_failed"
    assert manifest["preflight"]["omlx"]["status"] == "failed"
    assert manifest["preflight"]["ollama"]["status"] == "passed"
    assert manifest["runs"] == []


def test_matrix_preflight_rejects_declared_quantization_mismatch():
    engine = MagicMock()
    engine.is_installed.return_value = True
    engine.is_server_running.return_value = True
    engine.list_model_ids.return_value = ["org/model"]
    engine.resolve_listed_model_id.return_value = "org/model"
    engine.validate_model_backend.return_value = {"format": "mlx", "quantization": "8bit"}
    with patch("mlx_chronos.cli.get_engine", return_value=engine):
        with pytest.raises(RuntimeError, match="quantization does not match"):
            _run_model_preflight("omlx", "org/model", declared_quantization="4bit")
    engine.validate_completion_request.assert_not_called()


def test_matrix_failed_benchmark_stops_sweep_and_keeps_partial_manifest(tmp_path):
    with patch("mlx_chronos.cli._run_model_preflight", side_effect=lambda _, model, **kw: model), \
         patch("mlx_chronos.cli._run_once", side_effect=SystemExit(1)) as run, \
         patch("mlx_chronos.cli.sample_matrix_conditions", return_value={"thermal_state": "nominal"}):
        with pytest.raises(SystemExit) as error:
            cmd_matrix(_args(tmp_path))

    assert error.value.code == 1
    assert run.call_count == 1
    manifest = json.loads(next(tmp_path.glob("matrix_*.json")).read_text())
    assert manifest["status"] == "failed"
    assert len(manifest["runs"]) == 1


def test_matrix_rejects_invalid_cooldown_before_preflight(tmp_path):
    with patch("mlx_chronos.cli._run_model_preflight") as preflight:
        with pytest.raises(SystemExit) as error:
            cmd_matrix(_args(tmp_path, cooldown_seconds=float("nan")))
    assert error.value.code == 2
    preflight.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"rounds": 0}, {"rounds": MAX_REPEATS + 1}, {"seed": -1},
    {"trials": 0}, {"max_tokens": 0},
    {"min_tokens": 101}, {"ram_sample_interval": float("inf")},
    {"model_url": "not-a-url"}, {"quantization": "  "},
])
def test_matrix_rejects_invalid_options_before_any_probe(tmp_path, changes):
    with patch("mlx_chronos.cli._run_model_preflight") as preflight:
        with pytest.raises(SystemExit) as error:
            cmd_matrix(_args(tmp_path, **changes))
    assert error.value.code == 2
    preflight.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_run_once_records_snapshot_after_cooldown_and_before_benchmark(tmp_path):
    order = []

    def benchmark(**_kwargs):
        order.append("benchmark")
        return EXAMPLE_RESULT

    args = _args(tmp_path)
    args.engine = "omlx"
    args.model = "org/model-a"
    args.preflight = False
    paths = {}
    with patch("mlx_chronos.cli.time.sleep", side_effect=lambda _: order.append("cooldown")), \
         patch("mlx_chronos.cli.run_benchmark", side_effect=benchmark), \
         patch("mlx_chronos.cli.JSONReporter") as reporter, \
         patch("mlx_chronos.cli._log_result_summary"), \
         patch("mlx_chronos.cli._log_publishability_summary"):
        reporter.return_value.save.return_value = tmp_path / "result.json"
        _run_once(
            args, profile="baseline", trials=3, max_tokens=100,
            min_tokens=None, connection_mode="persistent", cooldown_seconds=5.0,
            results_dir=tmp_path, last_run_finished_at=time.monotonic(),
            pre_run_hook=lambda: order.append("snapshot"), saved_paths=paths,
        )
    assert order == ["cooldown", "snapshot", "benchmark"]
    assert paths == {"json": tmp_path / "result.json"}
