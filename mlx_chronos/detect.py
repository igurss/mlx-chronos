import subprocess
import platform
import psutil


def get_chip_model() -> str:
    """Detect the Apple Silicon chip model (e.g. 'Apple M3 Ultra')."""
    try:
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True
        )
        chip = result.stdout.strip()
        if chip:
            return chip
        # Fallback for Apple Silicon
        result = subprocess.run(
            ["sysctl", "-n", "hw.model"],
            capture_output=True,
            text=True
        )
        return result.stdout.strip()
    except Exception as e:
        return f"unknown ({e})"


def get_memory_gb() -> float:
    """Return total unified memory in GB."""
    bytes_total = psutil.virtual_memory().total
    return round(bytes_total / (1024 ** 3), 1)


def get_macos_version() -> str:
    """Return macOS version (e.g. '15.3.1')."""
    return platform.mac_ver()[0]


def get_python_version() -> str:
    """Return Python version (e.g. '3.11.4')."""
    return platform.python_version()


def detect_hardware() -> dict:
    """
    Detect all hardware information from the host Mac.
    Returns a dict ready to be embedded in the result JSON.
    """
    return {
        "chip": get_chip_model(),
        "memory_gb": get_memory_gb(),
        "macos_version": get_macos_version(),
        "python_version": get_python_version(),
    }


if __name__ == "__main__":
    import json
    info = detect_hardware()
    print(json.dumps(info, indent=2))