import copy
import json

import pytest

from mlx_chronos.examples import EXAMPLE_RESULT
from mlx_chronos.integrity import seal_result
from mlx_chronos.leaderboard import (
    DuplicateResultError,
    build_results_index,
    load_archive_results,
    main,
    write_results_index,
)


def write_result(path, result):
    path.write_text(json.dumps(seal_result(result)), encoding="utf-8")
    return path


def test_archive_rejects_duplicate_digest(tmp_path):
    write_result(tmp_path / "first.json", copy.deepcopy(EXAMPLE_RESULT))
    write_result(tmp_path / "second.json", copy.deepcopy(EXAMPLE_RESULT))

    with pytest.raises(DuplicateResultError, match="duplicate digest"):
        load_archive_results(tmp_path)


def test_archive_rejects_resealed_duplicate_run_identity(tmp_path):
    first = copy.deepcopy(EXAMPLE_RESULT)
    second = copy.deepcopy(EXAMPLE_RESULT)
    second["meta"]["notes"] = "same run, changed note"
    write_result(tmp_path / "first.json", first)
    write_result(tmp_path / "second.json", second)

    with pytest.raises(DuplicateResultError, match="duplicate run identity"):
        load_archive_results(tmp_path)


def test_index_exposes_only_public_model_identity_fields(tmp_path):
    result = copy.deepcopy(EXAMPLE_RESULT)
    result["model"]["format"] = "safetensors"
    write_result(tmp_path / "result.json", result)

    row = build_results_index(tmp_path)["results"][0]
    assert row["model_reference_url"] == result["model"]["reference_url"]
    assert row["model_format"] == "safetensors"
    assert "model_source" not in row
    assert "model_revision" not in row
    assert "model_weight_hash" not in row
    assert "model_tokenizer_hash" not in row
    assert "model_chat_template_hash" not in row
    assert "model_architecture" not in row
    assert "model_family" not in row
    assert "model_parameter_size" not in row


def test_index_contains_public_policy_metadata(tmp_path):
    write_result(tmp_path / "result.json", copy.deepcopy(EXAMPLE_RESULT))

    metadata = build_results_index(tmp_path)["metadata"]

    assert metadata == {
        "standard_throughput_max_tokens": 100,
        "standard_baseline_trials": 5,
        "standard_sustained_max_tokens": 1000,
        "standard_sustained_trials": 1,
        "minimum_completion_token_ratio": 0.8,
    }


def test_write_results_index_writes_json_file(tmp_path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    write_result(results_dir / "result.json", copy.deepcopy(EXAMPLE_RESULT))
    output = tmp_path / "index.json"

    assert write_results_index(results_dir, output) == 1
    assert json.loads(output.read_text(encoding="utf-8"))["results"][0][
        "engine"
    ] == "omlx"


def test_leaderboard_cli_main_generates_requested_output(tmp_path, capsys):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    write_result(results_dir / "result.json", copy.deepcopy(EXAMPLE_RESULT))
    output = tmp_path / "index.json"

    exit_code = main(
        ["--results-dir", str(results_dir), "--output", str(output)]
    )

    assert exit_code == 0
    assert output.exists()
    assert "Generated index with 1 results" in capsys.readouterr().out
