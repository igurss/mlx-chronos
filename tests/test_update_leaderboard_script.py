"""Exercise the index publisher against a local Git remote, without a network."""

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".github" / "scripts" / "update_leaderboard_index.sh"


def _git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def test_index_publisher_regenerates_after_main_advances(tmp_path: Path):
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    competing = tmp_path / "competing"
    runner = tmp_path / "runner"
    _git("init", "--bare", "--initial-branch=main", str(remote), cwd=tmp_path)
    _git("clone", str(remote), str(seed), cwd=tmp_path)
    _git("config", "user.name", "Test", cwd=seed)
    _git("config", "user.email", "test@example.invalid", cwd=seed)
    (seed / "docs").mkdir()
    (seed / "results" / "submitted").mkdir(parents=True)
    (seed / "docs" / "results_index.json").write_text("stale\n")
    (seed / "results" / "submitted" / "value.txt").write_text("first\n")
    _git("add", ".", cwd=seed)
    _git("commit", "-m", "seed", cwd=seed)
    _git("push", "origin", "main", cwd=seed)
    _git("clone", str(remote), str(competing), cwd=tmp_path)
    _git("clone", str(remote), str(runner), cwd=tmp_path)
    _git("config", "user.name", "Other", cwd=competing)
    _git("config", "user.email", "other@example.invalid", cwd=competing)
    (competing / "results" / "submitted" / "value.txt").write_text("second\n")
    _git("add", ".", cwd=competing)
    _git("commit", "-m", "concurrent submission", cwd=competing)

    # The fake Python command makes the competing push after the first index
    # generation, precisely between the publisher's fetch and push.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python = bin_dir / "python"
    python.write_text(
        "#!/bin/sh\n"
        "if [ \"$*\" = '-m pip install .' ]; then exit 0; fi\n"
        "if [ \"$*\" != '-m mlx_chronos.leaderboard' ]; then exit 2; fi\n"
        "cp results/submitted/value.txt docs/results_index.json\n"
        "if [ ! -f \"$RACE_MARKER\" ]; then\n"
        "  touch \"$RACE_MARKER\"\n"
        "  git -C \"$RACE_REPO\" push origin main\n"
        "fi\n"
    )
    python.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["RACE_MARKER"] = str(tmp_path / "race-fired")
    env["RACE_REPO"] = str(competing)

    completed = subprocess.run(
        ["bash", str(SCRIPT)], cwd=runner, env=env,
        capture_output=True, text=True, check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "main advanced during attempt 1" in completed.stdout
    assert (runner / "docs" / "results_index.json").read_text() == "second\n"
    assert _git("log", "-1", "--format=%s", cwd=runner) == (
        "chore: update leaderboard index [skip ci]"
    )
    _git("fetch", "origin", "main", cwd=seed)
    assert _git("show", "FETCH_HEAD:docs/results_index.json", cwd=seed) == "second"
