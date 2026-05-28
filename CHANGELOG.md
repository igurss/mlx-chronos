# Changelog

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
