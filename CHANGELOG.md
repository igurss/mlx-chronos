# Changelog

## Unreleased

### Features
- Add benchmark protocol metadata to new result JSON, including exact prompts,
  requested token bounds, and input-token count source.
- Add throughput `--max-tokens` and opt-in `--min-tokens` requests for more
  explicit token-bound comparability.

### Reliability
- Validate usage-based throughput completion counts against requested token
  bounds when those bounds are available.

## [0.1.1] — 2026-06-01

Patch release focused on safer community submissions, clearer leaderboard
semantics, and stronger validation since `0.1.0`.

### Features
- Add `mlx-chronos submit` for validated benchmark result submissions to the maintainer inbox.
- Add dry-run submission validation and optional submitter contact email metadata.
- Add model search plus machine model and memory filters to the leaderboard.
- Add broader leaderboard column tooltips to clarify result fields.
- Add throughput completion-token counts to new benchmark JSON output and the leaderboard.
- Warn during `mlx-chronos validate` and `mlx-chronos run` when thermal state, battery power, or Low Power Mode may make results less comparable.

### Reliability
- Require public submissions to use `usage.completion_tokens` for throughput comparability.
- Send benchmark JSON as `result_json` with minimal form metadata so the inbox provider does not classify submissions as blank spam.
- Keep leaderboard publication manual: maintainers review accepted JSON before adding it to `results/submitted/`.
- Use System RAM Peak as the main public leaderboard memory metric; keep process RSS as diagnostic JSON data.
- Add deterministic integration tests against mock OpenAI-compatible `/v1/models` and `/v1/chat/completions` endpoints.

### Documentation
- Update README and CONTRIBUTING with the inbox submission flow.
- Update methodology notes to include dry-run validation before submission.
- Clarify that TTFT fields measure client-observed streamed-token latency and preserve the v0.1 field names for compatibility.

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
- Add a timeout to the Rapid-MLX version probe to avoid hanging validation or runs.
- Correct Ollama sample quantization metadata and generated leaderboard index.
- Update mlx-lm documentation links to the dedicated upstream repository.
- Run smoke checks and tests on macOS in CI.

### Known Limitations At Release
- oMLX version not retrievable when server is already running.
- Tool calling rate not yet implemented.
- `mlx-chronos submit` helper command was not included in 0.1.0; it is added in 0.1.1.
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
- TTFT measures the first non-empty streamed content/reasoning/text delta and uses a monotonic high-resolution timer.
- Whitespace-only streamed text is counted for TTFT because it is still the first generated token observed from the engine.
- Cold TTFT, cached TTFT, and throughput run in separate phases to avoid cache pollution between metrics.
- Engine RSS and total system RAM are sampled continuously during the benchmark.
- Throughput submissions require `usage.completion_tokens` for comparable leaderboard results.

### Validation and Reliability
- Pydantic schema with strict engine names, timezone-aware timestamps, non-negative metrics, and raw-trial consistency checks.
- GitHub Actions validate submitted results and regenerate the leaderboard index.
- Local benchmark output is separated from publishable leaderboard submissions.
- Unit tests cover schema, benchmark math, SSE parsing, CLI behavior, engine helpers, and hardware detection.
- Documentation covers setup, methodology, memory semantics, and contribution flow.

### Known Limitations At Release
- oMLX version not retrievable when server is already running
- Tool calling rate not yet implemented
- `mlx-chronos validate` and `mlx-chronos submit` helper commands were not included in this beta
- Published sample results currently cover Apple M2 8GB only
