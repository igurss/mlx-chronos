# Changelog

## [0.1.0] — 2026-05-28

First public PyPI-ready release.

### Features
- Add `mlx-chronos validate` to preflight hardware detection, engine availability, server health, model listing, and optional model completion checks before running a benchmark.
- Add direct PyPI packaging metadata so the CLI can be installed with `pip install mlx-chronos`.

### Reliability
- Preserve full model identifiers containing `/` in saved benchmark results.
- Reject blank model names before benchmark execution.
- Improve engine/model request errors with attempted URL, engine, model, HTTP status, and response body context.
- Harden engine response parsing so malformed `/models` or completion responses produce controlled `RuntimeError` messages.
- Run smoke checks and tests on macOS in CI.

### Known Limitations
- oMLX version not retrievable when server is already running.
- Tool calling rate not yet implemented.
- `mlx-chronos submit` helper command not yet implemented.
- Published sample results currently cover Apple M2 8GB only.

## [0.1.0b1] — 2026-05-27

First usable public beta of mlx-Chronos, published as tag `v0.1.0-beta.1`.

### Features
- Benchmark CLI for local Apple Silicon inference engines.
- Support for oMLX, Rapid-MLX, mlx-lm, and Ollama.
- Standardized metrics: cold TTFT, cached TTFT, throughput, engine RSS peak, and system RAM peak.
- Hardware detection for chip, machine model, unified memory, macOS, Python, architecture, and thermal state.
- JSON and Markdown result output.
- GitHub Pages leaderboard with engine/chip filters and submitted Apple M2 sample results.

### Benchmark Methodology
- TTFT measures the first real streamed content token and uses a monotonic high-resolution timer.
- Cold TTFT, cached TTFT, and throughput run in separate phases to avoid cache pollution between metrics.
- Engine RSS and total system RAM are sampled continuously during the benchmark.
- Throughput submissions require `usage.completion_tokens` for comparable leaderboard results.

### Validation and Reliability
- Pydantic schema with strict engine names, timezone-aware timestamps, non-negative metrics, and raw-trial consistency checks.
- GitHub Actions validate submitted results and regenerate the leaderboard index.
- Local benchmark output is separated from publishable leaderboard submissions.
- Unit tests cover schema, benchmark math, SSE parsing, CLI behavior, engine helpers, and hardware detection.
- Documentation covers setup, methodology, memory semantics, and contribution flow.

### Known Limitations
- oMLX version not retrievable when server is already running
- Tool calling rate not yet implemented
- `mlx-chronos validate` and `mlx-chronos submit` helper commands not yet implemented
- Published sample results currently cover Apple M2 8GB only
