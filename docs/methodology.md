# mlx-Chronos Benchmark Methodology

This document explains exactly what mlx-Chronos measures, how it measures it,
and why each decision was made. Reproducibility and transparency are core goals.

---

## Metrics

### TTFT Cold — Time to First Token (cold)
Time in seconds from sending the request to receiving the first real content
token in the streaming response. "Cold" means the model has not seen this
prompt before — no cache advantage.

TTFT is measured with Python's monotonic high-resolution performance counter,
so wall-clock changes during a run do not affect the latency value.

Each trial uses a **unique prompt** from a fixed pool defined in `benchmark.py`.
This ensures the engine cannot serve the response from a previous cache hit.

### TTFT Cached — Time to First Token (cached)
Same measurement, but using a **fixed prompt** that is sent on every trial.
A priming call (not recorded) is made before the trial loop to load this prompt
into the engine cache. Subsequent measurements reflect true cache performance.

### Throughput (tok/s)
Tokens generated per second, measured using a fixed standard prompt defined
in the project. The prompt is identical across all engines and all versions
of mlx-Chronos to ensure comparability. Do not change this prompt without
bumping `chronos_version`.

Non-streaming mode is used (`stream: false`) so the total token count can come
from the API response's `usage.completion_tokens` field. The result records
`metrics.token_count_source`. Leaderboard submissions must use
`usage.completion_tokens`; local runs that fall back to a word-based estimate
are marked as `word_fallback` or `mixed` and are not considered comparable.

### Peak Engine RSS (GB)
Resident memory used by the engine server process, sampled continuously from
before warmup through the recorded trial loop and reported as the observed RSS
peak.

**Important:** this metric is best read as process overhead for the server, API
layer, and runtime. It may not include model weights or Metal allocations that
are mapped outside ordinary process RSS. Model sizes should still be read from
their model cards. This metric helps you understand how "heavy" the engine
process itself is when serving the same model.

When the engine process cannot be identified by port, system-used memory is
reported as a fallback (marked in the results). Fallback values are not the same
metric as process RSS and should not be compared directly against normal engine
RSS values.

The result records both `metrics.ram_is_process_rss` and
`metrics.ram_measurement_method` (`process_rss` or `system_fallback`) so the
leaderboard can distinguish direct process measurements from system-memory
fallbacks.

### System RAM Peak
Total Mac RAM usage is sampled continuously from before warmup through the
recorded trial loop, using the same sampling interval as engine RSS. The result
records the observed peak as `metrics.system_ram_peak_gb` and
`metrics.system_ram_peak_percent`.

This replaces the old pre-run baseline. mlx-Chronos reports memory pressure
while inference is actually happening, so model loading, cache growth, swap, and
other runtime pressure are represented in the result.

The default sampling interval is 50ms (`--ram-sample-interval 0.05`). Lower
values can catch shorter spikes but add more measurement overhead; higher values
reduce overhead but may miss brief peaks. The interval is recorded in result
metadata as `meta.ram_sample_interval_seconds`.

### Thermal State
Thermal state is detected without sudo through macOS `NSProcessInfo` when the
Foundation bridge is available. If that path is unavailable, mlx-Chronos falls
back to `powermetrics`, which requires sudo; otherwise the result records an
`unavailable_*` status.

Performance is heavily impacted by memory pressure (e.g., 7GB used out of 8GB
causes swapping and slows down inference, whereas 7GB used out of 16GB does
not). System RAM peak helps explain performance variances between identical
chips and models.

---

## Trial Protocol

| Parameter | Value |
|-----------|-------|
| Trials per metric | 5 (default) |
| Warmup calls | 2 (not recorded, throughput prompt) |
| Cache priming | 1 call before trial loop (not recorded) |
| Max tokens — TTFT | 1 |
| Max tokens — throughput | 100 |

**Warmup:** two unrecorded calls using the throughput prompt are made before
any measurement. This reduces noise from model loading and JIT compilation.

**Statistics:** mean, stddev, min, max are reported for each metric.
p95 is intentionally omitted for small sample sizes (n=5) where it collapses
to the observed maximum and adds no information.

---

## What Is Not Measured (Yet)

- Tool calling success rate — planned for v0.2
- Thermal throttling awareness — planned for v0.2
- CPU/GPU load at benchmark time — planned for v0.2
- Multi-turn conversation latency

---

## Reproducibility

To reproduce a result:
1. Use the same engine version listed in the JSON
2. Use the same model name and quantization
3. Run on the same hardware (chip + memory)
4. Ensure no other GPU-intensive processes are running
5. Run `mlx-chronos run` with default trial count (5)
6. Submit only results whose throughput token source is `usage.completion_tokens`

Results may vary slightly across runs due to thermal state and system load.
This is expected and reflected in the stddev field.
