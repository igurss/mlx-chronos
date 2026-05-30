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
- **tok/s** — Generation throughput (mean, stddev, min, max across trials)
- **Engine RSS** — Peak RSS of the engine server process during the benchmark when available
- **System RAM peak** — Peak total Mac RAM in use during the benchmark
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

**Throughput (tok/s)** — measures tokens generated per second using a standard
fixed prompt, identical across all engines and versions.

**Peak engine RSS** — measures the resident memory of the engine server process
after warmup, through the recorded benchmark phases. This is
intentionally not the total memory occupied by the loaded model or by
macOS/Metal unified memory. It is meant to compare how light or heavy each
engine process is while serving the same model. The default RSS sampling
interval is 50ms and can be changed with `--ram-sample-interval`.

**System RAM peak** — continuously samples total Mac RAM usage from before
warmup through the recorded benchmark phases and reports the observed peak in
GB and percent. This is the metric to use when checking whether a run pushed
the machine into memory pressure or swap while the model was actually loading
or serving requests.

All metrics are run over multiple trials and reported with mean, stddev, min,
and max. The default is 5 trials, with a maximum of 8 unique cold prompts.
Results are saved as structured JSON in `results/local/` by default. Copy a
reviewed JSON into `results/submitted/` only when you want to publish it to the
community leaderboard.

---

## Community Leaderboard

View the full leaderboard with all submitted results:

**[→ igurss.github.io/mlx-chronos](https://igurss.github.io/mlx-chronos)**

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
- [x] GitHub Pages leaderboard with engine/chip filters
- [x] JSON and Markdown result export
- [x] `mlx-chronos submit` for sending validated JSON results to the maintainer inbox
- [x] Published Apple M2 sample results refreshed with the current benchmark protocol

### Next
- [ ] Add warnings for battery mode, low power mode, and non-nominal thermal state
- [ ] Improve leaderboard filtering by machine model and add broader column tooltips
- [ ] Add integration tests against mock OpenAI-compatible servers

### Future
- [ ] Support larger trial counts with a bigger cold-prompt pool
- [ ] Add p95 reporting for larger sample sizes
- [ ] Evaluate a clearer TTFT naming model without breaking the v0.1 JSON contract
- [ ] Add tool-calling success-rate benchmarks
- [ ] Explore anti-spoofing checks for community submissions
- [ ] Document external contributor branch workflow when community PRs start arriving
- [ ] Collect more results from M3, M4, and M5 systems

---

## License

Apache 2.0 — see [LICENSE](https://github.com/igurss/mlx-chronos/blob/main/LICENSE)
