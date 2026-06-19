# mlx-Chronos Benchmark Methodology

This document explains what mlx-Chronos measures, how it measures it, and how
to interpret the resulting JSON. Reproducibility and transparency are the main
goals.

## Contents

- [Design Goals](#design-goals)
- [Metric Summary](#metric-summary)
- [Latency Metrics](#latency-metrics)
- [Throughput Metrics](#throughput-metrics)
- [Memory Metrics](#memory-metrics)
- [Thermal and Power Context](#thermal-and-power-context)
- [Engine Metadata](#engine-metadata)
- [Trial Protocol](#trial-protocol)
- [Public Leaderboard Policy](#public-leaderboard-policy)
- [Trust Model](#trust-model)
- [What Is Not Measured Yet](#what-is-not-measured-yet)
- [Reproducibility Checklist](#reproducibility-checklist)

---

## Design Goals

mlx-Chronos is designed to report user-observed inference behavior from the
client side. It does not try to replace engine-internal profilers.

The protocol is built around four principles:

- Use fixed prompts and deterministic generation settings.
- Record enough metadata to reproduce and audit a run.
- Keep local experimentation flexible.
- Keep public leaderboard rows strict enough to compare.

---

## Metric Summary

| Area | JSON field | Meaning | Public comparison use |
| --- | --- | --- | --- |
| Cold TTFT | `metrics.ttft_cold` | Request start to first non-empty streamed token with cache-avoiding prompts | Yes |
| Cached TTFT | `metrics.ttft_cached` | Request start to first token after one cache-priming call | Yes |
| Request throughput | `metrics.tokens_per_second`, `metrics.request_tokens_per_second` | Completion tokens divided by full client-observed request time | Yes, with usage-based token counts |
| Decode throughput | `metrics.decode_tokens_per_second` | Completion tokens divided by first-token-to-stream-end time | Context metric |
| System RAM peak | `metrics.system_ram_peak_gb`, `metrics.system_ram_peak_percent` | Peak total Mac RAM in use during the benchmark | Yes |
| Engine RSS | `metrics.ram_peak_gb` with `metrics.ram_measurement_method=process_rss` | Post-warmup server-process RSS when identifiable | Diagnostic only |
| Thermal monitor | `meta.thermal_monitor` | Start/end/worst thermal state and affected phases | Context metric |
| Phase timings | `meta.phase_timings_seconds` | Wall time spent in benchmark phases | Context metric |

All repeated metrics report mean, stddev, min, and max. p95 is included only
when at least 20 trials are available; for small samples it collapses toward
the observed maximum and adds little information.

---

## Latency Metrics

### Cold TTFT

Cold TTFT is the time in seconds from sending the request to receiving the
first non-empty streamed content, reasoning, or text delta. Whitespace-only
streamed text counts because it is still generated output observed from the
engine.

Implementation details:

- Timing uses Python's monotonic high-resolution performance counter, so
  wall-clock changes do not affect the latency value.
- Each trial uses a unique prompt from the fixed pool in `protocol.py`.
- Unique prompts avoid same-run cache hits, but they do not prove the engine
  had no cache state from a previous process.
- For strict cold-run interpretation, restart or clear the engine server before
  running.
- Prompt text is recorded in `meta.benchmark_protocol`.

Cold prompts are fixed protocol text, not tokenizer-normalized strings. Input
length can vary slightly by tokenizer and engine. Input token counts remain
`unavailable` until mlx-Chronos can obtain them without adding unreliable
engine-specific estimates.

### Cached TTFT

Cached TTFT uses a fixed prompt for every cached trial. After cold TTFT trials
finish, a priming call loads that prompt into the engine cache. Cached TTFT
trials then run consecutively so unrelated prompts do not evict or overwrite
the cached prompt between measurements.

If the priming call fails, the benchmark stops. A cached-TTFT value is never
produced from a run whose priming state is unknown.

The field is named `metrics.ttft_cached` in the v0.1 JSON schema. It means
"fixed prompt after one priming request"; it does not guarantee that all
engines implement identical KV-cache or prefix-cache behavior.

Results set `meta.cached_ttft_warning=true` when cached TTFT is close to cold
TTFT, because that pattern may indicate that the engine did not reuse a
prompt/KV cache for that run. For local diagnostics,
`MLX_CHRONOS_CACHED_TTFT_RATIO` can override the warning ratio. This changes
only the warning threshold, not the measured values.

### Interpreting TTFT Across Engines

TTFT is observed client-side latency. mlx-Chronos starts timing before the HTTP
request and stops when the OpenAI-compatible stream yields the first valid
content, reasoning, or text delta.

It is not a direct measurement of an engine's internal prefill or decode
boundary. Different engines and proxy layers may buffer streamed output
differently:

- Some emit role-only chunks before text.
- Some batch small deltas.
- Some delay the first visible token until the HTTP layer flushes.

For that reason, `ttft_cold` and `ttft_cached` are strongest for comparing
repeated runs of the same engine and model configuration. Cross-engine
comparisons are still useful, but should be read as end-to-end user-observed
latency rather than pure model latency.

Current runs use one persistent `httpx.Client` across warmup, TTFT, and
throughput requests by default. This allows keep-alive reuse when the engine
supports it and better matches repeated agent-loop usage. Earlier result
formats used independent per-request calls, so their TTFT may include more
connection setup overhead.

---

## Throughput Metrics

### Request Throughput

Request throughput is completion tokens divided by full client-observed request
time. The metric includes HTTP/client overhead, prompt prefill, and decode. It
should be read as end-to-end request throughput, not pure decode speed.

Current JSON records this value in both:

- `metrics.tokens_per_second`
- `metrics.request_tokens_per_second`

Those fields are expected to match. Per-trial elapsed request times are stored
in `trials.throughput_elapsed_seconds_raw`.

### Prompt and Generation Rules

Throughput uses a fixed prompt pool defined in the project. Each trial uses a
different protocol prompt so same-run prefix/KV cache hits do not silently
remove prefill work from repeated trials. Warmup uses a separate prompt for the
same reason.

The prompt order is identical across engines and mlx-Chronos versions unless
the protocol contract is intentionally updated. Do not change these prompts
without updating the contract.

All benchmark requests set deterministic generation parameters:

```text
temperature=0.0
top_p=1.0
```

This avoids depending on engine-specific server defaults.

The prompts are not identical in tokenized length across every tokenizer, so
throughput stddev includes workload variation plus machine and engine noise.
This is a benchmark-suite average, not a pure engine-stability number.

### Token Counting

The current protocol uses streaming mode with:

```json
{
  "stream": true,
  "stream_options": {
    "include_usage": true
  }
}
```

This lets one request expose both time-to-first-content and final
`usage.completion_tokens`.

Leaderboard submissions must use `usage.completion_tokens`. Local runs that
fall back to a word-based estimate are marked as `word_fallback` or `mixed` in
`metrics.token_count_source` and are not considered public-comparable.

If an engine rejects `stream_options.include_usage`, mlx-Chronos retries the
same streaming request without that option and records the run as a local
fallback instead of failing the whole benchmark.

This compatibility fallback is triggered only by an explicit unsupported-field
response and starts a fresh timer. Transient failures in timed TTFT or
throughput streams are not retried; the benchmark fails instead of including
retry/backoff time in a metric.

### Decode Throughput

When reliable completion-token usage is available, mlx-Chronos also records
client-observed decode throughput in:

- `metrics.decode_tokens_per_second`
- `metrics.decode_timing_source`
- `trials.decode_tokens_per_second_raw`
- `trials.decode_elapsed_seconds_raw`

This is computed from the interval between first streamed content and the end
of the stream. It still includes engine flush policy and any inter-token
buffering or batching visible to the client. It is not an internal model/kernel
decode measurement. Public validation reconstructs each decode-throughput
value from completion tokens and raw decode elapsed time.

If token usage is unavailable, decode throughput is left unavailable rather
than estimated from word counts.

### Output Token Bounds

Throughput trials request a fixed `max_tokens` value. The baseline default is
`100`; the sustained profile default is `1000`.

Users can override `--max-tokens` for local experiments. They can also request
`--min-tokens` for engines that support it. When `usage.completion_tokens` is
available, mlx-Chronos checks whether recorded output respects the requested
range. If an engine ignores `min_tokens`, the run is not treated as comparable
under that requested bound.

### Sustained Throughput Profile

`mlx-chronos run --profile sustained` keeps the same benchmark phases but uses
one long throughput request by default:

| Setting | Standard sustained value |
| --- | ---: |
| Trials | 1 |
| `max_tokens` | 1000 |
| Progress interval | 100 generated output units |

During sustained throughput, mlx-Chronos records
`trials.throughput_progress_samples_raw`. Intermediate progress samples are
taken from live streamed text visible to the client. They are estimates unless
the stream exposes exact usage before the end.

The sustained profile also records `meta.sustained_throttling_warning` when a
late-run estimated throughput drop is observed and the thermal monitor saw a
state change or non-nominal thermal state. The check compares early and late
progress-window averages; a single noisy first/last sample is not enough. This
is a conservative heuristic, not proof of a specific hardware mechanism.

---

## Memory Metrics

### System RAM Peak

System RAM peak is sampled continuously from before warmup through recorded
benchmark phases. Results store:

- `metrics.system_ram_peak_gb`
- `metrics.system_ram_peak_percent`

This is the public leaderboard memory metric. It answers the practical
question of how much total memory pressure the run placed on the Mac while the
model was loading or serving requests.

The default sampling interval is 50ms:

```bash
mlx-chronos run ... --ram-sample-interval 0.05
```

Lower values can catch shorter spikes but add measurement overhead. Higher
values reduce overhead but may miss brief peaks. The interval is recorded in
`meta.ram_sample_interval_seconds`.

### Diagnostic Engine RSS

Engine RSS is the resident memory used by the engine server process. It is
sampled after warmup through recorded benchmark phases and reported as an
observed RSS peak.

This metric is diagnostic only. It is not a public comparison metric because it
may not include model weights or Metal allocations mapped outside ordinary
process RSS. Use System RAM Peak for memory comparison.

Child processes are resolved when RSS sampling starts and refreshed
periodically during long runs. That allows late-spawned workers to be included
without repeatedly scanning the process tree during latency-sensitive phases.

When the engine process cannot be identified by port, system-used memory is
reported as a fallback and marked in the result. Fallback values are not the
same metric as process RSS and should not be compared directly against normal
engine RSS values.

Relevant JSON fields:

- `metrics.ram_is_process_rss`
- `metrics.ram_measurement_method`
- `metrics.ram_peak_gb`

The public leaderboard excludes process RSS from the row index and uses System
RAM Peak as the comparable memory metric.

---

## Thermal and Power Context

Thermal state is detected through macOS `NSProcessInfo` when the Foundation
bridge is available. If that path is unavailable, mlx-Chronos falls back to a
single `powermetrics` sample when the current process can run it. Otherwise the
result records an `unavailable_*` status.

Installing optional thermal support enables the Foundation path:

```bash
pip install "mlx-chronos[thermal]"
```

`mlx-chronos validate` and `mlx-chronos run` warn when:

- thermal state is unavailable;
- macOS reports a non-nominal thermal state;
- battery power is detected;
- Low Power Mode is detected.

Warnings are informational and the run continues. Results record:

- `hardware.power_source`
- `hardware.low_power_mode`
- `meta.thermal_monitor`
- `meta.phase_timings_seconds`

Public leaderboard submissions must report Low Power Mode as `off`. Power
source is retained in the full JSON but is not used as a leaderboard field.
New public submissions also require error-free system RAM, engine RSS, and
continuous Foundation thermal sampling. Sampling failures remain recorded for
local diagnostics but make a run non-publishable.

The continuous thermal monitor samples only the Foundation path during the run.
mlx-Chronos intentionally does not run `powermetrics` repeatedly during the
benchmark because repeated subprocess calls would add measurement overhead.

`meta.phase_timings_seconds` records elapsed time for warmup, cold TTFT, cache
priming, cached TTFT, throughput, and total runtime. These fields make run
order and heat buildup easier to interpret, but they do not remove thermal
throttling from the measured results.

### Cross-Run Cooldown

When `mlx-chronos run` starts, the CLI checks the newest prior JSON result in
the selected output directory. If one exists, the new result records:

```text
meta.elapsed_since_last_benchmark_seconds
```

Passing `--cooldown-seconds N` makes the CLI wait until at least `N` seconds
have elapsed since that prior result. Without an explicit cooldown, the CLI
warns when the prior result is recent but does not block the run.

The built-in recent-run warning threshold is 300 seconds. It is a pragmatic
heuristic, not a measured guarantee that every Mac has returned to a fully cool
state.

---

## Engine Metadata

### Version Detection

Engine versions are recorded in `engine.version` when local detection succeeds.
Public leaderboard submissions require a known engine version; local runs may
still record `unknown` when detection is unavailable.

| Engine | Detection method |
| --- | --- |
| oMLX | `omlx --version`, legacy `omlx serve --help`, then `/v1/models` metadata fallback |
| Rapid-MLX | `rapid-mlx version` |
| vllm-mlx | installed package metadata, package `__version__`, then `/v1/models` metadata fallback |
| mlx-lm | installed package metadata for `mlx-lm` |
| Ollama | server `/api/version`, then `ollama --version` fallback |

If detection fails, the result records `unknown` instead of blocking the run.
Results also set `meta.engine_version_warning=true` so reports and the public
leaderboard can call out the comparability risk.

### Server Identity Checks

mlx-Chronos checks more than `/v1/models` for engines that can be confused with
another server on the same port.

oMLX and vllm-mlx both default to port `8000`, so oMLX validation also checks
the listening process with `lsof` and requires it to match the expected oMLX
process name. This prevents accidentally labeling a vllm-mlx server as oMLX.

If macOS blocks `lsof`, permissions are restricted, or the listener cannot be
inspected, `mlx-chronos validate` or `mlx-chronos run` may report that the oMLX
server is not running even though `/v1/models` responds. In that case, verify
the process on the port, adjust permissions, or move the server to a known port
and set `MLX_CHRONOS_OMLX_PORT`.

For Ollama, mlx-Chronos also verifies the local model format before a measured
run. It calls `POST /api/show` for the requested model and requires
`details.format` to be `safetensors`, which is the format Ollama reports for
MLX model weights. `gguf` models are rejected for public Ollama benchmark runs
because they use the non-MLX model format and are not comparable with the MLX
leaderboard entries.
The response's quantization is treated as authoritative and must match the
quantization requested on the mlx-Chronos command line. Family and parameter
size are retained when Ollama reports them.

---

## Trial Protocol

### Baseline Defaults

| Parameter | Value |
| --- | --- |
| Trials per metric | 5 |
| Maximum supported trials | 30 |
| Warmup calls | 2, not recorded |
| Warmup prompt | Separate throughput prompt |
| Cache priming | 1 call after cold TTFT and before cached TTFT, not recorded |
| `max_tokens` for warmup | 30 |
| `max_tokens` for TTFT | 1 |
| `max_tokens` for throughput | 100 |
| HTTP connection mode | `persistent` by default |

### Phase Order

1. Optional CLI preflight when `--preflight` is used.
2. Hardware and condition detection.
3. Warmup calls.
4. Cold TTFT trials.
5. Cached prompt priming.
6. Cached TTFT trials.
7. Throughput trials.
8. Result metadata and integrity seal.

The phases are intentionally not interleaved. Some local engines keep only one
active KV/prefix cache and can lose the cached prompt when unrelated prompts
are sent between cached trials.

`mlx-chronos run --preflight` sends an extra model access request before the
measured benchmark to fail fast on model errors. That request is not part of
the standard benchmark protocol and should be treated as a local diagnostic
aid.

### Protocol Metadata

Results include `meta.benchmark_protocol`, which records:

- internal compatibility label;
- selected benchmark profile: `baseline` or `sustained`;
- exact prompt text for warmup, cold TTFT, cached TTFT, and throughput;
- requested min/max token bounds per phase;
- whether the phase used streaming requests;
- whether `stream_options.include_usage` was requested;
- HTTP connection behavior: `persistent` or `per_request`;
- requested generation parameters such as `temperature` and `top_p`;
- input token count source, currently `unavailable`.

The small numeric labels stored in result JSON, such as `1`, `2`, or `3`, are
internal compatibility markers for validators. They are not public protocol
release versions.

### Integrity Metadata

Results include a top-level `integrity` seal. The seal is a SHA-256 digest over
canonical JSON with the `integrity` field removed.

GitHub Actions verifies this before accepting public submissions. The seal is
tamper-evident metadata, not cryptographic proof that the benchmark was run on
the claimed machine.

---

## Public Leaderboard Policy

Local runs may override trial counts, output token bounds, profiles, cooldown,
connection mode, and notes. Those records are useful locally but are not
automatically publishable.

Public rows must match one of the standard profiles:

| Profile | Trials | `max_tokens` | Minimum generated output | `min_tokens` |
| --- | ---: | ---: | ---: | --- |
| Baseline | 5 | 100 | 80 tokens | Not allowed |
| Sustained | 1 | 1000 | 800 tokens | Not allowed |

Public submissions must also:

- use `usage.completion_tokens` token counts;
- include `model.reference_url`, a link to the model used;
- complete all warmup calls without failures (`warmup_failures=0`);
- report Low Power Mode as `off`;
- use standard deterministic generation parameters;
- keep exact standard protocol metadata;
- pass schema validation;
- pass raw-trial consistency validation;
- pass integrity-seal validation;
- be added or modified only as submitted JSON files in result-submission PRs.

Model reference URLs are human-readable references. Model pages can change over
time when maintainers update files or tags.

GitHub Actions enforces this policy before generating the leaderboard index.
Baseline and sustained rows are kept as separate profile choices in the
leaderboard UI.

---

## Trust Model

mlx-Chronos treats public submissions as community-provided benchmark records,
not hardware-attested measurements. The project can detect many accidental or
casual problems, but it cannot prove that a submitter used the claimed machine,
model weights, tokenizer, chat template, backend implementation, or an
unmodified copy of the tool.

Realistic risks include:

- accidental local diagnostics submitted as comparable rows;
- hand-edited JSON;
- stale internal protocol labels;
- fallback token estimates;
- non-standard token bounds;
- Low Power Mode runs;
- mixed PRs that make review harder.

Mitigations include schema validation, raw-trial consistency validation,
integrity-seal validation, standard protocol metadata checks, usage-based
completion-token requirements, fixed public trial counts, minimum generated
output length, Low Power Mode checks, deterministic generation checks, phase
timing consistency, and PR-scope checks.

These checks improve comparability and catch accidental or casual tampering.
They are not a cryptographic hardware attestation system.

---

## What Is Not Measured Yet

- Tool-calling success rate.
- Full thermal-throttling attribution beyond the sustained-run warning.
- CPU/GPU utilization at benchmark time.
- Multi-turn conversation latency.

---

## Reproducibility Checklist

To reproduce a result:

1. Use the same engine version listed in the JSON.
2. Use the same model name, quantization, and model reference URL.
3. Run on the same hardware: chip and memory.
4. Disable Low Power Mode.
5. Avoid other GPU-intensive processes during the run.
6. Use the standard public profile you want to compare:
   - baseline: 5 trials;
   - sustained: 1 trial.
7. Validate the JSON:

   ```bash
   mlx-chronos submit --file results/local/your-result.json --dry-run
   ```

8. Submit only standard baseline or sustained results with
   `usage.completion_tokens` and Low Power Mode disabled.

Custom local runs are still valid local benchmark records. Do not submit them
to `results/submitted/`; the public validator rejects non-standard token
bounds, requested `min_tokens`, fallback token estimates, Low Power Mode runs,
and non-standard public-profile trial counts.

Results may vary slightly across runs due to thermal state, power behavior, and
system load. This is expected and reflected in the stddev field.
