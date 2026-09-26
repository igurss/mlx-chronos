# Releasing mlx-chronos

The [Release workflow](../.github/workflows/release.yml) supports two paths:

- A manual run (`workflow_dispatch`) checks the selected commit and packages.
  Its PyPI job is skipped, including when the selected ref is a tag.
- Pushing a `v*` tag runs the same checks and then publishes to PyPI. The tag
  must exactly match `v` followed by the version in `pyproject.toml`.

## Before creating a release tag

1. Prepare the version in `pyproject.toml`, the Current Release paragraph in
   `README.md`, and the dated release section in `CHANGELOG.md`. The package
   resolves its runtime version from source or installed distribution metadata;
   there is no second hard-coded version in `mlx_chronos/__init__.py`.
2. Review compatibility and the documented scope of experimental diagnostics.
   Real-engine checks should use available hardware without interpreting a
   small local smoke run as a publishable benchmark or a scaling study.
3. Commit and push the release preparation. Run the workflow on that commit:

   ```bash
   gh workflow run release.yml --ref main
   gh run list --workflow release.yml --event workflow_dispatch
   ```

4. Check the selected run's commit SHA and wait for every verification job to
   succeed. Confirm that **Publish to PyPI** is skipped. The workflow runs:
   - tests and CLI/frontend checks on macOS with Python 3.10 through 3.14;
   - lint, type checking, coverage and a read-only leaderboard-index check;
   - isolated source and wheel builds and strict Twine metadata validation;
   - artifact download and fresh installation of both distributions on Python
     3.10 and 3.14, outside a source checkout. Wheel checks include the optional
     `thermal` dependency; source-distribution checks use base dependencies.
5. If release preparation changes again, validate the new commit before tagging.
   Confirm that the target version has not already been published on PyPI.

## Publishing

Creating and pushing the version tag is the publication step. Tag the exact
validated commit, and observe the tag-triggered workflow through the PyPI job.
Trusted Publishing uses the repository's `pypi` environment and a job-scoped
GitHub identity token; the manual rehearsal does not exercise that token
exchange or upload to PyPI.

After successful publication, verify the version and both distribution files
on PyPI, then test installation of that version into a fresh environment.
Record the workflow result and publish the corresponding GitHub release notes.
Do not move an already published version tag to a different commit.

## Interpreting the checks

Passing tests, installed-package checks and a vulnerability scan provide
evidence for the exact revision and dependency versions tested. They do not
guarantee all future dependency releases or every engine/server configuration.
Keep LM Studio and the local diagnostics within their documented scope; record
which real engines, models and hardware were used for manual checks.
