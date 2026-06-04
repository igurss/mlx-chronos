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
- **Output tokens** — Completion token counts for throughput trials
- **System RAM peak** — Peak total Mac RAM in use during the benchmark, used as the public memory comparison metric
- **Engine RSS** — Diagnostic peak RSS of the engine server process when available
- **Tool calling** — Success rate *(coming in v0.2)*

---

## How It Works

When you run mlx-Chronos, it executes a fixed benchmark protocol against the
running engine:

**Cold TTFT** — sends a prompt to the model and measures the time from request
to first non-empty streamed token, including whitespace-only text tokens. Each
trial uses a unique prompt to avoid cache hits.

**Cached TTFT** — sends the same fixed prompt on every cached trial. A priming
call loads it into cache first, then cached trials run consecutively. This
measures cache performance without interleaving unrelated prompts between
cached measurements.

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
where non-nominal thermal state was observed.

**Peak engine RSS** — records the resident memory of the engine server process
after warmup, through the recorded benchmark phases, when the process can be
identified. This is diagnostic only: it is not total model memory or a public
efficiency ranking metric, because macOS/Metal unified-memory accounting can
vary across environments. The default RAM sampling interval is 50ms and can be
changed with `--ram-sample-interval`.

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

View the full leaderboard with all submitted results:

**[→ igurss.github.io/mlx-chronos](https://igurss.github.io/mlx-chronos)**

The leaderboard supports model search plus engine, chip, machine model, and
memory filters so contributors can quickly compare a specific model across
local inference engines and Apple Silicon hardware.

---

## Current Release

`0.1.1` is a compatibility-preserving patch release over `0.1.0`. It adds the
submission helper, stricter result validation, clearer TTFT and memory
methodology, completion-token visibility, benchmark-condition warnings, and
mock OpenAI-compatible integration coverage.

---

## Quick Start

```bash
# Install
pip install mlx-chronos

# Check available engines
mlx-chronos engines

# Validate setup before a run
mlx-chronos validate --engine omlx --model "Qwen3.5-4B-OptiQ-4bit"

# Run benchmark (JSON by default)
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit"

# Optional: request throughput output token bounds
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --max-tokens 100 --min-tokens 80

# Optional: write both JSON and Markdown outputs
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --format all

# Optional: choose a custom output directory
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --output-dir ~/Desktop/benchmarks
```

> **Note:** the engine server must be running before you launch mlx-chronos.
> See [CONTRIBUTING.md](https://github.com/igurss/mlx-chronos/blob/main/CONTRIBUTING.md) for setup instructions.

---

## Contributing Your Results

1. Run `mlx-chronos run` on your Mac
2. A JSON file is generated in `results/local/` (use `--format all` for a Markdown summary too)
3. Check the result without sending it:
   ```bash
   mlx-chronos submit --file results/local/your-result.json --dry-run
   ```
4. Send the JSON to the maintainer inbox:
   ```bash
   mlx-chronos submit --file results/local/your-result.json
   ```
5. The maintainer reviews accepted JSON files and publishes verified results manually

Leaderboard submissions must report throughput using the engine response's
`usage.completion_tokens`. Local runs can still be saved with a fallback token
estimate, but those results are not accepted for the public leaderboard.

Maintainers can override the public inbox endpoint with `--endpoint` or the
`MLX_CHRONOS_SUBMIT_ENDPOINT` environment variable. The command sends the JSON
file as `result_json` plus brief form metadata so the inbox provider does not
classify the submission as blank spam. To include a real contact address, pass
`--email` or set `MLX_CHRONOS_SUBMITTER_EMAIL`.

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
- [x] Continuous engine RSS and system RAM peak sampling
- [x] Preflight validation for engine, server, and model access
- [x] GitHub Actions validation for submitted results
- [x] GitHub Pages leaderboard with model search and engine/chip/machine/memory filters
- [x] JSON and Markdown result export
- [x] `mlx-chronos submit` for sending validated JSON results to the maintainer inbox
- [x] Published Apple M2 sample results refreshed with the current benchmark protocol
- [x] Warnings for battery mode, Low Power Mode, non-nominal thermal state, and unavailable thermal state
- [x] Integration tests against mock OpenAI-compatible servers
- [x] Larger fixed cold-prompt pool with optional p95 reporting for larger runs
- [x] Request-throughput timing metadata and client-observed streaming decode throughput
- [x] Phase timing metadata and lightweight continuous thermal monitoring

### Next
- [ ] Add richer benchmark condition metadata without breaking the v0.1 JSON contract

### Future
- [ ] Evaluate a clearer TTFT naming model without breaking the v0.1 JSON contract
- [ ] Add tool-calling success-rate benchmarks
- [ ] Explore anti-spoofing checks for community submissions
- [ ] Document external contributor branch workflow when community PRs start arriving
- [ ] Collect more results from M3, M4, and M5 systems

---

## License

Apache 2.0 — see [LICENSE](https://github.com/igurss/mlx-chronos/blob/main/LICENSE)
