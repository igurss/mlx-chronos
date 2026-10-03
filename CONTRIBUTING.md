# Contributing to mlx-Chronos

Thanks for helping improve mlx-Chronos. Contributions usually fall into two
paths: submitting benchmark results or improving the project itself.

This guide follows `main`. Check the [changelog](CHANGELOG.md) for changes
after the latest release; use the
[source installation](README.md#development-version-from-main) to test those
changes before publication.

## Contents

- [Ways to Contribute](#ways-to-contribute)
- [Submit Benchmark Results](#submit-benchmark-results)
- [Contribute Code or Docs](#contribute-code-or-docs)
- [macOS App Development](#macos-app-development)
- [Open an Issue](#open-an-issue)
- [Code of Conduct](#code-of-conduct)
- [Releases](#releases)

---

## Ways to Contribute

| Contribution | Best path | Keep separate from |
| --- | --- | --- |
| Public benchmark result | Pull request with JSON under `results/submitted/` | Code or docs changes |
| Code fix | Focused pull request from a fork or branch | Leaderboard result files |
| Documentation update | Focused pull request | Benchmark result files |
| Feature idea | Issue first, then implementation PR | Unrelated refactors |
| Bug report | Issue with reproduction details | Speculative fixes |

Mixed PRs are harder to validate and review. Keep each PR focused on one
result submission, one fix, or one feature.

---

## Submit Benchmark Results

### Requirements

| Requirement | Details |
| --- | --- |
| Hardware | Apple Silicon Mac with an M-series chip, `arm64`, and a valid macOS version |
| Python | Python 3.10 or newer |
| Engine | One supported engine installed and running, with a known engine version |
| Power mode | Low Power Mode must be off for public leaderboard rows |
| Token counts | Public rows must use `usage.completion_tokens` |
| Monitoring | Continuous Foundation thermal sampling and error-free RAM/RSS monitoring |

Supported engines:

- [Ollama](https://github.com/ollama/ollama) with the MLX backend
- [oMLX](https://github.com/jundot/omlx)
- [Rapid-MLX](https://github.com/raullenchai/Rapid-MLX)
- [vllm-mlx](https://github.com/waybarrios/vllm-mlx)
- [mlx-lm](https://github.com/ml-explore/mlx-lm)
- [LM Studio](https://lmstudio.ai), experimental MLX-runtime-only support
  (see the note below)

### 1. Install mlx-Chronos

```bash
pip install mlx-chronos
```

Thermal-state support is optional for local runs but required for new public
results using the Foundation monitor:

```bash
pip install "mlx-chronos[thermal]"
```

These commands install from PyPI. For unreleased features, follow the
[development installation](README.md#development-version-from-main) instead.

### 2. Start an Engine Server

Use the server command for your engine and model.

```bash
# oMLX
omlx serve --model-dir ~/models

# Rapid-MLX
rapid-mlx --no-telemetry serve /path/to/model --port 8001

# vllm-mlx
vllm-mlx serve mlx-community/Llama-3.2-3B-Instruct-4bit --port 8000

# mlx-lm
mlx_lm.server --model /path/to/model --port 8080

# Ollama
ollama serve

# LM Studio (desktop app) — from the Developer tab, start the server, and load
# an MLX model. This CLI command starts only the server, not a model:
lms server start --port 1234
```

> **LM Studio: experimental, MLX only**
> LM Studio also serves llama.cpp/GGUF models. mlx-Chronos checks both the
> model's `compatibility_type` and the runtime that actually answered a probe
> request, and rejects anything that is not confirmed MLX end to end. Load an
> MLX build (for example from the `mlx-community` publisher in LM Studio's
> model browser) and make sure its runtime is set to MLX before benchmarking.
> `supported_formats: ["safetensors"]` is valid alongside an MLX runtime name;
> the format by itself is not runtime proof. Starting the server without a
> usable model is enough to test reachability, not to verify inference or the
> MLX runtime. Use `models --engine lmstudio` and then
> `validate --engine lmstudio --model <exact-id>` to check an actual model.
> See [the gate and API scope](docs/methodology.md#lm-studio-mlx-only-gate).

Default OpenAI-compatible endpoints:

| Engine | Default URL |
| --- | --- |
| oMLX | `http://localhost:8000/v1` |
| Rapid-MLX | `http://localhost:8001/v1` |
| vllm-mlx | `http://localhost:8000/v1` |
| mlx-lm | `http://localhost:8080/v1` |
| Ollama | `http://localhost:11434/v1` |
| LM Studio | `http://localhost:1234/v1` (native checks use `/api/v0`) |

Override ports with environment variables:

```bash
export MLX_CHRONOS_VLLM_MLX_PORT=8003
export MLX_CHRONOS_MLX_LM_PORT=8002
export MLX_CHRONOS_LMSTUDIO_PORT=1235
```

Set only the variables for servers you actually moved. These values tell
mlx-Chronos where to connect; they do not reconfigure or start those servers.

> **Port note**
> oMLX and vllm-mlx both default to port `8000`. Run only one of them on that
> port at a time, or move one server and set the matching
> `MLX_CHRONOS_<ENGINE>_PORT` variable.

For oMLX, mlx-Chronos also checks the listening process with `lsof` so a
different OpenAI-compatible server on port `8000` is not mislabeled as oMLX. If
`lsof` cannot inspect the listener, validation may report that oMLX is not
running even when `/v1/models` responds.

### 3. Validate the Setup

```bash
mlx-chronos engines
mlx-chronos validate --engine omlx --model "Qwen3.5-4B-OptiQ-4bit"
```

`validate` checks hardware, engine availability, server reachability, model
listing, and an optional tiny completion request.

### 4. Run the Benchmark

```bash
mlx-chronos run --publishable --engine omlx \
  --model "Qwen3.5-4B-OptiQ-4bit" \
  --model-url "https://huggingface.co/mlx-community/Qwen3.5-4B-OptiQ-4bit" \
  --trials 5
```

The result JSON is written to `results/local/`. Use `--format all` if you also
want a Markdown summary for local reading.

`--publishable` performs preflight and rejects incompatible requested settings
before measurement; final eligibility still depends on the measured result.
It requires JSON output (`json` or `all`), not Markdown alone. Add
`--submitted-by YOUR_HANDLE` if you want optional public contributor credit;
the wizard offers the same choice.

Local runs may use custom trial counts, token bounds, profiles, cooldown,
connection mode, and notes. Keep non-standard runs in `results/local/` for your
own diagnostics and omit `--publishable` for them. The separate `concurrency`,
`context` and `energy` reports and the `matrix` manifest are not public result
files; see [Local Diagnostics](README.md#local-diagnostics).

### 5. Check Public Eligibility

```bash
mlx-chronos submit --file results/local/your-result.json --dry-run
```

This validates the JSON locally without sending it anywhere.

Public leaderboard submissions must pass this check and meet one of the
standard profiles:

| Profile | Trials | `requested_max_tokens` | Minimum generated output | `min_tokens` |
| --- | ---: | ---: | ---: | --- |
| Baseline | 5 | 100 | 80 tokens | Not allowed |
| Sustained | 1 | 1000 | 800 tokens | Not allowed |

Additional public requirements:

- `metrics.token_count_source` must be `usage.completion_tokens`.
- `model.reference_url` must point to the model used for the run.
- `meta.warmup_failures` must be `0`.
- `hardware.low_power_mode` must be `off`.
- Engine version and hardware identity must satisfy the requirements above;
  timestamps may not be more than 10 minutes in the future.
- RAM/RSS and thermal monitors must record no sampling errors. The thermal
  monitor must use Foundation with at least two valid samples and a recorded
  maximum sample gap no larger than `max(1.0, 2.5 * sample_interval_seconds)`.
- Benchmark protocol metadata must remain unchanged.
- Generation parameters must remain deterministic: `temperature=0.0`,
  `top_p=1.0`.
- Throughput timing fields and raw trial arrays must not be edited by hand.
- Raw decode timings must allow reconstruction, and the result must not
  duplicate an archived integrity digest or run identity.

Model pages can change over time when maintainers update files or tags.

If your JSON says `"token_count_source": "word_fallback"` or `"mixed"`, keep it
as a local result until the engine can return real completion-token usage. New
fallback results also set `meta.word_fallback_warning`.

The small protocol labels stored in JSON, such as `1`, `2`, `3`, or `4`, are
internal compatibility markers used by validators. They are not public protocol
release versions.

Current-source submissions require label `4`, which records fully drained and
validated completion streams plus thermal sampling coverage. Archived label
`3` results retain their original data and seals; they do not satisfy the
current rules for a new submission. Never relabel an existing measurement.

### 6. Open a Result PR

1. Copy the checked JSON into `results/submitted/` with a clear filename.
2. Open a pull request that changes only that JSON file.
3. GitHub Actions labels the PR as `result-submission`.
4. The result-validation workflow checks PR scope and rejects deletions before
   installing the package, then validates schema, raw trials, integrity and
   public-profile rules.
5. A maintainer reviews the result before merge.

> **Do not edit result JSON by hand**
> Public submissions include an `integrity` seal over the canonical result
> payload. Changing benchmark fields invalidates the seal and CI rejects the
> file.

### Inbox Fallback

If opening a PR is inconvenient, send a validated result to the maintainer
inbox:

```bash
mlx-chronos submit --file results/local/your-result.json
```

Add `--email you@example.com` (or set `MLX_CHRONOS_SUBMITTER_EMAIL`) if you
want the maintainer to be able to reply. Without it, the inbox uses an anonymous
placeholder contact, never the maintainer's address. This does **not** remove
`meta.submitted_by` or other identifying information already in the attached
JSON. The public handle is independently set during `run`, not inferred from
the contact email, and it is not proof of GitHub account ownership.

Maintainers can override the inbox endpoint with `--endpoint` or
`MLX_CHRONOS_SUBMIT_ENDPOINT`.

### Result File Format

Results must follow the schema in `mlx_chronos/schema.py`.
See [docs/methodology.md](docs/methodology.md) for field-level measurement
details.

---

## Contribute Code or Docs

### Setup

```bash
git clone --branch main https://github.com/igurss/mlx-chronos.git
cd mlx-chronos
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
```

### Workflow

1. Fork the repository or create a focused branch from `main`.
2. Keep code/docs changes separate from leaderboard JSON submissions.
3. Make the smallest change that solves the issue.
4. Add or update tests when behavior changes.
5. Run the relevant tests locally.
6. Open a pull request back to `igurss/mlx-chronos`.

### Local Checks

```bash
python -m pytest
```

For targeted work, run the smallest relevant subset first, then the full suite
before opening the PR when practical. To run the other CI quality gates from
the repository root (Node.js is needed for the frontend tests):

```bash
python -m ruff check mlx_chronos tests
python -m mypy
python -m pytest --cov --cov-report=term-missing
python -m mlx_chronos.leaderboard --check
node --test tests/frontend.test.cjs
git diff --check
```

Coverage must meet the threshold in `pyproject.toml` (currently 78%). The
leaderboard `--check` command is read-only: it fails if the checked-in index
differs from the validated submitted archive. For an intentional archive or
index-format change, regenerate with `python -m mlx_chronos.leaderboard`, review
the generated diff, and run `--check` again. Keep generated-data work separate
from unrelated source changes.

CI tests Python 3.10 through 3.14 on macOS; one local Python run does not replace
that matrix. Mock-engine tests do not prove every real server configuration.
Record the engine/runtime version, model, hardware, command and scope of any
real-engine smoke test, and never submit a short diagnostic as a public run.

When changing documented behavior, update README examples, the relevant
methodology section and `CHANGELOG.md` under **Unreleased**. Check local links,
heading anchors and CLI options as well as prose; no version bump is needed
for an ordinary unreleased change. Packaging and publication checks are in the
[release checklist](docs/releasing.md).

### Guidelines

- Follow the existing code style.
- Prefer focused changes over broad refactors.
- Add comments only where they clarify non-obvious behavior.
- Include tests for behavior changes, regressions, and schema validation.
- Reference the relevant issue in the PR or commit when one exists, for example
  `feat: add engine support (#3)`.
- Explain user-visible behavior changes in the PR description.

GitHub Actions rejects mixed PRs, deleted submitted result files, invalid
schemas, broken integrity seals, non-standard public benchmark profiles,
fallback token counts, requested `min_tokens`, Low Power Mode runs,
short-output runs, and non-standard public trial counts or token bounds.

---

## macOS App Development

The native app is part of this repository under `apps/mlx-chronos-mac/`.
It is a SwiftUI front end; measurement/validation changes belong in the Python
CLI, not a duplicate implementation in the app. Use the
[app user guide](apps/mlx-chronos-mac/USER_GUIDE.md) for product behavior.

### Source layout

| Path inside the app folder | Purpose |
| --- | --- |
| `MLXChronos/` | Application state, runtime discovery, command construction, process execution, result loading and SwiftUI views. |
| `MLXChronos/Resources/` | Python adapter and license notices. No CLI wheel, interpreter or model weights. |
| `MLXChronos/Assets.xcassets/`, `MLXChronos/AppIcon.icon/` | Sidebar artwork, colors and native light/dark app icons. |
| `MLXChronos.xcodeproj/` | App target and shared build scheme. |
| `Tests/` | Reusable bridge and Swift core regressions with mocks/temporary fixtures. |
| `scripts/` | Local build, regression checks, disposable standalone bootstrap and published release registration. |

Requires an Apple Silicon Mac, Xcode 26+ with its command-line tools, and an
Python 3.10+ for developer checks. End users get a private Python download. The deployment target remains macOS 14.
Open `MLXChronos.xcodeproj` and choose the `MLXChronos` scheme to run/debug.

### Reusable checks

Create a separate Python environment with the approved published CLI:

```bash
python3 -m venv .venv-app
.venv-app/bin/python -m pip install "mlx-chronos[thermal]==0.5.0"
bash apps/mlx-chronos-mac/scripts/check.sh "$PWD/.venv-app/bin/python"
```

These checks cover command/options parity, literal argument handling,
validation/defaults, removal protections, result classification/order,
process output, timeouts and cancellation. They use synthetic temporary
fixtures and mocks, not your engines/models or app preferences. They are not
an all-hardware or full-interface acceptance certification.

The separate **macOS App** workflow runs these reusable bridge/core checks
against the approved published CLI and current source, including full Release
build and disposable standalone Python bootstrap. It does not load real models, run
personal acceptance scenarios, publish binaries or certify Gatekeeper trust.

Optional networked setup/removal regression, using **only its own disposable
environment**, never a selected user installation:

```bash
.venv-app/bin/python -I -B apps/mlx-chronos-mac/scripts/check_fresh_runtime.py
```

Python is preserved; this test checks targeted CLI removal and remaining
dependencies. Owner-specific engine/model acceptance scripts and personal
reports are not required to build or run the public project.

### Local Release build

```bash
bash apps/mlx-chronos-mac/scripts/build_release.sh
```

The script saves an Apple Silicon app and version/build-named ZIP under the
ignored app `dist/` directory, verifies its local signature and removes its
temporary Xcode cache. It refuses to overwrite an existing app; choose a new
output folder when comparing candidates. This is an **ad-hoc/local build**,
not Developer ID signing, notarization, a DMG or publication.

Package an already-built local app as the free DMG:

```bash
bash apps/mlx-chronos-mac/scripts/package_dmg.sh
```

This preserves/verifies the app signature, creates the Applications shortcut
and first-launch instructions, verifies the image and writes a matching SHA-256
file. It does not notarize, upload or change macOS security settings, and
refuses to overwrite an existing image/checksum. Inspect the mounted app before
distribution. This recipe intentionally accepts only an arm64 ad-hoc build;
Developer ID distribution would require a separately reviewed recipe.

Public DMG filenames include the app version and architecture, not the build
number. The build remains in the app metadata and local candidate ZIP names.
Renaming a download does not create a new binary or justify moving its source
tag; changed binaries need a new release identity.

### Approving independently released CLI updates

The app reads `docs/app-runtime.json` from the official Pages site, then checks
published versions on PyPI. Its compatibility contract is independent of the
benchmark measurement protocol. Never infer app compatibility solely from a
package version or a successful pip install.

After publishing a CLI release, run:

```bash
python3 apps/mlx-chronos-mac/scripts/register_runtime_release.py X.Y.Z
bash apps/mlx-chronos-mac/scripts/check_bootstrap.sh
```

The registrar verifies the published wheel hash and reads its literal
`mlx_chronos/app_contract.py` declaration without executing wheel code. Review
minimum app version, API version, required capabilities, supported commands and
artifact identity before committing the catalog. Existing entries are immutable.
The single 0.5.0 legacy entry is an explicitly reviewed exception for the initial
published package; new entries must include the package-side contract.

Run standalone bootstrap checks only on macOS with network access. They create
and remove their own temporary directory, install no global Python, and verify
fresh setup, reuse, repair, rollback and failed-update preservation. Catalog
approval does not publish a CLI release or app DMG. A missing/unknown contract
blocks automatic installation; incompatible versions prompt an app update.

### Documentation, license and release identity

Keep the app's `USER_GUIDE.md` focused on useful setup, command options and
limits. Update its separate `CHANGELOG.md` for app behavior changes; use the
root changelog for CLI changes. App source is covered by the root Apache 2.0
license, and the app includes the full license and runtime notices. Preserve
upstream notices when changing redistributed resources.

App `MARKETING_VERSION` and `CURRENT_PROJECT_VERSION` are manual, independent
of the CLI version. Assign a unique increasing build number to each distributed
candidate; compiling or committing does not increment it automatically.
The initial app version is 0.1.0. Reserve **`app-vX.Y.Z`** for app release tags:
CLI tags are `vX.Y.Z` and trigger the separate PyPI publication workflow.
Do not create either tag merely to record a local build.

Public binary distribution is a separate maintainer step. A DMG is a container,
not proof of trust: normal Gatekeeper distribution requires Developer ID
signing and Apple notarization. Never commit certificates, private keys,
credentials, personal results or local build artifacts.

---

## Open an Issue

Open an issue before starting a larger feature or protocol change. Bug reports
and small fixes are also welcome; include the engine, model, command, logs, and
environment details needed to reproduce the problem.

---

## Code of Conduct

Be respectful. This is an open project welcoming contributors of all levels.

## Releases

Maintainers should follow [the release checklist](docs/releasing.md), including
the manual workflow rehearsal before creating a tag that publishes to PyPI.
