"""Cross-field and monitor regressions absent from nominal benchmark fixtures."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import psutil
import pytest

from mlx_chronos.benchmark import run_benchmark
from mlx_chronos.examples import EXAMPLE_RESULT
from mlx_chronos.integrity import seal_result
from mlx_chronos.leaderboard import _index_row, load_archive_results
from mlx_chronos.measurements import ThroughputMeasurement, validate_throughput_measurement
from mlx_chronos.schema import BenchmarkResult
from mlx_chronos.stats import compute_stats
from mlx_chronos.submit import SubmissionError, submit_result_file, validate_publishable_result
from mlx_chronos.trackers import RAMTracker, SystemRAMTracker, ThermalStateTracker
from mlx_chronos.wizard import RunWizardConfig, build_run_command, validate_run_config
from mlx_chronos.compare import compare_results
from mlx_chronos.reporters import MarkdownReporter


def test_unavailable_thermal_samples_are_errors_and_not_valid_samples():
    values = iter(["nominal", None, "nominal", "nominal"])
    tracker = ThermalStateTracker(sampler=lambda: next(values))
    for _ in range(3):
        tracker._record_sample()
    summary = tracker.stop()
    assert summary["samples"] == 3
    assert summary["sampling_errors"] == 1
    data = deepcopy(EXAMPLE_RESULT)
    data["meta"]["thermal_monitor"] = summary
    with pytest.raises(SubmissionError, match="error-free thermal"):
        validate_publishable_result(BenchmarkResult.model_validate(seal_result(data)))


@pytest.mark.parametrize("gap", [None, 10])
def test_current_public_protocol_requires_bounded_thermal_gaps(gap):
    data = deepcopy(EXAMPLE_RESULT)
    data["meta"]["thermal_monitor"]["max_sample_gap_seconds"] = gap
    with pytest.raises(SubmissionError, match="complete thermal"):
        validate_publishable_result(BenchmarkResult.model_validate(seal_result(data)))


def test_access_denied_child_marks_the_rss_sample_incomplete():
    child = SimpleNamespace(memory_info=lambda: (_ for _ in ()).throw(psutil.AccessDenied(123)))
    parent = SimpleNamespace(children=lambda **_: [child], memory_info=lambda: SimpleNamespace(rss=1024))
    with patch("mlx_chronos.trackers.psutil.Process", return_value=parent):
        tracker = RAMTracker()
        assert tracker._sample_rss() == 1024
        assert tracker.sample_errors == 1


def test_access_denied_child_enumeration_is_reported():
    parent = SimpleNamespace(children=lambda **_: (_ for _ in ()).throw(psutil.AccessDenied(123)),
                             memory_info=lambda: SimpleNamespace(rss=1024))
    with patch("mlx_chronos.trackers.psutil.Process", return_value=parent):
        tracker = RAMTracker()
        tracker._sample_rss()
        assert tracker.sample_errors == 1


def test_incomplete_swap_observation_does_not_claim_zero_growth():
    tracker = SystemRAMTracker()
    with patch.object(tracker, "_sample_system_ram", return_value=(100, 10, 1000)), \
         patch.object(tracker, "_sample_swap_used", side_effect=[0, None, 0]):
        for _ in range(3):
            tracker._record_sample()
    assert tracker.occupancy_summary()["swap_growth_gb"] is None


@pytest.mark.parametrize("excess", [0.01, 100])
def test_decode_interval_cannot_exceed_its_request(excess):
    data = deepcopy(EXAMPLE_RESULT)
    elapsed = [e + excess for e in data["trials"]["throughput_elapsed_seconds_raw"]]
    tps = [round((n - 1) / e, 2) for n, e in zip(data["trials"]["completion_tokens_raw"], elapsed)]
    data["trials"]["decode_elapsed_seconds_raw"] = elapsed
    data["trials"]["decode_tokens_per_second_raw"] = tps
    data["metrics"]["decode_tokens_per_second"] = compute_stats(tps)
    with pytest.raises(ValueError, match="cannot exceed request"):
        BenchmarkResult.model_validate(data)


@pytest.mark.parametrize("excess", [0, 0.0009])
def test_decode_interval_accepts_equal_or_millisecond_rounded_durations(excess):
    data = deepcopy(EXAMPLE_RESULT)
    elapsed = [e + excess for e in data["trials"]["throughput_elapsed_seconds_raw"]]
    tokens = data["trials"]["completion_tokens_raw"]
    tps = [round((n - 1) / e, 2) for n, e in zip(tokens, elapsed)]
    data["trials"]["decode_elapsed_seconds_raw"] = elapsed
    data["trials"]["decode_tokens_per_second_raw"] = tps
    data["metrics"]["decode_tokens_per_second"] = compute_stats(tps)
    BenchmarkResult.model_validate(data)
    validate_throughput_measurement(ThroughputMeasurement(
        request_tokens_per_second=data["trials"]["tokens_per_second_raw"][0],
        completion_tokens=tokens[0], token_count_source="usage.completion_tokens",
        elapsed_seconds=data["trials"]["throughput_elapsed_seconds_raw"][0],
        decode_tokens_per_second=tps[0], decode_elapsed_seconds=elapsed[0],
        decode_timing_source="client_stream",
    ))


@pytest.mark.parametrize("change", [
    {"completion_tokens": 100000, "request_tokens_per_second": 100000},
    {"request_tokens_per_second": 99},
    {"token_count_source": "usage"},
    {"token_count_source": []},
    {"decode_tokens_per_second": 2, "decode_elapsed_seconds": 10, "decode_timing_source": "client_stream"},
])
def test_shared_measurement_validation_rejects_inconsistent_data(change):
    value = replace(ThroughputMeasurement(60, 60, "usage.completion_tokens", 1), **change)
    with pytest.raises(RuntimeError):
        validate_throughput_measurement(value, max_tokens=60)


@pytest.mark.parametrize("invalid", [{"submitted_by": "bad/handle"}, {"model_quantization": "  "}])
def test_invalid_static_metadata_causes_zero_engine_requests(invalid):
    kwargs = dict(engine_name="omlx", model_name="fake", model_quantization="4bit")
    kwargs.update(invalid)
    with patch("mlx_chronos.benchmark.get_engine") as engine:
        with pytest.raises(ValueError):
            run_benchmark(**kwargs)
    engine.assert_not_called()


def test_wizard_validates_attribution_and_protects_leading_dash_values():
    assert any("GitHub handle" in e for e in validate_run_config(RunWizardConfig(model="fake", submitted_by="bad/handle")))
    import shlex
    from mlx_chronos.cli import main
    command = build_run_command(RunWizardConfig(model="--model-value", notes="--notes-value"))
    with patch("sys.argv", shlex.split(command)), patch("mlx_chronos.cli.cmd_run") as run:
        main()
    assert run.call_args.args[0].model == "--model-value"
    assert run.call_args.args[0].notes == "--notes-value"


def test_index_retains_worst_thermal_state_and_quality():
    data = deepcopy(EXAMPLE_RESULT)
    data["meta"]["thermal_monitor"].update(end_state="serious", worst_state="serious",
        non_nominal_observed=True, changed_during_run=True, non_nominal_phases=["throughput"])
    row = _index_row(BenchmarkResult.model_validate(data))
    assert row["thermal_state"] == "nominal"
    assert row["thermal_worst_state"] == "serious"
    assert row["thermal_non_nominal_phases"] == ["throughput"]
    assert row["protocol_version"] == "5"


def test_archived_protocol_loads_but_cannot_be_submitted_as_current(tmp_path):
    import json
    data = deepcopy(EXAMPLE_RESULT)
    data["meta"]["benchmark_protocol"]["version"] = "3"
    data["meta"]["thermal_monitor"].pop("max_sample_gap_seconds")
    (tmp_path / "old.json").write_text(json.dumps(seal_result(data)))
    assert len(load_archive_results(tmp_path)) == 1
    with pytest.raises(SubmissionError, match="current internal protocol"):
        validate_publishable_result(BenchmarkResult.model_validate(data))


@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.WriteTimeout, httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError])
def test_ambiguous_post_failure_is_never_retried(failure, tmp_path):
    result = BenchmarkResult.model_validate(EXAMPLE_RESULT)
    with patch("mlx_chronos.submit.httpx.post", side_effect=failure("receipt unknown")) as post:
        with pytest.raises(SubmissionError, match="outcome is unknown"):
            submit_result_file(tmp_path / "fake.json", "https://example.test/form",
                               raw=b"{}", result=result)
    assert post.call_count == 1


def test_legacy_missing_thermal_error_counter_stays_unknown_in_index():
    data = deepcopy(EXAMPLE_RESULT)
    data["meta"]["thermal_monitor"].pop("sampling_errors")
    row = _index_row(BenchmarkResult.model_validate(data))
    assert row["thermal_sampling_errors"] is None


@pytest.mark.parametrize('span,samples', [(1.0, 2), (38.0, 2), (None, 40)])
def test_public_thermal_trace_must_cover_measured_phases(span, samples):
    data = deepcopy(EXAMPLE_RESULT)
    data['meta']['thermal_monitor'].update(sample_span_seconds=span, samples=samples)
    with pytest.raises(SubmissionError, match='thermal sampling covering'):
        validate_publishable_result(BenchmarkResult.model_validate(data))


@pytest.mark.parametrize('count', ['100', 100.0, True])
def test_exact_completion_counts_are_strict_in_saved_results(count):
    data = deepcopy(EXAMPLE_RESULT)
    data['trials']['completion_tokens_raw'][0] = count
    with pytest.raises(ValueError, match='completion_tokens_raw'):
        BenchmarkResult.model_validate(data)


def test_progress_cannot_escape_or_reverse_trial_time():
    data = deepcopy(EXAMPLE_RESULT)
    elapsed = data['trials']['throughput_elapsed_seconds_raw'][0]
    data['trials']['throughput_progress_samples_raw'] = [[
        {'completion_tokens': 50, 'elapsed_seconds': 50., 'tokens_per_second': 1., 'token_count_source': 'word_fallback'},
        {'completion_tokens': 100, 'elapsed_seconds': elapsed, 'tokens_per_second': round(100 / elapsed, 2), 'token_count_source': 'usage.completion_tokens'},
    ], [], [], [], []]
    with pytest.raises(ValueError, match='exceeds trial duration'):
        BenchmarkResult.model_validate(data)


@pytest.mark.parametrize('version', ['3', '4'])
def test_legacy_progress_anomaly_stays_readable_without_changing_sealed_data(tmp_path, version):
    import json
    # Old timing could produce [t1, t3, t2] when the terminal event also
    # crossed a progress threshold. The final observation itself is correct.
    data = deepcopy(EXAMPLE_RESULT)
    data['meta']['benchmark_protocol']['version'] = version
    data['meta']['sustained_throttling_warning'] = True
    elapsed = data['trials']['throughput_elapsed_seconds_raw'][0]
    data['trials']['throughput_progress_samples_raw'] = [[
        {'completion_tokens': 50, 'elapsed_seconds': elapsed + .01,
         'tokens_per_second': round(50 / (elapsed + .01), 2), 'token_count_source': 'word_fallback'},
        {'completion_tokens': 100, 'elapsed_seconds': elapsed,
         'tokens_per_second': round(100 / elapsed, 2), 'token_count_source': 'usage.completion_tokens'},
    ], [], [], [], []]
    data = seal_result(data)
    original = json.dumps(data)
    path = tmp_path / 'historical.json'
    path.write_text(original)
    parsed = BenchmarkResult.model_validate(data)
    assert parsed.progress_chronology_issue(0) is not None
    reference = tmp_path / 'reference.json'
    reference.write_text(json.dumps(seal_result(deepcopy(EXAMPLE_RESULT))))
    report = compare_results([reference, path])
    assert any(w['field'] == 'trials.throughput_progress_samples_raw' for w in report['warnings'])
    markdown = MarkdownReporter().save(data, tmp_path).read_text()
    assert 'legacy progress has inconsistent chronology' in markdown
    assert 'Raw samples remain in JSON' in markdown
    assert 'recorded sustained warning is unverified' in markdown
    assert 'degradation with a thermal-state signal' not in markdown
    row = _index_row(parsed)
    assert row['sustained_throttling_warning'] is False
    assert row['progress_chronology_warning'] is True
    assert row['sustained_warning_unverified'] is True
    assert parsed.meta.sustained_throttling_warning is True
    assert path.read_text() == original


def test_published_protocol_four_remains_eligible_during_transition(tmp_path):
    import json
    from mlx_chronos.submit import load_publishable_result
    data = deepcopy(EXAMPLE_RESULT)
    data['meta']['benchmark_protocol']['version'] = '4'
    data['engine'].pop('version_source')
    data['engine'].pop('client_version', None)
    data['meta']['thermal_monitor'].pop('sample_span_seconds')
    data = seal_result(data)
    path = tmp_path / 'published.json'
    path.write_text(json.dumps(data))
    raw, result = load_publishable_result(path)
    assert result.meta.benchmark_protocol.version == '4'
    assert json.loads(raw) == data
    data['meta']['benchmark_protocol']['throughput']['prompts'][0] = 'changed method'
    with pytest.raises(SubmissionError, match='protocol exactly'):
        validate_publishable_result(BenchmarkResult.model_validate(seal_result(data)))


@pytest.mark.parametrize('source', ['client_cli', 'client_package'])
def test_client_version_remains_readable_but_cannot_establish_serving_version(tmp_path, source):
    import json
    data = deepcopy(EXAMPLE_RESULT)
    data['engine'].update(version_source=source, client_version=data['engine']['version'])
    data = seal_result(data)
    result = BenchmarkResult.model_validate(data)
    with pytest.raises(SubmissionError, match='client installation alone is insufficient'):
        validate_publishable_result(result)
    row = _index_row(result)
    assert row['engine_version_source'] == source
    assert row['engine_client_version'] == result.engine.version
    assert 'serving version is unverified' in MarkdownReporter().save(data, tmp_path).read_text()
    path = tmp_path / 'local-version.json'
    path.write_text(json.dumps(data))
    reference = tmp_path / 'reference.json'
    reference.write_text(json.dumps(seal_result(deepcopy(EXAMPLE_RESULT))))
    assert any(w['field'] == 'engine.version_source' for w in compare_results([reference, path])['warnings'])
    data['engine']['client_version'] = 'different'
    with pytest.raises(SubmissionError, match='client installation alone is insufficient'):
        validate_publishable_result(BenchmarkResult.model_validate(data))


def test_process_installation_is_publishable_with_explicit_indirect_evidence(tmp_path):
    import json
    data = deepcopy(EXAMPLE_RESULT)
    data['engine'].update(version_source='process_package', client_version='9.8.7')
    data = seal_result(data)
    result = BenchmarkResult.model_validate(data)
    validate_publishable_result(result)
    assert _index_row(result)['engine_version_source'] == 'process_package'
    path = tmp_path / 'process-version.json'
    path.write_text(json.dumps(data))
    reference = tmp_path / 'reference.json'
    reference.write_text(json.dumps(seal_result(deepcopy(EXAMPLE_RESULT))))
    assert any(w['field'] == 'engine.version_source' for w in compare_results([reference, path])['warnings'])
    assert 'loaded runtime did not report its version' in MarkdownReporter().save(data, tmp_path).read_text()
