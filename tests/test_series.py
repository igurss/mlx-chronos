import json

import pytest

from mlx_chronos.compare import (
    CompareError,
    compare_series,
    load_result_for_compare,
    summarize_results,
)
from mlx_chronos.integrity import seal_result
from mlx_chronos.stats import compute_stats
from tests.test_compare import write_result


def row(report, label):
    return next(item for item in report["rows"] if item["label"] == label)


def test_series_compare_complete_sessions_not_pooled_prompt_trials(tmp_path):
    a = [
        write_result(tmp_path / f"a{i}.json", tps=tps)
        for i, tps in enumerate([20, 22, 100])
    ]
    b = [
        write_result(tmp_path / f"b{i}.json", tps=tps)
        for i, tps in enumerate([24, 26, 28])
    ]
    report = compare_series(a, b)
    a_stats = row(report["summaries"][0], "Request tok/s")["stats"]
    assert a_stats["count"] == 3  # Not the 15 underlying prompt trials.
    assert a_stats["median"] == 22
    assert a_stats["mean"] == pytest.approx(142 / 3)
    assert a_stats["mad"] == 2
    assert a_stats["max"] == 100  # No automatic outlier removal.
    change = row(report, "Request tok/s")
    assert change["values"] == [22, 26]
    assert change["delta_percent"] == 18.2
    assert change["delta_status"] == "descriptive"


def test_copies_and_repeated_paths_do_not_inflate_evidence(tmp_path):
    a = write_result(tmp_path / "a.json", tps=20)
    copy = tmp_path / "copy.json"
    copy.write_bytes(a.read_bytes())
    b = write_result(tmp_path / "b.json", tps=25)
    report = compare_series([a, copy, a], [b])
    assert report["summaries"][0]["count"] == 1
    assert report["ignored_duplicates"] == [copy, a]
    assert report["labels"] == ["A[1]", "B[1]"]
    stats = row(report["summaries"][0], "Request tok/s")["stats"]
    assert stats["stddev"] is None
    assert stats["mad"] is None


def test_the_same_evidence_cannot_appear_on_both_sides(tmp_path):
    a = write_result(tmp_path / "a.json")
    copy = tmp_path / "copy.json"
    copy.write_bytes(a.read_bytes())
    with pytest.raises(CompareError, match="both series"):
        compare_series([a], [copy])


def test_series_with_missing_metrics_show_available_counts(tmp_path):
    a1 = write_result(tmp_path / "a1.json", tps=20, decode_tps=False)
    a2 = write_result(tmp_path / "a2.json", tps=22, ram_delta=2)
    b = write_result(tmp_path / "b.json", tps=25)
    report = compare_series([a1, a2], [b])
    stats = row(report["summaries"][0], "Decode tok/s")["stats"]
    assert (stats["count"], stats["missing"]) == (1, 1)
    assert stats["mad"] is None
    assert row(report, "Decode tok/s")["delta_percent"] is not None
    ram_stats = row(report["summaries"][0], "System RAM rise (GB)")["stats"]
    assert (ram_stats["count"], ram_stats["missing"]) == (1, 1)
    assert (
        row(report, "System RAM rise (GB)")["delta_reason"]
        == "metric missing from reference or result"
    )


@pytest.mark.parametrize(
    "source_a,source_b,status",
    [
        ("usage.completion_tokens", "usage.completion_tokens", "descriptive"),
        ("word_fallback", "word_fallback", "estimated"),
        ("usage.completion_tokens", "word_fallback", "unavailable"),
        ("word_fallback", "usage.completion_tokens", "unavailable"),
        ("mixed", "usage.completion_tokens", "unavailable"),
    ],
)
def test_series_respect_completion_count_units(tmp_path, source_a, source_b, status):
    a = write_result(
        tmp_path / "a.json",
        tps=20,
        mutate=lambda d: d["metrics"].update(token_count_source=source_a),
    )
    b = write_result(
        tmp_path / "b.json",
        tps=25,
        mutate=lambda d: d["metrics"].update(token_count_source=source_b),
    )
    report = compare_series([a], [b])
    for label in ("Request tok/s", "Decode tok/s"):
        assert row(report, label)["delta_status"] == status
        assert (row(report, label)["delta_percent"] is None) == (
            status == "unavailable"
        )
    assert row(report, "TTFT cold (s)")["delta_status"] == "descriptive"
    assert row(report, "RAM peak (GB)")["delta_status"] == "descriptive"


def test_inconsistent_units_within_a_series_have_no_aggregate_throughput(tmp_path):
    a1 = write_result(tmp_path / "a1.json", tps=20)
    a2 = write_result(
        tmp_path / "a2.json",
        tps=24,
        mutate=lambda d: d["metrics"].update(token_count_source="word_fallback"),
    )
    b = write_result(tmp_path / "b.json", tps=25)
    report = compare_series([a1, a2], [b])
    throughput = row(report["summaries"][0], "Request tok/s")
    assert throughput["stats"] is None
    assert throughput["values"] == [20, 24]
    assert "within series" in row(report, "Request tok/s")["delta_reason"]
    assert row(report, "TTFT cached (s)")["delta_percent"] is not None


def test_series_cautions_keep_global_pair_indices_and_engine_changes(tmp_path):
    a1 = write_result(tmp_path / "a1.json", tps=20)
    a2 = write_result(
        tmp_path / "a2.json",
        tps=22,
        mutate=lambda d: d["engine"].update(version="0.4.0"),
    )
    b1 = write_result(tmp_path / "b1.json", tps=25)
    b2 = write_result(
        tmp_path / "b2.json",
        tps=26,
        mutate=lambda d: d["engine"].update(name="rapid-mlx"),
    )
    report = compare_series([a1, a2], [b1, b2])
    a_warning = next(w for w in report["warnings"] if w["field"] == "engine.version")
    assert (a_warning["baseline_index"], a_warning["result_index"]) == (0, 1)
    b_warning = next(w for w in report["warnings"] if w["field"] == "engine.name")
    assert (b_warning["baseline_index"], b_warning["result_index"]) == (2, 3)
    assert any(
        w["baseline_index"] == 0 and w["result_index"] == 3 for w in report["warnings"]
    )


def test_session_means_are_computed_from_unrounded_raw_observations(tmp_path):
    def mutate(data):
        raw = [0.000101, 0.000102, 0.000105, 0.000102, 0.000102]
        data["trials"]["ttft_cold_raw"] = raw
        data["metrics"]["ttft_cold"] = compute_stats(raw)

    path = write_result(tmp_path / "a.json", mutate=mutate)
    result = load_result_for_compare(path)
    assert result.metrics.ttft_cold.mean == 0
    summary = summarize_results([result])
    assert row(summary, "TTFT cold (s)")["stats"]["mean"] == pytest.approx(0.0001024)


def test_series_reject_invalid_schema_or_seal_before_aggregation(tmp_path):
    a = write_result(tmp_path / "a.json", tps=20)
    b = write_result(tmp_path / "b.json", tps=25)
    data = json.loads(b.read_text())
    data["meta"]["notes"] = "Edited after capture"
    b.write_text(json.dumps(data))
    with pytest.raises(CompareError, match="invalid integrity seal"):
        compare_series([a], [b])
    data["trials"]["count"] = 2
    b.write_text(json.dumps(seal_result(data)))
    with pytest.raises(CompareError, match="not a valid benchmark"):
        compare_series([a], [b])


def test_empty_series_are_rejected(tmp_path):
    a = write_result(tmp_path / "a.json")
    with pytest.raises(ValueError, match="each series"):
        compare_series([a], [])
    with pytest.raises(ValueError, match="one session"):
        summarize_results([])
