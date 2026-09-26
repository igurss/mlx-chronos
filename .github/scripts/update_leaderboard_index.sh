#!/usr/bin/env bash
set -euo pipefail

# Always generate from the current main, not the commit that triggered this
# workflow. A concurrent push may advance main while generation is running.
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

for attempt in 1 2 3; do
  git fetch --no-tags origin refs/heads/main
  git switch --detach FETCH_HEAD

  # A newer main may have changed the generator or its dependencies.
  python -m pip install .
  python -m mlx_chronos.leaderboard
  git add docs/results_index.json
  if git diff --cached --quiet; then
    echo "Leaderboard index is already current."
    exit 0
  fi

  git commit -m "chore: update leaderboard index [skip ci]"
  if git push origin HEAD:refs/heads/main; then
    exit 0
  fi

  # Retry only when the remote actually moved. Permissions, branch protection,
  # and network failures will not be repaired by repeating the same push.
  git fetch --no-tags origin refs/heads/main
  if [ "$(git rev-parse FETCH_HEAD)" = "$(git rev-parse HEAD^)" ]; then
    echo "Index push failed without main advancing; not retrying." >&2
    exit 1
  fi
  echo "main advanced during attempt ${attempt}; regenerating on its new tip."
done

echo "Could not publish the regenerated index after 3 attempts." >&2
exit 1
