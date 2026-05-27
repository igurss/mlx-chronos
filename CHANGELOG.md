# Changelog

## [Unreleased]

### Added
- **Ollama** engine support (MLX backend, port 11434).
- Comprehensive unit tests using `pytest` for schema validation and benchmark math.
- GitHub Actions workflow for unit tests on code changes.
- Added Literal constraints to `engine.name` in Pydantic schema for strict validation.
- Added non-negative bounds to all numerical fields in the schema.
- Added schema validation for trial raw-list lengths and summary statistic ranges.
- Added configurable RAM sampling interval metadata.
- Added configurable engine ports via `MLX_CHRONOS_<ENGINE>_PORT` environment variables.
- Added explicit `token_count_source`, `ram_measurement_method`, and hardware `architecture` fields to result metadata.
- Added continuous system RAM peak tracking during benchmark runs.

### Removed
- **llama.cpp** engine — out of scope. mlx-Chronos benchmarks MLX inference engines only; llama.cpp runs GGUF models, not MLX.

### Fixed
- Changed `RESULTS_DIR` logic to resolve output directory relative to the current working directory at runtime, fixing PIP installation paths.
- Removed duplicated `logging.basicConfig` preventing log formatting from applying correctly.
- Translated all Italian log messages to English.
- Fixed `mlx-chronos engines` crashing when `mlx-lm` import initializes Metal in restricted environments.
- Fixed TTFT measurement so role/tool metadata chunks are not counted as first content tokens.
- Switched latency timing to `time.perf_counter()` for monotonic high-resolution measurements.
- Improved thermal-state detection with a no-sudo Foundation/NSProcessInfo path when available.
- Fixed leaderboard sorting for string columns and escaped community-submitted values before rendering.
- Improved CLI error output for invalid runtime arguments.
- Split local benchmark output from publishable leaderboard submissions.
- Hardened result validation so summary statistics must match raw trial data.
- Made leaderboard generation fail on invalid submitted JSON instead of silently skipping files.
- Decoupled schema engine-name validation from the engine implementation registry.
- Made Rapid-MLX model ID caching instance-scoped to avoid cross-test leakage.
- Separated cold TTFT, cached TTFT, and throughput phases so cached TTFT is not polluted by interleaved prompts.
- Added a `system_profiler` fallback for Mac chip and machine-model detection when `sysctl` is unavailable.
- Corrected Ollama submitted-result quantization metadata to canonical `bf16`.
- Removed stale one-shot RAM measurement helper now replaced by continuous benchmark sampling.
- Made engine RSS sampling back off cleanly if process access is temporarily denied.

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
