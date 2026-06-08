# mlx-Chronos Benchmark Methodology

This document explains exactly what mlx-Chronos measures, how it measures it,
and why each decision was made. Reproducibility and transparency are core goals.

---

## Metrics

### TTFT Cold — Time to First Token (cold)
Time in seconds from sending the request to receiving the first non-empty
streamed content, reasoning, or text delta. Whitespace-only streamed text
counts because it is still a generated token observed from the engine. "Cold"
means the model has not seen this prompt before — no cache advantage.

TTFT is measured with Python's monotonic high-resolution performance counter,
so wall-clock changes during a run do not affect the latency value.

Each trial uses a **unique prompt within the run** from a fixed pool defined in
`protocol.py`. This avoids cache hits caused by earlier trials in the same
benchmark. It does not prove the engine had no matching cache state from a
previous benchmark process; for strict cold-run interpretation, restart or clear
the engine server before running. The JSON field remains `metrics.ttft_cold`
for compatibility with existing v0.1 submissions.

Cold prompts are fixed protocol text, not tokenizer-normalized strings. Their
input length can vary slightly by tokenizer and engine. That variance is part
of the published protocol and is visible through the exact prompt text in
`meta.benchmark_protocol`; input token counts remain `unavailable` until they
can be measured without adding engine-specific estimates.

### TTFT Cached — Time to First Token (cached)
Same measurement, but using a **fixed prompt** that is sent on every cached
trial. After cold TTFT trials finish, a priming call (not recorded) loads this
prompt into the engine cache. Cached TTFT trials then run consecutively so
unrelated prompts do not evict or overwrite the cache between measurements.
The JSON field remains `metrics.ttft_cached` for compatibility with existing
v0.1 submissions.

### TTFT Interpretation Across Engines
TTFT is an observed client-side latency: mlx-Chronos starts timing before the
HTTP request and stops when the OpenAI-compatible stream yields the first valid
content/reasoning/text delta. It is not a direct measurement of an engine's
internal prefill or decode boundary.

Different engines and proxy layers may buffer streamed output differently. Some
emit role-only chunks before text, some batch small deltas, and some may delay
the first visible token until their HTTP layer flushes. For that reason,
`ttft_cold` and `ttft_cached` are most reliable for comparing repeated runs of
the same engine and model configuration. Cross-engine comparisons are still
useful, but should be read as end-to-end user-observed latency rather than pure
model latency.

The cached metric is intentionally named `ttft_cached` in the v0.1 JSON schema.
It means "fixed prompt after one priming request"; it does not guarantee that
all engines implement identical KV-cache or prefix-cache behavior.
New results set `meta.cached_ttft_warning=true` when cached TTFT is close to
cold TTFT, because that pattern may indicate that the engine did not reuse a
prompt/KV cache for that run.

### Request Throughput (tok/s)
Completion tokens divided by the full client-observed request time, measured
using a fixed standard prompt defined in the project. The prompt is identical
across all engines and all versions of mlx-Chronos to ensure comparability. Do
not change this prompt without bumping `chronos_version`.

This metric includes HTTP/client overhead, prompt prefill, and decode. It should
be read as end-to-end request throughput, not pure decode speed. The legacy JSON
field remains `metrics.tokens_per_second` for compatibility; new results also
mirror it as `metrics.request_tokens_per_second` and record per-trial elapsed
request times in `trials.throughput_elapsed_seconds_raw`. Streaming throughput
timing stops at the observed stream completion marker when one is provided, so
socket/context teardown after the stream is not counted as generation time.

Protocol v2 uses streaming mode (`stream: true`) with
`stream_options.include_usage=true` so the same request can expose both
time-to-first-content and final `usage.completion_tokens`. Protocol v1 used
non-streaming throughput requests, so v1 and v2 throughput numbers are not the
same workload and should not be treated as perfectly interchangeable. The result
records `metrics.token_count_source`. Leaderboard submissions must use
`usage.completion_tokens`; local runs that fall back to a word-based estimate
are marked as `word_fallback` or `mixed` and are not considered comparable.
New benchmark results also record `trials.completion_tokens_raw`, the generated
completion-token count for each throughput trial.
If an engine rejects `stream_options.include_usage`, mlx-Chronos retries the
same streaming request without that option and records the result as a local
fallback instead of failing the whole run.

When the streaming response provides reliable completion-token usage,
mlx-Chronos records client-observed decode throughput in
`metrics.decode_tokens_per_second`, `metrics.decode_timing_source`, and
`trials.decode_tokens_per_second_raw`. This is computed from the interval
between first streamed content and the end of the stream. This is still a
client-observed stream metric: it includes engine flush policy and any
inter-token buffering or batching visible to the client. It is not an internal
model/kernel decode measurement. The calculation assumes
`usage.completion_tokens` counts generated completion tokens; if an engine uses
different usage semantics, request throughput is the safer cross-engine metric.
If token usage is not available, decode throughput is left unavailable rather
than estimated from word counts.

Throughput trials request a fixed `max_tokens` value, 100 by default. Users can
override this with `--max-tokens`. An optional `--min-tokens` request can be
sent to engines that support it; when `usage.completion_tokens` is available,
mlx-Chronos checks that the recorded throughput output respects the requested
range. If an engine ignores `min_tokens`, the run is not treated as comparable
under that requested bound.

The default leaderboard workload is `max_tokens=100`. The result metadata
records the requested throughput token bound in
`meta.benchmark_protocol.throughput.requested_max_tokens`. The public
leaderboard's compare view defaults to standard runs, while the raw-data view
keeps token-bound metadata available as optional columns. Rows with
`max_tokens=100` and no requested `min_tokens` are marked as the standard
workload; other rows are treated as custom-token runs.

### Sustained Throughput Profile
`mlx-chronos run --profile sustained` keeps the same benchmark phases but
changes the default run shape to one trial and a long throughput request:
`max_tokens=1000`. Users can still override `--trials` or `--max-tokens`
explicitly.

During sustained throughput, mlx-Chronos records
`trials.throughput_progress_samples_raw`. Intermediate progress samples are
taken every 100 generated output units using the live streamed text available
to the client. These intermediate samples are estimates unless the stream
exposes exact usage before the end. Final throughput still uses
`usage.completion_tokens` when the engine provides it; intermediate samples may
be marked `word_fallback` because most OpenAI-compatible streams expose exact
usage only at the end of the stream.

The sustained profile also records `meta.sustained_throttling_warning` when a
late-run estimated throughput drop is observed and the thermal monitor saw a
state change or non-nominal thermal state. The check requires several progress
intervals and compares the average of early intervals with the average of late
intervals, so a single noisy first/last sample is not enough. This is still a
conservative heuristic, not proof of a specific hardware mechanism.

### System RAM Peak
Total Mac RAM usage is sampled continuously from before warmup through the
recorded benchmark phases, using the configured RAM sampling interval. The result
records the observed peak as `metrics.system_ram_peak_gb` and
`metrics.system_ram_peak_percent`.

This is the public leaderboard memory metric. It answers the practical question
of how much memory pressure a run placed on the Mac while the model was loading
or serving requests.

This replaces the old pre-run baseline. mlx-Chronos reports memory pressure
while inference is actually happening, so model loading, cache growth, swap, and
other runtime pressure are represented in the result.

The default sampling interval is 50ms (`--ram-sample-interval 0.05`). Lower
values can catch shorter spikes but add more measurement overhead; higher values
reduce overhead but may miss brief peaks. The interval is recorded in result
metadata as `meta.ram_sample_interval_seconds`.

### Diagnostic Post-Warmup Engine RSS (GB)
Resident memory used by the engine server process, sampled continuously after
warmup through the recorded benchmark phases, then reported as the observed RSS
peak. This diagnostic RSS sampler intentionally starts after warmup, while
system RAM starts before warmup so model loading and cache pressure are
included in the public memory metric.
Child processes are resolved when RSS sampling starts and then reused during
sampling to avoid repeatedly scanning the process tree during latency-sensitive
phases.

**Important:** this metric is diagnostic and retained for legacy JSON
compatibility. It is not a public comparison metric. It is best read as process
overhead for the server, API layer, and runtime. It may not include model
weights or Metal allocations that are mapped outside ordinary process RSS. Model
sizes should still be read from their model cards. Use System RAM Peak for
memory comparison.

When the engine process cannot be identified by port, system-used memory is
reported as a fallback (marked in the results). Fallback values are not the same
metric as process RSS and should not be compared directly against normal engine
RSS values.

The result records both `metrics.ram_is_process_rss` and
`metrics.ram_measurement_method` (`process_rss` or `system_fallback`) so the
JSON can distinguish direct process measurements from system-memory fallbacks.
The public leaderboard keeps this field in row details only and does not use
process RSS as a main comparison metric.

### Thermal State
Thermal state is detected through macOS `NSProcessInfo` when the Foundation
bridge is available. If that path is unavailable, mlx-Chronos falls back to a
single `powermetrics` sample when the current process can run it; otherwise the
result records an `unavailable_*` status.

`mlx-chronos validate` and `mlx-chronos run` warn when thermal state is
unavailable, when macOS reports a non-nominal thermal state, or when battery
power / Low Power Mode are detected. These warnings are informational: the run
continues. New results record power source and Low Power Mode in
`hardware.power_source` and `hardware.low_power_mode` so benchmark conditions
can be audited later.

Installing `mlx-chronos[thermal]` adds the optional PyObjC Foundation bridge,
which lets mlx-Chronos read thermal state through macOS APIs without requiring
`powermetrics` privileges.

New benchmark results also include a lightweight continuous thermal monitor in
`meta.thermal_monitor`. It samples only the Foundation path during the run and
records start/end/worst thermal state, sample count, whether the state changed,
and which benchmark phases observed a known non-nominal state.
mlx-Chronos intentionally does not run `powermetrics` repeatedly during the
benchmark because that would add subprocess overhead to the measurement.
If PyObjC/Foundation is not installed, the continuous monitor records
`source: unavailable` even though the one-shot hardware thermal state may still
come from `powermetrics` before the benchmark starts.

The result also records `meta.phase_timings_seconds` with elapsed time for
warmup, cold TTFT, cache priming, cached TTFT, throughput, and total runtime.
These fields make run order and heat buildup easier to interpret, but they do
not magically remove thermal throttling.

### Cross-Run Cooldown
When `mlx-chronos run` starts, the CLI checks the newest prior JSON result in
the selected output directory. If one exists, the result records
`meta.elapsed_since_last_benchmark_seconds`. This helps identify back-to-back
runs where the second run starts with already-warm hardware.

Passing `--cooldown-seconds N` makes the CLI wait until at least `N` seconds
have elapsed since that prior result. Without an explicit cooldown, the CLI
warns when the prior result is recent, but it does not block the run. The
built-in recent-run warning threshold is a pragmatic 300-second heuristic, not
a measured guarantee that every Mac has returned to a fully cool state.

### Engine Version Detection
Engine versions are recorded in `engine.version` when local detection succeeds:

- oMLX: `omlx --version` on current releases, with a legacy
  `omlx serve --help` fallback for older installs. If those fail, mlx-Chronos
  also checks `/v1/models` for explicit engine/server version metadata.
- Rapid-MLX: `rapid-mlx version`.
- mlx-lm: installed Python package metadata for `mlx-lm`.
- Ollama: `ollama --version`.

If detection fails, the result records `unknown` instead of blocking the run.
New results also set `meta.engine_version_warning=true` so local reports and
the public leaderboard can call out the comparability risk.

Performance is heavily impacted by memory pressure (e.g., 7GB used out of 8GB
causes swapping and slows down inference, whereas 7GB used out of 16GB does
not). System RAM peak helps explain performance variances between identical
chips and models.

---

## Trial Protocol

| Parameter | Value |
|-----------|-------|
| Trials per metric | 5 (default), 30 max |
| Warmup calls | 2 (not recorded, throughput prompt) |
| Cache priming | 1 call after cold TTFT and before cached TTFT (not recorded) |
| Max tokens — warmup | 30 |
| Max tokens — TTFT | 1 |
| Max tokens — throughput | 100 |

**Warmup:** two unrecorded calls using the throughput prompt are made before
any measurement. This reduces noise from model loading and JIT compilation.

**Phase order:** mlx-Chronos measures cold TTFT trials first, primes the fixed
cached prompt once, measures cached TTFT trials consecutively, and then measures
throughput trials. The phases are intentionally not interleaved, because some
local engines keep only one active KV/prefix cache and can lose the cached
prompt when unrelated prompts are sent between cached trials.

**Statistics:** mean, stddev, min, max are reported for each metric. p95 is
reported only when at least 20 trials are available; it is intentionally omitted
for small sample sizes where it collapses toward the observed maximum and adds
little information.

**Protocol metadata:** new results include `meta.benchmark_protocol`, which
records the baseline protocol version, exact prompt text for warmup, cold TTFT,
cached TTFT, and throughput, plus the requested min/max token bounds per phase.
Protocol phase metadata also records whether the phase used streaming requests
and whether `stream_options.include_usage` was requested. The protocol name
matches the selected benchmark profile (`baseline` or `sustained`) for new
results. Results without protocol metadata should be treated as protocol v1.
Input token counts are marked as `unavailable` until mlx-Chronos can obtain
them from a tokenizer or engine response without adding unreliable estimates.

**Phase timing and thermal metadata:** new results include
`meta.phase_timings_seconds` and `meta.thermal_monitor` so readers can see how
long each phase took and whether thermal state changed during the run.

---

## What Is Not Measured (Yet)

- Tool calling success rate — planned for v0.2
- Full thermal throttling attribution beyond the sustained-run warning —
  planned for v0.2
- CPU/GPU load at benchmark time — planned for v0.2
- Multi-turn conversation latency

---

## Reproducibility

To reproduce a result:
1. Use the same engine version listed in the JSON
2. Use the same model name and quantization
3. Run on the same hardware (chip + memory)
4. Ensure no other GPU-intensive processes are running
5. Run `mlx-chronos run` with default trial count (5), or use the same explicit
   trial count when comparing larger runs
6. Check the JSON with `mlx-chronos submit --file results/local/your-result.json --dry-run`
7. Submit only results whose throughput token source is `usage.completion_tokens`

Results may vary slightly across runs due to thermal state, battery/Low Power
Mode behavior, and system load. This is expected and reflected in the stddev
field.
