"""Check an approved CLI install/removal in a disposable environment.

The app's complete private Python bootstrap is checked by check_bootstrap.sh.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request


def install(python, catalog, temporary):
    release = catalog["releases"][-1]
    with urllib.request.urlopen(release["url"], timeout=60) as response:
        data = response.read(10_000_001)
    assert len(data) <= 10_000_000 and hashlib.sha256(data).hexdigest() == release["sha256"]
    wheel = Path(temporary) / release["url"].split("/")[-1]
    wheel.write_bytes(data)
    subprocess.run([str(python), "-I", "-m", "pip", "install", "--disable-pip-version-check", str(wheel) + "[thermal]"], check=True, timeout=600)
    subprocess.run([str(python), "-I", "-m", "pip", "check"], check=True, timeout=60)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-only", type=Path)
    args = parser.parse_args()
    app = Path(__file__).resolve().parents[1]
    catalog = json.loads((app.parents[1] / "docs/app-runtime.json").read_text())
    bridge = app / "MLXChronos/Resources/chronos_bridge.py"
    with tempfile.TemporaryDirectory(prefix="chronos-fresh-") as temporary:
        if args.install_only:
            install(args.install_only, catalog, temporary)
            return
        root = Path(temporary) / "venv"
        subprocess.run([sys.executable, "-I", "-m", "venv", str(root)], check=True, timeout=180)
        python = root / "bin/python"
        install(python, catalog, temporary)
        probe = subprocess.run([str(python), "-I", "-B", str(bridge), "probe"], check=True, capture_output=True, text=True, timeout=30)
        result = json.loads(probe.stdout)
        assert result["error"] is None and result["package_owned"]
        assert result["thermal_state"] in {"nominal", "fair", "serious", "critical"}
        subprocess.run([str(python), "-I", "-m", "pip", "uninstall", "-y", "mlx-chronos"], check=True, timeout=60)
        subprocess.run([str(python), "-I", "-c", "import Foundation, psutil, httpx"], check=True, timeout=30)
    print("Approved installation and targeted removal passed in a disposable environment.")


if __name__ == "__main__":
    main()
