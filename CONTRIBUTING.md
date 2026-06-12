# Contributing to mlx-Chronos

Thank you for your interest in contributing to mlx-Chronos.
There are two ways to contribute: submitting benchmark results and improving the codebase.

---

## Submitting Your Benchmark Results

### Prerequisites

- A Mac with Apple Silicon (M1, M2, M3, M4, or M5)
- At least one supported engine installed and running:
  - [Ollama](https://github.com/ollama/ollama) (MLX backend)
  - [oMLX](https://github.com/jundot/omlx)
  - [Rapid-MLX](https://github.com/raullenchai/Rapid-MLX)
  - [vllm-mlx](https://github.com/raullenchai/vllm-mlx)
  - [mlx-lm](https://github.com/ml-explore/mlx-lm)
- Python 3.10+

### Steps

**1. Install mlx-Chronos**
```bash
pip install mlx-chronos
```

**2. Start your engine server**

Use the server command for your engine and model. Examples:

For oMLX:
```bash
omlx serve --model-dir ~/models
```

For Rapid-MLX:
```bash
rapid-mlx --no-telemetry serve /path/to/model --port 8001
```

For vllm-mlx:
```bash
vllm-mlx serve mlx-community/Llama-3.2-3B-Instruct-4bit --port 8000
```

For mlx-lm:
```bash
mlx_lm.server --model /path/to/model --port 8080
```

For Ollama:
```bash
ollama serve
```

mlx-Chronos checks these default OpenAI-compatible endpoints:

| Engine | Default URL |
|--------|-------------|
| oMLX | `http://localhost:8000/v1` |
| Rapid-MLX | `http://localhost:8001/v1` |
| vllm-mlx | `http://localhost:8000/v1` |
| mlx-lm | `http://localhost:8080/v1` |
| Ollama | `http://localhost:11434/v1` |

You can override a port with an environment variable such as
`MLX_CHRONOS_VLLM_MLX_PORT=8003` or `MLX_CHRONOS_MLX_LM_PORT=8002`.
oMLX and vllm-mlx both default to port 8000, so run only one of them on that
port at a time, or move one server and set the matching environment variable.
For oMLX, mlx-Chronos also checks the listening process with `lsof` to avoid
mistaking another OpenAI-compatible server on port 8000 for oMLX. If `lsof`
cannot inspect the listener, validation may report that oMLX is not running even
when `/v1/models` responds.

**3. Run the benchmark**
```bash
mlx-chronos engines                          # check engine status
mlx-chronos validate --engine omlx \
  --model "Qwen3.5-4B-OptiQ-4bit"
mlx-chronos run --engine omlx \
  --model "Qwen3.5-4B-OptiQ-4bit" \
  --trials 5
```

**4. Submit your result**
```bash
mlx-chronos submit --file results/local/your-result.json --dry-run
```

This validates the JSON locally without sending it. To submit the result for the
public leaderboard, copy the checked JSON into `results/submitted/` with a clear
filename and open a pull request that changes only that JSON file. GitHub
Actions will label the PR as `result-submission`, validate the file, and keep
submission PRs easy to filter from code changes.

If opening a PR is inconvenient, the maintainer inbox remains available as a
fallback:
```bash
mlx-chronos submit --file results/local/your-result.json
```

Local benchmark runs can use custom trial counts, token bounds, profiles,
cooldown, connection mode, and notes. Keep those results in `results/local/`
for your own diagnostics.

Public leaderboard submissions are stricter. They must use
`usage.completion_tokens` as the throughput token-count source and one of the
standard profiles: `baseline` with exactly 5 trials and
`requested_max_tokens=100`, or `sustained` with exactly 1 trial and
`requested_max_tokens=1000`. Neither profile may request `min_tokens`, and
macOS Low Power Mode must be disabled. Each throughput trial must generate at
least 80% of the standard token limit: 80 tokens for baseline, 800 tokens for
sustained. If your JSON says
`"token_count_source": "word_fallback"` or `"mixed"`, keep it as a local result
until the engine can return a real completion-token count. New local fallback
results also set `meta.word_fallback_warning` to make that limitation explicit.

New result files include benchmark protocol metadata with the exact prompts and
requested token bounds and generation parameters. Keep those fields unchanged
when submitting results; they are used to make runs reproducible and easier to
compare. Current publishable results use streaming throughput requests with a
persistent HTTP client and deterministic generation parameters
(`temperature=0.0`, `top_p=1.0`).
The small protocol labels stored in JSON, such as `1`, `2`, or `3`, are internal
compatibility markers used by validators; they are not public protocol release
versions.
The standard leaderboard workloads are baseline `requested_max_tokens=100` and
sustained `requested_max_tokens=1000`, both without a requested `min_tokens`;
non-standard token-bound runs are useful locally but are not accepted as public
leaderboard submissions.

New results also distinguish request throughput from decode throughput. Do not
edit `tokens_per_second`, `request_tokens_per_second`,
`decode_tokens_per_second`, or the raw trial arrays by hand.

### Result File Format

Results must follow the schema defined in `mlx_chronos/schema.py`.
See `docs/methodology.md` for a full explanation of each field.

---

## Contributing Code

### Setup

```bash
git clone https://github.com/igurss/mlx-chronos.git
cd mlx-chronos
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
```

### External Contributor Workflow

For code or documentation changes, fork the repository, create a focused branch
from `main`, and open a pull request back to `igurss/mlx-chronos`. Keep code
changes separate from leaderboard result submissions so each PR has one review
path.

For leaderboard result submissions, open a PR that changes only JSON files under
`results/submitted/`. GitHub Actions rejects mixed PRs, deleted submitted result
files, invalid schemas, broken integrity seals, non-standard public benchmark
profiles, fallback token counts, requested `min_tokens`, Low Power Mode runs,
short-output runs, and non-standard public trial counts or token bounds.

For code changes, run the relevant tests locally before opening the PR. The
maintainer reviews code, docs, and result-submission PRs separately; benchmark
result PRs are expected to be mechanical JSON submissions, while feature PRs
should explain the behavior change and include tests.

### Guidelines

- Follow the existing code style
- Add docstrings or comments only where they clarify non-obvious behavior
- Test your changes before opening a PR
- Reference the relevant Issue in your commit message (e.g. `feat: add engine (#3)`)
- Keep PRs focused — one feature or fix per PR

### Opening an Issue

Before opening a PR for a new feature, open an Issue first to discuss it.
Bug reports and feature requests are welcome.

---

## Code of Conduct

Be respectful. This is an open project welcoming contributors of all levels.
