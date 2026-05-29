import json
from datetime import datetime, timezone
from pathlib import Path

from mlx_chronos.reporters import JSONReporter, MarkdownReporter, BaseReporter
from mlx_chronos.schema import EXAMPLE_RESULT

class DummyReporter(BaseReporter):
    def save(self, result: dict, results_dir: Path) -> Path:
        return results_dir / "dummy"

def test_base_reporter_slug():
    reporter = DummyReporter()
    assert reporter._slug("Apple M2") == "apple_m2"
    assert reporter._slug("Qwen3.5-4B-OptiQ") == "qwen3_5_4b_optiq"
    assert reporter._slug("  ") == "unknown"
    assert reporter._slug("!@#") == "unknown"

def test_generate_base_filename_string_timestamp():
    reporter = DummyReporter()
    result = {
        "hardware": {"chip": "M1"},
        "engine": {"name": "omlx"},
        "meta": {"timestamp": "2026-05-28T10:00:00Z"}
    }
    assert reporter._generate_base_filename(result) == "omlx_m1_20260528_100000"

def test_generate_base_filename_datetime_timestamp():
    reporter = DummyReporter()
    result = {
        "hardware": {"chip": "M1"},
        "engine": {"name": "omlx"},
        "meta": {"timestamp": datetime(2026, 5, 28, 10, 0, 0, tzinfo=timezone.utc)}
    }
    assert reporter._generate_base_filename(result) == "omlx_m1_20260528_100000"

def test_json_reporter_save(tmp_path):
    reporter = JSONReporter()
    output_path = reporter.save(EXAMPLE_RESULT, tmp_path)
    assert output_path.exists()
    assert output_path.suffix == ".json"

    with open(output_path) as f:
        data = json.load(f)
    assert data["engine"]["name"] == "omlx"

def test_markdown_reporter_save(tmp_path):
    reporter = MarkdownReporter()
    output_path = reporter.save(EXAMPLE_RESULT, tmp_path)
    assert output_path.exists()
    assert output_path.suffix == ".md"

    content = output_path.read_text()
    assert "# mlx-chronos Benchmark Result" in content
    assert "**Engine:** omlx" in content
    assert "Apple M2" in content
