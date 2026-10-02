"""Download the published pure-Python CLI wheel; Python is never bundled.

Run before preparing a release: python3 scripts/bundle_runtime.py 0.5.0
The wheel and its SHA-256 manifest are tracked, so Xcode builds need no network.
Runtime dependency installation always requests the thermal extra.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


def main():
    version = sys.argv[1] if len(sys.argv) == 2 else "0.5.0"
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?", version):
        raise SystemExit("Expected an explicit release version")
    destination = Path(__file__).resolve().parents[1] / "MLXChronos/Resources"
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="chronos-wheel-") as temporary:
        subprocess.run([sys.executable, "-m", "pip", "download", "--no-deps", "--only-binary=:all:",
                        "--dest", temporary, f"mlx-chronos=={version}"], check=True)
        wheel = next(Path(temporary).glob("mlx_chronos-*-py3-none-any.whl"))
        with zipfile.ZipFile(wheel) as archive:
            metadata_name = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
            metadata = archive.read(metadata_name).decode()
            if "Provides-Extra: thermal" not in metadata or "pyobjc-framework-Cocoa" not in metadata:
                raise SystemExit("The selected wheel does not provide the required thermal extra")
        shutil.copy2(wheel, destination / wheel.name)
        manifest = {"version": version, "wheel": wheel.name,
                    "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}
        (destination / "runtime_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"Bundled mlx-chronos {version}; thermal extra verified")


if __name__ == "__main__":
    main()
