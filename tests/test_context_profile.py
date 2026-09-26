import json
import math
from argparse import Namespace
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest

from mlx_chronos.cli import cmd_context
from mlx_chronos.context_profile import (
    CONTEXT_LENGTH_BUCKETS,
    build_context_prompt,
    run_context_profile,
    save_context_reports,
)
from mlx_chronos.measurements import TTFTMeasurement
from mlx_chronos.submit import SubmissionError, load_publishable_result


def test_all_maximum_bucket_trial_pairs_have_unique_early_markers_and_hashes():
    prompts = [
        build_context_prompt(label, target, trial, run_nonce="one-run")
        for label, target in CONTEXT_LENGTH_BUCKETS.items()
        for trial in range(10)
    ]
    assert len(prompts) == 40
    assert len(set(prompts)) == 40
    assert len({prompt.split(" ", 1)[0] for prompt in prompts}) == 40
    for prompt, target in zip(prompts, [v for v in CONTEXT_LENGTH_BUCKETS.values()
                                        for _ in range(10)]):
        assert len(prompt) >= target


def test_prompt_is_reproducible_for_one_identity_and_changes_across_runs():
    a = build_context_prompt("small", 2000, 0, run_nonce="run-a")
    assert a == build_context_prompt("small", 2000, 0, run_nonce="run-a")
    assert a != build_context_prompt("small", 2000, 0, run_nonce="run-b")


@pytest.mark.parametrize("kwargs", [
    {"bucket_label": "unknown"},
    {"target_chars": 0},
    {"target_chars": True},
    {"trial_index": -1},
    {"trial_index": True},
    {"run_nonce": ""},
])
def test_invalid_prompt_arguments_rejected(kwargs):
    values = {"bucket_label": "small", "target_chars": 2000,
              "trial_index": 0, "run_nonce": "test"}
    values.update(kwargs)
    with pytest.raises(ValueError):
        build_context_prompt(**values)


def _engine(measurements):
    engine = MagicMock()
    engine.is_installed.return_value = True
    engine.is_server_running.return_value = True
    engine.validate_model_backend.return_value = {
        "format": "safetensors", "quantization": "4bit",
    }
    engine.http_client.return_value = nullcontext(None)
    engine.get_version.return_value = "test"
    engine.measure_ttft_with_input_tokens.side_effect = measurements
    return engine


def _run(engine, **kwargs):
    with patch("mlx_chronos.context_profile.get_engine", return_value=engine), \
         patch("mlx_chronos.context_profile.sample_matrix_conditions",
               return_value={"thermal_state": "nominal"}), \
         patch("mlx_chronos.context_profile.detect_hardware",
               return_value={"chip": "Apple M", "memory_gb": 8}), \
         patch("mlx_chronos.context_profile.secrets.token_hex", return_value="run12345"):
        return run_context_profile("ollama", "test-model", **kwargs)


def test_profile_keeps_token_counts_aligned_and_mean_only_when_complete():
    engine = _engine([
        TTFTMeasurement(0.2, 510, "engine"),
        TTFTMeasurement(0.3, None, "unavailable"),
        TTFTMeasurement(0.4, 520, "engine"),
    ])
    report = _run(engine, buckets=["small"], trials_per_bucket=3)
    bucket = report["buckets"][0]
    assert bucket["input_tokens_raw"] == [510, None, 520]
    assert bucket["input_tokens_mean"] is None
    assert bucket["input_token_count_source"] == "partial_engine"
    assert bucket["ttft_seconds_raw"] == [0.2, 0.3, 0.4]
    assert len(set(bucket["prompt_sha256"])) == 3
    assert "prefill_tokens_per_second" not in bucket
    assert report["kind"] == "local_context_diagnostic"
    assert "canonical_id" not in report["model"]
    assert engine.measure_ttft_with_input_tokens.call_count == 3
    engine.validate_completion_request.assert_called_once_with("test-model")


def test_profile_maximum_trials_across_all_buckets_never_reuse_prompt():
    engine = _engine([TTFTMeasurement(0.2) for _ in range(40)])
    report = _run(engine, buckets=list(CONTEXT_LENGTH_BUCKETS), trials_per_bucket=10)
    prompts = [call.args[0] for call in engine.measure_ttft_with_input_tokens.call_args_list]
    assert len(prompts) == len(set(prompts)) == 40
    assert len({prompt.split(" ", 1)[0] for prompt in prompts}) == 40
    assert [b["label"] for b in report["buckets"]] == list(CONTEXT_LENGTH_BUCKETS)


@pytest.mark.parametrize("options", [
    {"buckets": []}, {"buckets": ["huge"]}, {"buckets": ["small", "small"]},
    {"trials_per_bucket": 0}, {"trials_per_bucket": 11},
    {"request_timeout_seconds": math.nan}, {"model_name": " "},
])
def test_invalid_options_fail_before_engine_probe(options):
    with patch("mlx_chronos.context_profile.get_engine") as get_engine:
        arguments = {"engine_name": "ollama", "model_name": "model", **options}
        with pytest.raises(ValueError):
            run_context_profile(**arguments)
    get_engine.assert_not_called()


def test_bad_engine_measurement_fails_without_a_report():
    engine = _engine([TTFTMeasurement(math.nan)])
    with pytest.raises(RuntimeError, match="invalid context"):
        _run(engine, buckets=["small"], trials_per_bucket=1)


def test_local_json_and_markdown_are_distinct_and_escape_metadata(tmp_path):
    engine = _engine([TTFTMeasurement(0.2, 500, "engine")])
    report = _run(engine, buckets=["small"], trials_per_bucket=1)
    report["model"]["name"] = '<img src=x onerror="x">'
    paths = save_context_reports(report, tmp_path)
    assert len(paths) == 2
    assert paths[0].stem == paths[1].stem
    assert json.loads(paths[0].read_text())["kind"] == "local_context_diagnostic"
    markdown = paths[1].read_text()
    assert "<img" not in markdown
    assert "&lt;img" in markdown
    with pytest.raises(SubmissionError, match="integrity"):
        load_publishable_result(paths[0])


def test_cli_context_writes_only_local_diagnostics(tmp_path):
    args = Namespace(
        engine="ollama", model="test", quantization=None, model_url=None,
        buckets="small", trials_per_bucket=1, connection_mode="persistent",
        request_timeout_seconds=120, format="json", output_dir=tmp_path,
    )
    report = {
        "kind": "local_context_diagnostic", "timestamp": "2026-09-26T00:00:00Z",
        "engine": {"name": "ollama"}, "model": {"name": "test"},
        "hardware": {"chip": "Apple M"}, "warning": "local only",
        "buckets": [{"label": "small", "prompt_chars_raw": [2000],
                     "trials": 1, "ttft_seconds": {"mean": 0.2, "stddev": 0.0},
                     "input_tokens_mean": None,
                     "input_token_count_source": "unavailable"}],
    }
    with patch("mlx_chronos.cli.run_context_profile", return_value=report) as run:
        cmd_context(args)
    assert run.call_args.kwargs["buckets"] == ["small"]
    assert len(list(tmp_path.glob("context_*.json"))) == 1
