# Changelog

## [Unreleased]

## [0.1.0] — 2026-05-27

Official v0.1.0 release notes, compared with `v0.1.0-beta.1`.

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
- Benchmark execution now runs cold TTFT, cached TTFT, and throughput in separate phases.
- Result validation is stricter: engine names are controlled, numeric fields are non-negative, raw trial arrays must match trial count, and summary statistics must match raw values.
- Leaderboard submissions are validated from the shared Pydantic schema and must use `usage.completion_tokens` for comparable throughput.
- Leaderboard rendering now escapes submitted values, sorts strings correctly, and displays engine RSS separately from total system RAM peak.
- Documentation now reflects the current benchmark methodology, memory semantics, submission flow, and supported engines.

### Removed
- Legacy `requirements.txt`, old report module, and model `size_gb` field from result files.

### Fixed
- Result output paths now resolve from the current working directory, fixing installed-package usage.
- TTFT no longer counts streamed metadata chunks as first tokens and now uses a monotonic high-resolution timer.
- Cached TTFT is no longer polluted by interleaved cold/throughput prompts.
- Local benchmark output is separated from publishable leaderboard submissions.
- Hardware detection falls back to `system_profiler` when `sysctl` is unavailable.
- Leaderboard generation now fails on invalid submitted JSON instead of silently skipping files.
- CLI errors, process detection, and engine RSS sampling are more robust.

## [0.1.0-beta.1] — 2026-05-24

### First public pre-release

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
