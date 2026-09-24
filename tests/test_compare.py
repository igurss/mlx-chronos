import copy
import json

import pytest

from mlx_chronos.compare import CompareError, compare_results, load_result_for_compare
from mlx_chronos.examples import EXAMPLE_RESULT
from mlx_chronos.integrity import seal_result
from mlx_chronos.stats import compute_stats


def write_result(path, tps=None, decode_tps=None, ram_delta=None):
    """Build a schema-valid EXAMPLE_RESULT variant with a chosen throughput.

    BenchmarkResult cross-checks tokens_per_second_raw[i] against
    completion_tokens_raw[i] / throughput_elapsed_seconds_raw[i] (and the
    equivalent for decode), so a desired tps is reached by deriving elapsed
    time from the (unchanged) completion token count, rather than setting a
    mean directly and fighting every downstream consistency check
    separately. throughput_progress_samples_raw is dropped since it would
    otherwise also need to be kept in sync with the derived elapsed times.
    """
    data = copy.deepcopy(EXAMPLE_RESULT)
    tokens = data["trials"]["completion_tokens_raw"]
    data["trials"]["throughput_progress_samples_raw"] = None

    if tps is not None:
        elapsed = [round(n / tps, 6) for n in tokens]
        raw = [round(n / e, 2) for n, e in zip(tokens, elapsed)]
        data["trials"]["throughput_elapsed_seconds_raw"] = elapsed
        data["trials"]["tokens_per_second_raw"] = raw
        data["metrics"]["request_tokens_per_second"] = compute_stats(raw)
        data["metrics"]["tokens_per_second"] = compute_stats(raw)

    if decode_tps is False:
        data["metrics"]["decode_tokens_per_second"] = None
        data["metrics"]["decode_timing_source"] = "unavailable"
        data["trials"]["decode_tokens_per_second_raw"] = None
        data["trials"]["decode_elapsed_seconds_raw"] = None
    elif decode_tps is not None:
        decode_elapsed = [round((n - 1) / decode_tps, 6) for n in tokens]
        decode_raw = [round((n - 1) / e, 2) for n, e in zip(tokens, decode_elapsed)]
        data["trials"]["decode_elapsed_seconds_raw"] = decode_elapsed
        data["trials"]["decode_tokens_per_second_raw"] = decode_raw
        data["metrics"]["decode_tokens_per_second"] = compute_stats(decode_raw)
    if ram_delta is not None:
        data["metrics"]["system_ram_baseline_gb"] = 1.0
        data["metrics"]["system_ram_delta_gb"] = ram_delta
        data["metrics"]["system_ram_peak_gb"] = round(1.0 + ram_delta, 3)
    path.write_text(json.dumps(seal_result(data)), encoding="utf-8")
    return path


# --- load_result_for_compare ------------------------------------------------------

def test_load_result_for_compare_loads_a_valid_file(tmp_path):
    path = write_result(tmp_path / "a.json")

    result = load_result_for_compare(path)

    assert result.engine.name == EXAMPLE_RESULT["engine"]["name"]


def test_load_result_for_compare_rejects_a_missing_file(tmp_path):
    with pytest.raises(CompareError, match="file not found"):
        load_result_for_compare(tmp_path / "does-not-exist.json")


def test_load_result_for_compare_rejects_a_directory(tmp_path):
    with pytest.raises(CompareError, match="not a file"):
        load_result_for_compare(tmp_path)


def test_load_result_for_compare_rejects_invalid_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(CompareError, match="not valid JSON"):
        load_result_for_compare(path)


def test_load_result_for_compare_rejects_a_file_that_fails_schema_validation(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps({"not": "a benchmark result"}), encoding="utf-8")

    with pytest.raises(CompareError, match="not a valid benchmark result"):
        load_result_for_compare(path)


def test_load_result_for_compare_rejects_a_changed_value_with_stale_seal(tmp_path):
    path = write_result(tmp_path / "changed.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["meta"]["notes"] = "edited after capture"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(CompareError, match="invalid integrity seal"):
        load_result_for_compare(path)


# --- compare_results ---------------------------------------------------------------

def test_compare_results_requires_at_least_two_files(tmp_path):
    path = write_result(tmp_path / "a.json")

    with pytest.raises(ValueError, match="at least two"):
        compare_results([path])


def test_compare_results_reports_identifying_columns_per_file(tmp_path):
    path_a = write_result(tmp_path / "a.json", tps=20.0)
    path_b = write_result(tmp_path / "b.json", tps=24.0)

    report = compare_results([path_a, path_b])

    assert len(report["columns"]) == 2
    assert report["columns"][0]["path"] == str(path_a)
    assert report["columns"][0]["engine"] == EXAMPLE_RESULT["engine"]["name"]
    assert report["columns"][1]["path"] == str(path_b)


def test_compare_results_computes_exact_percentage_deltas_against_the_first_file(tmp_path):
    path_a = write_result(tmp_path / "a.json", tps=20.0)
    path_b = write_result(tmp_path / "b.json", tps=24.0)  # +20% over a

    report = compare_results([path_a, path_b])

    tps_row = next(row for row in report["rows"] if row["label"] == "Request tok/s")
    assert tps_row["values"] == [20.0, 24.0]
    # First file is always the baseline: its own delta against itself is 0.
    assert tps_row["deltas_percent"] == [0.0, 20.0]
    assert tps_row["higher_is_better"] is True


def test_compare_results_handles_a_regression_as_a_negative_delta(tmp_path):
    path_a = write_result(tmp_path / "a.json", tps=25.0)
    path_b = write_result(tmp_path / "b.json", tps=20.0)  # -20% over a

    report = compare_results([path_a, path_b])

    tps_row = next(row for row in report["rows"] if row["label"] == "Request tok/s")
    assert tps_row["deltas_percent"] == [0.0, -20.0]


def test_compare_results_handles_decode_tps_missing_from_one_file(tmp_path):
    path_a = write_result(tmp_path / "a.json", decode_tps=False)
    path_b = write_result(tmp_path / "b.json", decode_tps=30.0)

    report = compare_results([path_a, path_b])

    decode_row = next(row for row in report["rows"] if row["label"] == "Decode tok/s")
    assert decode_row["values"] == [None, 30.0]
    # No baseline to compare against: both deltas are unknown, not zero.
    assert decode_row["deltas_percent"] == [None, None]


def test_compare_results_handles_a_missing_ram_delta_gracefully(tmp_path):
    # RAM baseline/delta are optional; older files have none.
    path_a = write_result(tmp_path / "a.json")
    path_b = write_result(tmp_path / "b.json", ram_delta=2.0)

    report = compare_results([path_a, path_b])

    ram_row = next(row for row in report["rows"] if row["label"] == "System RAM rise (GB)")
    assert ram_row["values"][0] is None
    assert ram_row["deltas_percent"] == [None, None]


def test_compare_results_supports_more_than_two_files(tmp_path):
    paths = [
        write_result(tmp_path / f"{i}.json", tps=tps)
        for i, tps in enumerate([10.0, 20.0, 30.0])
    ]

    report = compare_results(paths)

    tps_row = next(row for row in report["rows"] if row["label"] == "Request tok/s")
    assert tps_row["values"] == [10.0, 20.0, 30.0]
    assert tps_row["deltas_percent"] == [0.0, 100.0, 200.0]


def test_compare_results_warns_when_hardware_differs(tmp_path):
    path_a = write_result(tmp_path / "a.json", tps=20.0)
    path_b = write_result(tmp_path / "b.json", tps=24.0)
    data = json.loads(path_b.read_text(encoding="utf-8"))
    data["hardware"]["chip"] = "Different chip"
    path_b.write_text(json.dumps(seal_result(data)), encoding="utf-8")

    report = compare_results([path_a, path_b])

    assert any("hardware differs" in warning for warning in report["warnings"])


def test_compare_results_raises_with_the_offending_path_named(tmp_path):
    good = write_result(tmp_path / "good.json")
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")

    with pytest.raises(CompareError, match=str(bad)):
        compare_results([good, bad])
