# mlx-Chronos ⏱️

> Benchmark suite and community leaderboard for local LLM inference on Apple Silicon.  
> Run it. Share your results. Compare across hardware.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/igurss/mlx-chronos/blob/main/LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-green.svg)](https://python.org)
[![Apple Silicon](https://img.shields.io/badge/Apple_Silicon-M1_|_M2_|_M3_|_M4_|_M5-black?logo=apple)](https://apple.com)
[![Contributions Welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg)](https://github.com/igurss/mlx-chronos/blob/main/CONTRIBUTING.md)

---

## What is mlx-Chronos?

mlx-Chronos is a standardized benchmarking tool for local LLM inference engines
on Apple Silicon. It automatically detects your hardware, runs a consistent set
of tests across installed engines, and produces a structured JSON result you can
contribute to the community leaderboard.

**Supported engines:**
- [Ollama](https://github.com/ollama/ollama) (MLX backend)
- [oMLX](https://github.com/jundot/omlx)
- [Rapid-MLX](https://github.com/raullenchai/Rapid-MLX)
- [mlx-lm (Apple MLX)](https://github.com/ml-explore/mlx-lm)

**Metrics measured:**
- **TTFT** — Time to First Token (cold and cached, with statistics)
- **tok/s** — Client-observed request throughput (mean, stddev, min, max across trials)
- **Sustained tok/s** — Optional long throughput profile for heat buildup and late-run degradation checks
- **Output tokens** — Completion token counts for throughput trials
- **System RAM peak** — Peak total Mac RAM in use during the benchmark, used as the public memory comparison metric
- **Post-warmup engine RSS** — Legacy diagnostic peak RSS of the engine server process when available, not a comparison metric
- **Tool calling** — Success rate *(coming in v0.2)*

---

## How It Works

When you run mlx-Chronos, it executes a fixed benchmark protocol against the
running engine:

**Cold TTFT** — sends a prompt to the model and measures the time from request
to first non-empty streamed token, including whitespace-only text tokens. Each
trial uses a unique prompt inside the run to avoid same-run cache hits.

**Cached TTFT** — sends the same fixed prompt on every cached trial. A priming
call loads it into cache first, then cached trials run consecutively. This
measures cache performance without interleaving unrelated prompts between
cached measurements. If cached TTFT is close to cold TTFT, new runs record a
warning that cache reuse may not have happened.

**Request throughput (tok/s)** — measures completion tokens divided by the full
client-observed request time for a standard fixed prompt. This includes request
overhead, prefill, and decode, so it is an end-to-end throughput metric rather
than pure decode speed. New runs also record client-observed
`decode_tokens_per_second` from the streaming throughput trial when reliable
completion-token usage is available. If an engine cannot provide usage in the
streaming response, the run falls back to a local estimate and is marked as not
leaderboard-comparable. Throughput uses a fixed
requested `max_tokens` value by default, and optional output token bounds can be
requested with `--max-tokens` / `--min-tokens`.

**System RAM peak** — continuously samples total Mac RAM usage from before
warmup through the recorded benchmark phases and reports the observed peak in
GB and percent. This is the public leaderboard memory metric because it answers
the practical question of how much memory pressure the run placed on the Mac.

**Thermal monitor** — records phase timings plus a lightweight thermal summary
during the run when macOS thermal state is available through Foundation/PyObjC.
New JSON results include start/end/worst thermal state, sample count, and phases
where non-nominal thermal state was observed. Without PyObjC/Foundation, the
continuous monitor is unavailable even if a one-shot pre-run thermal state can
be read through `powermetrics`.

**Sustained profile** — `--profile sustained` runs a single long throughput
trial with `max_tokens=1000` by default and records progress samples every 100
generated output units. Intermediate samples are estimates when the stream only
reports exact token usage at the end. These samples make late-run throughput
drops easier to spot. When a sustained run also observes a thermal-state change
or non-nominal thermal state, mlx-Chronos records a sustained throttling warning
in result metadata. The warning compares early and late progress-window
averages, not a single first/last sample.

**Cooldown tracking** — before each run, mlx-Chronos checks the latest prior
JSON result in the same output directory. The elapsed time is saved as
`meta.elapsed_since_last_benchmark_seconds`; `--cooldown-seconds` can enforce a
pause before starting a new run. The default recent-run warning threshold is a
300-second heuristic.

**Post-warmup engine RSS diagnostic** — records the resident memory of the
engine server process after warmup, through the recorded benchmark phases, when
the process can be identified. This is retained for debugging and legacy JSON
compatibility only: it is not total model memory and not a public comparison
metric, because macOS/Metal unified-memory accounting can vary across
environments. The default RAM sampling interval is 50ms and can be changed with
`--ram-sample-interval`.

All metrics are run over multiple trials and reported with mean, stddev, min,
and max. p95 is added only when at least 20 trials are available. The default is
5 trials, with a maximum of 30 unique cold prompts.
Results are saved as structured JSON in `results/local/` by default. Maintainers
publish reviewed JSON files into `results/submitted/` after accepting them for
the community leaderboard.
New result JSON also records the benchmark protocol metadata, including exact
prompt text and requested token bounds, so runs can be reproduced without
digging through source code.
Current protocol v2 throughput uses streaming requests with usage metadata.
Older protocol v1 results used non-streaming throughput, so compare those rows
with that workload difference in mind.

---

## Community Leaderboard

Compare submitted results by model, chip, and RAM:

**[→ igurss.github.io/mlx-chronos](https://igurss.github.io/mlx-chronos)**

The default view compares engines for a selected model and Mac configuration.
The raw-data view keeps the full table available with optional columns for
secondary metadata such as protocol, token bounds, thermal state, power source,
Low Power Mode, and engine version.

---

## Current Release

`0.1.3` is a compatibility-preserving patch release over `0.1.2`. It tightens
throughput timing, sustained-run warnings, release checks, and submission
validation, clarifies System RAM Peak as the comparable memory metric, and
keeps Engine RSS as a legacy diagnostic field in the raw result details.

---

## Quick Start

```bash
# Install
pip install mlx-chronos

# Confirm installed version
mlx-chronos --version

# Check available engines
mlx-chronos engines

# List models exposed by a running engine server
mlx-chronos models --engine omlx

# Validate setup before a run
mlx-chronos validate --engine omlx --model "Qwen3.5-4B-OptiQ-4bit"

# Run benchmark (JSON by default)
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit"

# Optional: request throughput output token bounds
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --max-tokens 100 --min-tokens 80

# Optional: sustained profile for a longer heat/throttling-sensitive run
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --profile sustained

# Optional: enforce a pause after a recent run in the same output directory
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --cooldown-seconds 300

# Optional: write both JSON and Markdown outputs
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --format all

# Optional: choose a custom output directory
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --output-dir ~/Desktop/benchmarks
```

> **Note:** the engine server must be running before you launch mlx-chronos.
> See [CONTRIBUTING.md](https://github.com/igurss/mlx-chronos/blob/main/CONTRIBUTING.md) for setup instructions.

Optional thermal-state support through macOS Foundation can be installed with
`pip install "mlx-chronos[thermal]"`. Engine ports can be overridden with
`MLX_CHRONOS_<ENGINE>_PORT`, for example
`MLX_CHRONOS_OMLX_PORT=8002` or `MLX_CHRONOS_MLX_LM_PORT=8002`.

---

## Contributing Your Results

1. Run `mlx-chronos run` on your Mac
2. A JSON file is generated in `results/local/` (use `--format all` for a Markdown summary too)
3. Check the result:
   ```bash
   mlx-chronos submit --file results/local/your-result.json --dry-run
   ```
4. Copy the checked JSON into `results/submitted/` with a clear filename
5. Open a pull request with only that JSON file changed
6. GitHub Actions labels the PR as `result-submission`, validates the schema,
   and the maintainer reviews it before merge

Leaderboard submissions must report throughput using the engine response's
`usage.completion_tokens`. Local runs can still be saved with a fallback token
estimate, but those results are not accepted for the public leaderboard and are
marked with `meta.word_fallback_warning`.

If opening a PR is inconvenient, `mlx-chronos submit --file ...` still sends the
validated JSON to the maintainer inbox as a fallback. Maintainers can override
the inbox endpoint with `--endpoint` or the `MLX_CHRONOS_SUBMIT_ENDPOINT`
environment variable.

See [CONTRIBUTING.md](https://github.com/igurss/mlx-chronos/blob/main/CONTRIBUTING.md) for detailed instructions.

---

## Benchmark Methodology

See [docs/methodology.md](https://github.com/igurss/mlx-chronos/blob/main/docs/methodology.md) for a full explanation of what
is measured, how, and why.

---

## Roadmap

### Completed
- [x] Core benchmark runner with repeated trials, warmup, cache priming, and phase-separated metrics
- [x] Engine support for oMLX, Rapid-MLX, mlx-lm, and Ollama
- [x] Hardware detection for chip, machine model, memory, macOS, Python, architecture, and thermal state
- [x] Strict JSON schema validation with raw-trial consistency checks
- [x] Continuous system RAM peak sampling, with post-warmup engine RSS kept as a diagnostic field
- [x] Preflight validation for engine, server, and model access
- [x] GitHub Actions validation for submitted results
- [x] PR-based result submissions with automatic `result-submission`, `code`, and `documentation` labels
- [x] GitHub Pages leaderboard with model/chip/RAM engine comparison and configurable raw-data columns
- [x] JSON and Markdown result export
- [x] `mlx-chronos submit` for sending validated JSON results to the maintainer inbox
- [x] Published Apple M2 sample results refreshed with the current benchmark protocol
- [x] Warnings for battery mode, Low Power Mode, non-nominal thermal state, and unavailable thermal state
- [x] Integration tests against mock OpenAI-compatible servers
- [x] Larger fixed cold-prompt pool with optional p95 reporting for larger runs
- [x] Request-throughput timing metadata and client-observed streaming decode throughput
- [x] Phase timing metadata and lightweight continuous thermal monitoring
- [x] Sustained benchmark profile, cooldown metadata, and standard/custom token-bound visibility in the leaderboard

### Future
- [ ] Evaluate a clearer TTFT naming model without breaking the v0.1 JSON contract
- [ ] Add tool-calling success-rate benchmarks
- [ ] Explore anti-spoofing checks for community submissions
- [ ] Document external contributor branch workflow when community PRs start arriving
- [ ] Collect more results from M3, M4, and M5 systems

---

## License

Apache 2.0 — see [LICENSE](https://github.com/igurss/mlx-chronos/blob/main/LICENSE)
