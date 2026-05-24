# Changelog

## [0.1.0] — 2026-05-24

### First public release

**Engines supported:**
- oMLX (port 8000)
- Rapid-MLX (port 8001)

**Features:**
- Hardware auto-detection (chip, RAM, macOS, Python version)
- Standardized benchmark protocol: 5 trials, unique cold prompts, cache priming
- Statistical output: mean, stddev, min, max per metric
- Pydantic schema validation for all results
- CLI: `mlx-chronos run` and `mlx-chronos engines`
- GitHub Actions: automatic result validation on PR
- GitHub Pages leaderboard with sortable table and engine/chip filters
- Community submission workflow via Pull Request

**Known limitations:**
- oMLX version not retrievable when server is already running
- RAM measured as system fallback (process RSS detection pending)
- Tool calling rate not yet implemented
- mlx-lm integration not yet available