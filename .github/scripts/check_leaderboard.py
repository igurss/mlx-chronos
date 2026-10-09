"""Check the index, except while a JSON-only submission awaits the index bot."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

from mlx_chronos.leaderboard import build_results_index, check_results_index


def submission_only(base: str, *, root: Path = Path('.')) -> bool:
    if not base or set(base) == {'0'}:
        return False
    # A rewritten history may leave the previous push tip outside the checkout.
    # Without that base, require the full archive/index check below.
    if subprocess.run(
        ['git', 'cat-file', '-e', f'{base}^{{commit}}'], cwd=root,
        stderr=subprocess.DEVNULL,
    ).returncode != 0:
        return False
    paths = subprocess.check_output(
        ['git', 'diff', '--name-only', '-z', base, 'HEAD', '--'], cwd=root,
    ).decode('utf-8').split('\0')
    changed = [Path(path) for path in paths if path]
    return bool(changed) and all(
        path.parts[:2] == ('results', 'submitted') and path.suffix == '.json'
        and (root / path).is_file() for path in changed
    )


def main() -> None:
    archive = Path('results/submitted')
    if submission_only(os.environ.get('INDEX_BASE_SHA', '')):
        payload = build_results_index(archive)
        print(f"Submission archive is valid and index is generable ({len(payload['results'])} results).")
    else:
        count = check_results_index(archive, Path('docs/results_index.json'))
        print(f'Leaderboard index is current ({count} results).')


if __name__ == '__main__':
    main()
