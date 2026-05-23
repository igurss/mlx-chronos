# mlx-Chronos ⏱️

> Benchmark suite and community leaderboard for local LLM inference on Apple Silicon.  
> Run it. Share your results. Compare across hardware.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-green.svg)](https://python.org)
[![Apple Silicon](https://img.shields.io/badge/Apple_Silicon-M1_|_M2_|_M3_|_M4-black?logo=apple)](https://apple.com)
[![Contributions Welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg)](CONTRIBUTING.md)

---

## What is mlx-Chronos?

mlx-Chronos is a standardized benchmarking tool for local LLM inference engines
on Apple Silicon. It automatically detects your hardware, runs a consistent set
of tests across installed engines, and produces a structured JSON result you can
contribute to the community leaderboard.

**Supported engines:**
- [oMLX](https://github.com/jundot/omlx)
- [Rapid-MLX](https://github.com/raullenchai/Rapid-MLX)
- [mlx-lm](https://github.com/ml-explore/mlx-examples)

**Metrics measured:**
- **TTFT** — Time to First Token (cold and cached)
- **tok/s** — Generation throughput
- **Tool calling** — Success rate across model families
- **RAM usage** — Peak memory during inference

---

## Community Leaderboard

> 🚧 Results coming soon — be the first to submit yours.

| Hardware | Engine | Model | tok/s | TTFT cold | TTFT cached |
|----------|--------|-------|-------|-----------|-------------|
| — | — | — | — | — | — |

---

## Quick Start

```bash
# Install
pip install git+https://github.com/igurss/mlx-chronos.git

# Run benchmarks
mlx-chronos run

# View your results
mlx-chronos report
```

---

## Contributing Your Results

1. Run `mlx-chronos run` on your Mac
2. A JSON file is generated in `results/submitted/`
3. Fork this repo, add your result file, open a PR
4. GitHub Actions validates your result automatically
5. Once merged, the leaderboard updates

---

## Roadmap

- [x] Project structure
- [ ] Hardware detection (chip, RAM, macOS)
- [ ] oMLX integration
- [ ] Rapid-MLX integration  
- [ ] mlx-lm integration
- [ ] GitHub Actions result validator
- [ ] GitHub Pages leaderboard

---

## License

Apache 2.0 — see [LICENSE](LICENSE)