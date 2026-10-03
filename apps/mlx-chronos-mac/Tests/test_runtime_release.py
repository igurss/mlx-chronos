"""Keep release-approval checks with the app; CLI sdists intentionally omit apps."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest
import zipfile

APP = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("register_runtime_release", APP / "scripts/register_runtime_release.py")
registrar = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(registrar)
CONTRACT = json.loads((APP.parents[1] / "docs/app-runtime.json").read_text())["releases"][0]["contract"]


def wheel_with_contract(source):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mlx_chronos/app_contract.py", source)
    return buffer.getvalue()


class RuntimeReleaseTests(unittest.TestCase):
    def test_reader_uses_literal_contract_without_executing_code(self):
        source = "raise RuntimeError('must not execute')\nAPP_CONTRACT = " + repr(CONTRACT) + "\n"
        self.assertEqual(registrar.contract_from_wheel(wheel_with_contract(source)), CONTRACT)
        with self.assertRaises(ValueError):
            registrar.contract_from_wheel(wheel_with_contract("APP_CONTRACT = dict(api_version=1)"))

    def test_reader_rejects_malformed_compatibility_metadata(self):
        for field, value in [
            ("api_version", True), ("api_version", 0), ("api_version", "1"),
            ("minimum_app_version", "0.2.0rc1"), ("minimum_app_version", "00.2.0"),
            ("minimum_app_version", None), ("supported_commands", ["run", "run"]),
            ("supported_commands", ["run", " "]), ("supported_commands", "run"),
            ("required_capabilities", []), ("required_capabilities", [1]),
        ]:
            with self.subTest(field=field, value=value):
                contract = copy.deepcopy(CONTRACT)
                contract[field] = value
                with self.assertRaises(ValueError):
                    registrar.contract_from_wheel(wheel_with_contract("APP_CONTRACT = " + repr(contract)))

    def test_reader_rejects_missing_contract_and_unknown_fields(self):
        with self.assertRaisesRegex(ValueError, "no literal"):
            registrar.contract_from_wheel(wheel_with_contract("VERSION = '1.0.0'"))
        contract = copy.deepcopy(CONTRACT)
        contract["typo_field"] = True
        with self.assertRaisesRegex(ValueError, "fields"):
            registrar.contract_from_wheel(wheel_with_contract("APP_CONTRACT = " + repr(contract)))

    def test_reader_rejects_ambiguous_or_oversized_contract_sources(self):
        for source in ("APP_CONTRACT = 1", "APP_CONTRACT = " + repr(CONTRACT) + "\nAPP_CONTRACT = " + repr(CONTRACT),
                       "#" * 100_001):
            with self.subTest(source_length=len(source)), self.assertRaises(ValueError):
                registrar.contract_from_wheel(wheel_with_contract(source))
