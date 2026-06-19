"""mlx-chronos: Benchmark suite and community leaderboard for local LLM inference on Apple Silicon."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re


def _source_tree_version() -> str | None:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


def _resolve_version(
    source_tree_version: str | None,
    installed_version: str | None,
) -> str:
    """Resolve a version without duplicating release numbers in source code."""
    return source_tree_version or installed_version or "unknown"


_installed_version: str | None
try:
    _installed_version = version("mlx-chronos")
except PackageNotFoundError:
    _installed_version = None

__version__ = _resolve_version(_source_tree_version(), _installed_version)

__all__ = ["__version__", "run_benchmark"]


def __getattr__(name: str) -> object:
    if name == "run_benchmark":
        from .benchmark import run_benchmark

        return run_benchmark
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
