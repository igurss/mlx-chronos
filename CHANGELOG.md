# Changelog

## Unreleased

### Reliability
- Calculate request throughput from the same rounded elapsed time saved in raw
  trial metadata so valid runs cannot fail schema validation because of
  rounding drift.
- Abort a run when every warmup request fails, and record partial warmup
  failures in new result metadata.
- Record the selected profile name in benchmark protocol metadata so sustained
  runs are not labeled as baseline protocols.
- Reject mixed-content or deletion PRs in the submitted-result validation
  workflow.
- Extend CI coverage to Python 3.14 and leaderboard JavaScript syntax checks.
- Read the leaderboard's standard throughput token bound from generated index
  metadata instead of duplicating the protocol default in JavaScript.
- Compare sustained-throughput early/late window averages and require enough
  progress intervals before emitting a throttling warning.
- Avoid matching arbitrary Python processes as engine servers when locating the
  listening process for RSS sampling.
- Warn when cached TTFT is close to cold TTFT, since prompt/KV cache reuse may
  not have occurred.
- Avoid re-reading and re-validating benchmark JSON during `mlx-chronos submit`
  after the CLI has already loaded a publishable result.
- Derive runtime benchmark profile validation from the schema `BenchmarkProfile`
  literal so CLI/runtime and Pydantic validation cannot drift.
- Ignore sustained-throughput interval drops that cross from word-fallback
  progress estimates to final usage-token counts.
- Record power source and Low Power Mode in new result JSON and reuse those
  values for benchmark condition warnings.
- Share sampling, cooldown, phase-timing, and HTTP excerpt constants from one
  module.
- Test release tags against the `pyproject.toml` version before publishing and
  run release tests on the same Python matrix as CI.
- Warn when a benchmark runs with fewer than 3 trials, since single-trial
  standard deviation is reported as `0.0` but has low statistical value.
- Type `engine.name` as an explicit schema literal while preserving the existing
  engine-name validation message.
- Add direct coverage for the Foundation/PyObjC thermal-state import fallback.

### Features
- Add `mlx-chronos --version` and `mlx-chronos models --engine ...`.
- Add automatic pull-request labels for benchmark result submissions, code
  changes, and documentation-only changes.
- Redesign the public leaderboard around a model/chip/RAM compare view, while
  keeping raw submitted data available behind configurable optional columns.
- Expose decode throughput, power source, and Low Power Mode in the generated
  leaderboard index when results provide them.
- Add an optional `thermal` install extra for PyObjC/Foundation thermal-state
  detection.

### Documentation
- Clarify that cold TTFT prompts avoid same-run cache hits but cannot prove a
  server had no matching cache state from an earlier process.
- Clarify that sustained progress samples are estimated unless the stream
  provides exact usage before the final chunk.
- Document the cached-TTFT warning, post-warmup scope of engine RSS, sustained
  throttling heuristic, decode-throughput assumption, and 300-second cooldown
  warning heuristic.
- Document the PR-first benchmark submission flow while keeping the maintainer
  inbox as a fallback path.
- Document benchmark port overrides, optional thermal install support, warmup
  token bounds, and the RAM sampling start-point asymmetry.
- Note that legacy `metrics.tokens_per_second` mirrors
  `metrics.request_tokens_per_second` for compatibility and is expected to be
  revisited in the v0.2 schema cleanup.

## [0.1.2] — 2026-06-05

Patch release focused on benchmark comparability, sustained-run visibility, and
clearer local result warnings since `0.1.1`.

### Features
- Add benchmark protocol metadata to new result JSON, including exact prompts,
  requested token bounds, and input-token count source.
- Add throughput `--max-tokens` and opt-in `--min-tokens` requests for more
  explicit token-bound comparability.
- Clarify throughput as client-observed request throughput and add optional
  client-observed decode throughput when reliable streaming token usage is
  available.
- Expand the fixed cold-prompt pool to 30 prompts and add p95 reporting only
  for runs with at least 20 trials.
- Add phase timing metadata and lightweight continuous thermal monitoring to
  new benchmark results.
- Bump the baseline benchmark protocol to v2 for streaming throughput trials
  with usage metadata.
- Add a `--profile sustained` benchmark mode for one longer throughput trial
  with progress samples for late-run degradation checks.
- Add `--cooldown-seconds` and elapsed-since-prior-result metadata to make
  back-to-back hot runs easier to spot.
- Add throughput max-token metadata and a max-token filter to the leaderboard.

### Reliability
- Validate usage-based throughput completion counts against requested token
  bounds when those bounds are available.
- Replace mutable engine scratch-state reads during benchmark throughput trials
  with structured `ThroughputMeasurement` results.
- Split benchmark support code for protocol metadata, statistics, and RAM
  trackers into focused modules.
- Validate request throughput raw trials against completion-token counts and
  elapsed request seconds when all three values are present.
- Warn when continuous thermal monitoring is unavailable, changes during a run,
  or observes known non-nominal thermal state.
- Use `omlx --version` for current oMLX releases, with a legacy help fallback,
  so engine version reporting works while the server is already running.
- Measure throughput trials over streaming completions with usage metadata so
  request throughput and decode throughput come from the same request.
- Retry throughput streams without usage metadata when an engine rejects
  `stream_options.include_usage`, while keeping the result marked as fallback.
- Mark word-fallback throughput results and unknown engine versions with
  explicit warning metadata.
- Try `/v1/models` metadata as a final oMLX version fallback when local CLI
  version probes fail.

### Bug Fixes
- Compute sustained progress sample throughput from the same rounded elapsed
  value saved in JSON, avoiding false schema validation failures.
- Remove the unproduced `engine_response` decode timing source from runtime and
  schema validation.
- Require throughput completion-token and elapsed-time raw trial fields to be
  present together when either one is present.
- Avoid duplicate total-runtime rows in Markdown reports.
- Keep example result metadata aligned with the `0.1.2` release version/date.

### Compatibility
- Protocol v1 throughput used non-streaming requests; protocol v2 throughput
  uses streaming requests. Existing v1 leaderboard rows remain valid, but their
  throughput workload is not identical to new v2 rows.

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
