import copy
import json

import pytest

from mlx_chronos.compare import CompareError, compare_results, load_result_for_compare
from mlx_chronos.examples import EXAMPLE_RESULT
from mlx_chronos.integrity import seal_result
from mlx_chronos.stats import compute_stats


def write_result(path, tps=None, decode_tps=None, ram_delta=None, *, mutate=None):
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

    if tps is not None and decode_tps is None:
        # Preserve the prefill fraction when changing request speed, so decode
        # remains an interval inside that same request.
        fraction = [
            d / e
            for d, e in zip(
                data["trials"]["decode_elapsed_seconds_raw"],
                data["trials"]["throughput_elapsed_seconds_raw"],
            )
        ]
        decode_elapsed = [round(n / tps * f, 6) for n, f in zip(tokens, fraction)]
        decode_raw = [round((n - 1) / e, 2) for n, e in zip(tokens, decode_elapsed)]
        data["trials"]["decode_elapsed_seconds_raw"] = decode_elapsed
        data["trials"]["decode_tokens_per_second_raw"] = decode_raw
        data["metrics"]["decode_tokens_per_second"] = compute_stats(decode_raw)
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
    if mutate is not None:
        mutate(data)
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


def test_load_result_for_compare_rejects_non_utf8_file(tmp_path):
    path = tmp_path / "non-utf8.json"
    path.write_bytes(b"\xff\xfe")

    with pytest.raises(CompareError, match="could not read file"):
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


def test_compare_results_computes_exact_percentage_deltas_against_the_first_file(
    tmp_path,
):
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

    ram_row = next(
        row for row in report["rows"] if row["label"] == "System RAM rise (GB)"
    )
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

    assert any(
        "hardware differs" in warning["message"] for warning in report["warnings"]
    )


def test_compare_results_raises_with_the_offending_path_named(tmp_path):
    good = write_result(tmp_path / "good.json")
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")

    with pytest.raises(CompareError, match=str(bad)):
        compare_results([good, bad])


def change_field(data, path, value):
    target = data
    for field in path[:-1]:
        target = target[field]
    target[path[-1]] = value


def test_differences_are_scoped_to_one_reference_pair(tmp_path):
    paths = [write_result(tmp_path / f"{i}.json", tps=20 + i) for i in range(3)]
    changed = json.loads(paths[2].read_text())
    changed["hardware"]["chip"] = "Apple M4"
    paths[2].write_text(json.dumps(seal_result(changed)))
    report = compare_results(paths)
    differences = [w for w in report["warnings"] if w["kind"] == "difference"]
    assert len(differences) == 1
    assert differences[0]["baseline_index"] == 0
    assert differences[0]["result_index"] == 2
    assert differences[0]["baseline_value"] == "Apple M2"
    assert differences[0]["value"] == "Apple M4"
    assert next(r for r in report["rows"] if r["label"] == "Request tok/s")[
        "deltas_percent"
    ] == [0, 5, 10]


@pytest.mark.parametrize(
    "path,value",
    [
        (("hardware", "memory_gb"), 16),
        (("model", "name"), "Another model"),
        (
            ("model", "reference_url"),
            "https://huggingface.co/mlx-community/another-model",
        ),
        (("model", "quantization"), "8bit"),
        (("model", "format"), "gguf"),
        (("meta", "benchmark_profile"), "sustained"),
        (("meta", "benchmark_protocol", "version"), "3"),
    ],
)
def test_general_differences_retain_descriptive_percentages(tmp_path, path, value):
    def mutate(data):
        change_field(data, path, value)
        if path[-1] == "benchmark_profile":
            data["meta"]["benchmark_protocol"]["name"] = value

    first = write_result(
        tmp_path / "first.json",
        tps=20,
        mutate=lambda d: d["model"].update(format="safetensors"),
    )
    second = write_result(tmp_path / "second.json", tps=24, mutate=mutate)
    report = compare_results([first, second])
    warning = next(w for w in report["warnings"] if w["field"] == ".".join(path))
    assert warning["kind"] == "difference"
    assert set(warning["metrics"]) == {r["label"] for r in report["rows"]}
    assert report["rows"][0]["deltas_percent"][1] == 20
    assert report["rows"][0]["delta_status"][1] == "descriptive"


@pytest.mark.parametrize(
    "phase,affected",
    [
        (
            "warmup",
            {
                "Request tok/s",
                "Decode tok/s",
                "TTFT cold (s)",
                "TTFT cached (s)",
                "RAM peak (GB)",
                "System RAM rise (GB)",
            },
        ),
        (
            "ttft_cold",
            {
                "Request tok/s",
                "Decode tok/s",
                "TTFT cold (s)",
                "TTFT cached (s)",
                "RAM peak (GB)",
                "System RAM rise (GB)",
            },
        ),
        (
            "ttft_cached",
            {
                "Request tok/s",
                "Decode tok/s",
                "TTFT cached (s)",
                "RAM peak (GB)",
                "System RAM rise (GB)",
            },
        ),
        (
            "throughput",
            {"Request tok/s", "Decode tok/s", "RAM peak (GB)", "System RAM rise (GB)"},
        ),
    ],
)
def test_phase_differences_respect_warmup_priming_and_sequence(
    tmp_path, phase, affected
):
    first = write_result(tmp_path / "first.json")
    second = write_result(
        tmp_path / "second.json",
        mutate=lambda d: change_field(
            d,
            (
                "meta",
                "benchmark_protocol",
                phase,
                "generation_parameters",
                "temperature",
            ),
            0.5,
        ),
    )
    report = compare_results([first, second])
    differences = [w for w in report["warnings"] if w["kind"] == "difference"]
    assert len(differences) == 1
    assert differences[0]["field"].endswith(
        f"{phase}.generation_parameters.temperature"
    )
    assert set(differences[0]["metrics"]) == affected
    assert differences[0]["baseline_value"] == 0
    assert differences[0]["value"] == 0.5


def test_prompt_changes_identify_the_position_even_when_lengths_match(tmp_path):
    first = write_result(tmp_path / "first.json")

    def mutate(data):
        data["meta"]["benchmark_protocol"]["throughput"]["prompts"][3] = (
            "Different fourth prompt"
        )

    second = write_result(tmp_path / "second.json", mutate=mutate)
    warning = next(
        w
        for w in compare_results([first, second])["warnings"]
        if w["kind"] == "difference"
    )
    assert "changed prompt positions: 4" in warning["message"]
    assert warning["value"][3] == "Different fourth prompt"
    assert "TTFT cold (s)" not in warning["metrics"]
    assert "TTFT cached (s)" not in warning["metrics"]


def test_cache_run_warning_only_applies_to_cached_ttft(tmp_path):
    first = write_result(tmp_path / "first.json")
    second = write_result(
        tmp_path / "second.json",
        mutate=lambda d: d["meta"].update(cached_ttft_warning=True),
    )
    warning = next(
        w
        for w in compare_results([first, second])["warnings"]
        if w["kind"] == "run_warning"
    )
    assert warning["field"] == "meta.cached_ttft_warning"
    assert warning["metrics"] == ("TTFT cached (s)",)
    assert warning["baseline_value"] is False
    assert warning["value"] is True


@pytest.mark.parametrize(
    "left,right,status,reason",
    [
        ("usage.completion_tokens", "usage.completion_tokens", "descriptive", None),
        ("word_fallback", "word_fallback", "estimated", None),
        ("usage.completion_tokens", "word_fallback", "unavailable", "different units"),
        ("word_fallback", "usage.completion_tokens", "unavailable", "different units"),
        ("mixed", "usage.completion_tokens", "unavailable", "mixed"),
        ("usage.completion_tokens", "mixed", "unavailable", "mixed"),
        ("mixed", "word_fallback", "unavailable", "mixed"),
        ("word_fallback", "mixed", "unavailable", "mixed"),
        ("mixed", "mixed", "unavailable", "mixed"),
    ],
)
def test_throughput_delta_token_units_do_not_affect_ttft_or_ram(
    tmp_path, left, right, status, reason
):
    first = write_result(
        tmp_path / "first.json",
        tps=20,
        ram_delta=2,
        mutate=lambda d: d["metrics"].update(token_count_source=left),
    )
    second = write_result(
        tmp_path / "second.json",
        tps=24,
        ram_delta=3,
        mutate=lambda d: d["metrics"].update(token_count_source=right),
    )
    report = compare_results([first, second])
    for row in report["rows"][:2]:
        assert row["values"][1] is not None
        assert row["delta_status"][1] == status
        if reason is None:
            assert row["deltas_percent"][1] is not None
            assert row["delta_reasons"][1] is None
        else:
            assert row["deltas_percent"][1] is None
            assert reason in row["delta_reasons"][1]
    assert report["rows"][0]["deltas_percent"][1] == (20 if reason is None else None)
    for row in report["rows"][2:]:
        assert row["deltas_percent"][1] is not None
        assert row["delta_status"][1] == "descriptive"
    provenance = [
        w for w in report["warnings"] if w["field"] == "metrics.token_count_source"
    ]
    assert bool(provenance) == (left != right)
    assert all(w["metrics"] == ("Request tok/s", "Decode tok/s") for w in provenance)


def test_absence_and_unknown_values_are_incomplete_even_on_both_sides(tmp_path):
    def mutate(data):
        data["model"].update(reference_url=None, format=None, quantization="unknown")
        data["engine"]["version"] = "unknown"

    first = write_result(tmp_path / "first.json", mutate=mutate)
    second = write_result(tmp_path / "second.json", mutate=mutate)
    warnings = compare_results([first, second])["warnings"]
    for field in (
        "model.reference_url",
        "model.format",
        "model.quantization",
        "engine.version",
    ):
        warning = next(w for w in warnings if w["field"] == field)
        assert warning["kind"] == "incomplete"
    assert not any(w["kind"] == "difference" for w in warnings)


def test_engine_version_changes_remain_visible_without_a_difference_warning(tmp_path):
    first = write_result(tmp_path / "first.json")
    second = write_result(
        tmp_path / "second.json", mutate=lambda d: d["engine"].update(version="0.4.0")
    )
    report = compare_results([first, second])
    assert report["columns"][1]["engine_version"] == "0.4.0"
    assert not any(w["field"] == "engine.version" for w in report["warnings"])


def test_omitted_optional_phase_fields_are_not_inferred_as_defaults(tmp_path):
    def mutate(data):
        phase = data["meta"]["benchmark_protocol"]["throughput"]
        for field in ("requested_min_tokens", "request_mode", "stream_usage_requested"):
            phase.pop(field)

    first = write_result(tmp_path / "first.json", mutate=mutate)
    second = write_result(tmp_path / "second.json", mutate=mutate)
    warnings = compare_results([first, second])["warnings"]
    for field in ("requested_min_tokens", "request_mode", "stream_usage_requested"):
        warning = next(
            w for w in warnings if w["field"].endswith(f"throughput.{field}")
        )
        assert warning["kind"] == "incomplete"


def test_explicit_null_minimum_and_false_usage_option_are_known_settings(tmp_path):
    first = write_result(tmp_path / "first.json")
    second = write_result(tmp_path / "second.json")
    warnings = compare_results([first, second])["warnings"]
    assert not any(
        w["field"].endswith(("requested_min_tokens", "stream_usage_requested"))
        for w in warnings
    )


def test_an_explicit_minimum_differs_from_no_minimum(tmp_path):
    first = write_result(tmp_path / "first.json")
    second = write_result(
        tmp_path / "second.json",
        mutate=lambda d: change_field(
            d, ("meta", "benchmark_protocol", "throughput", "requested_min_tokens"), 80
        ),
    )
    warning = next(
        w
        for w in compare_results([first, second])["warnings"]
        if w["kind"] == "difference"
    )
    assert warning["field"].endswith("throughput.requested_min_tokens")
    assert warning["baseline_value"] is None
    assert warning["value"] == 80


def test_missing_metric_and_zero_reference_explain_unavailable_deltas(tmp_path):
    def mutate(data):
        data["trials"]["ttft_cold_raw"] = [0] * data["trials"]["count"]
        data["metrics"]["ttft_cold"] = compute_stats(data["trials"]["ttft_cold_raw"])

    first = write_result(tmp_path / "first.json", decode_tps=False, mutate=mutate)
    second = write_result(tmp_path / "second.json")
    rows = {r["label"]: r for r in compare_results([first, second])["rows"]}
    assert rows["Decode tok/s"]["delta_status"][1] == "unavailable"
    assert "missing" in rows["Decode tok/s"]["delta_reasons"][1]
    assert rows["TTFT cold (s)"]["deltas_percent"] == [None, None]
    assert rows["TTFT cold (s)"]["delta_reasons"][1] == "reference value is zero"


def test_api_cache_evidence_is_not_inferred_from_matching_false_flags(tmp_path):
    first = write_result(tmp_path / "first.json")
    second = write_result(tmp_path / "second.json")
    warning = next(
        w
        for w in compare_results([first, second])["warnings"]
        if w["field"] == "meta.cache_validation.cached_prefix_hit_verified"
    )
    assert warning["kind"] == "incomplete"
    assert warning["metrics"] == ("TTFT cached (s)",)


def test_identical_complete_metadata_does_not_need_a_warning(tmp_path):
    def mutate(data):
        data["model"]["format"] = "safetensors"
        data["meta"]["cache_validation"] = {
            "source": "engine_cache_api",
            "cold_cache_cleared": True,
            "cached_prefix_hit_verified": True,
        }
        for phase in data["meta"]["benchmark_protocol"].values():
            if isinstance(phase, dict):
                phase["input_tokens"] = [20] * len(phase["prompts"])
                phase["input_token_count_source"] = "engine"

    first = write_result(tmp_path / "first.json", mutate=mutate)
    second = write_result(tmp_path / "second.json", mutate=mutate)
    report = compare_results([first, second])
    assert report["warnings"] == []
    assert all(
        row["delta_status"][1] == "descriptive"
        for row in report["rows"]
        if row["values"][1] is not None
    )


@pytest.mark.parametrize("cache", [None, {}])
def test_missing_cache_fields_are_incomplete_even_after_schema_defaults(
    tmp_path, cache
):
    first = write_result(
        tmp_path / "first.json",
        mutate=lambda d: d["meta"].update(cache_validation=cache),
    )
    second = write_result(
        tmp_path / "second.json",
        mutate=lambda d: d["meta"].update(cache_validation=cache),
    )
    warnings = [
        w
        for w in compare_results([first, second])["warnings"]
        if "cache_validation" in w["field"]
    ]
    assert warnings
    assert all(w["kind"] == "incomplete" for w in warnings)
    assert all(w["baseline_value"] is None and w["value"] is None for w in warnings)


def test_cache_clearing_evidence_only_affects_cold_ttft(tmp_path):
    first = write_result(tmp_path / "first.json")
    second = write_result(
        tmp_path / "second.json",
        mutate=lambda d: d["meta"].update(
            cache_validation={
                "source": "engine_cache_api",
                "cold_cache_cleared": True,
                "cached_prefix_hit_verified": True,
            }
        ),
    )
    warnings = compare_results([first, second])["warnings"]
    cleared = next(w for w in warnings if w["field"].endswith("cold_cache_cleared"))
    assert cleared["kind"] == "difference"
    assert cleared["metrics"] == ("TTFT cold (s)",)
    source = next(w for w in warnings if w["field"] == "meta.cache_validation.source")
    assert source["metrics"] == ("TTFT cold (s)", "TTFT cached (s)")


def test_input_token_provenance_is_compared_only_with_available_counts(tmp_path):
    def mutate(data, source):
        phase = data["meta"]["benchmark_protocol"]["throughput"]
        phase["input_tokens"] = [20] * len(phase["prompts"])
        phase["input_token_count_source"] = source

    first = write_result(tmp_path / "first.json", mutate=lambda d: mutate(d, "engine"))
    second = write_result(
        tmp_path / "second.json", mutate=lambda d: mutate(d, "estimated")
    )
    warnings = compare_results([first, second])["warnings"]
    source = next(
        w
        for w in warnings
        if w["field"].endswith("throughput.input_token_count_source")
    )
    assert source["kind"] == "difference"
    assert "TTFT cold (s)" not in source["metrics"]
    assert not any(w["field"].endswith("throughput.input_tokens") for w in warnings)


@pytest.mark.parametrize(
    "left,right,kinds",
    [
        ([20, None, 22, 23, 24], [20, None, 22, 23, 24], {"incomplete"}),
        ([20, None, 22, 23, 24], [20, 21, 22, 23, 24], {"incomplete"}),
        ([20, None, 22, 23, 24], [21, None, 22, 23, 24], {"incomplete", "difference"}),
        ([20, 21, 22, 23, 24], [21, 21, 22, 23, 24], {"difference"}),
    ],
)
def test_input_token_comparison_uses_only_mutually_known_counts(tmp_path, left, right, kinds):
    def mutate(data, counts):
        data["meta"]["benchmark_protocol"]["throughput"].update(
            input_tokens=counts, input_token_count_source="engine",
        )

    first = write_result(tmp_path / "first.json", mutate=lambda d: mutate(d, left))
    second = write_result(tmp_path / "second.json", mutate=lambda d: mutate(d, right))
    warnings = [
        w for w in compare_results([first, second])["warnings"]
        if w["field"].endswith("throughput.input_tokens")
    ]
    assert {w["kind"] for w in warnings} == kinds
    assert all(w["baseline_value"] == left and w["value"] == right for w in warnings)
    assert all("TTFT cold (s)" not in w["metrics"] for w in warnings)
    if "difference" in kinds and "incomplete" in kinds:
        assert "prompt positions: 1" in next(w["message"] for w in warnings if w["kind"] == "difference")


@pytest.mark.parametrize(
    "field,metrics",
    [
        (
            "warmup_failures",
            {
                "Request tok/s",
                "Decode tok/s",
                "TTFT cold (s)",
                "TTFT cached (s)",
                "RAM peak (GB)",
                "System RAM rise (GB)",
            },
        ),
        ("sustained_throttling_warning", {"Request tok/s", "Decode tok/s"}),
    ],
)
def test_existing_reference_run_warnings_are_not_lost_when_both_flags_match(
    tmp_path, field, metrics
):
    first = write_result(
        tmp_path / "first.json", mutate=lambda d: d["meta"].update({field: 1})
    )
    second = write_result(
        tmp_path / "second.json", mutate=lambda d: d["meta"].update({field: 1})
    )
    warning = next(
        w
        for w in compare_results([first, second])["warnings"]
        if w["field"] == f"meta.{field}"
    )
    assert warning["kind"] == "run_warning"
    assert set(warning["metrics"]) == metrics
