# Contributing to mlx-Chronos

Thanks for helping improve mlx-Chronos. Contributions usually fall into two
paths: submitting benchmark results or improving the project itself.

## Contents

- [Ways to Contribute](#ways-to-contribute)
- [Submit Benchmark Results](#submit-benchmark-results)
- [Contribute Code or Docs](#contribute-code-or-docs)
- [Open an Issue](#open-an-issue)
- [Code of Conduct](#code-of-conduct)

---

## Ways to Contribute

| Contribution | Best path | Keep separate from |
| --- | --- | --- |
| Public benchmark result | Pull request with JSON under `results/submitted/` | Code or docs changes |
| Code fix | Focused pull request from a fork or branch | Leaderboard result files |
| Documentation update | Focused pull request | Benchmark result files |
| Feature idea | Issue first, then implementation PR | Unrelated refactors |
| Bug report | Issue with reproduction details | Speculative fixes |

Mixed PRs are harder to validate and review. Keep each PR focused on one
result submission, one fix, or one feature.

---

## Submit Benchmark Results

### Requirements

| Requirement | Details |
| --- | --- |
| Hardware | Apple Silicon Mac: M1, M2, M3, M4, or M5 |
| Python | Python 3.10 or newer |
| Engine | One supported engine installed and running |
| Power mode | Low Power Mode must be off for public leaderboard rows |
| Token counts | Public rows must use `usage.completion_tokens` |

Supported engines:

- [Ollama](https://github.com/ollama/ollama) with the MLX backend
- [oMLX](https://github.com/jundot/omlx)
- [Rapid-MLX](https://github.com/raullenchai/Rapid-MLX)
- [vllm-mlx](https://github.com/waybarrios/vllm-mlx)
- [mlx-lm](https://github.com/ml-explore/mlx-lm)

### 1. Install mlx-Chronos

```bash
pip install mlx-chronos
```

Optional thermal-state support:

```bash
pip install "mlx-chronos[thermal]"
```

### 2. Start an Engine Server

Use the server command for your engine and model.

```bash
# oMLX
omlx serve --model-dir ~/models

# Rapid-MLX
rapid-mlx --no-telemetry serve /path/to/model --port 8001

# vllm-mlx
vllm-mlx serve mlx-community/Llama-3.2-3B-Instruct-4bit --port 8000

# mlx-lm
mlx_lm.server --model /path/to/model --port 8080

# Ollama
ollama serve
```

Default OpenAI-compatible endpoints:

| Engine | Default URL |
| --- | --- |
| oMLX | `http://localhost:8000/v1` |
| Rapid-MLX | `http://localhost:8001/v1` |
| vllm-mlx | `http://localhost:8000/v1` |
| mlx-lm | `http://localhost:8080/v1` |
| Ollama | `http://localhost:11434/v1` |

Override ports with environment variables:

```bash
MLX_CHRONOS_VLLM_MLX_PORT=8003
MLX_CHRONOS_MLX_LM_PORT=8002
```

> **Port note**
> oMLX and vllm-mlx both default to port `8000`. Run only one of them on that
> port at a time, or move one server and set the matching
> `MLX_CHRONOS_<ENGINE>_PORT` variable.

For oMLX, mlx-Chronos also checks the listening process with `lsof` so a
different OpenAI-compatible server on port `8000` is not mislabeled as oMLX. If
`lsof` cannot inspect the listener, validation may report that oMLX is not
running even when `/v1/models` responds.

### 3. Validate the Setup

```bash
mlx-chronos engines
mlx-chronos validate --engine omlx --model "Qwen3.5-4B-OptiQ-4bit"
```

`validate` checks hardware, engine availability, server reachability, model
listing, and an optional tiny completion request.

### 4. Run the Benchmark

```bash
mlx-chronos run --engine omlx \
  --model "Qwen3.5-4B-OptiQ-4bit" \
  --model-url "https://huggingface.co/mlx-community/Qwen3.5-4B-OptiQ-4bit" \
  --trials 5
```

The result JSON is written to `results/local/`. Use `--format all` if you also
want a Markdown summary for local reading.

Local runs may use custom trial counts, token bounds, profiles, cooldown,
connection mode, and notes. Keep non-standard runs in `results/local/` for your
own diagnostics.

### 5. Check Public Eligibility

```bash
mlx-chronos submit --file results/local/your-result.json --dry-run
```

This validates the JSON locally without sending it anywhere.

Public leaderboard submissions must pass this check and meet one of the
standard profiles:

| Profile | Trials | `requested_max_tokens` | Minimum generated output | `min_tokens` |
| --- | ---: | ---: | ---: | --- |
| Baseline | 5 | 100 | 80 tokens | Not allowed |
| Sustained | 1 | 1000 | 800 tokens | Not allowed |

Additional public requirements:

- `metrics.token_count_source` must be `usage.completion_tokens`.
- `model.reference_url` must point to the model used for the run.
- `hardware.low_power_mode` must be `off`.
- Benchmark protocol metadata must remain unchanged.
- Generation parameters must remain deterministic: `temperature=0.0`,
  `top_p=1.0`.
- Throughput timing fields and raw trial arrays must not be edited by hand.

Model pages can change over time when maintainers update files or tags.

If your JSON says `"token_count_source": "word_fallback"` or `"mixed"`, keep it
as a local result until the engine can return real completion-token usage. New
fallback results also set `meta.word_fallback_warning`.

The small protocol labels stored in JSON, such as `1`, `2`, or `3`, are
internal compatibility markers used by validators. They are not public protocol
release versions.

### 6. Open a Result PR

1. Copy the checked JSON into `results/submitted/` with a clear filename.
2. Open a pull request that changes only that JSON file.
3. GitHub Actions labels the PR as `result-submission`.
4. CI validates schema, raw trials, integrity seal, public-profile rules, and
   PR scope.
5. A maintainer reviews the result before merge.

> **Do not edit result JSON by hand**
> Public submissions include an `integrity` seal over the canonical result
> payload. Changing benchmark fields invalidates the seal and CI rejects the
> file.

### Inbox Fallback

If opening a PR is inconvenient, send a validated result to the maintainer
inbox:

```bash
mlx-chronos submit --file results/local/your-result.json
```

Maintainers can override the inbox endpoint with `--endpoint` or
`MLX_CHRONOS_SUBMIT_ENDPOINT`.

### Result File Format

Results must follow the schema in `mlx_chronos/schema.py`.
See [docs/methodology.md](docs/methodology.md) for field-level measurement
details.

---

## Contribute Code or Docs

### Setup

```bash
git clone https://github.com/igurss/mlx-chronos.git
cd mlx-chronos
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
```

### Workflow

1. Fork the repository or create a focused branch from `main`.
2. Keep code/docs changes separate from leaderboard JSON submissions.
3. Make the smallest change that solves the issue.
4. Add or update tests when behavior changes.
5. Run the relevant tests locally.
6. Open a pull request back to `igurss/mlx-chronos`.

### Test Command

```bash
python -m pytest
```

For targeted work, run the smallest relevant subset first, then the full suite
before opening the PR when practical.

### Guidelines

- Follow the existing code style.
- Prefer focused changes over broad refactors.
- Add comments only where they clarify non-obvious behavior.
- Include tests for behavior changes, regressions, and schema validation.
- Reference the relevant issue in the PR or commit when one exists, for example
  `feat: add engine support (#3)`.
- Explain user-visible behavior changes in the PR description.

GitHub Actions rejects mixed PRs, deleted submitted result files, invalid
schemas, broken integrity seals, non-standard public benchmark profiles,
fallback token counts, requested `min_tokens`, Low Power Mode runs,
short-output runs, and non-standard public trial counts or token bounds.

---

## Open an Issue

Open an issue before starting a larger feature or protocol change. Bug reports
and small fixes are also welcome; include the engine, model, command, logs, and
environment details needed to reproduce the problem.

---

## Code of Conduct

Be respectful. This is an open project welcoming contributors of all levels.
