# mlx-Chronos Benchmark Methodology

This document explains exactly what mlx-Chronos measures, how it measures it,
and why each decision was made. Reproducibility and transparency are core goals.

---

## Metrics

### TTFT Cold — Time to First Token (cold)
Time in seconds from sending the request to receiving the first real content
token in the streaming response. "Cold" means the model has not seen this
prompt before — no cache advantage.

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

Non-streaming mode is used (`stream: false`) so the total token count is
available from the API response's `usage.completion_tokens` field.

### RAM Peak (GB)
Memory used by the engine process during inference, measured after all trials
complete. Reported in GB.

When the engine process cannot be identified by port, system-used memory is
reported as a fallback. This is noted in the result with a warning.

### Base RAM Load (%)
System RAM usage percentage measured before the benchmark starts. This is
captured once during hardware detection to give context about background load.

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

Results may vary slightly across runs due to thermal state and system load.
This is expected and reflected in the stddev field.