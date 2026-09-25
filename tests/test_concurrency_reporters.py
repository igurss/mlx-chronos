import pytest

from mlx_chronos.reporters import (
    ConcurrencyProfileJSONReporter,
    ConcurrencyProfileMarkdownReporter,
)
from mlx_chronos.submit import SubmissionError, load_publishable_result


def test_local_concurrency_reports_share_a_basename_and_cannot_be_submitted(tmp_path):
    report = {
        "timestamp": "2026-09-25T12:00:00.123456+00:00",
        "hardware": {"chip": "Apple M4 Max", "memory_gb": 64},
        "engine": {"name": "vllm-mlx", "version": "1.0"},
        "model": {"name": "Example|Model\n<script>alert(1)</script>"},
        "request_max_tokens": 60,
        "levels": [{
            "concurrency": 1,
            "trials": 1,
            "aggregate_tokens_per_second": {"mean": 50, "stddev": 0},
            "per_request_elapsed_seconds": {"mean": 1},
            "waves": [{"cache_clear_confirmed": False,
                       "prefix_cache_hits_delta": None}],
        }],
        "warnings": ["Cache status unknown."],
    }
    json_path = ConcurrencyProfileJSONReporter().save(report, tmp_path)
    markdown_path = ConcurrencyProfileMarkdownReporter().save(report, tmp_path)

    assert json_path.stem == markdown_path.stem
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Example\\|Model" in markdown
    assert "<script>" not in markdown
    assert "## Cautions" in markdown
    assert "cache_clear_confirmed" in json_path.read_text(encoding="utf-8")
    with pytest.raises(SubmissionError):
        load_publishable_result(json_path)
