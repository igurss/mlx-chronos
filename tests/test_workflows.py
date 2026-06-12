import json
from pathlib import Path

from mlx_chronos.constants import (
    DEFAULT_THROUGHPUT_MAX_TOKENS,
    PUBLIC_BASELINE_TRIALS,
    SUSTAINED_THROUGHPUT_MAX_TOKENS,
    SUSTAINED_TRIALS,
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
    assert data["metadata"]["standard_baseline_trials"] == PUBLIC_BASELINE_TRIALS
    assert data["metadata"]["standard_sustained_max_tokens"] == (
        SUSTAINED_THROUGHPUT_MAX_TOKENS
    )
    assert data["metadata"]["standard_sustained_trials"] == SUSTAINED_TRIALS
    assert isinstance(data["results"], list)


def test_protocol_reexports_default_throughput_constant():
    assert PROTOCOL_DEFAULT == DEFAULT_THROUGHPUT_MAX_TOKENS


def test_update_leaderboard_workflow_uses_publishable_result_policy():
    text = workflow_text("update_leaderboard.yml")

    assert "load_publishable_result(path)" in text
    assert "PUBLIC_BASELINE_TRIALS" in text
    assert "SUSTAINED_TRIALS" in text
    assert '"timestamp": meta["timestamp"]' in text
    assert '"protocol_version"' not in text
    assert '"connection_mode"' not in text
    assert '"power_source"' not in text
    assert '"low_power_mode"' not in text
    assert '"notes"' not in text
    assert '"is_standard_throughput_tokens"' not in text
    assert '"throughput_max_tokens"' not in text
    assert '"throughput_min_tokens"' not in text
    assert '"trials": tri["count"]' not in text


def test_result_workflows_use_single_error_handler():
    for name in ("update_leaderboard.yml", "validate_result.yml"):
        text = workflow_text(name)
        assert "import SubmissionError" not in text
        assert "except SubmissionError" not in text


def test_leaderboard_html_does_not_hardcode_standard_token_default():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert "const STANDARD_THROUGHPUT_MAX_TOKENS = 100" not in html
    assert "standardThroughputMaxTokens" in html
    assert "standardBaselineTrials" in html
    assert "standardSustainedMaxTokens" in html
    assert "standardSustainedTrials" in html
    assert "project default trial counts and token bounds" in html
    assert 'fetch(RESULTS_INDEX, { cache: "no-store" })' in html
    assert "baseline 5 trials" in html
    assert "sustained 1 trial" in html
    assert "integrity-sealed" in html
    assert "Standard runs" not in html
    assert "raw-standard" not in html
    assert "compare-standard" not in html
    assert "custom tokens" not in html


def test_leaderboard_html_shows_result_load_errors():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert "resultsLoadError" in html
    assert "Could not load benchmark results from" in html
    assert "catch (error)" in html


def test_leaderboard_tabs_use_hidden_without_inline_display_toggle():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert 'document.getElementById("raw-view").style.display' not in html


def test_leaderboard_has_persistent_theme_toggle():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert 'id="theme-toggle"' in html
    assert 'role="switch"' in html
    assert 'aria-checked="false"' in html
    assert "mlxChronosTheme" in html
    assert "document.documentElement.dataset.theme" in html


def test_leaderboard_column_menu_is_not_clipped_by_panel():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert ".raw-panel {\n      overflow: visible;" in html
    assert "--columns-popover-max-height" in html
    assert "updateColumnPopoverLayout" in html
    assert 'columnsMenu.dataset.openDirection = openUp ? "up" : "down";' in html


def test_leaderboard_compare_recency_uses_full_timestamp():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert "b.timestamp || b.date" in html
    assert "dateFromTimestamp" in html


def test_leaderboard_hides_internal_protocol_and_condition_noise():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert "HTTP mode" not in html
    assert "Protocol" not in html
    assert "Power source" not in html
    assert 'key: "low_power_mode"' not in html
    assert '["Low Power Mode"' not in html
    assert "Notes" not in html
    assert "Max tokens" not in html
    assert "tok/s stddev" in html
    assert "Machine" in html
    assert 'label: "Trials"' not in html
    assert '["Trials"' not in html
    assert "compare-button" not in html
    assert "Conditions" in html
    assert "updateShareUrl" in html


def test_leaderboard_clean_badge_is_not_blocked_by_integrity_badge():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert "const integrityBadges = []" not in html
    assert "return badges.join(\"\")" in html
    assert "no flags" in html
    assert "warmup skipped" not in html
    assert "warmup failure" in html
