# mlx-Chronos Benchmark Methodology

This document explains what mlx-Chronos measures, how it measures it, and how
to interpret the resulting JSON. Reproducibility and transparency are the main
goals.

This document follows the current `main` branch. Changes in
[Unreleased](../CHANGELOG.md#unreleased) require the
[development installation](../README.md#development-version-from-main) until
they are included in a published release.

## Contents

- [Design Goals](#design-goals)
- [Metric Summary](#metric-summary)
- [Latency Metrics](#latency-metrics)
- [Throughput Metrics](#throughput-metrics)
- [Memory Metrics](#memory-metrics)
- [Thermal and Power Context](#thermal-and-power-context)
- [Reusable Run Configurations](#reusable-run-configurations)
- [Engine Metadata](#engine-metadata)
- [Concurrency: Local Throughput-Under-Load Diagnostic](#concurrency-local-throughput-under-load-diagnostic)
- [Local Multi-Engine Matrix](#local-multi-engine-matrix)
- [Local Context Diagnostic](#local-context-diagnostic)
- [Experimental Local Energy Diagnostic](#experimental-local-energy-diagnostic)
- [Local Comparison and History](#local-comparison-and-history)
- [Trial Protocol](#trial-protocol)
- [What does the protocol number mean?](#what-does-the-protocol-number-mean)
- [Public Leaderboard Policy](#public-leaderboard-policy)
- [Trust Model](#trust-model)
- [Leaderboard Export and Chart](#leaderboard-export-and-chart)
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
| Decode throughput | `metrics.decode_tokens_per_second` | Completion tokens after the first, divided by first-token-to-stream-end time | Context metric |
| System RAM peak | `metrics.system_ram_peak_gb`, `metrics.system_ram_peak_percent` | Peak total Mac RAM in use during the benchmark | Whole-device stress context |
| RAM baseline and rise | `metrics.system_ram_baseline_gb`, `metrics.system_ram_delta_gb` | First sample and peak minus first sample | Diagnostic only; not engine memory |
| Swap growth | `metrics.swap_growth_gb` | Largest rise from the first system swap sample; unknown if any reading is unavailable | Diagnostic; warning at 0.5 GB |
| Engine RSS | `metrics.ram_peak_gb` with `metrics.ram_measurement_method=process_rss` | Post-warmup server-process RSS when identifiable | Diagnostic only |
| Thermal monitor | `meta.thermal_monitor` | Start/end/worst thermal state and affected phases | Context metric |
| Phase timings | `meta.phase_timings_seconds` | Wall time spent in benchmark phases | Context metric |

Within a session, trial metrics report mean, stddev, min, and max. p95 is included only
when at least 20 trials are available; for small samples it collapses toward
the observed maximum and adds little information.

---

## Latency Metrics

### Cold TTFT

Cold TTFT is the time in seconds from sending the request to receiving the
first non-empty streamed content, reasoning, or text delta. Whitespace-only
streamed text counts because it is still generated output observed from the
engine.

For the one-token TTFT request, a terminal `finish_reason=length` without
visible content is also accepted. Some reasoning models consume the token
budget without emitting text; that terminal signal is not a measurement of
time to visible text. The same rule applies to cached TTFT and `context`.

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
length can vary by tokenizer and engine. Cold and cached TTFT input token
counts remain `unavailable`: these requests do not request streamed usage.
Throughput trials retain available input counts from their own responses.
The separate local [`context` diagnostic](#local-context-diagnostic) can retain optional
engine-reported input counts; it does not change the standard protocol.

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
TTFT. This is a timing observation; latency alone cannot confirm a cache miss
or cache reuse. For local diagnostics,
`MLX_CHRONOS_CACHED_TTFT_RATIO` can override the warning ratio. This changes
only the warning threshold, not the measured values.

For engines with a documented cache-control API, mlx-Chronos may additionally
record `meta.cache_validation`. This evidence is optional and never changes a
timing value: `cold_cache_cleared` means the engine confirmed a clear before
cold trials, while `cached_prefix_hit_verified` is true only when a dedicated
text prefix-cache hit counter increases during cached trials. An API without
such a counter remains unverified rather than being inferred from latency.

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
throughput requests by default. Protocol labels `4` and `5` consume and
validate the complete HTTP body after capturing the first-token or completion
timestamp. This allows keep-alive reuse when the engine supports it without
adding response-drain time to those metrics. Stream errors, malformed JSON and
EOF without `[DONE]` or a supported terminal `finish_reason` fail the request.
Read timeouts and an overall stream deadline bound completion processing.

Label `3` also reused the client object, but TTFT returned at the first token
and throughput stopped at `[DONE]`, so incomplete body consumption could prevent
TCP reuse. Older per-request runs used separate clients. These transport
differences can affect connection overhead and cache priming; archived runs
retain their original labels and appear as separate protocol variants.

---

## Throughput Metrics

### Request Throughput

Protocol 5 preserves raw clock durations and computes request/decode rates from
those durations, without a millisecond floor. Standard-run summary statistics
also retain their precision; presentation may format them for readability.
Historical values keep their original rounding and protocol labels.

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

Streamed token counts must be positive JSON integers. Booleans, strings,
fractional values and non-finite numbers are not converted into apparently
exact counts. Missing or unusable usage can trigger a local word estimate;
diagnostics that require exact completion counts, such as `concurrency`, fail
instead of accepting that estimate.

If an engine explicitly rejects `stream_options.include_usage`, the standard
throughput measurement allows one compatibility attempt without that option,
with a fresh timer. Token-count provenance depends on the accepted response:
exact integer usage is retained if the server still supplies it; otherwise
the word estimate makes the run local-only. Removing the unsupported option
does not by itself establish or invalidate exact token counts. `concurrency`
disables this compatibility retry and stops on the unsupported request.

When the final streaming choice supplies `finish_reason`, it is recorded per
throughput trial in `trials.finish_reasons_raw`. This is diagnostic provenance:
the count remains the engine-reported `usage.completion_tokens`, while the
field distinguishes natural EOS (for example `stop`) from a `max_tokens` limit
(`length`).

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

Progress samples record elapsed time from the start of the request, so the
first window also contains connection setup and prompt prefill while every
later window is decode only. When the trial recorded decode timing, that
prefill offset is subtracted from the first window; otherwise the first window
is discarded instead of being averaged against decode-only windows. Windows
that straddle a change of token-count source are also skipped, because the
intermediate samples count streamed words while the final sample carries the
engine's completion-token total.

---

## Memory Metrics

### System RAM Peak and Added Occupancy

System RAM peak is sampled continuously from before warmup through recorded
benchmark phases. Results store:

- `metrics.system_ram_peak_gb`
- `metrics.system_ram_peak_percent`

Peak occupancy shows the highest observed whole-Mac usage during the run. It is
useful device-stress context, not memory attributable to the engine alone.

Peak includes whatever was already resident before the benchmark started. New
results also record the first observed sample and the rise from that sample:

- `metrics.system_ram_baseline_gb` — total RAM in use at the first sample
- `metrics.system_ram_delta_gb` — peak minus baseline, validated as exactly that

The leaderboard keeps peak usage as the main stress reading and displays the
increase alongside it as diagnostic context. The increase is **not** a
cross-submitter memory benchmark: other processes can change during sampling,
and the model may already be loaded before the first sample. Older results keep
only the peak.

One caveat the numbers cannot resolve on their own: the engine server is started
outside mlx-Chronos, so whether model loading falls inside the sampled window
depends on whether the model was already resident when the benchmark began.
The measured increase therefore includes weight loading only when it happens
inside the sampling window.

### Swap Pressure

`metrics.swap_growth_gb` records the largest observed rise in system-wide macOS
swap usage relative to the first valid swap sample.
`meta.memory_pressure_warning` is set once that rise reaches 0.5 GB. This is a
reason to scrutinize the timings, not proof that the benchmark process itself
caused paging or slowed down.

It is a warning, never a submission blocker. Blocking would lock 8 GB Macs out
of the public leaderboard, and those are exactly the machines whose numbers
people most want to look up. The leaderboard marks affected rows with a
`swap grew` badge instead.

The default sampling interval is 50ms:

```bash
mlx-chronos run --engine ollama --model 'model-alias:tag' --ram-sample-interval 0.05
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
process RSS. Use System RAM Peak to describe whole-device occupancy, not to
rank the engines' own memory footprints.

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

The public leaderboard excludes process RSS from the row index and displays
System RAM Peak as whole-device stress context, not an engine-only comparison.

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

Labels `4` and `5` count only known thermal states as valid samples;
unavailable readings increment `sampling_errors`. Public eligibility requires
at least two valid samples and `max_sample_gap_seconds` no larger than
`max(1.0, 2.5 * sample_interval_seconds)`. Missing coverage fields remain unknown
in historical files rather than being inferred from the initial state. Protocol
`5` additionally stores the first-to-last monotonic `sample_span_seconds`, requires
that span to cover all measured phases (within the phase timing tolerance), and
checks that the valid sample count and maximum gap can account for the span.

The continuous thermal monitor samples only the Foundation path during the run.
mlx-Chronos intentionally does not run `powermetrics` repeatedly during the
benchmark because repeated subprocess calls would add measurement overhead.

`meta.phase_timings_seconds` records elapsed time for warmup, cold TTFT, cache
priming, cached TTFT, throughput, and total runtime. These fields make run
order and heat buildup easier to interpret, but they do not remove thermal
throttling from the measured results.

### Repeating a Run

`--repeat N` runs the entire benchmark N times (default 1, max 20). Each
repeat is a complete session through the same protocol and is saved as
its own self-contained result file — nothing is written back into any of
them, and each is independently eligible for the public leaderboard exactly as
a single run would be.

Result filenames preserve fractional seconds when available, so two quick
repeats in the same second do not overwrite one another.

After the last repeat, mlx-Chronos prints a console-only cross-session summary
for request/decode throughput, cold/cached TTFT and system RAM peak/rise. Each
session contributes one suite mean per timing/rate metric, recomputed from its
raw trials without intermediate rounding, or one RAM diagnostic. Prompt trials
from separate sessions are not pooled into a larger sample.

Each metric shows its available session count (`n=available/total`), mean,
median, Q1–Q3, MAD, sample standard deviation and min/max. Quartiles use Python's
inclusive interpolation convention. MAD is the median absolute deviation from
the median, without a scaling factor; it describes the central spread and may
be zero despite differences in the tails. All observations, including extreme
values, remain in the summary. Missing values are counted, never replaced with
zero. With fewer than two available observations, SD, MAD and quartiles are
unavailable (`-`); a single observation cannot measure between-session spread.

Sequential sessions are not necessarily statistically independent: cache,
temperature and run order may persist. These statistics describe observed
variation, without confidence intervals, a superiority test or an automatic
stability verdict. Zero observed dispersion does not prove stable future runs.
They are never written into sealed result files and do not change leaderboard
eligibility. Throughput with inconsistent completion-count units has no series
aggregate; the per-session values remain visible. The same calculation is used
by the explicit two-series comparison below.

### Reusable Run Configurations

`run --save-config PATH` validates and saves a JSON configuration without
starting a benchmark, probing hardware/servers or checking for updates.
`run --config PATH` starts fresh sessions using its settings and the existing
run/preflight/measurement logic. This feature currently covers `run` only.

Files record the exact engine/model IDs, quantization and model reference,
profile, resolved trials/repetitions/token bounds, connection mode, cooldown,
RAM sampling interval, preflight/public-ready flags, output format, notes and
operator-declared server settings. Default values are resolved when saving;
later changes to CLI defaults do not silently replace them. Output directory,
contributor attribution, server ports, installed versions and measured system
conditions are not configuration settings. Set local paths/ports at execution;
new results retain actual runtime metadata and integrity seals.

Explicit CLI options override saved values. `--engine-opt` replaces the saved
declaration list when supplied; declarations still do not configure the server.
The existing `--preflight` and `--publishable` flags enable those checks. To
disable a saved true flag, edit the JSON boolean or load it into the app and
turn off the corresponding checkbox before running. Save an edited copy using
`--config OLD --save-config NEW`; this also does not start a benchmark.

`schema_version: mlx-chronos-run-config-v1` identifies the **configuration file
format**, separately from `benchmark_protocol_version` (currently `5` in
source and `4` in published CLI `0.5.1`), which identifies
the measurement method. `chronos_version` records the saving CLI, without
requiring that same software version on replay. Unknown/missing fields,
duplicate JSON keys, invalid types/bounds and files over 1 MB are rejected.
A different saved protocol produces an explicit notice and does not block valid
settings. Fresh measurements always use and record the current CLI's protocol;
loading old settings does not reproduce the old method or relabel old results.
Unsupported file formats and settings remain errors. Prompt text comes from the
current protocol.

Configurations are editable settings, not sealed results and not leaderboard
submissions. They do not establish matching weights/tokenizers, cache state or
thermal conditions. Save files only when explicitly requested; no automatic
configuration archive is created.

### Cross-Run Cooldown

When `mlx-chronos run` starts, the CLI checks the newest prior JSON result in
the selected output directory. If one exists, the new result records:

```text
meta.elapsed_since_last_benchmark_seconds
```

Passing `--cooldown-seconds N` makes the CLI wait until at least `N` seconds
have elapsed since that prior result. Without an explicit cooldown, the CLI
warns when the prior result is recent but does not block the run.

Within one `--repeat` invocation, elapsed time is measured from the end of the
previous run with a monotonic clock. This also enforces cooldown when only
Markdown reports are written and no new JSON file exists.

The built-in recent-run warning threshold is 300 seconds. It is a pragmatic
heuristic, not a measured guarantee that every Mac has returned to a fully cool
state.

---

## Engine Metadata

### Version Detection

Engine versions are recorded in `engine.version`, with their evidence in
`engine.version_source`. Public submissions require a known version. Protocol 5
accepts serving API/runtime evidence or indirect package evidence tied to the
identified server process. A package found only in the client's environment
does not meet that requirement. Local runs can record `unknown`.

| Engine | Detection method |
| --- | --- |
| oMLX | `/v1/models` version metadata, then native `/openapi.json` `info.version` (populated from `__version__`); otherwise the identified server process installation |
| Rapid-MLX | `/v1/models` version metadata when exposed; otherwise the identified server process installation |
| vllm-mlx | `/v1/models` version metadata when exposed; otherwise the identified server process installation |
| mlx-lm | Version prefix in the server's structured `system_fingerprint`, reused from existing completion/warmup responses; `/v1/models` metadata or the identified server process installation |
| mlx-serve | Serving binary's `/api/version`; named `mlx-serve --version` component is separate client evidence |
| Ollama | server `/api/version`; installed CLI version is recorded separately |
| LM Studio | version of the runtime that answered the MLX backend probe below |

If detection fails, a local result may record `unknown` rather than blocking
measurement. `meta.engine_version_warning=true` calls out that uncertainty in
reports. Public validation rejects an unknown engine version.

The process fallback (`process_package`) reads package metadata in an isolated
virtual environment identified from the unique listener's explicit Python path
or console-script shebang, and checks that the executable and listener still
match. It does not execute the server's Python, inspect its environment variables
or save paths/PIDs in results. Ambiguous launchers, editable installs, duplicate
distributions, inaccessible processes, and metadata changed after startup remain
unknown. System/Conda environments and macOS module launches that hide the virtual
environment path are not inferred from another installation. This identifies
the associated installation, not the modules already loaded in memory: custom
import paths or local code changes can differ from its package metadata. Reports,
comparisons and the app label this evidence as indirect.

Rapid-MLX and vllm-mlx currently hard-code their OpenAPI schema version, so Chronos
does not use it as a release identifier. See the upstream
[Rapid-MLX server](https://github.com/raullenchai/Rapid-MLX/blob/main/rapid_mlx/server.py),
[vllm-mlx server](https://github.com/waybarrios/vllm-mlx/blob/main/vllm_mlx/server.py),
[oMLX server](https://github.com/jundot/omlx/blob/main/omlx/server.py) and
[mlx-lm fingerprint](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/server.py).

### Serving Configuration

`engine.serving_config` is optional diagnostic context in new sealed results.
It has two separate maps: `observed` values came from a running-model API,
while `declared` values were supplied by the operator with repeatable
`run --engine-opt KEY=VALUE`. That option **records** a claim; it does not
configure the server. Conflicting observed and declared values remain separate
and visible instead of being merged under a misleading common source.

For example, after checking the server yourself:

```bash
mlx-chronos run --engine ollama --model 'model-alias:tag' \
  --engine-opt allocated_context_length=8192 \
  --engine-opt flash_attention=true
```

Keys are lowercased and must match `[a-z0-9][a-z0-9_.-]{0,63}`. The CLI parses
booleans, integers and floating-point values; non-finite numbers are rejected,
and other values remain text. Duplicate declared keys are rejected. There are
at most 24 entries across the two maps; string values are limited to 200
characters and cannot contain
control characters. Do not include secrets or private paths: declarations are
stored in the result and become public if that result is submitted.

Ollama's `/api/ps` can report the **allocated** context length of an exactly
matched running model. The model capacity in `/api/show` is not substituted for
it. LM Studio's optional `/api/v1/models` loaded-instance configuration can
report context length and, when present, other documented instance fields.
Some optional fields are backend-specific and may be absent for MLX; their
absence is not filled with a default. This read does not replace the existing
v0 model-format and active-runtime checks. Unsupported, ambiguous or
inaccessible APIs yield no observed value, not a guessed setting.

The current observed keys are `allocated_context_length` for Ollama and, when
provided for one unambiguous MLX instance, `context_length`, `eval_batch_size`,
`parallel`, `flash_attention` and `offload_kv_cache_to_gpu` for LM Studio.
mlx-serve records `backend` and, when exposed by the verified loaded instance,
`context_length`, `model_max_tokens`, `batched_decode`, `kv_quant`,
`drafter_loaded`, `mtp_loaded`, `mtp_available` and `spec_exact`. These are
captured before measured calls. A loaded draft/MTP component is not proof
that every request used it; `spec_exact` is the server's reported row-exact
decoding setting. Missing settings stay unknown. Other engines currently
contribute no API-observed serving settings.

The field is bounded and part of the integrity-sealed result. Historical results
without it remain valid. The leaderboard displays it in row details, but does
not use it to group models or claim that two settings are equivalent. Settings
can also change during a run. `observation_phase` and `observed_at` identify the
capture: mlx-serve uses its verified instance before measurement; Ollama and LM
Studio are queried after measurement. These snapshots do not prove that settings
stayed constant between the two boundaries.

### Version and client-environment evidence

`engine.version` prefers the serving API or, for LM Studio, the runtime that
answered the backend probe. `version_source` distinguishes `server_api` and
`runtime_probe` from `process_package`, the indirect evidence described above.
`client_version` is separate: a package or executable in the client's environment
cannot prove which version is running on another port or in another environment.
If no version can be established, it stays `unknown`. Protocol 5 requires explicit
evidence tied to the server; equality with `client_version` does not establish
that link. Historical `client_cli` and `client_package` values remain readable
with a warning, but are insufficient for a new protocol-5 submission. Protocol-4
submission rules remain unchanged during the release transition.

`meta.client_environment` records selected measurement-client dependency versions.
The existing result integrity seal covers this mapping, so no second hash is
generated. Early development files with a fingerprint remain readable. The field
contains no installation paths and makes no network requests. It documents the
client environment; it
does not attest the server environment or replace artifact verification.

### Server Identity Checks

mlx-Chronos checks more than `/v1/models` for engines that can be confused with
another server on the same port.

oMLX and vllm-mlx both default to port `8000`, so oMLX validation also checks
the listening process with `lsof` and requires it to match the expected oMLX
process name. Rapid-MLX and mlx-lm also require their expected listener process.
A reachable OpenAI-compatible endpoint alone does not establish engine identity.

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
size are not stored in the result.

### mlx-serve: Local MLX Gate

This integration targets [ddalcu/mlx-serve](https://github.com/ddalcu/mlx-serve),
not other projects with the same name. Requests use its OpenAI-compatible
`/v1/chat/completions` endpoint and the common client-side timing protocol.
Its internal timing extensions are not substituted for Chronos measurements.

Chronos requires one exact, unambiguous ID from `/v1/models`; serving aliases,
suffix matches and the server's default-model fallback are not used. A row
must advertise chat capability and belong to the local server. LAN peers and
configured providers are rejected, because local hardware/RAM/thermal samples
would not describe the machine performing their inference.

The row must first report `meta.engine: mlx`. Only then, if the instance is
unloaded, `POST /v1/load-model` loads that exact ID before measured work.
Chronos does not send `default: true`; automatic default
selection, such as the first chat model on a headless server, remains the
server's policy. Chronos then reads the
ready, loaded row and requires `meta.engine: mlx`, identifying the MLX
safetensors path. All GGUF paths are outside this integration's scope,
including the native MLX GGUF reader (`mlx-gguf`) and unresolved `gguf` stubs.
`llama`, `ds4` and missing backend evidence are also rejected. These checks
run before loading and again after loading, before any inference. New public
mlx-serve results require API-observed
`engine.serving_config.observed.backend: mlx` and `model.format: safetensors`.

Safetensors quantization metadata is authoritative for supported integer bit
widths. Ambiguous `0-bit`/`16-bit` metadata does not identify fp16 versus bf16,
so Chronos retains the operator's declaration in those cases. `engine.version` is the
mlx-serve server release, not the version of an unrelated local MLX package.
An inaccessible version API on an identified server remains `unknown`.
Cache clearing/hit-counter verification is not exposed by this integration;
cached TTFT retains the common priming procedure and its existing warnings.

### LM Studio: MLX-Only Gate

LM Studio ships two runtimes on Apple Silicon — MLX and llama.cpp — and this
project is scoped to MLX engines only. A model name alone does not say which
runtime will answer a request, so mlx-Chronos gates acceptance twice before any
measured call:

1. `GET /api/v0/models/{model}` must report `compatibility_type: "mlx"`. This
   describes the weights, not the runtime, so it is necessary but not
   sufficient.
2. A tiny non-streaming completion through `POST /api/v0/chat/completions`
   must come back with an MLX-named `runtime`. When `supported_formats` is
   present, it must include `mlx` or `safetensors`: LM Studio's MLX runtime
   can report the latter as the weight format. `safetensors` alone is not
   evidence of an MLX runtime. This describes what actually answered.

A GGUF model is rejected at step 1 without ever reaching step 2. Any probe
answered by a non-MLX runtime is rejected at step 2.
`engine.version` for LM Studio records the MLX runtime version returned by
that probe, not the LM Studio application version, because the runtime is what
determines the measured performance.

This experimental integration uses the documented v0 endpoints because the
completion response exposes both model and active-runtime evidence. LM Studio
recommends its newer v1 API for new clients, but a migration here requires
equivalent runtime proof and is not a mechanical endpoint substitution.

---

## Concurrency: Local Throughput-Under-Load Diagnostic

`mlx-chronos concurrency --engine vllm-mlx --model MODEL --levels 1,2,4,8`
tests how one running server handles multiple independent requests at once.
It is **not** a `run` profile or a sealed `BenchmarkResult`; its JSON and
Markdown reports go under `results/local/concurrency/`, and `submit` and the
public leaderboard do not accept them. The default is three measured waves
per level, 60 requested maximum output tokens per request, and one additional
unmeasured warm-up wave immediately before each measured wave. Thus the
default workload sends 45 warm-up and 45 measured requests. Start with low
levels if memory headroom is limited.

`--levels` accepts distinct integers from 1 to 32, `--trials-per-level` accepts
1 to 10 measured waves per level, and `--request-max-tokens` controls each
request's output bound. JSON and Markdown are both written by default;
`--format` and `--output-dir` can change report output.

Each worker waits on a barrier before starting its request. The wave clock
starts when the barrier releases; it excludes thread creation and queued
worker setup, but includes client-side dispatch, server processing, response
streaming and client parsing. The workers share one HTTP client whose idle
connection capacity is at least the highest selected level, so level 32 does
not silently lose warmed connections between waves. **Aggregate throughput**
is the *sum of exact completion tokens* across the wave divided by the elapsed
time until its last response. It is not the sum of each request's individual
tok/s. If a measured request fails, or the server does not supply exact
completion-token usage, the run stops without publishing a partial result.
The same happens when any measured request produces fewer than 80% of its
requested maximum tokens: short replies would change the workload across
levels. Request elapsed
times and request-start spread are also recorded so a staggered launch is
visible.

This is a **cache-minimized workload, not a verified cache-cold benchmark**:

- Every request, including warm-up, receives a unique run-specific identifier
  near the start of one fixed prompt template. This avoids exact repeats
  across waves and previous runs. The report stores the exact prompts and
  their character lengths; input *token* counts are not available uniformly.
- After warm-up and before each measured wave, mlx-Chronos asks the engine to
  clear its prefix cache when its documented API supports that operation.
  `cache_clear_confirmed` is true only for an affirmative response. For
  vllm-mlx, whose [cache API documents background re-warming](https://github.com/waybarrios/vllm-mlx/blob/main/docs/guides/warm-prompts.md),
  such a response is **not** treated as confirmation of a cold measurement.
  Other engines may not expose a usable cache-clear operation.
- When the engine exposes a labelled text-prefix-cache hit counter, its
  before/after values and delta are recorded. A missing counter means
  *unknown*, not zero hits; a counter can also include traffic from other
  clients. Different prompts can still share a short chat-template prefix.

Levels are rotated in execution order between rounds to reduce systematic
first-level versus last-level warm-up or thermal bias. The order and thermal
state immediately before and after each measured wave are retained in JSON.
This does not remove all thermal or memory-pressure effects, nor does a client
barrier prove that the server kept all requests active simultaneously.
Interpret the output as a local serving-capacity diagnostic, preferably with
the same model, hardware, server configuration, token bounds and cache policy.
There is deliberately no cache-warm mode in this initial implementation.

---

## Local Multi-Engine Matrix

`mlx-chronos matrix --engine-model 'omlx=ORG/MODEL' --engine-model
'ollama=ALIAS:TAG'` is a **local orchestration aid**, not a claim that different
server-side names identify the same weights. Pass one exact `ENGINE=MODEL` pair
per engine; an optional common `--model-url` is only a reference, not artifact
verification. Check repository, revision, weight file and quantization yourself
before interpreting cross-engine differences. All selected servers must already
be running. On a low-memory Mac, start with only engines and models the machine
can keep loaded safely; the command does not start, stop or unload servers.

Before any measured benchmark, matrix checks *every* selected engine for
identified server availability, model listing/backend and a small accepted
completion request. A declared quantization mismatch is rejected when the
engine exposes authoritative quantization metadata; unavailable metadata is
not treated as proof of a match. Any failed preflight aborts the whole sweep.
These probes can load or warm models; a cooldown follows the final preflight
as well as each full run. The default minimum is 120 seconds, adjustable via
`--cooldown-seconds`. Time elapsed between runs is measured on a monotonic
clock, not inferred from file timestamps. A fixed interval cannot guarantee
return to a cold, thermally identical or memory-idle state.

The first engine order is shuffled with a recorded seed (`--seed` can reproduce
the plan); later rounds cyclically rotate it. By default there are as many
rounds as engines, so every engine occupies every position once. More rounds
should be a multiple of the engine count; fewer rounds are permitted for local
experimentation but are marked as position-unbalanced. This balances *position*,
not every pairwise carryover or changing background activity. One full standard
benchmark is run per engine per round, using the same requested protocol
settings: with N engines the default is N² full benchmarks and N² cooldown
intervals including the one after preflight. Plan the workload before invoking
the command: it prints the schedule but does not wait for interactive
confirmation. The command stops at the first measured failure instead of
presenting a partial sweep as complete.

Standard sealed result files and an incrementally updated `matrix_*.json`
manifest are saved under `results/local/matrix/` by default. The manifest
records the model mapping, accepted request IDs, exact schedule, status, result
filenames, actual cooldown elapsed, and before/after thermal, power, available
RAM and swap snapshots. Unknown readings stay unknown. Each benchmark result
also retains its continuous thermal and RAM diagnostics. Neither snapshots nor
rotation isolate one engine from other servers, prove equal cache state, or
prove equal model artifacts. The manifest is **not** a `BenchmarkResult` and is
not submit-able; individual result files retain their normal schema, but a
matrix sweep alone does not establish leaderboard comparability or justify
publishing them as an engine ranking. There is deliberately no automatically
computed winner.

---

## Local Context Diagnostic

`mlx-chronos context --engine ENGINE --model MODEL` examines how time to first
token (TTFT) changes with *requested character length*. The default buckets
are `small` (2,000 characters) and `medium` (8,000). `large` (32,000) and
`xlarge` (128,000) are available only when explicitly selected with
`--buckets`; long requests may consume substantial RAM, time out, exceed the
model's context limit, or be silently truncated by a server. The command
cannot verify a uniform context limit across all supported engines.

`--trials-per-bucket` defaults to 3 (allowed range 1–10), and
`--request-timeout-seconds` defaults to 120. JSON and Markdown are both written
by default; `--format` can select only one. A failed trial aborts the diagnostic
instead of being silently excluded from an apparently complete report.

Each trial starts with a run/bucket/trial-specific marker before the rotating
filler text. Even at the maximum of ten trials in each of four buckets, no two
generated prompts are identical; a new run uses a new nonce. The report stores
each prompt's actual character length and SHA-256 hash so the input set can be
audited without embedding up to megabytes of prompt text. Distinct text reduces
exact-prefix reuse but **does not prove a cold server cache**.

The streaming TTFT clock stops when the first content or terminal token is
observed. The request continues only to read optional `usage.prompt_tokens`
from the server's trailing usage chunk. Token counts are never inferred from
characters. The report keeps the count alongside each TTFT; its mean is shown
only when *every* trial in that bucket has an engine-reported count. Partial
coverage is labelled `partial_engine`. Because TTFT also includes HTTP,
queueing, and first-token overhead, dividing input tokens by TTFT would not
yield pure prefill throughput; this command deliberately does not publish that
number. Before/after system conditions are recorded per bucket, but sequential
buckets can still have different cache, memory, and thermal states.

This is a local diagnostic, not a sealed `BenchmarkResult`. JSON and Markdown
reports go to `results/local/context/` by default; they are not listed by
`history`, accepted by `submit`, or included in the leaderboard. Comparing
different engines or machines by bucket alone is not justified without a
verified, equivalent model artifact, actual input token counts, context
retention, and controlled runtime conditions.

---

## Experimental Local Energy Diagnostic

`mlx-chronos energy --engine ENGINE --model MODEL` is deliberately separate
from `run`. Install [macmon](https://github.com/vladkens/macmon) first (for
example, `brew install macmon`), start the engine server, and ensure the model
is accessible. This command does not change the public benchmark protocol and
does not produce a sealed or submit-able `BenchmarkResult`.

The command validates model access, performs one short warm-up completion,
starts one long-lived `macmon pipe` sampler, waits for it to produce data, and
optionally settles (5 seconds by default). It then records a distinct
5-second **no-request** window, followed immediately by three unique
throughput requests of at most 100 completion tokens each by default. The
default macmon sampling interval is 500 milliseconds. The engine server and
loaded model remain running during the no-request window, so this is **not**
the Mac's unloaded idle power. No Chronos requests are sent during that window;
other apps and server background work can still affect power. On fast models, increase
`--trials` or `--max-tokens` so the throughput phase lasts long enough: both
measured windows must span at least the greater of 5 seconds and eight requested
sampling intervals. `--trials` accepts 1–30; `--idle-seconds`,
`--settle-seconds` and `--sample-interval-ms` control the windows and sampler.

Each valid `macmon` `sys_power` sample is time-stamped on receipt with the
local monotonic clock. The diagnostic rejects absent/invalid values, ambiguous
`sys_power` fallbacks, insufficient duration, incomplete boundary coverage and
large sample gaps. It linearly interpolates at phase boundaries and integrates
power using trapezoids to estimate joules for each window. The JSON report in
`results/local/energy/` stores both estimates, the sample trace, phase offsets,
macmon version, request token counts, thermal state and RAM/swap snapshots.
The local file is not indexed by `history` or accepted by `submit`.

`sys_power` is a macmon-reported SMC system-power estimate, **not** an
independently calibrated wall-plug measurement. macmon may internally floor it
at its component-power sum; equal values are rejected because their origin is
ambiguous. Sampling and phase boundaries are approximate, especially over
short windows. The reported no-request power is not subtracted from throughput
energy, and neither value isolates model energy, proves cross-machine
comparability, or supports a leaderboard ranking. Interpret it only as a local
diagnostic under recorded conditions. On hardware without a valid macmon
`sys_power` stream, the command fails without saving a misleading report.

---

## Local Comparison and History

`mlx-chronos compare <file1> <file2> [...]` and `mlx-chronos history` are
local conveniences over result files that already exist — neither talks to
an engine, and neither is a benchmark profile.

`compare` checks the schema and integrity seal of two or more result files,
without requiring the additional public-submission conditions. Comparing
exploratory local runs that are not publishable is still useful. It prints a
metric-by-metric table with each file's value and its percentage delta against the *first*
file, which is always the baseline. `*` marks cells with cautions; each caution
identifies the reference/result pair, affected metrics, field and values.
With files A, B and C, a hardware difference between A and C does not flag A–B.
A metric missing from one file (for
example, an older result with no `decode_tokens_per_second`, or one taken
before `system_ram_delta_gb` existed) shows as `-` rather than a fabricated
number, and its delta shows as unavailable rather than 0%. A zero baseline
also has no percentage delta. `n/a` and a reason identify unavailable deltas.

Completion-count provenance affects **request and decode tok/s**, not TTFT or
RAM. Exact `usage.completion_tokens` counts on both sides permit descriptive
percentages. Two `word_fallback` results permit percentages marked `~` as
word-count estimates. Exact-versus-estimated counts, or `mixed` counts on
either side, retain the measured values but have no throughput percentage:
their numerators do not represent the same unit consistently.

Warnings distinguish **known differences**, **incomplete information**, and
existing **run warnings**. Chip/RAM, model name/reference/quantization/format,
profile, protocol revision and trial-count differences apply across metrics.
Engine versions remain visible; an upgrade may be the intended variable under
study, so known version differences alone do not trigger a warning.

Protocol settings are compared by phase and field: prompts and their changed
positions, token limits, streaming/usage requests, connection mode, sampling
parameters, and available input-token counts/provenance. Cautions include the
phase's own measurements and later measurements that may inherit cache or
thermal state. Warmup and cold-phase changes can affect all subsequent metrics;
cached-phase changes affect cached TTFT and subsequent throughput, and include
the priming request using those same settings. Throughput changes affect
request/decode tok/s and RAM, never earlier TTFT measurements. System RAM
sampling spans all phases; sampling-interval differences apply only to RAM.
These are possible dependencies, not a claim that every setting caused a change.

The existing cached-TTFT warning and unverified prefix-hit evidence are scoped
to cached TTFT. Cache-control evidence identifies the relevant cold/cached
measurements. Failed warmup calls caution subsequent metrics, while the existing
sustained-throttling warning concerns throughput. Missing or unknown optional
metadata remains incomplete even on both sides; it never establishes equality.
The console groups missing evidence into informational comparison limits,
retaining affected pairs and metrics. Warmup/TTFT input-token counts absent on
both sides do not produce cautions because standard runs do not collect them;
available counts and throughput input-usage gaps remain compared. Cached timing
close to cold timing is an observation, not proof that cache reuse failed.
An explicitly recorded `requested_min_tokens: null` means no minimum was
requested, while an omitted field is unknown. Optional parser defaults do not
turn omitted cache evidence or phase settings into observations.

Hardware, model or protocol differences do not block exploratory percentages.
Each percentage is descriptive and does not establish a causal performance gain.
Even without cautions, these checks **do not certify equivalent conditions**:
inspect serving settings, runtime conditions and the underlying results as well.
RAM peak and rise are whole-device diagnostics, not memory attributable to the
engine. These interpretation changes do not alter saved results, the measurement
protocol, integrity seals or public-submission rules.

### Comparing Two Series

Select the two series explicitly, putting all A files before all B files:

```bash
mlx-chronos compare --series-a-size 2 a1.json a2.json b1.json b2.json
```

The first N entries form reference series A; the rest form B. Both must contain
at least one file. This mode uses the session summaries described under
[Repeating a Run](#repeating-a-run), with percentages comparing **B's median to
A's median**. With the option omitted, the existing per-file comparison is
unchanged. There is no inferred campaign grouping or automatic result export.

Every file must pass schema and seal validation before any summary is printed.
Repeated paths or copies with the same sealed payload count once within a
series, with a message identifying each duplicate. The same sealed result on
both sides is rejected: use disjoint selections. Counts describe distinct
recorded sessions, not a guarantee of statistical independence.

Cautions check members against their own series' first session and B members
against A's first session. Within a series, engine name/version changes are
also reported; between series, a known engine upgrade may be the intended
variable. Repeated incomplete fields are condensed into one message naming the
affected comparisons. This does not certify that either series is homogeneous.

Mixed completion-count units within a series prevent its throughput aggregate.
Two uniformly word-estimated series have percentages marked `~`; exact versus
estimated counts have no throughput percentage. TTFT and RAM remain available
independently of that restriction. Missing metrics can leave different available
counts in A and B; inspect those counts before interpreting a median difference.
RAM remains a whole-device diagnostic. No confidence interval or superiority
claim is produced, even when all metadata agrees.

### History

`history` lists valid JSON results directly under `results/local/`, newest
first, without recursing into `context/`, `concurrency/`, `energy/` or `matrix/`.
Use `--output-dir` to select another directory and `--limit N` to limit the
display (default: all). A file that cannot be read as UTF-8 JSON or fails schema
or integrity validation is reported as skipped by name rather than silently
vanishing. Selecting a matrix directory can list its sealed results, while its
manifest is correctly reported as an invalid benchmark result.

---

## Trial Protocol

### Baseline Defaults

Timing inputs such as timeout, cooldown and sampling interval must be finite;
`NaN` and infinity are rejected rather than used in waits or arithmetic.
Each option also enforces its positive or non-negative range. Trial counts
and output bounds must satisfy the selected command's limits.

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

- protocol revision label (`version`), explained below;
- selected benchmark profile: `baseline` or `sustained`;
- exact prompt text for warmup, cold TTFT, cached TTFT, and throughput;
- requested min/max token bounds per phase;
- whether the phase used streaming requests;
- whether `stream_options.include_usage` was requested;
- HTTP connection behavior: `persistent` or `per_request`;
- requested generation parameters such as `temperature` and `top_p`;
- input token counts aligned with phase prompts, and their source.

All seven adapters use the same input-count rule for baseline and sustained
throughput: retain the last positive JSON integer supplied in
`usage.prompt_tokens` by the measured request, with source `engine`. No extra
tokenization call, input estimate or change to request timing is introduced.
Zero placeholders, booleans, floats, strings and negative counts are ignored.
Counts describe the server's reported input; they do not establish tokenizer
identity or equivalent model artifacts.

`meta.benchmark_protocol.throughput.input_tokens` follows trial/prompt order.
If only some requests supply counts, missing positions are `null`; source
`engine` describes the known entries. If no counts are available, the whole
field is `null` and the source is `unavailable`, as in older results. Warmup
and TTFT counts remain unavailable. Local comparisons flag partial counts as
incomplete and compare only positions known in both results. This adds
observational metadata without making otherwise eligible runs unpublishable.

### What does the protocol number mean?

**The number identifies a revision of the standard benchmark method and its
validation rules.** In JSON it is `meta.benchmark_protocol.version`; reports
may show `baseline 5`, and leaderboard details show `Protocol: 5`. Here,
`baseline` is the test profile and `5` is the protocol revision. The `sustained`
profile uses the same revision number.

It is not a performance score, the mlx-Chronos package version, or the macOS
app version. Several package releases can use the same protocol. The label
helps identify measurements made under different rules; validators also
check the full protocol metadata, raw measurements, and integrity seal.
Matching numbers alone do not establish a fair comparison of different models,
engines, hardware, or test conditions.

| Label | What it records |
| --- | --- |
| `1` | Initial structured benchmark protocol metadata, including prompts and token bounds. |
| `2` | Streaming throughput, with the streaming and token-usage request settings recorded explicitly. |
| `3` | Persistent HTTP client behavior recorded in the protocol. Later refinements under this label added a separate warmup prompt, fixed throughput prompts, and deterministic generation settings. |
| `4` | Complete, validated consumption of completion streams, plus thermal sampling coverage requirements for public submissions. |
| `5` | Unrounded raw clock durations and rates, thermal coverage across measured phases, explicit version provenance, strict progress chronology and bounded stream parsing. |

With `4`, the client captures the first-token or completion timestamp and then
finishes reading and validating the response. The extra response-drain time is
not added to TTFT or throughput timing. This permits HTTP connection reuse
when the server supports it and detects incomplete or malformed streams.
Public validation also requires at least two thermal samples and no excessive
sampling gaps. Label `3` reused the client object but could leave response
bodies unread, preventing connection reuse.

**CLI `0.5.1` uses `4`; release `0.5.0` uses `3`.** Revision `4` is included in
[release 0.5.1](../CHANGELOG.md#051--2026-10-04), available through the normal
PyPI installation. The unreleased source on `main` produces `5`. During the
transition, public submissions accept both `4` and `5`, each with its own rules;
protocol `3` is archive-only. Acceptance of `4` will be retired only after the
replacement CLI is publicly available. Archived `3` and `4` remain readable with their
original data and seals; the leaderboard keeps protocol variants separate,
and local comparison warns about differing protocol metadata.

Older producers could record an intermediate progress timestamp after the final
timestamp. Such historical files remain readable without altering their seal.
Reports omit those progress curves from trend interpretation and comparisons
warn against inferring throttling from them. The leaderboard and app label a
stored sustained warning as unverified rather than reporting a confirmed late
slowdown. The derived index records `progress_chronology_warning` and, when the
original warning was set, `sustained_warning_unverified`; its usable
`sustained_throttling_warning` is false. The raw JSON and final trial metrics
remain intact. Protocol `5` rejects inconsistent progress chronology.

To produce a result under a newer protocol, install a CLI that implements it
and run the benchmark again. **Never change the number in an existing JSON.**
That would invalidate its seal, and resealing it would not turn the original
measurement into a run under the newer method.

Context, concurrency, and energy diagnostic reports have their own version
fields. The integrity seal format, app-to-CLI API, and app runtime catalog also
have independent versions. Those numbers do not refer to this standard
benchmark protocol and do not need to match it.

### Contributor Attribution

`meta.submitted_by` optionally records the GitHub handle of the contributor who
ran the benchmark, set with `mlx-chronos run --submitted-by <handle>`. It is
opt-in and validated against GitHub's own handle format. The handle remains in
the sealed result but is not displayed on the leaderboard. Leaving it out is
always allowed and never affects whether a result is publishable.

The wizard also offers this field and preserves it in the equivalent command.
It is a self-declared handle, not proof of account ownership. Inbox contact
email (`submit --email` or `MLX_CHRONOS_SUBMITTER_EMAIL`) is separate from the
sealed attribution. Without an email, the inbox uses an anonymous placeholder,
but any handle already in the JSON remains visible. Never edit sealed results
to add, remove or change attribution.

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
- report a known engine version, Apple M-series chip, `arm64` architecture and
  valid macOS version, with a timestamp no more than 10 minutes in the future;
- complete all warmup calls without failures (`warmup_failures=0`);
- report Low Power Mode as `off`;
- include error-free RAM/RSS monitor diagnostics and continuous Foundation
  thermal sampling, plus reconstructible raw decode timing;
- use standard deterministic generation parameters;
- keep exact standard protocol metadata;
- pass schema validation;
- pass raw-trial consistency validation;
- pass integrity-seal validation;
- avoid duplicate integrity digests or duplicate run identities in the archive;
- be added or modified only as submitted JSON files in result-submission PRs.

Model reference URLs are human-readable references. Model pages can change over
time when maintainers update files or tags.

The full URL remains part of leaderboard model grouping along with model name,
quantization and format. It is not reduced to a Hugging Face repository name,
and no `canonical_id` or automatic alias merging is used. Different engine
request IDs in a matrix are routing identifiers, not artifact identity proofs.
Even an identical URL does not verify unchanged weights, revision or tokenizer.

GitHub Actions enforces this policy before generating the leaderboard index.
Baseline and sustained rows are kept as separate profile choices in the
leaderboard UI.

Use `submit --dry-run` to check a newly generated JSON against the complete
current policy. The repository loader has explicit compatibility handling for
some already archived legacy results; this does not exempt new submissions
from required diagnostics. Swap-growth and thermal warnings provide context
and are not, by themselves, submission blockers.

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

The result-validation workflow checks that the PR changes only submitted JSON
and does not delete results **before installing the PR's package code**. This
ordering reduces that workflow's exposure to mixed result/code PRs; it is not
a general sandbox guarantee for every CI job.

These checks improve comparability and catch accidental or casual tampering.
They are not a cryptographic hardware attestation system.

---

## Leaderboard Export and Chart

The Raw tab exports the currently filtered and sorted index rows. CSV includes
only the currently visible columns and uses plain values rather than rendered
HTML. JSON includes all indexed fields in each filtered row; neither export is
a full benchmark result with trials and an integrity seal. The original public
result files are in the repository's `results/submitted/` directory.

The Compare tab uses the same representative rows as its table to draw an
inline chart of request throughput by engine. It is hidden when fewer than two
engines match. These are presentation tools, not new benchmark measurements.

The page also includes description, Open Graph, Twitter Card and favicon
metadata for clearer search and link previews. No social preview image is
declared.

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
