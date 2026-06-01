"""mlx-chronos: Benchmark suite and community leaderboard for local LLM inference on Apple Silicon."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mlx-chronos")
except PackageNotFoundError:
    __version__ = "0.1.1"

__all__ = ["__version__", "run_benchmark"]


def __getattr__(name: str):
    if name == "run_benchmark":
        from .benchmark import run_benchmark

        return run_benchmark
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
