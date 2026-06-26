# mlx-Chronos

> Benchmark suite and community leaderboard for local LLM inference on Apple Silicon.
> Run a reproducible benchmark, save a sealed JSON result, and compare engines across Macs.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/igurss/mlx-chronos/blob/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/mlx-chronos.svg)](https://pypi.org/project/mlx-chronos/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-green.svg)](https://python.org)
[![Apple Silicon](https://img.shields.io/badge/Apple_Silicon-M1_|_M2_|_M3_|_M4_|_M5-black?logo=apple)](https://apple.com)
[![Contributions Welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg)](https://github.com/igurss/mlx-chronos/blob/main/CONTRIBUTING.md)

## Start Here

If you already have a supported local engine server running on an Apple Silicon
Mac, the shortest path is:

```bash
pip install mlx-chronos
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
- [Quick Start](#quick-start)
- [Overview](#overview)
- [Supported Engines](#supported-engines)
- [CLI Reference](#cli-reference)
- [Configuration](#configuration)
- [Benchmark Protocol](#benchmark-protocol)
- [Leaderboard Rules](#leaderboard-rules)
- [Submit Results](#submit-results)
- [Roadmap](#roadmap)

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
| TTFT cold | Time from request start to first non-empty streamed token with cache-avoiding prompts | Yes |
| TTFT cached | Time to first token after a cache-priming call with the same prompt | Yes |
| Request throughput | Completion tokens divided by full client-observed request time | Yes, when engine token usage is reliable |
| Sustained throughput | Optional long throughput run for heat buildup and late-run degradation | Yes, under the sustained profile |
| System RAM peak | Peak total Mac RAM in use during the benchmark | Yes |
| Engine RSS | Post-warmup RSS of the engine server process when identifiable | Diagnostic only |
| Thermal state | Start, end, worst state, samples, and affected benchmark phases when available | Context metadata |
| Tool calling | Planned future success-rate benchmark | Not yet available |

### Current Release

`0.3.1` simplifies public model identity metadata to model name,
quantization, model format, and the required model reference URL, while keeping
the guided workflows, timing metadata, and stricter leaderboard integrity
checks introduced in `0.3.0`.

---

## Supported Engines

| Engine | Project | Notes |
| --- | --- | --- |
| Ollama | [ollama/ollama](https://github.com/ollama/ollama) | MLX backend |
| oMLX | [jundot/omlx](https://github.com/jundot/omlx) | OpenAI-compatible server |
| Rapid-MLX | [raullenchai/Rapid-MLX](https://github.com/raullenchai/Rapid-MLX) | OpenAI-compatible server |
| vllm-mlx | [waybarrios/vllm-mlx](https://github.com/waybarrios/vllm-mlx) | OpenAI-compatible server |
| mlx-lm | [ml-explore/mlx-lm](https://github.com/ml-explore/mlx-lm) | Apple MLX |

> **Note**
> The engine server must already be running before `mlx-chronos run`,
> `mlx-chronos models`, or `mlx-chronos validate` can query it.
> See [CONTRIBUTING.md](https://github.com/igurss/mlx-chronos/blob/main/CONTRIBUTING.md)
> for engine setup details.

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

```bash
pip install mlx-chronos
```

Optional thermal-state support through macOS Foundation/PyObjC:

```bash
pip install "mlx-chronos[thermal]"
```

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
mlx-chronos engines
mlx-chronos models --engine omlx
mlx-chronos validate --engine omlx --model "Qwen3.5-4B-OptiQ-4bit"
```

Use `mlx-chronos engines` first if you are not sure which supported server is
installed or currently reachable. Then use `mlx-chronos models` to copy the
exact model ID exposed by that server.

### 5. Use the Interactive Wizard

```bash
mlx-chronos wizard
```

The wizard provides a terminal menu for common actions and a guided benchmark
builder with engine, model, profile, token bounds, output format, cooldown,
preflight, notes, and other run options. When the selected engine server is
running, the wizard loads `/models` and lets you select a model from the exposed
IDs, with manual entry as a fallback. Before launching a benchmark, it shows the
equivalent `mlx-chronos run ...` command so the same configuration can be reused
in scripts. You can return to the main menu from benchmark setup without
starting a run.

### 6. Run a Benchmark Manually

```bash
mlx-chronos run \
  --engine omlx \
  --model "Qwen3.5-4B-OptiQ-4bit" \
  --model-url "https://huggingface.co/mlx-community/Qwen3.5-4B-OptiQ-4bit"
```

Results are written to `results/local/` by default. The model URL is optional
for private local experiments, but required if you want the result to pass the
public leaderboard checks.

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

# Write both JSON and Markdown outputs
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --format all

# Choose a custom output directory
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --output-dir ~/Desktop/benchmarks

# Request throughput output token bounds for local experiments
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --max-tokens 100 --min-tokens 80

# Run the longer heat/throttling-sensitive sustained profile
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --profile sustained

# Enforce cooldown after a recent run in the same output directory
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --cooldown-seconds 300

# Fail fast with an extra model access probe before measured work starts
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --preflight

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
| `mlx-chronos wizard` | Open an interactive menu for common commands and guided benchmark setup |
| `mlx-chronos upgrade` | Check PyPI and upgrade the current Python environment if a newer release exists |
| `mlx-chronos engines` | List supported engines and local installed/running status |
| `mlx-chronos models --engine <name>` | List model IDs exposed by a running engine server |
| `mlx-chronos validate --engine <name> --model <model>` | Validate hardware, engine, server, and optional model access |
| `mlx-chronos run --engine <name> --model <model>` | Run a benchmark and save local result files |
| `mlx-chronos submit --file <result.json> --dry-run` | Validate whether a result is publishable |
| `mlx-chronos submit --file <result.json>` | Send a validated result to the maintainer inbox |

---

## Configuration

| Setting | Example | What it changes |
| --- | --- | --- |
| `MLX_CHRONOS_<ENGINE>_PORT` | `MLX_CHRONOS_OMLX_PORT=8002` | Overrides an engine server port |
| `MLX_CHRONOS_CACHED_TTFT_RATIO` | `MLX_CHRONOS_CACHED_TTFT_RATIO=0.8` | Sets the cached-TTFT warning threshold |
| `MLX_CHRONOS_DISABLE_UPDATE_CHECK` | `MLX_CHRONOS_DISABLE_UPDATE_CHECK=1` | Disables automatic background update checks |
| `MLX_CHRONOS_SUBMIT_ENDPOINT` | `https://example.test/form` | Overrides the maintainer inbox endpoint |

Default engine ports:

| Engine | Default port |
| --- | --- |
| oMLX | `8000` |
| Rapid-MLX | `8001` |
| vllm-mlx | `8000` |
| mlx-lm | `8080` |
| Ollama | `11434` |

oMLX and vllm-mlx both default to port `8000`. To avoid mislabeling results,
mlx-Chronos checks the oMLX listener process with `lsof`; if that process cannot
be inspected, oMLX validation may fail even when `/v1/models` responds.

---

## Benchmark Protocol

`mlx-chronos run` executes a fixed protocol against the running engine. The JSON
result records exact prompt text, token bounds, benchmark profile, timing
metadata, hardware metadata, and an integrity seal.

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
- Cached TTFT is recorded only after cache priming completes successfully.
- Decode throughput records first-content-to-stream-end elapsed time so the
  value can be reconstructed from raw completion-token counts.
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

If the sustained run observes a thermal-state change or non-nominal thermal
state, result metadata includes a sustained throttling warning. The warning
compares early and late progress-window averages, not a single first/last
sample.

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

Result JSON also contains validator-only compatibility metadata used to detect
incompatible result formats. Users do not need to set or manage that metadata.
Model reference URLs point to the model page used for the run. Model pages can
change over time when maintainers update files or tags.
Leaderboard comparisons keep model name, quantization, format, and model
reference URL separate so distinct variants are not grouped together.

---

## Submit Results

### Pull Request Workflow

1. Run `mlx-chronos run` on your Mac.
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

Maintainers can override the inbox endpoint with `--endpoint` or
`MLX_CHRONOS_SUBMIT_ENDPOINT`.

See [CONTRIBUTING.md](https://github.com/igurss/mlx-chronos/blob/main/CONTRIBUTING.md)
for detailed contributor instructions.

---

## Roadmap

### Completed

- [x] Core benchmark runner with repeated trials, warmup, cache priming, and phase-separated metrics
- [x] Engine support for oMLX, Rapid-MLX, vllm-mlx, mlx-lm, and Ollama
- [x] Hardware detection for chip, machine model, memory, macOS, Python, architecture, and thermal state
- [x] Strict JSON schema validation with raw-trial consistency checks
- [x] Continuous system RAM peak sampling, with post-warmup engine RSS kept as a diagnostic field
- [x] Preflight validation for engine, server, and model access
- [x] GitHub Actions validation for submitted results
- [x] PR-based result submissions with automatic `result-submission`, `code`, and `documentation` labels
- [x] GitHub Pages leaderboard with model/chip/RAM engine comparison and configurable raw-data columns
- [x] JSON and Markdown result export
- [x] `mlx-chronos submit` for sending validated JSON results to the maintainer inbox
- [x] Warnings for battery mode, Low Power Mode, non-nominal thermal state, and unavailable thermal state
- [x] Integration tests against mock OpenAI-compatible servers
- [x] Larger fixed cold-prompt pool with optional p95 reporting for larger runs
- [x] Request-throughput timing metadata and client-observed streaming decode throughput
- [x] Phase timing metadata and lightweight continuous thermal monitoring
- [x] Sustained benchmark profile, cooldown metadata, and strict local-vs-public leaderboard policy
- [x] Public submission trust model with lightweight anti-spoofing checks
- [x] External contributor workflow for code PRs and leaderboard result submissions
- [x] CLI update notifications and `mlx-chronos upgrade`

### Future

- [ ] Evaluate a clearer TTFT naming model without breaking the v0.1 JSON contract
- [ ] Add tool-calling success-rate benchmarks
- [ ] Collect more results from M3, M4, and M5 systems

---

## License

Apache 2.0. See [LICENSE](https://github.com/igurss/mlx-chronos/blob/main/LICENSE).
