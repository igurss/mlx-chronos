# mlx-Chronos

> Benchmark suite and community leaderboard for local LLM inference on Apple Silicon.
> Run a reproducible benchmark, save a sealed JSON result, and compare engines across Macs.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/igurss/mlx-chronos/blob/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/mlx-chronos.svg)](https://pypi.org/project/mlx-chronos/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-green.svg)](https://python.org)
[![Apple Silicon](https://img.shields.io/badge/Apple_Silicon-M1_|_M2_|_M3_|_M4_|_M5_|_M6-black?logo=apple)](https://apple.com)
[![Contributions Welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg)](https://github.com/igurss/mlx-chronos/blob/main/CONTRIBUTING.md)

> **Documentation scope**
> This README describes the current `main` branch. See
> [Current Release](#current-release) for the published version,
> the [changelog](https://github.com/igurss/mlx-chronos/blob/main/CHANGELOG.md)
> for its full change history, and the
> [source installation instructions](#development-version-from-main) below.

## Start Here

Choose your interface:

- **macOS app:** configure tests, inspect your environment and work with results
  without assembling terminal commands. [Download app **0.2.0**](https://github.com/igurss/mlx-chronos/releases/tag/app-v0.2.0).
  It downloads private Python and the newest approved compatible CLI, starting
  with **0.5.1**. See the
  [app user guide](https://github.com/igurss/mlx-chronos/blob/main/apps/mlx-chronos-mac/USER_GUIDE.md) and
  [build instructions](https://github.com/igurss/mlx-chronos/blob/main/CONTRIBUTING.md#macos-app-development).
  The free DMG is **not Apple-notarized**; follow the guide's first-launch
  authorization instructions.
- **CLI:** use the guided wizard below, direct commands or scripts.

If you already have a supported local engine server running on an Apple Silicon
Mac, the shortest path is:

```bash
pip install mlx-chronos
mlx-chronos doctor
mlx-chronos wizard
```

The wizard walks through engine selection, model selection, benchmark profile,
output format, cooldown, preflight validation, notes, and the model reference
URL needed for public leaderboard submissions. Before starting a run, it shows
the equivalent `mlx-chronos run ...` command so you can reuse it later.

Prefer a direct command instead of the wizard:

```bash
mlx-chronos engines
mlx-chronos models --engine omlx
mlx-chronos run \
  --publishable \
  --engine omlx \
  --model "Qwen3.5-4B-OptiQ-4bit" \
  --model-url "https://huggingface.co/mlx-community/Qwen3.5-4B-OptiQ-4bit"
```

Results are saved as sealed JSON files under `results/local/` by default. To
check whether a result is ready for the public leaderboard:

```bash
mlx-chronos submit --file results/local/your-result.json --dry-run
```

## Contents

- [Start Here](#start-here)
- [Overview](#overview)
- [Current Release](#current-release)
- [macOS App](#macos-app)
- [Supported Engines](#supported-engines)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Local Diagnostics](#local-diagnostics)
- [Configuration](#configuration)
- [Benchmark Protocol](#benchmark-protocol)
- [Leaderboard Rules](#leaderboard-rules)
- [Submit Results](#submit-results)
- [Documentation and Development](#documentation-and-development)
- [License](#license)

---

## Overview

`mlx-chronos` is a standardized benchmark tool for local LLM inference engines
on Apple Silicon. It detects your Mac, runs a fixed benchmark protocol against
an OpenAI-compatible engine endpoint, and writes structured result files for
local analysis or public leaderboard submission.

The public leaderboard is available at
[igurss.github.io/mlx-chronos](https://igurss.github.io/mlx-chronos).

### What It Measures

| Metric | Meaning | Public comparison use |
| --- | --- | --- |
| TTFT cold | Request start to first streamed content or terminal token-limit signal, with cache-avoiding prompts | Yes |
| TTFT cached | Same timing after a cache-priming call with the fixed prompt | Yes |
| Request throughput | Completion tokens divided by full client-observed request time | Yes, when engine token usage is reliable |
| Sustained throughput | Optional long throughput run for heat buildup and late-run degradation | Yes, under the sustained profile |
| System RAM peak | Peak total Mac RAM in use during the benchmark | Stress context |
| RAM increase | Peak total Mac RAM minus the first sample; includes other processes | Diagnostic only |
| Swap growth | Increase in system-wide macOS swap usage during the run | Warning at 0.5 GB |
| Engine RSS | Post-warmup RSS of the engine server process when identifiable | Diagnostic only |
| Thermal state | Start, end, worst state, samples, and affected benchmark phases when available | Context metadata |
| Tool calling | Success-rate measurement is not implemented | Not available |

### Current Release

`0.5.1` fixes completion-stream handling, measurement validation, thermal/RSS
monitoring, and ambiguous submission retries. Standard benchmarks now use
protocol revision **4**; new public submissions require a new run, while
archived revision **3** results retain their original data and seals.
The package also declares its interface compatibility with app **0.2.0**.
The existing local diagnostics and experimental MLX-only LM Studio support
remain available. Full changes are detailed in the
[changelog](https://github.com/igurss/mlx-chronos/blob/main/CHANGELOG.md).

### macOS App

The native SwiftUI app lives in [`apps/mlx-chronos-mac/`](https://github.com/igurss/mlx-chronos/tree/main/apps/mlx-chronos-mac).
Environment, Tests, Results and Activity cover the CLI's non-interactive
commands; the forms replace the terminal wizard. Measurements, integrity
checks and public eligibility still come from the selected Python CLI, not a
second benchmark implementation.

It requires Apple Silicon and macOS 14+. On first launch it downloads private
Python and an approved compatible CLI with mandatory thermal support; existing
Python installations are preserved. You can explicitly choose another detected
installation or source checkout. Inference engines and models are installed
separately, and running a test does not automatically share its result.

App and CLI releases are independent. **App 0.2.0, build 4** contains no CLI
wheel or Python interpreter. It checks compatible CLI updates at launch,
retaining the prior copy until verification passes and supporting rollback.
CLI bug fixes can be delivered without rebuilding its DMG; incompatible
interfaces require an app update. App updates are checked separately and link
to the official download for manual replacement. See the
[user guide](apps/mlx-chronos-mac/USER_GUIDE.md) for setup and options.
[Download app 0.2.0](https://github.com/igurss/mlx-chronos/releases/tag/app-v0.2.0).
The DMG has a local/ad-hoc signature, not Developer ID signing or Apple
notarization; macOS may require explicit first-launch authorization.

---

## Supported Engines

| Engine | Project | Notes |
| --- | --- | --- |
| Ollama | [ollama/ollama](https://github.com/ollama/ollama) | MLX backend |
| oMLX | [jundot/omlx](https://github.com/jundot/omlx) | OpenAI-compatible server |
| Rapid-MLX | [raullenchai/Rapid-MLX](https://github.com/raullenchai/Rapid-MLX) | OpenAI-compatible server |
| vllm-mlx | [waybarrios/vllm-mlx](https://github.com/waybarrios/vllm-mlx) | OpenAI-compatible server |
| mlx-lm | [ml-explore/mlx-lm](https://github.com/ml-explore/mlx-lm) | Apple MLX |
| mlx-serve | [ddalcu/mlx-serve](https://github.com/ddalcu/mlx-serve) | Local MLX safetensors only; available from `main` |
| LM Studio | [lmstudio.ai](https://lmstudio.ai) | Experimental; MLX runtime only — see note below |

> **Note**
> The engine server must already be running before `mlx-chronos run`,
> `mlx-chronos models`, or `mlx-chronos validate` can query it.
> See [CONTRIBUTING.md](https://github.com/igurss/mlx-chronos/blob/main/CONTRIBUTING.md)
> for engine setup details.

> **LM Studio scope — experimental**
> LM Studio ships two runtimes on Apple Silicon: MLX and llama.cpp. This
> project benchmarks MLX engines only, so mlx-Chronos accepts an LM Studio
> model only when the weights are an MLX build *and* a live probe confirms the
> MLX runtime is the one that actually answered the request. GGUF models and
> probes answered by a non-MLX runtime are rejected. The runtime's
> `supported_formats` may report `safetensors`; that is accepted only alongside
> an MLX runtime name. See the [two-stage gate](https://github.com/igurss/mlx-chronos/blob/main/docs/methodology.md#lm-studio-mlx-only-gate)
> for API details and the distinction between application and runtime version.

mlx-serve support currently requires the
[development installation](#development-version-from-main). Use an exact ID
from `mlx-chronos models --engine mlx-serve`. Chronos confirms the loaded
`mlx` safetensors backend before measurement. All GGUF paths, including
upstream's native MLX GGUF reader, llama.cpp/ds4 and remote models are rejected.
See the [mlx-serve gate](docs/methodology.md#mlx-serve-local-mlx-gate).

---

## Quick Start

### 1. Prerequisites

You need:

- an Apple Silicon Mac;
- Python 3.10 or newer;
- one supported engine server already running locally;
- a model loaded or exposed by that engine.

`mlx-chronos` talks to an existing OpenAI-compatible local server. It does not
start, install, or download model weights for the engine.

### 2. Install

For the published release:

```bash
pip install mlx-chronos
```

Optional thermal-state support through macOS Foundation/PyObjC:

```bash
pip install "mlx-chronos[thermal]"
```

The thermal extra is optional for local diagnostics, but new public results
require continuous Foundation thermal monitoring. Install it in the same
Python environment as mlx-Chronos when preparing leaderboard submissions.

#### Development Version from Main

To test the exact current `main` revision, install the source in a separate
environment (Git is required):

```bash
git clone --branch main https://github.com/igurss/mlx-chronos.git
cd mlx-chronos
python3 -m venv .venv
source .venv/bin/activate
python -m pip install ".[thermal]"
git rev-parse HEAD
```

Record that commit SHA for reproducibility: `--version` identifies the package
release but not the exact source commit. `mlx-chronos upgrade` checks PyPI; it
does not update a Git checkout. For source development and test dependencies,
see [CONTRIBUTING.md](https://github.com/igurss/mlx-chronos/blob/main/CONTRIBUTING.md#setup).

### 3. Check Version and Updates

```bash
mlx-chronos --version
mlx-chronos upgrade
```

When run in an interactive terminal, `mlx-chronos` performs a best-effort
background PyPI version check. If a newer release is available, it prints a
short notice recommending:

```bash
mlx-chronos upgrade
```

Set `MLX_CHRONOS_DISABLE_UPDATE_CHECK=1` to disable the automatic check.

### 4. Inspect Your Engine

```bash
mlx-chronos doctor
mlx-chronos engines
mlx-chronos models --engine omlx
mlx-chronos validate --engine omlx --model "Qwen3.5-4B-OptiQ-4bit"
```

Use `mlx-chronos doctor` first if you are not sure what is missing. It checks
hardware, supported engines, running servers, model access, model URL readiness,
and public leaderboard blockers. Then use `mlx-chronos models` to copy the
exact model ID exposed by a running server.

### 5. Use the Interactive Wizard

```bash
mlx-chronos wizard
```

The wizard provides a terminal menu for common actions and a guided benchmark
builder with engine, model, profile, token bounds, output format, cooldown,
preflight, optional contributor handle, notes, and other run options. When the
selected engine server is running, the wizard loads `/models` and lets you
select a model from the exposed IDs, with manual entry as a fallback. Before
launching a benchmark, it shows the equivalent `mlx-chronos run ...` command so
the same configuration can be reused
in scripts. You can return to the main menu from benchmark setup without
starting a run.

### 6. Run a Benchmark Manually

```bash
mlx-chronos run \
  --publishable \
  --engine omlx \
  --model "Qwen3.5-4B-OptiQ-4bit" \
  --model-url "https://huggingface.co/mlx-community/Qwen3.5-4B-OptiQ-4bit"
```

Results are written to `results/local/` by default. `--publishable` fails fast
unless the run uses public leaderboard settings: standard profile shape, JSON
output, persistent HTTP connections, model URL, preflight validation, and Low
Power Mode off. Leave it out for private local experiments.

After every run, mlx-Chronos prints whether the result is ready for the public
leaderboard or local-only, including the first blocker and the concrete fix.

### 7. Validate a Result Before Submitting

```bash
mlx-chronos submit --file results/local/your-result.json --dry-run
```

If validation passes, you can submit the JSON through a pull request under
`results/submitted/` or send it through the maintainer inbox with
`mlx-chronos submit --file ...`.

### 8. Useful Run Options

```bash
# Open the guided terminal flow
mlx-chronos wizard

# Diagnose local setup and public leaderboard blockers
mlx-chronos doctor --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" \
  --model-url "https://huggingface.co/mlx-community/Qwen3.5-4B-OptiQ-4bit" \
  --publishable

# Write both JSON and Markdown outputs
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --format all

# Choose a custom output directory
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --output-dir ~/Desktop/benchmarks

# Request throughput output token bounds for local experiments
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --max-tokens 100 --min-tokens 80

# Run the longer heat/throttling-sensitive sustained profile
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --profile sustained

# Local-only server-load diagnostic: 1, 2, 4 and 8 simultaneous requests
# Use lower levels on machines with limited RAM.
mlx-chronos concurrency --engine vllm-mlx --model "Qwen3.5-4B-OptiQ-4bit" \
  --levels 1,2,4,8

# Local multi-engine sweep with each server's exact model ID; both servers
# must already be running. The default two rounds reverse their positions.
mlx-chronos matrix --engine-model 'omlx=org/model-id' \
  --engine-model 'ollama=model-alias:tag'

# Experimental local power diagnostic (requires macmon and a running server).
# A no-request phase follows model warm-up and precedes throughput measurement.
mlx-chronos energy --engine ollama --model 'model-alias:tag'

# Local TTFT-versus-input-length diagnostic; defaults to small and medium.
# Long buckets must be selected explicitly and may exceed server context limits.
mlx-chronos context --engine ollama --model 'model-alias:tag'

# Enforce cooldown after a recent run in the same output directory
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --cooldown-seconds 300

# Run the whole benchmark 5 times to see run-to-run variance; each repeat is
# saved as its own sealed result file
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --repeat 5

# Compare sealed local results; percentages are relative to the first file
mlx-chronos compare results/local/first.json results/local/second.json

# Compare two series: first 2 files form A, remaining files form B
mlx-chronos compare --series-a-size 2 a1.json a2.json b1.json b2.json

# List local results newest first, skipping invalid files with a reason
mlx-chronos history --limit 10

# Fail fast with an extra model access probe before measured work starts
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --preflight

# Credit a public leaderboard row to your GitHub handle
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --submitted-by igurss

# Record a server setting you checked yourself; this does not configure the server
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" \
  --engine-opt context_length=8192

# Include a model reference URL, required for public leaderboard submissions
mlx-chronos run --engine omlx \
  --model "Qwen3.5-4B-OptiQ-4bit" \
  --model-url "https://huggingface.co/mlx-community/Qwen3.5-4B-OptiQ-4bit"
```

---

## CLI Reference

| Command | Purpose |
| --- | --- |
| `mlx-chronos --version` | Print the installed package version |
| `mlx-chronos doctor` | Diagnose hardware, engines, server status, model access, and public-submission blockers |
| `mlx-chronos wizard` | Open an interactive menu for common commands and guided benchmark setup |
| `mlx-chronos upgrade` | Check PyPI and upgrade the current Python environment if a newer release exists |
| `mlx-chronos engines` | List supported engines and local installed/running status |
| `mlx-chronos models --engine <name>` | List model IDs exposed by a running engine server |
| `mlx-chronos validate --engine <name> --model <model>` | Validate hardware, engine, server, and optional model access |
| `mlx-chronos run --engine <name> --model <model>` | Run a benchmark and save local result files |
| `mlx-chronos run --publishable --engine <name> --model <model> --model-url <url>` | Run only if public leaderboard settings are satisfied |
| `mlx-chronos concurrency --engine <name> --model <model>` | Measure local aggregate throughput under simultaneous requests; never a leaderboard result |
| `mlx-chronos matrix --engine-model <engine>=<model> ...` | Preflight and rotate local full runs across engines; not a comparability verdict |
| `mlx-chronos energy --engine <name> --model <model>` | Experimental local macmon system-power diagnostic with a separate no-request phase; never a leaderboard result |
| `mlx-chronos context --engine <name> --model <model>` | Local TTFT versus approximate input-length diagnostic; not a prefill-speed or leaderboard metric |
| `mlx-chronos compare <file1> <file2>` | Compare sealed local results against the first file, with pairwise metric cautions |
| `mlx-chronos history [--limit N]` | List local results newest first |
| `mlx-chronos submit --file <result.json> --dry-run` | Validate whether a result is publishable |
| `mlx-chronos submit --file <result.json>` | Send a validated result to the maintainer inbox |

Use `mlx-chronos <command> --help` for that command's complete option list.
The wizard builds standard `run` commands; use the dedicated commands below
for the new local diagnostics.

In `compare`, `*` links a result/metric to the cautions below the table.
Missing metadata is reported as incomplete, even when absent from both files.
Throughput percentages use exact completion counts on both sides, or are marked
`~` when both use word estimates. Exact-versus-estimated or mixed counts have
no throughput percentage (`n/a`); TTFT and RAM deltas remain independent of that
restriction. Differences in hardware or model still allow descriptive deltas.
See [local comparison rules](docs/methodology.md#local-comparison-and-history).

With the Unreleased CLI changes, `--repeat` also reports median, quartiles,
MAD and available session counts for throughput, TTFT and system RAM.
`compare --series-a-size N` uses the first N files as series A and the rest
as B, comparing their medians. Each complete session counts once; copied
results do not increase the sample. These are descriptive summaries, without
confidence intervals or automatic claims that one configuration is better.
See [repeated-session statistics](docs/methodology.md#repeating-a-run).

## Local Diagnostics

These commands are not additional public benchmark profiles:

| Command | Purpose and main limit | Default report directory |
| --- | --- | --- |
| `concurrency` | Simultaneous requests to one server; client concurrency does not prove parallel model execution | `results/local/concurrency/` |
| `matrix` | Rotating, preflighted runs across explicit engine/model pairs; does not prove identical model artifacts or isolated conditions | `results/local/matrix/` |
| `context` | TTFT versus requested input length; not pure prefill speed or proof that a server retained the whole input | `results/local/context/` |
| `energy` | Experimental macmon system-power estimate with a separate no-request window; not model-only or wall-plug energy | `results/local/energy/` |

Start with small workloads on memory-constrained Macs. None of these commands
starts or stops an engine server. `context`, `concurrency` and `energy` reports
are not sealed benchmark results and cannot be submitted. A matrix manifest
cannot be submitted either; its individual standard results must be validated
separately, and passing validation does not prove that the engines used the
same weights or runtime conditions.

See [Methodology](https://github.com/igurss/mlx-chronos/blob/main/docs/methodology.md) for defaults, cache evidence, warm-up,
cooldown, report fields and interpretation limits. The leaderboard's filtered
CSV/JSON exports and chart are described [there too](https://github.com/igurss/mlx-chronos/blob/main/docs/methodology.md#leaderboard-export-and-chart);
exports are index data, not sealed result files.

---

## Configuration

### Reusable run configurations

Available from `main` with the Unreleased CLI changes:

```bash
# Save resolved settings only; no engine or benchmark is started.
mlx-chronos run --engine omlx --model ORG/MODEL --repeat 5 --save-config experiment.json

# Start a new experiment with those settings.
mlx-chronos run --config experiment.json --output-dir results/local/after-update

# Explicit options override saved values.
mlx-chronos run --config experiment.json --repeat 3
```

The file stores explicit defaults and a benchmark-protocol reference. Unknown
settings, invalid types and incompatible formats/protocols are rejected. Result
folders and contributor attribution stay local to each invocation. Saved
settings do not certify equal model files or runtime conditions. See
[configuration details](docs/methodology.md#reusable-run-configurations).

### Server settings

| Setting | Example | What it changes |
| --- | --- | --- |
| `MLX_CHRONOS_<ENGINE>_PORT` | `MLX_CHRONOS_OMLX_PORT=8002` | Overrides an engine server port |
| `MLX_CHRONOS_CACHED_TTFT_RATIO` | `MLX_CHRONOS_CACHED_TTFT_RATIO=0.8` | Sets the cached-TTFT warning threshold |
| `MLX_CHRONOS_DISABLE_UPDATE_CHECK` | `MLX_CHRONOS_DISABLE_UPDATE_CHECK=1` | Disables automatic background update checks |
| `MLX_CHRONOS_SUBMIT_ENDPOINT` | `https://example.test/form` | Overrides the maintainer inbox endpoint |
| `MLX_CHRONOS_SUBMITTER_EMAIL` | `you@example.com` | Contact address attached to inbox submissions |

Default engine ports:

| Engine | Default port |
| --- | --- |
| oMLX | `8000` |
| Rapid-MLX | `8001` |
| vllm-mlx | `8000` |
| mlx-lm | `8080` |
| Ollama | `11434` |
| LM Studio | `1234` |

oMLX and vllm-mlx both default to port `8000`. To avoid mislabeling results,
mlx-Chronos checks the oMLX listener process with `lsof`; if that process cannot
be inspected, oMLX validation may fail even when `/v1/models` responds.

---

## Benchmark Protocol

`mlx-chronos run` executes a fixed protocol against the running engine. The JSON
result records exact prompt text, token bounds, benchmark profile, timing
metadata, hardware metadata, and an integrity seal.

### What does the protocol number mean?

`Protocol: 4` on the leaderboard, `baseline 4` in a report, and
`meta.benchmark_protocol.version` in JSON identify the **revision of the
benchmark method and validation rules**. The number is separate from the CLI
and app versions; it is not a performance score. `baseline` and `sustained`
are test profiles and use the same protocol revision.

CLI `0.5.1` uses `4`, while release `0.5.0` uses `3`. Older measurements keep
their original labels and seals. A newer protocol requires a new benchmark
run, never a manual change to an existing JSON. See
[what each protocol number means](docs/methodology.md#what-does-the-protocol-number-mean)
for the history of labels `1`–`4`, comparison limits, and submission rules.

### Measurement Flow

| Phase | What happens |
| --- | --- |
| Hardware detection | Captures chip, machine model, memory, macOS, Python, architecture, battery state, Low Power Mode, and thermal context when available |
| Warmup | Uses a separate prompt so same-run prefix/KV cache hits do not remove throughput prefill work |
| Cold TTFT | Uses unique prompts inside the run to avoid same-run cache hits |
| Cached TTFT | Primes one fixed prompt, then measures consecutive cached trials |
| Throughput | Uses fixed protocol prompts and deterministic generation parameters |
| RAM and thermal tracking | Samples system RAM, diagnostic engine RSS, phase timings, and thermal state where available |
| Result sealing | Adds a tamper-evident integrity seal for public-submission validation |

### Important Details

- Requests use deterministic generation parameters: `temperature=0.0` and
  `top_p=1.0`.
- Throughput is end-to-end request throughput, not pure decode speed. It
  includes request overhead, prefill, and decode.
- Timed TTFT and throughput requests are never retried. A transient request
  failure invalidates the run instead of becoming part of a published timing.
  A specific rejection of `stream_options.include_usage` permits a fresh-timed
  compatibility attempt without that option; fallback token estimates are not
  publishable.
- TTFT normally ends at the first content, reasoning or text delta. With no
  visible output, a terminal `finish_reason=length` also counts as a signal
  for the one-token TTFT request; it is not proof of visible-text latency.
- Cached TTFT is recorded only after cache priming completes successfully.
- Rapid-MLX uses exact IDs returned by `/v1/models`; short suffixes are not
  resolved automatically because aliases can be ambiguous in multi-model serving.
- When Rapid-MLX exposes cache-control evidence, the result records whether
  the cold cache was cleared and whether cached prefix reuse was verified.
- Decode throughput records first-content-to-stream-end elapsed time so the
  value can be reconstructed from raw completion-token counts.
- Throughput raw trials also retain the server `finish_reason` when supplied,
  so natural EOS can be distinguished from a `max_tokens` limit.
- All seven adapters retain available `usage.prompt_tokens` from the same
  throughput requests in `meta.benchmark_protocol.throughput.input_tokens`,
  aligned with trial order. Missing counts stay unknown; input is never estimated.
- Throughput prompts intentionally vary to reduce cache artifacts, so run
  standard deviation includes workload variation plus system and engine noise.
- If an engine cannot provide reliable `usage.completion_tokens`, the run falls
  back to a local estimate and is marked as not leaderboard-comparable.
- p95 is reported only when at least 20 trials are available.
- The default baseline run uses 5 trials. The maximum prompt pool supports 30
  unique cold and throughput prompts.

### Sustained Profile

`--profile sustained` runs one long throughput trial with `max_tokens=1000` by
default and records progress samples every 100 generated output units.
Intermediate samples are estimates when the stream only reports exact token
usage at the end.

The sustained throttling warning requires both a late-run estimated throughput
drop and an observed thermal-state change or non-nominal thermal state. It
compares early and late progress-window averages, excluding prefill and
incompatible token-count transitions. This is a conservative warning, not
proof of thermal throttling or a specific hardware cause.

### Cooldown Metadata

Before each run, mlx-Chronos checks the latest prior JSON result in the same
output directory. The elapsed time is saved as
`meta.elapsed_since_last_benchmark_seconds`.

Use `--cooldown-seconds` to enforce a pause before starting another run. The
default recent-run warning threshold is 300 seconds.

For a fuller explanation, see
[docs/methodology.md](https://github.com/igurss/mlx-chronos/blob/main/docs/methodology.md).

---

## Leaderboard Rules

Local runs are intentionally flexible. You can change trial count, profile,
output token bounds, cooldown, connection mode, notes, and other parameters for
your own diagnostics.

Public leaderboard submissions are stricter so rows remain comparable.

### Publishable Profiles

| Profile | Trials | `max_tokens` | Minimum generated output | `min_tokens` |
| --- | ---: | ---: | ---: | --- |
| Baseline | 5 | 100 | 80 tokens | Not allowed |
| Sustained | 1 | 1000 | 800 tokens | Not allowed |

### Public Submission Requirements

- Throughput must use the engine response's `usage.completion_tokens`.
- The result must include `model.reference_url`, a link to the model used.
- The inference engine version must be known; `engine.version=unknown` is not
  accepted for public comparison.
- Hardware must report an Apple M-series chip, `arm64`, and a valid macOS
  version; timestamps may not be more than 10 minutes in the future.
- All warmup calls must complete successfully (`warmup_failures=0`).
- System RAM, engine RSS, and continuous Foundation thermal monitoring must
  complete without sampling errors.
- macOS Low Power Mode must be disabled.
- Decode throughput must include reconstructible raw decode elapsed time.
- The JSON must pass `mlx-chronos submit --dry-run`.
- The result must include a valid integrity seal.
- The archive rejects duplicate integrity digests and duplicate run identities.
- Custom token bounds, fallback token estimates, custom public-profile trial
  counts, short-output runs, and Low Power Mode runs are valid local records but
  are not accepted into the public leaderboard.

Result JSON records the
[benchmark protocol revision](docs/methodology.md#what-does-the-protocol-number-mean)
automatically, so validators can check which measurement rules apply.
Model reference URLs point to the model page used for the run. Model pages can
change over time when maintainers update files or tags.
Leaderboard comparisons keep model name, quantization, format, model
reference URL, and protocol revision separate so distinct variants are not
grouped together.
The full reference URL is retained, including revision or file paths; no
repository-only `canonical_id` merges results. A server's model ID selects
what to run, but does not independently prove artifact identity.

---

## Submit Results

### Pull Request Workflow

1. Run `mlx-chronos run --publishable` on your Mac.
2. Find the generated JSON in `results/local/`.
3. Validate it locally:

   ```bash
   mlx-chronos submit --file results/local/your-result.json --dry-run
   ```

4. Copy the checked JSON into `results/submitted/` with a clear filename.
5. Open a pull request with only that JSON file changed.
6. GitHub Actions labels the PR as `result-submission`, validates schema and
   integrity, and the maintainer reviews it before merge.

> **Warning**
> Do not edit submitted JSON by hand after the run. Public submissions include
> an `integrity` seal over the canonical result payload; changing any benchmark
> field invalidates that seal.

### Inbox Fallback

If opening a PR is inconvenient, send a validated result directly:

```bash
mlx-chronos submit --file results/local/your-result.json
```

Pass `--email you@example.com` (or set `MLX_CHRONOS_SUBMITTER_EMAIL`) so
maintainers can reply about your submission. Without it, the inbox uses an
anonymous placeholder contact address, never the maintainer's address.
Public attribution is separate: `run --submitted-by <handle>` records the
optional handle in the sealed JSON, and it remains present even if no email
is supplied. Omitting an email therefore does not anonymize an attributed
result. Neither an email nor a handle is required for eligibility; do not add
a handle by editing an already sealed JSON file.

Maintainers can override the inbox endpoint with `--endpoint` or
`MLX_CHRONOS_SUBMIT_ENDPOINT`.

See [CONTRIBUTING.md](https://github.com/igurss/mlx-chronos/blob/main/CONTRIBUTING.md)
for detailed contributor instructions.

---

## Documentation and Development

- [macOS app user guide](https://github.com/igurss/mlx-chronos/blob/main/apps/mlx-chronos-mac/USER_GUIDE.md): setup, tests, options, results and local-data behavior.
- [macOS app changelog](https://github.com/igurss/mlx-chronos/blob/main/apps/mlx-chronos-mac/CHANGELOG.md): the app's independent release history.
- [Changelog](https://github.com/igurss/mlx-chronos/blob/main/CHANGELOG.md): released changes and the current Unreleased section.
- [Methodology](https://github.com/igurss/mlx-chronos/blob/main/docs/methodology.md): measurement definitions, diagnostic limits,
  model-reference policy and public validation rules.
- [Contributing](https://github.com/igurss/mlx-chronos/blob/main/CONTRIBUTING.md): engine setup, submissions and local CI checks.
- [Release checklist](https://github.com/igurss/mlx-chronos/blob/main/docs/releasing.md): manual package validation before
  tagging, and the separate publication step.

Features listed as not measured are limitations, not release commitments.
Discuss proposals through [GitHub issues](https://github.com/igurss/mlx-chronos/issues).

---

## License

The CLI and macOS app source use Apache 2.0. See
[LICENSE](https://github.com/igurss/mlx-chronos/blob/main/LICENSE) and the app's
[downloaded runtime notices](https://github.com/igurss/mlx-chronos/blob/main/apps/mlx-chronos-mac/THIRD_PARTY_NOTICES.md).
