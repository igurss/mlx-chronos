import argparse
import copy
import importlib.util
import io
import json
import plistlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

BRIDGE = Path(__file__).resolve().parents[1] / "MLXChronos/Resources/chronos_bridge.py"
spec = importlib.util.spec_from_file_location("chronos_bridge", BRIDGE)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class BridgeTests(unittest.TestCase):
    def test_contract_is_complete_and_parser_is_restored(self):
        original = argparse.ArgumentParser.parse_args
        commands = bridge.cli_schema()
        self.assertIs(argparse.ArgumentParser.parse_args, original)
        self.assertEqual({c["name"] for c in commands}, {
            "run", "matrix", "energy", "context", "doctor", "engines", "models",
            "concurrency", "compare", "history", "validate", "submit", "upgrade", "wizard"})
        run = next(c for c in commands if c["name"] == "run")
        self.assertEqual({o["flag"] for o in run["options"]}, {
            "--engine", "--model", "--quantization", "--model-url", "--trials", "--profile",
            "--notes", "--engine-opt", "--repeat", "--submitted-by", "--ram-sample-interval",
            "--max-tokens", "--min-tokens", "--format", "--cooldown-seconds", "--connection-mode",
            "--preflight", "--publishable", "--output-dir"})
        self.assertEqual(len(run["options"]), 19)
        self.assertTrue(next(o for o in run["options"] if o["name"] == "model")["required"])
        from mlx_chronos.engines import ENGINES
        self.assertEqual(set(next(o for o in run["options"] if o["name"] == "engine")["choices"]), set(ENGINES))

    def test_probe_does_not_load_engine_libraries(self):
        with patch("mlx_chronos.engines.get_engine", side_effect=AssertionError("must not instantiate an engine")):
            result = bridge.probe(None)
        self.assertIsNone(result["error"])
        self.assertTrue(result["commands"])
        self.assertEqual(result["executable"], sys.executable)

    def test_working_directory_cannot_shadow_installed_cli(self):
        with tempfile.TemporaryDirectory(prefix="chronos-shadow-") as root:
            fake = Path(root) / "mlx_chronos"
            fake.mkdir()
            (fake / "__init__.py").write_text("raise RuntimeError('shadowed')\n")
            response = subprocess.run([sys.executable, "-I", "-B", str(BRIDGE), "probe"], cwd=root,
                                      capture_output=True, text=True, timeout=20)
            self.assertEqual(response.returncode, 0, response.stderr)
            result = json.loads(response.stdout)
            self.assertIsNone(result["error"])
            self.assertNotIn(root, result["package_path"])

    def test_source_is_explicit_and_validated(self):
        with self.assertRaises(ValueError):
            bridge.configure_source("/path/that/does/not/exist")

    def test_cli_help_dispatch_uses_actual_cli(self):
        response = subprocess.run([sys.executable, "-I", "-B", str(BRIDGE), "cli", "context", "--help"],
                                  capture_output=True, text=True, timeout=20)
        self.assertEqual(response.returncode, 0, response.stderr)
        self.assertIn("--trials-per-bucket", response.stdout)

    def test_cli_interrupt_is_clean_and_still_cleans_up_children(self):
        stderr = io.StringIO()
        with patch.object(sys, "argv", [str(BRIDGE), "cli", "run"]), \
             patch.object(bridge, "isolate_process_group"), \
             patch.object(bridge, "configure_source"), \
             patch.object(bridge.runpy, "run_module", side_effect=KeyboardInterrupt), \
             patch.object(bridge, "cleanup_children") as cleanup, \
             patch.object(sys, "stderr", stderr):
            with self.assertRaises(SystemExit) as stopped:
                bridge.main()
        self.assertEqual(stopped.exception.code, 130)
        self.assertEqual(stderr.getvalue().strip(), "Stopped.")
        cleanup.assert_called_once()

    def test_cli_failure_is_not_misreported_as_a_user_stop(self):
        with patch.object(sys, "argv", [str(BRIDGE), "cli", "run"]), \
             patch.object(bridge, "isolate_process_group"), \
             patch.object(bridge, "configure_source"), \
             patch.object(bridge.runpy, "run_module", side_effect=RuntimeError("real failure")), \
             patch.object(bridge, "cleanup_children") as cleanup:
            with self.assertRaisesRegex(RuntimeError, "real failure"):
                bridge.main()
        cleanup.assert_called_once()

    def test_compare_warns_without_blocking_non_homogeneous_results(self):
        from mlx_chronos.examples import EXAMPLE_RESULT
        from mlx_chronos.integrity import seal_result
        with tempfile.TemporaryDirectory(prefix="chronos-compare-") as root:
            first, second = Path(root) / "first.json", Path(root) / "second.json"
            first.write_text(json.dumps(seal_result(EXAMPLE_RESULT)), encoding="utf-8")
            changed = copy.deepcopy(EXAMPLE_RESULT)
            changed["hardware"]["chip"] = "Different chip for regression test"
            second.write_text(json.dumps(seal_result(changed)), encoding="utf-8")
            response = subprocess.run([sys.executable, "-I", "-B", str(BRIDGE), "cli", "compare", "--", str(first), str(second)],
                                      capture_output=True, text=True, timeout=20)
            self.assertEqual(response.returncode, 0, response.stderr)
            output = response.stdout + response.stderr
            self.assertIn("hardware differs", output)
            self.assertIn("Request tok/s", output)

    def test_compare_rejects_invalid_integrity_seals(self):
        from mlx_chronos.examples import EXAMPLE_RESULT
        from mlx_chronos.integrity import seal_result
        with tempfile.TemporaryDirectory(prefix="chronos-compare-invalid-") as root:
            first, second = Path(root) / "first.json", Path(root) / "second.json"
            data = seal_result(EXAMPLE_RESULT)
            first.write_text(json.dumps(data), encoding="utf-8")
            data["meta"]["notes"] = "Changed after sealing"
            second.write_text(json.dumps(data), encoding="utf-8")
            response = subprocess.run([sys.executable, "-I", "-B", str(BRIDGE), "cli", "compare", "--", str(first), str(second)],
                                      capture_output=True, text=True, timeout=20)
            self.assertNotEqual(response.returncode, 0)
            self.assertIn("invalid integrity seal", response.stdout + response.stderr)

    def test_compare_preserves_pair_metric_and_token_unit_cautions(self):
        from mlx_chronos.compare import compare_results
        from mlx_chronos.examples import EXAMPLE_RESULT
        from mlx_chronos.integrity import seal_result
        with tempfile.TemporaryDirectory(prefix="chronos-compare-units-") as root:
            paths = [Path(root) / f"{index}.json" for index in range(3)]
            for index, path in enumerate(paths):
                data = copy.deepcopy(EXAMPLE_RESULT)
                if index == 2:
                    data["metrics"]["token_count_source"] = "word_fallback"
                path.write_text(json.dumps(seal_result(data)), encoding="utf-8")
            warnings = compare_results(paths)["warnings"]
            if warnings and isinstance(warnings[0], str):
                self.skipTest("Published CLI 0.5.1 predates metric-specific comparisons")
            response = subprocess.run([sys.executable, "-I", "-B", str(BRIDGE), "cli", "compare", "--",
                                       *map(str, paths)], capture_output=True, text=True, timeout=20)
            self.assertEqual(response.returncode, 0, response.stderr)
            output = response.stdout + response.stderr
            lines = [line for line in output.splitlines() if "completion token count provenance differs" in line]
            self.assertEqual(len(lines), 1)
            self.assertIn("[1] vs [3] (Request tok/s, Decode tok/s)", lines[0])
            self.assertIn("exact and estimated completion counts use different units", output)
            self.assertIn("18.44 (n/a)", output)
            self.assertIn("not certify equivalence", output)

    def test_snapshot_never_generates_or_loads_models_and_keeps_partial_errors(self):
        class Engine:
            port = 1234
            def __init__(self, name): self.name = name
            def base_url(self): return "http://localhost:1234/v1"
            def root_url(self): return "http://localhost:1234"
            def is_installed(self):
                if self.name == "broken":
                    raise RuntimeError("detection failed")
                return True
            def is_server_running(self): return self.name != "broken"
            def get_version(self): return "test-version"
            def list_model_ids(self): return ["downloaded-model"]
            def measure_throughput(self, *args, **kwargs): raise AssertionError("inference forbidden")
            def validate_model_backend(self, *args, **kwargs): raise AssertionError("inference forbidden")
        class Response:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"models": [{"key": "downloaded-model", "loaded_instances": [{"id": "loaded-instance"}]}]}
        with patch("mlx_chronos.engines.ENGINES", {"lmstudio": None, "broken": None}), \
             patch("mlx_chronos.engines.get_engine", side_effect=Engine), \
             patch("mlx_chronos.detect.detect_hardware", return_value={"chip": "test"}), \
             patch("httpx.get", return_value=Response()):
            result = bridge.snapshot()
        self.assertEqual(result["engines"][0]["loaded_models"], ["loaded-instance"])
        self.assertEqual(result["engines"][1]["error"], "detection failed")
        self.assertFalse(result["engines"][1]["running"])

    def test_missing_loaded_field_is_unknown_not_zero(self):
        class Engine:
            port = 1234
            def base_url(self): return "http://localhost:1234/v1"
            def root_url(self): return "http://localhost:1234"
            def is_installed(self): return True
            def is_server_running(self): return True
            def get_version(self): return "unknown"
            def list_model_ids(self): return ["downloaded"]
        class Response:
            status_code = 200
            def json(self): return self.payload
        with patch("mlx_chronos.engines.ENGINES", {"lmstudio": None}), \
             patch("mlx_chronos.engines.get_engine", return_value=Engine()), \
             patch("mlx_chronos.detect.detect_hardware", return_value={}), \
             patch("httpx.get", return_value=Response()) as get:
            for payload in ({"models": [{"key": "downloaded"}]},
                            {"models": [{"loaded_instances": ["malformed"]}]}):
                get.return_value.payload = payload
                result = bridge.snapshot()
                self.assertIsNone(result["engines"][0]["loaded_models"])

    def test_mlx_serve_snapshot_keeps_app_server_and_loaded_evidence_separate(self):
        from unittest.mock import Mock
        engine = Mock()
        engine.port = 11234
        engine.is_installed.return_value = False
        engine.is_server_running.return_value = True
        engine.get_version.return_value = "26.10.1"
        engine.base_url.return_value = "http://localhost:11234/v1"
        engine.list_model_ids.return_value = ["local-model", "unloaded-model"]
        engine.list_loaded_model_ids.return_value = ["local-model"]
        engine.validate_model_backend.side_effect = AssertionError("must not load or infer")
        engine.validate_completion_request.side_effect = AssertionError("must not infer")
        engine.measure_throughput.side_effect = AssertionError("must not infer")
        def app_info(path, *args, **kwargs):
            if str(path) == "/Applications/MLX-Serve.app/Contents/Info.plist":
                return io.BytesIO(plistlib.dumps({"CFBundleShortVersionString": "26.9.9"}))
            raise FileNotFoundError(str(path))
        with patch("mlx_chronos.engines.ENGINES", {"mlx-serve": None}), \
             patch("mlx_chronos.engines.get_engine", return_value=engine), \
             patch("mlx_chronos.detect.detect_hardware", return_value={}), \
             patch.object(Path, "open", app_info), \
             patch("httpx.post", side_effect=AssertionError("must not load or infer")):
            result = bridge.snapshot()["engines"][0]
            self.assertTrue(result["installed"])
            self.assertEqual(result["application_version"], "26.9.9")
            self.assertEqual(result["version"], "26.10.1")
            self.assertEqual(result["loaded_models"], ["local-model"])
            self.assertEqual(result["models"], ["local-model", "unloaded-model"])
            engine.list_loaded_model_ids.return_value = None
            self.assertIsNone(bridge.snapshot()["engines"][0]["loaded_models"])
        engine.validate_model_backend.assert_not_called()
        engine.validate_completion_request.assert_not_called()
        engine.measure_throughput.assert_not_called()

    def test_cleanup_only_uses_children_of_this_process(self):
        from unittest.mock import Mock
        child = Mock()
        owner = Mock()
        owner.children.return_value = [child]
        with patch("psutil.Process", return_value=owner), \
             patch("psutil.wait_procs", side_effect=[([], [child]), ([child], [])]):
            bridge.cleanup_children()
        owner.children.assert_called_once_with(recursive=True)
        child.terminate.assert_called_once()
        child.kill.assert_called_once()


if __name__ == "__main__":
    unittest.main()
