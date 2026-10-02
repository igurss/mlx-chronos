"""Exercise bootstrap/removal in a disposable environment, never a user runtime.

Needs network access for dependencies, an existing Python >=3.10 and macOS.
Usage: python3 scripts/check_fresh_runtime.py
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    if sys.version_info < (3, 10):
        raise SystemExit("Use an existing Python 3.10 or newer")
    resources = Path(__file__).resolve().parents[1] / "MLXChronos/Resources"
    bridge = resources / "chronos_bridge.py"
    manifest = json.loads((resources / "runtime_manifest.json").read_text())
    wheel = resources / manifest["wheel"]
    with tempfile.TemporaryDirectory(prefix="chronos-fresh-") as temporary:
        root = Path(temporary) / "venv"
        subprocess.run([sys.executable, "-I", "-B", str(bridge), "venv", str(root)],
                       check=True, timeout=180)
        python = root / "bin/python"

        def execute(action, *arguments, capture=False):
            return subprocess.run([str(python), "-I", "-B", str(bridge), action, *arguments],
                                  check=True, timeout=600, text=True, capture_output=capture,
                                  cwd=temporary)

        execute("pip", "install", "--disable-pip-version-check", str(wheel) + "[thermal]")
        execute("pip", "check")
        probe = json.loads(execute("probe", capture=True).stdout)
        assert probe["error"] is None, probe
        assert probe["package_version"] == manifest["version"]
        assert probe["package_owned"] and probe["installer"] == "pip"
        assert Path(probe["package_path"]).is_relative_to(root.resolve())
        assert probe["thermal_state"] in {"nominal", "fair", "serious", "critical"}
        assert len(probe["commands"]) == 14
        execute("cli", "--version")

        # This is exactly the targeted removal used by the app, but the target
        # here is a new temporary environment created by this test alone.
        execute("pip", "uninstall", "-y", "mlx-chronos")
        after = json.loads(execute("probe", capture=True).stdout)
        assert after["package_version"] is None
        assert not (root / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" /
                    "site-packages/mlx_chronos").exists()
        assert python.is_file(), "Python was removed"
        subprocess.run([str(python), "-I", "-c", "import Foundation, psutil, httpx"],
                       check=True, timeout=30)
        execute("pip", "check")
    print("Fresh installation and targeted removal passed; Python, thermal support and other dependencies were preserved.")


if __name__ == "__main__":
    main()
