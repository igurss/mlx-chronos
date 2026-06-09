import json
from pathlib import Path

from mlx_chronos.protocol import DEFAULT_THROUGHPUT_MAX_TOKENS
from mlx_chronos.constants import SUSTAINED_THROUGHPUT_MAX_TOKENS


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
    assert "validate_publishable_result(result)" in text


def test_leaderboard_index_carries_standard_token_metadata():
    data = json.loads((ROOT / "docs" / "results_index.json").read_text())

    assert data["metadata"]["standard_throughput_max_tokens"] == (
        DEFAULT_THROUGHPUT_MAX_TOKENS
    )
    assert data["metadata"]["standard_sustained_max_tokens"] == (
        SUSTAINED_THROUGHPUT_MAX_TOKENS
    )
    assert isinstance(data["results"], list)


def test_update_leaderboard_workflow_uses_publishable_result_policy():
    assert "validate_publishable_result(result)" in workflow_text(
        "update_leaderboard.yml"
    )


def test_leaderboard_html_does_not_hardcode_standard_token_default():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert "const STANDARD_THROUGHPUT_MAX_TOKENS = 100" not in html
    assert "standardThroughputMaxTokens" in html
    assert "standardSustainedMaxTokens" in html
