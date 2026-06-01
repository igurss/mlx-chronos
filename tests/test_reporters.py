import json
import copy
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
    assert "**Timestamp:** 2026-05-23T15:08:36Z" in content
    assert "**Chronos version:** 0.1.0" in content
    assert "**Trials:** 5" in content
    assert "**Token count source:** usage.completion_tokens" in content
    assert "**Thermal state:** unavailable_no_sudo" in content
    assert "**RAM measurement method:** system_fallback" in content
    assert "Apple M2" in content
    assert "## Raw Trials" in content
    assert "**Cold TTFT:** 0.044, 0.066, 0.028, 0.039, 0.03" in content

def test_markdown_reporter_handles_missing_ram_fields(tmp_path):
    result = copy.deepcopy(EXAMPLE_RESULT)
    del result["metrics"]["ram_peak_gb"]
    del result["metrics"]["system_ram_peak_gb"]
    del result["metrics"]["system_ram_peak_percent"]

    output_path = MarkdownReporter().save(result, tmp_path)

    content = output_path.read_text()
    assert "**Peak engine RSS fallback (system RAM):** unknown GB" in content
    assert "**Peak system RAM:** unknown GB (unknown%)" in content
