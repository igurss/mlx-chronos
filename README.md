# mlx-Chronos ⏱️

> Benchmark suite and community leaderboard for local LLM inference on Apple Silicon.  
> Run it. Share your results. Compare across hardware.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-green.svg)](https://python.org)
[![Apple Silicon](https://img.shields.io/badge/Apple_Silicon-M1_|_M2_|_M3_|_M4_|_M5-black?logo=apple)](https://apple.com)
[![Contributions Welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg)](CONTRIBUTING.md)

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
- [mlx-lm (Apple MLX)](https://github.com/ml-explore/mlx-examples)

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
to first real token. Each trial uses a unique prompt to avoid cache hits.

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
pip install git+https://github.com/igurss/mlx-chronos.git

# Check available engines
mlx-chronos engines

# Run benchmark (JSON by default)
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit"

# Optional: also write a Markdown summary
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --format markdown

# Optional: choose a custom output directory
mlx-chronos run --engine omlx --model "Qwen3.5-4B-OptiQ-4bit" --output-dir results/local
```

> **Note:** the engine server must be running before you launch mlx-chronos.
> See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions.

---

## Contributing Your Results

1. Run `mlx-chronos run` on your Mac
2. A JSON file is generated in `results/local/` (use `--format all` for a Markdown summary too)
3. Fork this repo and copy the JSON you want to publish into `results/submitted/`
4. GitHub Actions validates your result automatically
5. Once merged, the leaderboard updates

Leaderboard submissions must report throughput using the engine response's
`usage.completion_tokens`. Local runs can still be saved with a fallback token
estimate, but those results are not accepted for the public leaderboard.

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed instructions.

---

## Benchmark Methodology

See [docs/methodology.md](docs/methodology.md) for a full explanation of what
is measured, how, and why.

---

## Roadmap

- [x] Project structure
- [x] Hardware detection (chip, RAM, macOS)
- [x] JSON result schema (Pydantic)
- [x] oMLX integration
- [x] Statistical benchmark (repeated trials, mean/stddev/min/max)
- [x] CLI (`mlx-chronos run`, `mlx-chronos engines`)
- [X] Rapid-MLX integration
- [X] mlx-lm integration
- [X] GitHub Actions result validator
- [X] GitHub Pages leaderboard

---

## License

Apache 2.0 — see [LICENSE](LICENSE)
