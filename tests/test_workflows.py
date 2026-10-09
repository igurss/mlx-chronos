import json
from pathlib import Path
import re

import pytest

from mlx_chronos.constants import (
    DEFAULT_THROUGHPUT_MAX_TOKENS,
    PUBLIC_BASELINE_TRIALS,
    PUBLIC_MIN_COMPLETION_TOKEN_RATIO,
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
    assert text.count("README.md") == 2
    assert "'3.14'" in text
    assert "Validate leaderboard JavaScript syntax" in text
    assert "node --test tests/frontend.test.cjs" in text
    assert "ruff check mlx_chronos tests" in text
    assert "mypy" in text
    assert "pytest --cov" in text
    assert "python .github/scripts/check_leaderboard.py" in text
    assert "python -m mlx_chronos.detect" not in text
    assert "detect_hardware" in text


def test_release_workflow_runs_full_quality_gates():
    text = workflow_text("release.yml")

    assert "'3.14'" in text
    assert "Validate leaderboard JavaScript syntax" in text
    assert "node --test tests/frontend.test.cjs" in text
    assert "ruff check mlx_chronos tests" in text
    assert "mypy" in text
    assert "pytest --cov" in text
    assert "python -m mlx_chronos.leaderboard --check" in text
    assert "python -m twine check --strict dist/*" in text
    assert "needs: [test, quality]" in text


def test_release_manual_runs_validate_artifacts_without_publishing():
    text = workflow_text("release.yml")
    assert "workflow_dispatch:" in text
    install = text.split("  install:\n", 1)[1].split("  publish:\n", 1)[0]
    publish = text.split("  publish:\n", 1)[1]

    assert "needs: build" in install
    assert "distribution: [wheel, sdist]" in install
    assert "actions/download-artifact@" in install
    assert "actions/checkout@" not in install
    assert "python -m venv installed" in install
    assert "installed/bin/python -m pip check" in install
    assert "needs: install" in publish
    assert (
        "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')"
        in publish
    )
    # Only the guarded publisher can request an identity token from GitHub.
    assert text.count("id-token: write") == 1
    assert "id-token: write" in publish


def test_validate_result_workflow_rejects_mixed_or_deleted_submission_prs():
    text = workflow_text("validate_result.yml")

    assert "must only change JSON files " in text
    assert "under results/submitted/:" in text
    assert "must not delete submitted " in text
    assert "result files:" in text
    assert "load_publishable_result(path)" in text
    assert "load_archive_results" in text
    assert '"results/submitted",' not in text


def test_validate_result_workflow_checks_scope_before_running_pr_code():
    text = workflow_text("validate_result.yml")

    scope_step = text.index("- name: Check pull request scope")
    install_step = text.index("- name: Install package and dependencies")
    validate_step = text.index("- name: Validate submitted results")

    # `pip install .` executes the pull request's own build backend, so the
    # scope check has to gate it rather than run after it.
    assert scope_step < install_step < validate_step
    assert "if: steps.scope.outputs.changed_count != '0'" in text
    assert "changed_count=${count}" in text


def test_leaderboard_html_has_a_description_and_og_tags():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert '<meta name="description"' in html
    assert 'property="og:title"' in html
    assert 'property="og:description"' in html
    assert 'name="twitter:card"' in html
    assert 'rel="icon"' in html


def test_leaderboard_html_has_csv_and_json_export_controls():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert 'id="export-csv"' in html
    assert 'id="export-json"' in html
    assert "function buildCsvExport" in html
    assert "function buildJsonExport" in html


def test_leaderboard_html_has_a_compare_chart():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert 'id="compare-chart-wrap"' in html
    assert "function buildCompareChartMarkup" in html
    assert "renderCompareChart(representatives)" in html


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
    assert data["metadata"]["minimum_completion_token_ratio"] == (
        PUBLIC_MIN_COMPLETION_TOKEN_RATIO
    )
    assert isinstance(data["results"], list)


def test_protocol_reexports_default_throughput_constant():
    assert PROTOCOL_DEFAULT == DEFAULT_THROUGHPUT_MAX_TOKENS


def test_readme_lists_every_default_engine_port():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    from mlx_chronos.engines import ENGINES
    labels = {"omlx": "oMLX", "rapid-mlx": "Rapid-MLX", "ollama": "Ollama", "lmstudio": "LM Studio"}
    for name, adapter in ENGINES.items():
        assert f"| {labels.get(name, name)} | `{adapter.default_port}` |" in readme


def test_readme_current_release_matches_pyproject_version():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project_version = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
    readme_version = re.search(
        r"### Current Release\n\n`([^`]+)`",
        readme,
    )

    assert project_version is not None
    assert readme_version is not None
    assert readme_version.group(1) == project_version.group(1)


def test_update_leaderboard_workflow_uses_publishable_result_policy():
    text = workflow_text("update_leaderboard.yml")
    script = (ROOT / ".github" / "scripts" / "update_leaderboard_index.sh").read_text()

    assert "bash .github/scripts/update_leaderboard_index.sh" in text
    assert "python -m mlx_chronos.leaderboard" in script
    assert "git fetch --no-tags origin refs/heads/main" in script
    assert "git push origin HEAD:refs/heads/main" in script
    assert "python - <<'EOF'" not in text


def test_update_leaderboard_requests_pages_build_after_bot_push():
    text = workflow_text("update_leaderboard.yml")

    assert "pages: write" in text
    assert "GH_TOKEN: ${{ github.token }}" in text
    assert 'gh api --method POST "repos/${GITHUB_REPOSITORY}/pages/builds"' in text
    assert text.index("bash .github/scripts/update_leaderboard_index.sh") < text.index(
        "gh api --method POST"
    )


def test_result_workflows_use_single_error_handler():
    for name in ("update_leaderboard.yml", "validate_result.yml"):
        text = workflow_text(name)
        assert "import SubmissionError" not in text
        assert "except SubmissionError" not in text


def test_library_modules_do_not_expose_debug_main_blocks():
    for path in (
        ROOT / "mlx_chronos" / "benchmark.py",
        ROOT / "mlx_chronos" / "detect.py",
        ROOT / "mlx_chronos" / "engines.py",
        ROOT / "mlx_chronos" / "schema.py",
    ):
        assert 'if __name__ == "__main__"' not in path.read_text(encoding="utf-8")


def test_leaderboard_html_does_not_hardcode_standard_token_default():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert "const STANDARD_THROUGHPUT_MAX_TOKENS = 100" not in html
    assert "standardThroughputMaxTokens" in html
    assert "standardBaselineTrials" in html
    assert "standardSustainedMaxTokens" in html
    assert "standardSustainedTrials" in html
    assert "minimumCompletionTokenRatio" in html
    assert "model_reference_url" in html
    assert "Model format" in html
    assert "Model reference" in html
    for removed_field in (
        "model_source",
        "model_revision",
        "model_weight_hash",
        "model_tokenizer_hash",
        "model_chat_template_hash",
        "model_architecture",
        "model_family",
        "model_parameter_size",
        "Model source",
        "Model revision",
        "Model family",
        "Parameter size",
    ):
        assert removed_field not in html
    assert "macos_version" in html
    assert "warmup failures=0" in html
    assert "project default trial counts, token bounds, and warmup policy" in html
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
    css = (ROOT / "docs" / "leaderboard.css").read_text(encoding="utf-8")

    assert 'href="leaderboard.css"' in html
    assert re.search(r"\.raw-panel\s*\{[^}]*overflow:\s*visible\s*;", css)
    assert "--columns-popover-max-height" in css
    assert "updateColumnPopoverLayout" in html
    assert 'columnsMenu.dataset.openDirection = openUp ? "up" : "down";' in html


def test_leaderboard_compare_recency_uses_full_timestamp():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert "b.timestamp || b.date" in html
    assert "dateFromTimestamp" in html


def test_leaderboard_compare_sorts_consistently_by_request_tps():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert "primaryThroughput" not in html
    assert "numericSortValue(b.tps) - numericSortValue(a.tps)" in html
    # The ranked column comes first and carries the emphasis; decode throughput
    # must never be the emphasised column while the table is ranked by request
    # throughput.
    assert "<th>Request tok/s</th>\n                <th>Decode tok/s</th>" in html
    assert '<td><span class="metric-strong">${fmt(row.tps, 2)}</span></td>' in html
    assert 'metric-strong">${fmt(row.decode_tps, 2)}' not in html


def test_leaderboard_keeps_table_focused_and_method_in_details():
    html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert "HTTP mode" not in html
    assert 'key: "protocol_version"' not in html
    assert '["Protocol", row.protocol_version' in html
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


def test_json_only_submission_passes_both_ci_policies(tmp_path):
    import os
    import subprocess
    import sys
    import textwrap
    from copy import deepcopy
    from mlx_chronos.examples import EXAMPLE_RESULT
    from mlx_chronos.integrity import seal_result
    from mlx_chronos.leaderboard import write_results_index

    def git(*args):
        return subprocess.check_output(['git', '-c', 'user.name=Fixture', '-c',
            'user.email=fixture@example.test', *args], cwd=tmp_path, text=True).strip()

    git('init', '-q')
    archive = tmp_path / 'results/submitted'
    archive.mkdir(parents=True)
    output = tmp_path / 'docs/results_index.json'
    output.parent.mkdir()
    (archive / 'one.json').write_text(json.dumps(seal_result(EXAMPLE_RESULT)))
    write_results_index(archive, output)
    git('add', '.')
    git('commit', '-qm', 'initial fixture')
    base = git('rev-parse', 'HEAD')
    second = deepcopy(EXAMPLE_RESULT)
    second['meta']['timestamp'] = '2026-10-04T09:00:00Z'
    (archive / 'two.json').write_text(json.dumps(seal_result(second)))
    git('add', '.')
    git('commit', '-qm', 'new submission')

    workflow = workflow_text('validate_result.yml')
    scope = workflow.split('      - name: Check pull request scope', 1)[1]
    script = textwrap.dedent(scope.split('        run: |\n', 1)[1].split('\n      - name:', 1)[0])
    env = dict(os.environ, TARGET_BRANCH=base, GITHUB_OUTPUT=str(tmp_path / 'output'), INDEX_BASE_SHA=base)
    scope_result = subprocess.run(['bash', '-c', script], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert scope_result.returncode == 0, scope_result.stderr + scope_result.stdout
    quality_script = ROOT / '.github/scripts/check_leaderboard.py'
    quality = subprocess.run([sys.executable, str(quality_script)], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert quality.returncode == 0, quality.stderr
    assert 'generable (2 results)' in quality.stdout
    # Once source/index ownership changes, a stale index must be rejected.
    (tmp_path / 'source.py').write_text('# changed code')
    git('add', 'source.py')
    git('commit', '-qm', 'code change')
    quality = subprocess.run([sys.executable, str(quality_script)], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert quality.returncode != 0 and 'stale' in quality.stderr


@pytest.mark.parametrize('stale_index', [False, True])
def test_index_check_without_previous_commit_keeps_full_validation(tmp_path, stale_index):
    import os
    import subprocess
    import sys
    from copy import deepcopy
    from mlx_chronos.examples import EXAMPLE_RESULT
    from mlx_chronos.integrity import seal_result
    from mlx_chronos.leaderboard import write_results_index

    def git(*args):
        return subprocess.check_output(['git', '-c', 'user.name=Fixture', '-c',
            'user.email=fixture@example.test', *args], cwd=tmp_path, text=True).strip()

    git('init', '-q')
    archive = tmp_path / 'results/submitted'
    archive.mkdir(parents=True)
    output = tmp_path / 'docs/results_index.json'
    output.parent.mkdir()
    (archive / 'one.json').write_text(json.dumps(seal_result(EXAMPLE_RESULT)))
    write_results_index(archive, output)
    git('add', '.')
    git('commit', '-qm', 'fixture with current index')

    second = deepcopy(EXAMPLE_RESULT)
    second['meta']['timestamp'] = '2026-10-04T09:00:00Z'
    (archive / 'two.json').write_text(json.dumps(seal_result(second)))
    if not stale_index:
        write_results_index(archive, output)
    git('add', '.')
    git('commit', '-qm', 'fixture after history rewrite')

    # Like github.event.before after a force push, this SHA is not in the checkout.
    env = dict(os.environ, INDEX_BASE_SHA='f' * 40)
    quality_script = ROOT / '.github/scripts/check_leaderboard.py'
    quality = subprocess.run([sys.executable, str(quality_script)], cwd=tmp_path,
        env=env, capture_output=True, text=True)
    if stale_index:
        assert quality.returncode != 0 and 'stale' in quality.stderr
    else:
        assert quality.returncode == 0, quality.stderr
        assert 'index is current (2 results)' in quality.stdout
    assert 'bad object' not in quality.stderr
