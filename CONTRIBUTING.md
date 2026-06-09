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
| mlx-lm | `http://localhost:8080/v1` |
| Ollama | `http://localhost:11434/v1` |

You can override a port with an environment variable such as
`MLX_CHRONOS_MLX_LM_PORT=8002`.

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

Public leaderboard submissions must use `usage.completion_tokens` as the
throughput token-count source and one of the standard profiles: `baseline` with
at least 5 trials and `requested_max_tokens=100`, or `sustained` with 1 trial
and `requested_max_tokens=1000`. Neither profile may request `min_tokens`. If
your JSON says `"token_count_source": "word_fallback"` or `"mixed"`, keep it as
a local result until the engine can return a real completion-token count. New
local fallback results also set
`meta.word_fallback_warning` to make that limitation explicit.

New result files include benchmark protocol metadata with the exact prompts and
requested token bounds. Keep those fields unchanged when submitting results;
they are used to make runs reproducible and easier to compare. Current
protocol v2 results use streaming throughput requests; older protocol v1
results used non-streaming throughput requests. The standard leaderboard
workloads are baseline `requested_max_tokens=100` and sustained
`requested_max_tokens=1000`, both without a requested `min_tokens`;
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
