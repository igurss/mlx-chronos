import json
from pathlib import Path

from mlx_chronos.constants import (
    DEFAULT_THROUGHPUT_MAX_TOKENS,
    SUSTAINED_THROUGHPUT_MAX_TOKENS,
)
from mlx_chronos.protocol import DEFAULT_THROUGHPUT_MAX_TOKENS as PROTOCOL_DEFAULT


ROOT = Path(__file__).resolve().parent.parent


def workflow_text(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_tests_workflow_covers_leaderboard_and_python_314():
    text = workflow_text("tests.yml")

    assert "docs/index.html" in text
    assert ".github/workflows/*.yml" in text
    assert "'3.14'" in text
    assert "Validate leaderboard JavaScript syntax" in text


def test_release_workflow_tests_python_314():
    assert "'3.14'" in workflow_text("release.yml")


def test_validate_result_workflow_rejects_mixed_or_deleted_submission_prs():
    text = workflow_text("validate_result.yml")

    assert "must only change JSON files " in text
    assert "under results/submitted/:" in text
    assert "must not delete submitted " in text
    assert "result files:" in text
    assert "load_publishable_result(path)" in text


def test_leaderboard_index_carries_standard_token_metadata():
    data = json.loads((ROOT / "docs" / "results_index.json").read_text())

    assert data["metadata"]["standard_throughput_max_tokens"] == (
        DEFAULT_THROUGHPUT_MAX_TOKENS
    )
    assert data["metadata"]["standard_sustained_max_tokens"] == (
        SUSTAINED_THROUGHPUT_MAX_TOKENS
    )
    assert isinstance(data["results"], list)


def test_protocol_reexports_default_throughput_constant():
    assert PROTOCOL_DEFAULT == DEFAULT_THROUGHPUT_MAX_TOKENS


def test_update_leaderboard_workflow_uses_publishable_result_policy():
    text = workflow_text("update_leaderboard.yml")

    assert "load_publishable_result(path)" in text
    assert '"timestamp": meta["timestamp"]' in text


def test_result_workflows_use_single_error_handler():
    for name in ("update_leaderboard.yml", "validate_result.yml"):
        text = workflow_text(name)
        assert "import SubmissionError" not in text
        assert "except SubmissionError" not in text


def test_leaderboard_html_does_not_hardcode_standard_token_default():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert "const STANDARD_THROUGHPUT_MAX_TOKENS = 100" not in html
    assert "standardThroughputMaxTokens" in html
    assert "standardSustainedMaxTokens" in html
    assert "integrity-sealed" in html


def test_leaderboard_html_shows_result_load_errors():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert "resultsLoadError" in html
    assert "Could not load benchmark results from" in html
    assert "catch (error)" in html


def test_leaderboard_tabs_use_hidden_without_inline_display_toggle():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert 'document.getElementById("raw-view").style.display' not in html


def test_leaderboard_compare_recency_uses_full_timestamp():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert "b.timestamp || b.date" in html


def test_leaderboard_clean_badge_is_not_blocked_by_integrity_badge():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert "const integrityBadges = []" in html
    assert "return integrityBadges.concat(badges).join(\"\")" in html
