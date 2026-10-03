"""Approve a published CLI wheel after app checks: register_runtime_release.py VERSION.

Read the literal compatibility contract without executing downloaded code.
Review the catalog diff and run app checks before pushing it.
"""
import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
import re
import urllib.request
from urllib.parse import urlsplit
import zipfile

STABLE_VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"


def validate_contract(contract: dict) -> None:
    if set(contract) != {"api_version", "minimum_app_version", "required_capabilities", "supported_commands"}:
        raise ValueError("Unexpected app contract fields")
    if type(contract["api_version"]) is not int or contract["api_version"] < 1:
        raise ValueError("App API version must be a positive integer")
    version = contract["minimum_app_version"]
    if not isinstance(version, str) or not re.fullmatch(STABLE_VERSION, version):
        raise ValueError("Minimum app version must be a stable version")
    for field in ("required_capabilities", "supported_commands"):
        values = contract[field]
        if not isinstance(values, list) or not values or any(
            not isinstance(v, str) or not v or v.strip() != v for v in values
        ) or len(set(values)) != len(values):
            raise ValueError(f"Invalid or duplicate {field}")


def contract_from_wheel(wheel: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
        if archive.getinfo("mlx_chronos/app_contract.py").file_size > 100_000:
            raise ValueError("App contract source exceeded the size limit")
        source = archive.read("mlx_chronos/app_contract.py").decode("utf-8")
    declarations = [node for node in ast.parse(source).body if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "APP_CONTRACT" for t in node.targets)]
    if len(declarations) != 1:
        raise ValueError("Published wheel has no literal APP_CONTRACT declaration or has multiple declarations")
    value = ast.literal_eval(declarations[0].value)
    if not isinstance(value, dict):
        raise ValueError("App contract must be a dictionary")
    validate_contract(value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    args = parser.parse_args()
    if not re.fullmatch(STABLE_VERSION, args.version):
        parser.error("Use an exact stable release version")
    with urllib.request.urlopen(f"https://pypi.org/pypi/mlx-chronos/{args.version}/json", timeout=30) as response:
        project = json.load(response)
    candidates = [v for v in project["urls"] if v["filename"] == f"mlx_chronos-{args.version}-py3-none-any.whl" and not v["yanked"]]
    if len(candidates) != 1:
        raise ValueError("Expected one published, non-yanked universal wheel")
    artifact = candidates[0]
    url = urlsplit(artifact["url"])
    if url.scheme != "https" or url.hostname != "files.pythonhosted.org" or url.path.split("/")[-1] != artifact["filename"]:
        raise ValueError("Wheel must come from the official PyPI artifact host")
    with urllib.request.urlopen(artifact["url"], timeout=60) as response:
        wheel = response.read(10_000_001)
    if len(wheel) > 10_000_000 or hashlib.sha256(wheel).hexdigest() != artifact["digests"]["sha256"]:
        raise ValueError("Published wheel checksum/size verification failed")
    contract = contract_from_wheel(wheel)
    catalog_path = Path(__file__).resolve().parents[3] / "docs/app-runtime.json"
    catalog = json.loads(catalog_path.read_text())
    entry = {"version": args.version, "url": artifact["url"], "sha256": artifact["digests"]["sha256"],
             "contract": contract, "allow_legacy_bridge": False}
    old = next((v for v in catalog["releases"] if v["version"] == args.version), None)
    if old is not None and old != entry:
        raise ValueError("An approved release is immutable; do not replace its artifact or contract")
    if old is None:
        catalog["releases"].append(entry)
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n")
    print(f"Registered published CLI {args.version}. Review compatibility and run app checks before pushing the catalog.")


if __name__ == "__main__":
    main()
