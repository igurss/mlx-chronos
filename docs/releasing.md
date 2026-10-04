# Releasing mlx-chronos

The [Release workflow](../.github/workflows/release.yml) supports two paths:

- A manual run (`workflow_dispatch`) checks the selected commit and packages.
  Its PyPI job is skipped, including when the selected ref is a tag.
- Pushing a `v*` tag runs the same checks and then publishes to PyPI. The tag
  must exactly match `v` followed by the version in `pyproject.toml`.

Documentation updates and a successful manual run do not publish a release.
Do not bump the version or create a tag as a side effect of routine maintenance.

## Before creating a release tag

1. Prepare the version in `pyproject.toml`, the Current Release paragraph in
   `README.md`, and the dated release section in `CHANGELOG.md`. The package
   resolves its runtime version from source or installed distribution metadata;
   there is no second hard-coded version in `mlx_chronos/__init__.py`.
   Move the implemented Unreleased entries into that dated section. Update
   README's development-versus-release notice so newly released features are
   not still described as absent from PyPI, and retain any genuinely unreleased
   work separately. Check README, CONTRIBUTING, methodology and leaderboard
   text against the actual CLI and validation rules, including local links.
2. Review compatibility and the documented scope of experimental diagnostics.
   Real-engine checks should use available hardware without interpreting a
   small local smoke run as a publishable benchmark or a scaling study.
   Run the [local quality gates](../CONTRIBUTING.md#local-checks) and retain the
   verification evidence described below. Check relevant failure paths as well
   as successful runs; do not use a local-only diagnostic as a submitted result.
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

## Publishing the independent macOS app

App releases use `app-vX.Y.Z`; they do not trigger CLI publication. Update the
app's `MARKETING_VERSION`, increasing `CURRENT_PROJECT_VERSION`, separate
changelog, user guide and README download link. App 0.2.0, build 4 downloads
private Python and an approved compatible CLI instead of embedding a wheel.

1. Publish and verify any accompanying CLI release first. Register its exact
   published wheel with
   `python3 apps/mlx-chronos-mac/scripts/register_runtime_release.py X.Y.Z`.
   Review the artifact checksum and interface contract; keep existing approved
   entries unchanged. CLI 0.5.1 includes the app compatibility declaration and
   benchmark protocol revision 4.
2. Run the app's bridge/Swift checks against that published CLI and the
   standalone bootstrap checks with the updated catalog. Commit and push the
   catalog, then verify Pages serves the approved entry and the macOS App
   workflow passes on the app release commit.
3. Build the arm64 Release app and package it with `build_release.sh` and
   `package_dmg.sh`, following the
   [app build instructions](../CONTRIBUTING.md#local-release-build). Verify the
   signature, app version/build, DMG checksum and the mounted image contents.
   The app must contain no CLI wheel or Python interpreter.
4. Tag the validated source commit and create the GitHub app release with its
   DMG and matching `.sha256` file. Include first-launch instructions and the
   local/ad-hoc signing and Apple notarization status in the release notes.
   Verify the public download against its checksum after publication.

Future compatible CLI fixes need a reviewed catalog update, not a new app
binary. Changes to the app itself require a new app release. Neither release
may include private acceptance reports, credentials or personal results.

## Interpreting the checks

Passing tests, installed-package checks and a vulnerability scan provide
evidence for the exact revision and dependency versions tested. They do not
guarantee all future dependency releases or every engine/server configuration.
Dependency vulnerability scanning is a separate check, not currently a job in
the Release workflow; record its tool, date, environment and coverage if run.
Keep LM Studio and the local diagnostics within their documented scope; record
which real engines, models and hardware were used for manual checks.

## Verification evidence to retain

- Exact source commit, workflow URL and outcome, with publication skipped for
  a manual rehearsal; package version alone cannot identify an unreleased commit.
- Python/macOS versions, installed wheel/source-distribution checks and any
  optional dependencies tested. CLI `--help` checks establish command loading,
  not real inference against every supported engine.
- For manual engine checks: hardware/RAM, engine and runtime versions, model ID
  and reference, command/options, output locations, observed warnings and
  relevant server settings. Preserve local diagnostic reports separately from
  the public submitted archive.
- What was not tested and why. A concurrency smoke test against a server that
  queues requests does not validate parallel generation or high-load scaling;
  a single-engine check does not validate a real multi-engine matrix; macmon
  estimates do not become calibrated power measurements because a test passes.

If a later change affects behavior or packaging, rerun the relevant checks on
the new revision and the manual workflow before tagging. Earlier reports must
not be presented as validation of an untested release commit.
