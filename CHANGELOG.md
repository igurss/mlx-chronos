# Changelog

## [Unreleased]

## [0.1.0] — 2026-05-27

Official v0.1.0 release notes, compared with `v0.1.0-beta.1`
(`9d1bed23bf938e602ebef15b7a5e10ad5064488b`).

### Added
- **Ollama** engine support (MLX backend, port 11434).
- **mlx-lm** engine support and improved oMLX/Rapid-MLX/Ollama engine integration.
- Continuous engine RSS and system RAM peak sampling during benchmark runs.
- Explicit result metadata for token-count source, RAM measurement method, hardware architecture, machine model, and timezone-aware timestamps.
- Configurable engine ports via `MLX_CHRONOS_<ENGINE>_PORT` environment variables.
- JSON and Markdown output support through reporter classes.
- Unit test suite and GitHub Actions coverage for schema, benchmark, engine, CLI, and hardware-detection behavior.
- Apple M2 benchmark submissions for oMLX, Rapid-MLX, mlx-lm, and Ollama.

### Changed
- TTFT now measures the first real streamed content token, uses `time.perf_counter()`, and runs cold TTFT, cached TTFT, and throughput in separate phases.
- Result validation is stricter: engine names are controlled, numeric fields are non-negative, raw trial arrays must match trial count, and summary statistics must match raw values.
- Leaderboard submissions are validated from the shared Pydantic schema and must use `usage.completion_tokens` for comparable throughput.
- Leaderboard rendering now escapes submitted values, sorts strings correctly, and displays engine RSS separately from total system RAM peak.
- Documentation now reflects the current benchmark methodology, memory semantics, submission flow, and supported engines.

### Removed
- **llama.cpp** engine — out of scope. mlx-Chronos benchmarks MLX inference engines only; llama.cpp runs GGUF models, not MLX.
- Legacy `requirements.txt`, old report module, model `size_gb`, and unreliable pre-run RAM baseline fields.

### Fixed
- Result output paths now resolve from the current working directory, fixing installed-package usage.
- Fixed `mlx-chronos engines` crashing when `mlx-lm` import initializes Metal in restricted environments.
- Improved process detection, engine RSS sampling stability, and fallback hardware detection via `system_profiler`.
- Split local benchmark output from publishable leaderboard submissions and made leaderboard generation fail on invalid submitted JSON.
- Decoupled schema engine-name validation from the engine implementation registry.
- Made Rapid-MLX model ID caching instance-scoped to avoid cross-test leakage.
- Corrected Ollama submitted-result quantization metadata to canonical `bf16`.
- Improved CLI errors and cleaned up logging/output consistency.

## [0.1.0-beta.1] — 2026-05-24

### First public release

**Engines supported:**
- oMLX (port 8000)
- Rapid-MLX (port 8001)

**Features:**
- Hardware auto-detection (chip, RAM, macOS, Python version)
- Standardized benchmark protocol: 5 trials, unique cold prompts, cache priming
- Statistical output: mean, stddev, min, max per metric
- Pydantic schema validation for all results
- CLI: `mlx-chronos run` and `mlx-chronos engines`
- GitHub Actions: automatic result validation on PR
- GitHub Pages leaderboard with sortable table and engine/chip filters
- Community submission workflow via Pull Request

**Known limitations:**
- oMLX version not retrievable when server is already running
- RAM measured as system fallback (process RSS detection pending)
- Tool calling rate not yet implemented
- mlx-lm integration not yet available
