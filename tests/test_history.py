import copy
import json

import pytest

from mlx_chronos.examples import EXAMPLE_RESULT
from mlx_chronos.integrity import seal_result
from mlx_chronos.history import list_history
from tests.test_compare import write_result


def test_list_history_returns_empty_for_a_missing_directory(tmp_path):
    entries, skipped = list_history(tmp_path / "does-not-exist")

    assert entries == []
    assert skipped == []


def test_list_history_returns_empty_for_an_empty_directory(tmp_path):
    entries, skipped = list_history(tmp_path)

    assert entries == []
    assert skipped == []


def test_list_history_lists_every_valid_result(tmp_path):
    write_result(tmp_path / "a.json", tps=20.0)
    write_result(tmp_path / "b.json", tps=24.0)

    entries, skipped = list_history(tmp_path)

    assert len(entries) == 2
    assert skipped == []
    assert {entry["request_tokens_per_second"] for entry in entries} == {20.0, 24.0}


def test_list_history_sorts_by_timestamp_newest_first(tmp_path):
    older = copy.deepcopy(EXAMPLE_RESULT)
    older["meta"]["timestamp"] = "2026-01-01T00:00:00Z"
    newer = copy.deepcopy(EXAMPLE_RESULT)
    newer["meta"]["timestamp"] = "2026-06-01T00:00:00Z"

    (tmp_path / "older.json").write_text(json.dumps(seal_result(older)), encoding="utf-8")
    (tmp_path / "newer.json").write_text(json.dumps(seal_result(newer)), encoding="utf-8")

    entries, _skipped = list_history(tmp_path)

    assert [entry["path"] for entry in entries] == [
        str(tmp_path / "newer.json"),
        str(tmp_path / "older.json"),
    ]


def test_list_history_rejects_non_positive_limit(tmp_path):
    with pytest.raises(ValueError, match="at least 1"):
        list_history(tmp_path, limit=0)


def test_list_history_respects_the_limit(tmp_path):
    for i in range(5):
        write_result(tmp_path / f"{i}.json", tps=20.0 + i)

    entries, _skipped = list_history(tmp_path, limit=2)

    assert len(entries) == 2


def test_list_history_skips_invalid_files_without_hiding_the_valid_ones(tmp_path):
    write_result(tmp_path / "good.json", tps=20.0)
    (tmp_path / "bad.json").write_text("not json", encoding="utf-8")

    entries, skipped = list_history(tmp_path)

    assert len(entries) == 1
    assert len(skipped) == 1
    assert skipped[0][0] == tmp_path / "bad.json"
    assert "not valid JSON" in skipped[0][1]


def test_list_history_ignores_non_json_files(tmp_path):
    write_result(tmp_path / "good.json", tps=20.0)
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")

    entries, skipped = list_history(tmp_path)

    assert len(entries) == 1
    assert skipped == []


def test_list_history_does_not_recurse_into_subdirectories(tmp_path):
    write_result(tmp_path / "good.json", tps=20.0)
    subdir = tmp_path / "context"
    subdir.mkdir()
    write_result(subdir / "nested.json", tps=99.0)

    entries, skipped = list_history(tmp_path)

    assert len(entries) == 1
    assert skipped == []
