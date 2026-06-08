from pathlib import Path


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
