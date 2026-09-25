"""Local multi-engine sweep planning and environmental diagnostics.

This module deliberately does not infer that differently named models have
identical weights. A matrix is an execution schedule, not an identity proof.
"""

import json
import random
from datetime import datetime, timezone
from pathlib import Path

import psutil

from mlx_chronos.detect import get_low_power_mode, get_power_source, get_thermal_state
from mlx_chronos.reporters import _write_text_atomic


def parse_engine_models(assignments: list[str], valid_engines: set[str]) -> dict[str, str]:
    """Require one explicit, non-empty model ID for every selected engine."""
    if not assignments:
        raise ValueError("specify at least one --engine-model ENGINE=MODEL")
    models: dict[str, str] = {}
    for assignment in assignments:
        if "=" not in assignment:
            raise ValueError(f"invalid --engine-model {assignment!r}; expected ENGINE=MODEL")
        engine, model = (part.strip() for part in assignment.split("=", 1))
        if engine not in valid_engines:
            raise ValueError(f"unknown engine {engine!r}; choose from {sorted(valid_engines)}")
        if not model:
            raise ValueError(f"empty model ID for engine {engine!r}")
        if engine in models:
            raise ValueError(f"duplicate model assignment for engine {engine!r}")
        models[engine] = model
    return models


def rotation_schedule(engines: list[str], rounds: int, seed: int) -> list[list[str]]:
    """Shuffle a reproducible base order, then rotate each successive round."""
    if not engines or rounds < 1:
        raise ValueError("schedule needs at least one engine and one round")
    if len(set(engines)) != len(engines):
        raise ValueError("schedule engines must be distinct")
    base = list(engines)
    random.Random(seed).shuffle(base)
    return [base[index % len(base):] + base[:index % len(base)] for index in range(rounds)]


def _probe(probe) -> str:
    try:
        return str(probe())
    except Exception:
        return "unavailable_error"


def sample_matrix_conditions() -> dict:
    """Take a point-in-time snapshot; unknown measurements remain unknown."""
    snapshot: dict[str, str | float | None] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "thermal_state": _probe(get_thermal_state),
        "power_source": _probe(get_power_source),
        "low_power_mode": _probe(get_low_power_mode),
        "ram_available_gb": None,
        "ram_used_gb": None,
        "swap_used_gb": None,
    }
    try:
        memory = psutil.virtual_memory()
        snapshot["ram_available_gb"] = round(memory.available / 1024**3, 3)
        snapshot["ram_used_gb"] = round((memory.total - memory.available) / 1024**3, 3)
    except Exception:
        pass
    try:
        snapshot["swap_used_gb"] = round(psutil.swap_memory().used / 1024**3, 3)
    except Exception:
        pass
    return snapshot


def save_matrix_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_text_atomic(path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
