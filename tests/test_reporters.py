import json
import copy
from datetime import datetime, timezone
from pathlib import Path

from mlx_chronos.reporters import JSONReporter, MarkdownReporter, BaseReporter
from mlx_chronos.examples import EXAMPLE_RESULT

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
    assert "**Timestamp:** 2026-06-05T12:00:00Z" in content
    assert "**Chronos version:** 0.1.2" in content
    assert "**Profile:** baseline" in content
    assert "**Trials:** 5" in content
    assert "**Token count source:** usage.completion_tokens" in content
    assert "**Protocol:** baseline v2" in content
    assert "**Throughput token bounds:** max 100, min none" in content
    assert "**Total runtime:** 38.1 s" in content
    assert content.count("**Total runtime:**") == 1
    assert "**Request throughput:** 18.44 tokens/s" in content
    assert "**Decode throughput:** 18.654 tokens/s" in content
    assert "**Decode timing source:** client_stream" in content
    assert "**Thermal state:** unavailable_permission" in content
    assert "**Power source:** ac_power" in content
    assert "**Low Power Mode:** off" in content
    assert "min 18.27, max 18.51" in content
    assert "## Thermal Monitor" in content
    assert "**Source:** unavailable" in content
    assert "**Sample interval:** 1.0 s" in content
    assert "**State:** unavailable_foundation -> unavailable_foundation" in content
    assert "## Phase Timings" in content
    assert "**Throughput:** 27.104 s" in content
    assert "**RAM measurement method:** system_fallback" in content
    assert "Apple M2" in content
    assert "## Raw Trials" in content
    assert "**Cold TTFT:** 0.044, 0.066, 0.028, 0.039, 0.03" in content
    assert "**Throughput elapsed seconds:** 5.411, 5.473, 5.402, 5.411, 5.417" in content
    assert "**Decode throughput:** 18.7, 18.49, 18.73, 18.69, 18.66" in content
    assert "**Completion tokens:** 100, 100, 100, 100, 100" in content

def test_markdown_reporter_handles_missing_ram_fields(tmp_path):
    result = copy.deepcopy(EXAMPLE_RESULT)
    del result["metrics"]["ram_peak_gb"]
    del result["metrics"]["system_ram_peak_gb"]
    del result["metrics"]["system_ram_peak_percent"]

    output_path = MarkdownReporter().save(result, tmp_path)

    content = output_path.read_text()
    assert "**Post-warmup engine RSS fallback (system RAM):** unknown GB" in content
    assert "**Peak system RAM:** unknown GB (unknown%)" in content
