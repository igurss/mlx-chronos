import subprocess
import platform
import os
import psutil


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
    return "unknown"


def get_machine_model() -> str:
    """Return the Mac machine identifier (e.g. 'Mac14,2')."""
    try:
        result = subprocess.run(
            ["sysctl", "-n", "hw.model"],
            capture_output=True, text=True
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def get_memory_gb() -> float:
    """Return total unified memory in GB."""
    return round(psutil.virtual_memory().total / (1024 ** 3), 1)


def get_ram_used_gb() -> float:
    """Return currently used RAM in GB before benchmark starts."""
    mem = psutil.virtual_memory()
    return round((mem.total - mem.available) / (1024 ** 3), 2)


def get_macos_version() -> str:
    """Return macOS version (e.g. '15.3.1')."""
    return platform.mac_ver()[0]


def get_python_version() -> str:
    """Return Python version (e.g. '3.11.4')."""
    return platform.python_version()


def get_thermal_state() -> str:
    """
    Return macOS thermal pressure level via powermetrics.
    Requires sudo. Returns a descriptive status string if unavailable.
    """
    if os.geteuid() != 0:
        return "unavailable_no_sudo"
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
    except Exception as e:
        return f"unavailable_error"


def detect_hardware() -> dict:
    """
    Detect all hardware information from the host Mac.
    Returns a dict ready to be embedded in the result JSON.
    """
    return {
        "chip": get_chip_model(),
        "machine_model": get_machine_model(),
        "memory_gb": get_memory_gb(),
        "ram_used_before_gb": get_ram_used_gb(),
        "macos_version": get_macos_version(),
        "python_version": get_python_version(),
        "thermal_state": get_thermal_state(),
    }


if __name__ == "__main__":
    import json
    info = detect_hardware()
    print(json.dumps(info, indent=2))