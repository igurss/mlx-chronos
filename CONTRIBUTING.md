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
  - [mlx-lm](https://github.com/ml-explore/mlx-examples)
- Python 3.10+

### Steps

**1. Install mlx-Chronos**
```bash
pip install git+https://github.com/igurss/mlx-chronos.git
```

**2. Start your engine server**

For oMLX:
```bash
omlx serve --model-dir ~/models
```

For mlx-lm:
```bash
mlx_lm.server --model /path/to/model --port 8080
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
mlx-chronos run --engine omlx \
  --model "Qwen3.5-4B-OptiQ-4bit" \
  --trials 5
```

**4. Submit your result**
- Fork this repository
- Copy the JSON you want to publish from `results/local/` into `results/submitted/`
- Open a Pull Request
- GitHub Actions will validate your result automatically
- Once approved and merged, the leaderboard updates

Public leaderboard submissions must use `usage.completion_tokens` as the
throughput token-count source. If your JSON says `"token_count_source":
"word_fallback"` or `"mixed"`, keep it as a local result until the engine can
return a real completion-token count.

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
- Add docstrings to all functions
- Test your changes before opening a PR
- Reference the relevant Issue in your commit message (e.g. `feat: add engine (#3)`)
- Keep PRs focused — one feature or fix per PR

### Opening an Issue

Before opening a PR for a new feature, open an Issue first to discuss it.
Bug reports and feature requests are welcome.

---

## Code of Conduct

Be respectful. This is an open project welcoming contributors of all levels.
