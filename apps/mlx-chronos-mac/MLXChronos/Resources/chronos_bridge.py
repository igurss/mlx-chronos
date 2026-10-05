"""Small, structured adapter to the selected CLI; never implements measurements.

Run with a selected Python interpreter and -I. Sources are opt-in, and installed
packages are resolved without the working directory or inherited PYTHONPATH.
"""
from __future__ import annotations

import argparse
import importlib.metadata as metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import runpy
import site
import sys
import sysconfig


def isolate_process_group():
    if os.name == "posix" and os.getpgrp() != os.getpid():
        os.setsid()


def configure_source(source):
    if sys.prefix == sys.base_prefix:
        user_site = site.getusersitepackages()
        if isinstance(user_site, str) and Path(user_site).is_dir():
            sys.path.append(user_site)
    if source:
        root = Path(source).resolve()
        if not (root / "pyproject.toml").is_file() or not (root / "mlx_chronos/cli.py").is_file():
            raise ValueError("The selected source is not an mlx-chronos checkout")
        sys.path.insert(0, str(root))


def cleanup_children():
    """Stop only descendants started by this adapter, before the leader exits.

    psutil guards terminate/kill against PID reuse. Existing engine servers are
    not children of this process and are never included in this cleanup.
    """
    try:
        import psutil
        children = psutil.Process().children(recursive=True)
    except (ImportError, OSError):
        return
    for child in children:
        try:
            child.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    _, alive = psutil.wait_procs(children, timeout=2)
    for child in alive:
        try:
            child.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    psutil.wait_procs(alive, timeout=1)


def cli_schema():
    """Read the actual argparse contract, without dispatching any command."""
    from mlx_chronos import cli

    class Captured(BaseException):
        pass

    captured = None
    original = argparse.ArgumentParser.parse_args

    def capture(parser, *args, **kwargs):
        nonlocal captured
        captured = parser
        raise Captured()

    argparse.ArgumentParser.parse_args = capture
    try:
        try:
            cli.main()
        except Captured:
            pass
    finally:
        argparse.ArgumentParser.parse_args = original
    if captured is None:
        raise RuntimeError("Could not read the selected CLI's command contract")
    subparser = next(a for a in captured._actions if isinstance(a, argparse._SubParsersAction))
    descriptions = {a.dest: a.help for a in subparser._choices_actions}
    commands = []
    for name, parser in subparser.choices.items():
        options = []
        for action in parser._actions:
            if isinstance(action, argparse._HelpAction):
                continue
            default = action.default
            if default is argparse.SUPPRESS:
                default = None
            if default is not None and not isinstance(default, (bool, str, int, float)):
                default = str(default)
            options.append({
                "name": action.dest,
                "flag": next((f for f in action.option_strings if f.startswith("--")), None),
                "kind": ("boolean" if isinstance(action, argparse._StoreTrueAction)
                         else "repeat" if isinstance(action, argparse._AppendAction)
                         else "integer" if action.type is int
                         else "number" if action.type is float else "text"),
                "required": action.required or (not action.option_strings and action.nargs in (None, "+")),
                "multiple": action.nargs in ("+", "*"),
                "choices": [str(c) for c in action.choices] if action.choices is not None else [],
                "default": None if default is None else str(default),
                "help": action.help or "",
            })
        commands.append({"name": name, "help": descriptions.get(name, ""), "options": options})
    return commands


def probe(source):
    engines = {}
    for name in ("omlx", "rapid-mlx", "vllm-mlx", "mlx-lm"):
        try:
            engines[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pass
    info = {
        "python_version": platform.python_version(), "architecture": platform.machine(),
        "executable": sys.executable, "prefix": sys.prefix, "base_prefix": sys.base_prefix,
        "is_virtualenv": sys.prefix != sys.base_prefix,
        "externally_managed": sys.prefix == sys.base_prefix and
            (Path(sysconfig.get_path("stdlib")) / "EXTERNALLY-MANAGED").is_file(),
        "pip_available": importlib.util.find_spec("pip") is not None,
        "engine_packages": engines, "commands": [], "thermal_state": None,
        "package_version": None, "package_path": None, "installer": None,
        "package_owned": False,
        "environment_manager": "pipx" if (Path(sys.prefix) / "pipx_metadata.json").is_file() else "python",
        "error": None, "source_path": source, "app_contract": None,
    }
    try:
        import mlx_chronos
        info["package_version"] = mlx_chronos.__version__
        info["package_path"] = str(Path(mlx_chronos.__file__).resolve().parent)
        try:
            distribution = metadata.distribution("mlx-chronos")
            info["installer"] = (distribution.read_text("INSTALLER") or "").strip()
            location = Path(distribution.locate_file("")).resolve()
            prefix = Path(sys.prefix).resolve()
            user_site = Path(site.getusersitepackages()).resolve()
            info["package_owned"] = (location.is_relative_to(prefix) or
                (sys.prefix == sys.base_prefix and location.is_relative_to(user_site)))
        except metadata.PackageNotFoundError:
            pass
        info["commands"] = cli_schema()
        if importlib.util.find_spec("mlx_chronos.app_contract") is not None:
            from mlx_chronos.app_contract import describe_app_contract
            info["app_contract"] = describe_app_contract()
        from mlx_chronos.detect import get_thermal_state_from_foundation
        info["thermal_state"] = get_thermal_state_from_foundation()
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def snapshot():
    """Read installation/server evidence only; never generate or load a model."""
    import concurrent.futures
    import plistlib
    import shutil
    import httpx
    from mlx_chronos.detect import detect_hardware
    from mlx_chronos.engines import ENGINES, get_engine

    def inspect(name):
        engine = get_engine(name)
        error = None
        try:
            installed = engine.is_installed()
        except Exception as exc:
            installed = False
            error = str(exc)
        try:
            running = engine.is_server_running()
        except Exception as exc:
            running = False
            error = str(exc)
        application_version = None
        app_names = {
            "lmstudio": ("LM Studio.app",), "ollama": ("Ollama.app",),
            "mlx-serve": ("MLX-Serve.app", "MLX Core.app"),
        }.get(name, ())
        if app_names:
            application_detected = False
            for directory in (Path("/Applications"), Path.home() / "Applications"):
                for app_name in app_names:
                    try:
                        with (directory / app_name / "Contents/Info.plist").open("rb") as handle:
                            info = plistlib.load(handle)
                        if not isinstance(info, dict):
                            continue
                        value = info.get("CFBundleShortVersionString")
                        application_version = value if isinstance(value, str) and value.strip() else None
                        installed = True
                        application_detected = True
                        break
                    except (OSError, ValueError, plistlib.InvalidFileException):
                        pass
                if application_detected:
                    break
        try:
            version = engine.get_version() if installed or running else "unknown"
        except Exception as exc:
            version = "unknown"
            error = str(exc)
        models = []
        loaded = None
        if running:
            try:
                models = engine.list_model_ids()
            except Exception as exc:
                error = str(exc)
            try:
                if name == "ollama":
                    response = httpx.get(engine.root_url() + "/api/ps", timeout=2)
                    response.raise_for_status()
                    payload = response.json()
                    entries = payload.get("models")
                    if isinstance(entries, list) and all(isinstance(e, dict) and isinstance(e.get("name") or e.get("model"), str) for e in entries):
                        loaded = [e.get("name") or e.get("model") for e in entries if isinstance(e, dict)]
                elif name == "lmstudio":
                    response = httpx.get(engine.root_url() + "/api/v1/models", timeout=2)
                    if response.status_code == 200:
                        entries = response.json().get("models")
                        if (isinstance(entries, list) and
                                all(isinstance(e, dict) and isinstance(e.get("loaded_instances"), list)
                                    and all(isinstance(i, dict) and isinstance(i.get("id"), str)
                                            for i in e["loaded_instances"]) for e in entries)):
                            loaded = [i["id"] for e in entries for i in e["loaded_instances"]]
                elif name == "mlx-serve":
                    loaded = engine.list_loaded_model_ids()
            except Exception:
                pass
        return {"name": name, "installed": installed, "running": running,
                "version": version, "endpoint": engine.base_url(), "port": engine.port,
                "models": models, "loaded_models": loaded, "error": error,
                "application_version": application_version}

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        engines = list(pool.map(inspect, ENGINES))
    return {"hardware": detect_hardware(), "engines": engines,
            "macmon_available": shutil.which("macmon") is not None}


def main():
    isolate_process_group()
    parser = argparse.ArgumentParser()
    parser.add_argument("--source")
    parser.add_argument("action", choices=("probe", "snapshot", "cli", "pip", "venv"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    configure_source(args.source)
    if args.action == "probe":
        print(json.dumps(probe(args.source), allow_nan=False))
    elif args.action == "snapshot":
        print(json.dumps(snapshot(), allow_nan=False))
    elif args.action == "cli":
        sys.argv = ["mlx-chronos"] + args.arguments
        try:
            runpy.run_module("mlx_chronos.cli", run_name="__main__")
        except KeyboardInterrupt:
            # Stop is an expected user action, not an unhandled CLI failure.
            # Keep the conventional interrupt exit code and descendant cleanup.
            print("\nStopped.", file=sys.stderr)
            raise SystemExit(130) from None
        finally:
            cleanup_children()
    elif args.action == "pip":
        import subprocess
        # pip runs in its own interpreter. Importing cleanup dependencies inside
        # pip's process is deprecated, and can import a just-replaced package.
        try:
            completed = subprocess.run([sys.executable, "-I", "-B", "-m", "pip"] + args.arguments)
            raise SystemExit(completed.returncode)
        finally:
            cleanup_children()
    elif args.action == "venv":
        import venv
        if len(args.arguments) != 1:
            raise ValueError("A dedicated virtual environment path is required")
        venv.EnvBuilder(with_pip=True, symlinks=True).create(args.arguments[0])


if __name__ == "__main__":
    main()
