import subprocess
import platform
import os
import importlib
import psutil
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class BenchmarkConditionWarning:
    """A user-facing warning about conditions that can skew benchmark results."""

    label: str
    detail: str


@lru_cache(maxsize=1)
def get_system_profiler_hardware() -> dict[str, str]:
    """Return selected hardware fields from system_profiler when available."""
    try:
        result = subprocess.run(
            ["system_profiler", "SPHardwareDataType"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return {}

    fields = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            continue
        fields[key.strip()] = value.strip()
    return fields


@lru_cache(maxsize=1)
def get_chip_model() -> str:
    """Detect the Apple Silicon chip model (e.g. 'Apple M3 Ultra')."""
    try:
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True, text=True
        )
        chip = result.stdout.strip()
        if chip:
            return chip
    except Exception:
        pass
    chip = get_system_profiler_hardware().get("Chip")
    if chip:
        return chip
    return "unknown"


@lru_cache(maxsize=1)
def get_machine_model() -> str:
    """Return the Mac machine identifier (e.g. 'Mac14,2')."""
    try:
        result = subprocess.run(
            ["sysctl", "-n", "hw.model"],
            capture_output=True, text=True
        )
        model = result.stdout.strip()
        if model:
            return model
    except Exception:
        pass
    model = get_system_profiler_hardware().get("Model Identifier")
    if model:
        return model
    return "unknown"


def get_memory_gb() -> float:
    """Return total unified memory in GB."""
    return round(psutil.virtual_memory().total / (1024 ** 3), 1)


def get_macos_version() -> str:
    """Return macOS version (e.g. '15.3.1')."""
    return platform.mac_ver()[0]


def get_python_version() -> str:
    """Return Python version (e.g. '3.11.4')."""
    return platform.python_version()


def get_architecture() -> str:
    """Return host CPU architecture (e.g. 'arm64')."""
    return platform.machine() or "unknown"


def get_thermal_state_from_foundation() -> str | None:
    """Return thermal state via NSProcessInfo when PyObjC/Foundation is available."""
    try:
        foundation = importlib.import_module("Foundation")
        state_value = int(foundation.NSProcessInfo.processInfo().thermalState())
    except Exception:
        return None

    states = {
        0: "nominal",
        1: "fair",
        2: "serious",
        3: "critical",
    }
    return states.get(state_value, f"unavailable_foundation_unknown_state_{state_value}")


def get_thermal_state() -> str:
    """
    Return macOS thermal pressure level.
    Uses NSProcessInfo when available, then falls back to powermetrics.
    """
    foundation_state = get_thermal_state_from_foundation()
    if foundation_state is not None:
        return foundation_state

    if getattr(os, "geteuid", lambda: -1)() != 0:
        return "unavailable_permission"
    try:
        result = subprocess.run(
            ["powermetrics", "-n", "1", "-i", "100", "-s", "thermal"],
            capture_output=True,
            text=True,
            timeout=5
        )
        for line in result.stdout.splitlines():
            if "pressure level" in line.lower():
                return line.split(":")[-1].strip().lower()
        return "unavailable_parse_error"
    except subprocess.TimeoutExpired:
        return "unavailable_timeout"
    except FileNotFoundError:
        return "unavailable_powermetrics_not_found"
    except Exception:
        return "unavailable_error"


def get_power_source() -> str:
    """Return the current macOS power source when pmset is available."""
    try:
        result = subprocess.run(
            ["pmset", "-g", "batt"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except subprocess.TimeoutExpired:
        return "unavailable_timeout"
    except FileNotFoundError:
        return "unavailable_pmset_not_found"
    except Exception:
        return "unavailable_error"

    output = f"{result.stdout}\n{result.stderr}".lower()
    if "battery power" in output:
        return "battery"
    if "ac power" in output:
        return "ac_power"
    return "unavailable_parse_error"


def get_low_power_mode() -> str:
    """Return whether macOS Low Power Mode is enabled when pmset is available."""
    try:
        result = subprocess.run(
            ["pmset", "-g"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except subprocess.TimeoutExpired:
        return "unavailable_timeout"
    except FileNotFoundError:
        return "unavailable_pmset_not_found"
    except Exception:
        return "unavailable_error"

    for line in f"{result.stdout}\n{result.stderr}".splitlines():
        parts = line.strip().lower().split()
        if len(parts) >= 2 and parts[0] == "lowpowermode":
            if parts[-1] == "1":
                return "on"
            if parts[-1] == "0":
                return "off"
            return "unavailable_parse_error"
    return "unavailable_parse_error"


def get_benchmark_condition_warnings(
    hardware: dict,
    power_source: str | None = None,
    low_power_mode: str | None = None,
) -> list[BenchmarkConditionWarning]:
    """Return warnings for detectable local conditions that can skew results."""
    warnings: list[BenchmarkConditionWarning] = []
    thermal_state = str(hardware.get("thermal_state") or "unavailable_unknown")

    if thermal_state.startswith("unavailable"):
        warnings.append(
            BenchmarkConditionWarning(
                "thermal state unavailable",
                (
                    f"thermal_state={thermal_state}; mlx-chronos could not read "
                    "macOS thermal pressure through the available local probes. "
                    "The run can continue, but thermal context is missing."
                ),
            )
        )
    elif thermal_state != "nominal":
        warnings.append(
            BenchmarkConditionWarning(
                "thermal state",
                (
                    f"thermal_state={thermal_state}; thermal pressure can reduce "
                    "performance and make results less comparable."
                ),
            )
        )

    power_source = (
        hardware.get("power_source")
        if power_source is None
        else power_source
    )
    power_source = get_power_source() if power_source is None else power_source
    if power_source == "battery":
        warnings.append(
            BenchmarkConditionWarning(
                "power source",
                "running on battery power can reduce performance; use AC power for comparable runs.",
            )
        )

    low_power_mode = (
        hardware.get("low_power_mode")
        if low_power_mode is None
        else low_power_mode
    )
    low_power_mode = get_low_power_mode() if low_power_mode is None else low_power_mode
    if low_power_mode == "on":
        warnings.append(
            BenchmarkConditionWarning(
                "low power mode",
                "Low Power Mode is enabled; disable it for comparable benchmark runs.",
            )
        )

    return warnings


def detect_hardware() -> dict:
    """
    Detect all hardware information from the host Mac.
    Returns a dict ready to be embedded in the result JSON.
    """
    return {
        "chip": get_chip_model(),
        "machine_model": get_machine_model(),
        "memory_gb": get_memory_gb(),
        "macos_version": get_macos_version(),
        "python_version": get_python_version(),
        "architecture": get_architecture(),
        "thermal_state": get_thermal_state(),
        "power_source": get_power_source(),
        "low_power_mode": get_low_power_mode(),
    }


if __name__ == "__main__":
    import json
    info = detect_hardware()
    print(json.dumps(info, indent=2))
