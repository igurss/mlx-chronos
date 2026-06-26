import argparse
import sys
import logging
import os
import json
import time
import subprocess
import re

from pathlib import Path
from datetime import datetime, timezone
from pydantic import ValidationError

from mlx_chronos import __version__ as VERSION
from mlx_chronos.benchmark import (
    BENCHMARK_PROFILE_BASELINE,
    BENCHMARK_PROFILE_SUSTAINED,
    DEFAULT_TRIALS,
    VALID_BENCHMARK_PROFILES,
    run_benchmark,
)
from mlx_chronos.detect import detect_hardware, get_benchmark_condition_warnings
from mlx_chronos.engines import ENGINES, get_engine
from mlx_chronos.integrity import IntegrityError, validate_integrity_seal
from mlx_chronos.protocol import CONNECTION_MODE_PERSISTENT, VALID_CONNECTION_MODES
from mlx_chronos.reporters import BaseReporter, JSONReporter, MarkdownReporter
from mlx_chronos.schema import BenchmarkResult
from mlx_chronos.submit import (
    DEFAULT_SUBMIT_ENDPOINT,
    DEFAULT_SUBMITTER_EMAIL,
    SUBMIT_ENDPOINT_ENV,
    SUBMITTER_EMAIL_ENV,
    SubmissionError,
    load_publishable_result,
    submit_result_file,
    validate_publishable_result,
)
from mlx_chronos.updates import (
    DEFAULT_UPDATE_CHECK_TIMEOUT,
    PROJECT_NAME,
    check_for_update,
    start_background_update_check,
    update_check_disabled,
)
from mlx_chronos.constants import (
    DEFAULT_RAM_SAMPLE_INTERVAL,
    DEFAULT_THROUGHPUT_MAX_TOKENS,
    MAX_TRIALS,
    PUBLIC_BASELINE_TRIALS,
    RECENT_BENCHMARK_WARNING_SECONDS,
    SUSTAINED_PROGRESS_SAMPLE_INTERVAL_TOKENS,
    SUSTAINED_THROUGHPUT_MAX_TOKENS,
    SUSTAINED_TRIALS,
)


logger = logging.getLogger("mlx_chronos")


def _should_start_update_check(command: str | None, stream=None) -> bool:
    if command == "upgrade" or update_check_disabled():
        return False
    output = sys.stderr if stream is None else stream
    try:
        return bool(output.isatty())
    except Exception:
        return False


def _maybe_start_update_check(command: str | None) -> None:
    if _should_start_update_check(command):
        start_background_update_check()


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _result_timestamp(path: Path) -> datetime | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = None
    if isinstance(data, dict):
        timestamp = _parse_timestamp(data.get("meta", {}).get("timestamp"))
        if timestamp is not None:
            return timestamp

    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _latest_result_timestamp(results_dir: Path) -> datetime | None:
    if not results_dir.exists():
        return None
    timestamps = [
        timestamp
        for path in results_dir.glob("*.json")
        if (timestamp := _result_timestamp(path)) is not None
    ]
    return max(timestamps) if timestamps else None


def _elapsed_since_last_result(results_dir: Path) -> float | None:
    latest = _latest_result_timestamp(results_dir)
    if latest is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - latest).total_seconds())


def _resolve_profile_defaults(args) -> tuple[str, int, int]:
    profile = getattr(args, "profile", BENCHMARK_PROFILE_BASELINE)
    if profile == BENCHMARK_PROFILE_SUSTAINED:
        default_trials = SUSTAINED_TRIALS
        default_max_tokens = SUSTAINED_THROUGHPUT_MAX_TOKENS
    else:
        default_trials = DEFAULT_TRIALS
        default_max_tokens = DEFAULT_THROUGHPUT_MAX_TOKENS

    trials = getattr(args, "trials", None)
    max_tokens = getattr(args, "max_tokens", None)
    return (
        profile,
        default_trials if trials is None else trials,
        default_max_tokens if max_tokens is None else max_tokens,
    )


def _publishable_profile_shape(profile: str) -> tuple[int, int]:
    if profile == BENCHMARK_PROFILE_SUSTAINED:
        return SUSTAINED_TRIALS, SUSTAINED_THROUGHPUT_MAX_TOKENS
    return PUBLIC_BASELINE_TRIALS, DEFAULT_THROUGHPUT_MAX_TOKENS


def _ensure_publishable_run_args(
    args,
    *,
    profile: str,
    trials: int,
    max_tokens: int,
    min_tokens: int | None,
    connection_mode: str,
) -> tuple[int, int, int | None, str]:
    if not getattr(args, "publishable", False):
        return trials, max_tokens, min_tokens, connection_mode

    errors = []
    expected_trials, expected_max_tokens = _publishable_profile_shape(profile)
    if trials != expected_trials:
        errors.append(
            f"--publishable requires {profile} trials={expected_trials}; got {trials}"
        )
    if max_tokens != expected_max_tokens:
        errors.append(
            f"--publishable requires {profile} --max-tokens={expected_max_tokens}; "
            f"got {max_tokens}"
        )
    if min_tokens is not None:
        errors.append("--publishable does not allow --min-tokens")
    if connection_mode != CONNECTION_MODE_PERSISTENT:
        errors.append("--publishable requires --connection-mode persistent")
    if not getattr(args, "model_url", None):
        errors.append("--publishable requires --model-url")
    if getattr(args, "format", "json") == "markdown":
        errors.append("--publishable requires JSON output; use --format json or --format all")

    if errors:
        print("Error: publishable run configuration is not valid:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print(
            "Fix: remove conflicting overrides or use the standard public profile "
            "defaults.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    args.preflight = True
    return expected_trials, expected_max_tokens, None, CONNECTION_MODE_PERSISTENT


def _publishable_environment_errors(hardware: dict) -> list[str]:
    errors = []
    architecture = str(hardware.get("architecture", "")).strip().lower()
    if architecture != "arm64":
        errors.append(f"Apple Silicon architecture arm64 required; got {architecture!r}")
    chip = str(hardware.get("chip", ""))
    if re.fullmatch(r"Apple M\d+(?: (?:Pro|Max|Ultra))?", chip) is None:
        errors.append(f"Apple M-series chip required; got {chip!r}")
    macos_version = str(hardware.get("macos_version", ""))
    if re.fullmatch(r"\d+(?:\.\d+){1,2}", macos_version) is None:
        errors.append(f"valid macOS version required; got {macos_version!r}")
    low_power_mode = hardware.get("low_power_mode")
    if low_power_mode != "off":
        errors.append(
            "Low Power Mode must be off for public leaderboard submissions; "
            f"got {low_power_mode!r}"
        )
    return errors


def _ensure_publishable_environment() -> None:
    try:
        hardware = detect_hardware()
    except Exception as exc:
        print(f"Error: could not detect hardware for --publishable: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    errors = _publishable_environment_errors(hardware)
    if errors:
        print("Error: current machine is not ready for a publishable run:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print(
            "Fix: use an Apple Silicon Mac, disable Low Power Mode, and rerun "
            "`mlx-chronos doctor --publishable`.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def _publishability_errors(result: dict) -> list[str]:
    errors = []
    try:
        validate_integrity_seal(result)
    except IntegrityError as exc:
        errors.append(f"integrity seal failed: {exc}")

    try:
        parsed = BenchmarkResult.model_validate(result)
    except ValidationError as exc:
        errors.append(f"schema validation failed: {exc}")
    else:
        try:
            validate_publishable_result(parsed)
        except SubmissionError as exc:
            errors.append(str(exc))
    return errors


def _publishability_fix(error: str) -> str:
    if "model.reference_url" in error:
        return "rerun with --model-url pointing to the model page you used."
    if "known engine version" in error or "engine.version" in error:
        return "restart or update the engine so mlx-chronos can detect its version."
    if "Low Power Mode" in error or "lowpowermode" in error:
        return "disable Low Power Mode in macOS Battery settings and rerun."
    if "warmup_failures" in error:
        return "make sure the engine is stable, then rerun the benchmark."
    if "usage.completion_tokens" in error:
        return "use an engine/server that returns usage.completion_tokens."
    if "model.format" in error or "safetensors" in error:
        return "use an Ollama MLX safetensors model and rerun."
    if "trial count" in error or "max_tokens" in error or "min_tokens" in error:
        return "rerun with --publishable or the standard public profile settings."
    if "thermal" in error:
        return "install the thermal extra if needed and rerun with working Foundation thermal sampling."
    if "RAM monitoring" in error or "monitor" in error:
        return "rerun after closing interfering processes so RAM and thermal monitors complete cleanly."
    return "run `mlx-chronos doctor --publishable` for the next concrete check."


def _log_publishability_summary(result: dict, json_path: Path | None) -> bool:
    errors = _publishability_errors(result)
    logger.info("")
    logger.info("  Leaderboard readiness")
    if not errors:
        logger.info("  Status     : ready")
        if json_path is not None:
            logger.info("  Validate   : mlx-chronos submit --file %s --dry-run", json_path)
            logger.info("  Submit PR  : copy that JSON into results/submitted/ and open a PR")
        else:
            logger.info("  Next       : rerun with --format json or --format all before submitting")
        return True

    logger.info("  Status     : local-only")
    logger.info("  Blocker    : %s", errors[0])
    logger.info("  Fix        : %s", _publishability_fix(errors[0]))
    if len(errors) > 1:
        logger.info("  More       : %d additional issue(s) may remain", len(errors) - 1)
    return False


def _emit_result_warnings(result: dict) -> None:
    meta = result.get("meta", {})
    if meta.get("word_fallback_warning"):
        print(
            "Warning: throughput used word_fallback token counts. Local tok/s is "
            "an estimate and will not be accepted for the public leaderboard; "
            "use an engine/server that returns usage.completion_tokens.",
            file=sys.stderr,
        )
    if meta.get("engine_version_warning"):
        print(
            "Warning: engine.version is 'unknown'. Engine versions affect "
            "comparability; try restarting the engine server or updating the "
            "engine CLI if detection keeps failing.",
            file=sys.stderr,
        )
    if meta.get("sustained_throttling_warning"):
        print(
            "Warning: sustained profile observed a late throughput drop while "
            "thermal state changed or became non-nominal.",
            file=sys.stderr,
        )


def _result_warning_labels(result: dict) -> list[str]:
    meta = result.get("meta", {})
    hardware = result.get("hardware", {})
    labels = []
    for field, label in (
        ("word_fallback_warning", "estimated token counts"),
        ("engine_version_warning", "unknown engine version"),
        ("sustained_throttling_warning", "possible sustained throttling"),
        ("cached_ttft_warning", "cached TTFT close to cold TTFT"),
    ):
        if meta.get(field):
            labels.append(label)
    if meta.get("warmup_failures", 0):
        labels.append("warmup failures")
    if meta.get("system_ram_monitor_errors", 0):
        labels.append("system RAM monitor errors")
    if meta.get("engine_ram_monitor_errors", 0):
        labels.append("engine RAM monitor errors")
    thermal_monitor = meta.get("thermal_monitor") or {}
    if thermal_monitor.get("sampling_errors", 0):
        labels.append("thermal monitor errors")
    worst_thermal_state = thermal_monitor.get("worst_state")
    if str(worst_thermal_state or "").startswith("unavailable"):
        labels.append("thermal state unavailable")
    elif worst_thermal_state not in {None, "nominal"}:
        labels.append(f"thermal state {worst_thermal_state}")
    if hardware.get("power_source") == "battery":
        labels.append("battery power")
    if hardware.get("low_power_mode") == "on":
        labels.append("Low Power Mode")
    return labels


def _log_result_summary(result: dict) -> None:
    metrics = result["metrics"]
    meta = result["meta"]
    thermal = meta["thermal_monitor"]
    throughput = metrics["tokens_per_second"]
    cold = metrics["ttft_cold"]
    cached = metrics["ttft_cached"]
    warnings = _result_warning_labels(result)

    logger.info("\n%s", "=" * 50)
    logger.info("  Results Summary")
    logger.info(
        "  Throughput : %.2f tok/s (±%.2f)",
        throughput["mean"],
        throughput["stddev"],
    )
    logger.info(
        "  TTFT       : cold %.3fs | cached %.3fs",
        cold["mean"],
        cached["mean"],
    )
    logger.info(
        "  Thermal    : %s -> %s (worst: %s)",
        thermal["start_state"],
        thermal["end_state"],
        thermal["worst_state"],
    )
    logger.info(
        "  Peak RAM   : %.2f GB (%.1f%%)",
        metrics["system_ram_peak_gb"],
        metrics["system_ram_peak_percent"],
    )
    logger.info("  Warnings   : %s", ", ".join(warnings) if warnings else "none")
    logger.info("%s\n", "=" * 50)


def _run_model_preflight(engine_name: str, model: str) -> None:
    """Run an opt-in model access probe before the measured benchmark."""
    logger.info("Running preflight model access check...")
    engine = get_engine(engine_name)
    if not engine.is_installed():
        raise RuntimeError(f"Engine '{engine_name}' is not installed.")
    if not engine.is_server_running():
        raise RuntimeError(
            f"Engine '{engine_name}' server is not running at {engine.base_url()}."
        )

    model_ids = engine.list_model_ids()
    resolved_model = engine.resolve_listed_model_id(model, model_ids)
    if resolved_model is None:
        logger.warning(
            "  Warning: %s was not found in /models; trying a completion request.",
            model,
        )
    else:
        logger.info("  Model listed: %s", resolved_model)

    model_backend_metadata = engine.validate_model_backend(model)
    if engine.requires_model_backend_validation is True:
        model_format = model_backend_metadata.get("format", "unknown")
        logger.info("  Model backend verified: format=%s", model_format)

    request_model = engine.validate_completion_request(model)
    logger.info("  Completion request accepted as: %s", request_model)
    logger.info("")


def cmd_run(args):
    """Run a benchmark session."""
    profile, trials, max_tokens = _resolve_profile_defaults(args)
    cooldown_seconds = getattr(args, "cooldown_seconds", 0.0)
    min_tokens = getattr(args, "min_tokens", None)
    connection_mode = getattr(args, "connection_mode", CONNECTION_MODE_PERSISTENT)
    if trials < 1:
        print("Error: --trials must be at least 1.", file=sys.stderr)
        raise SystemExit(2)
    if trials > MAX_TRIALS:
        print(f"Error: --trials must be <= {MAX_TRIALS}.", file=sys.stderr)
        raise SystemExit(2)
    if args.ram_sample_interval <= 0:
        print("Error: --ram-sample-interval must be greater than 0.", file=sys.stderr)
        raise SystemExit(2)
    if max_tokens < 1:
        print("Error: --max-tokens must be at least 1.", file=sys.stderr)
        raise SystemExit(2)
    if min_tokens is not None and min_tokens < 1:
        print("Error: --min-tokens must be at least 1.", file=sys.stderr)
        raise SystemExit(2)
    if min_tokens is not None and min_tokens > max_tokens:
        print("Error: --min-tokens must be <= --max-tokens.", file=sys.stderr)
        raise SystemExit(2)
    if cooldown_seconds < 0:
        print("Error: --cooldown-seconds must be non-negative.", file=sys.stderr)
        raise SystemExit(2)
    if not args.model.strip():
        print("Error: --model must not be empty.", file=sys.stderr)
        raise SystemExit(2)

    trials, max_tokens, min_tokens, connection_mode = _ensure_publishable_run_args(
        args,
        profile=profile,
        trials=trials,
        max_tokens=max_tokens,
        min_tokens=min_tokens,
        connection_mode=connection_mode,
    )
    if getattr(args, "publishable", False):
        _ensure_publishable_environment()

    results_dir = args.output_dir or Path.cwd() / "results" / "local"
    elapsed_since_last = _elapsed_since_last_result(results_dir)
    if elapsed_since_last is not None:
        if cooldown_seconds > elapsed_since_last:
            delay = cooldown_seconds - elapsed_since_last
            logger.info(
                "Previous benchmark in this output directory was %.1f seconds ago; "
                "cooling down for %.1f seconds.",
                elapsed_since_last,
                delay,
            )
            time.sleep(delay)
            elapsed_since_last = _elapsed_since_last_result(results_dir)
        elif elapsed_since_last < RECENT_BENCHMARK_WARNING_SECONDS:
            logger.warning(
                "Warning: previous benchmark in this output directory was %.1f "
                "seconds ago. Consecutive hot runs may be slower; use "
                "--cooldown-seconds to enforce a pause.",
                elapsed_since_last,
            )

    if getattr(args, "preflight", False):
        try:
            _run_model_preflight(args.engine, args.model)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc

    progress_sample_interval_tokens = (
        SUSTAINED_PROGRESS_SAMPLE_INTERVAL_TOKENS
        if profile == BENCHMARK_PROFILE_SUSTAINED
        else None
    )
    try:
        result = run_benchmark(
            engine_name=args.engine,
            model_name=args.model,
            model_quantization=args.quantization,
            model_reference_url=getattr(args, "model_url", None),
            trials=trials,
            notes=args.notes,
            ram_sample_interval=args.ram_sample_interval,
            throughput_max_tokens=max_tokens,
            throughput_min_tokens=min_tokens,
            benchmark_profile=profile,
            elapsed_since_last_benchmark_seconds=elapsed_since_last,
            cooldown_seconds=cooldown_seconds,
            progress_sample_interval_tokens=progress_sample_interval_tokens,
            connection_mode=connection_mode,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    _emit_result_warnings(result)
    _log_result_summary(result)
    reporters: list[tuple[str, BaseReporter]] = []
    if args.format in ("json", "all"):
        reporters.append(("json", JSONReporter()))
    if args.format in ("markdown", "all"):
        reporters.append(("markdown", MarkdownReporter()))

    json_path = None
    for report_format, reporter in reporters:
        path = reporter.save(result, results_dir)
        if report_format == "json":
            json_path = path
        logger.info(f"Result saved to: {path}")

    _log_publishability_summary(result, json_path)
    logger.info("\nDone.")


def cmd_engines(args):
    """List available engines and their status."""
    logger.info("\nAvailable engines:\n")
    for name in ENGINES:
        engine = get_engine(name)
        installed = engine.is_installed()
        running = engine.is_server_running() if installed else False
        status = "running" if running else ("installed" if installed else "not installed")
        logger.info(f"  {name:<15} {status:<13} {engine.base_url()}")
    logger.info("")


def cmd_doctor(args):
    """Diagnose the local setup and suggest the next useful command."""
    model = args.model.strip() if args.model is not None else None
    if args.model is not None and not model:
        print("Error: --model must not be empty.", file=sys.stderr)
        raise SystemExit(2)
    if model and args.engine is None:
        print("Error: --model requires --engine.", file=sys.stderr)
        raise SystemExit(2)

    failures = 0
    running_engines: list[str] = []
    selected_engine = args.engine
    selected_engine_ready = False

    logger.info("\nmlx-chronos doctor:\n")

    hardware = None
    try:
        hardware = detect_hardware()
        log_validation_check(
            "ok",
            "Apple Silicon host",
            (
                f"{hardware['chip']} / {hardware['memory_gb']} GB / "
                f"macOS {hardware['macos_version']} / {hardware.get('architecture')}"
            ),
        )
        for warning in get_benchmark_condition_warnings(hardware):
            log_validation_check("warn", warning.label, warning.detail)
    except Exception as exc:
        failures += 1
        log_validation_check("fail", "hardware detection", str(exc))

    if args.publishable and hardware is not None:
        for error in _publishable_environment_errors(hardware):
            failures += 1
            log_validation_check("fail", "publishable environment", error)

    logger.info("")
    logger.info("Engines:")
    engine_names = [selected_engine] if selected_engine else list(ENGINES)
    for name in engine_names:
        engine = get_engine(name)
        installed = engine.is_installed()
        if not installed:
            status = "fail" if selected_engine else "skip"
            log_validation_check(status, f"{name} installed", "not installed")
            if selected_engine:
                failures += 1
            continue

        version = engine.get_version()
        running = engine.is_server_running()
        if running:
            running_engines.append(name)
            selected_engine_ready = selected_engine == name or selected_engine is None
        status = "ok" if running else ("fail" if selected_engine else "warn")
        detail = f"{version} at {engine.base_url()}"
        log_validation_check(status, f"{name} server", detail if running else f"not running at {engine.base_url()}")
        if selected_engine and not running:
            failures += 1
        if selected_engine and version == "unknown":
            failures += 1 if args.publishable else 0
            log_validation_check(
                "fail" if args.publishable else "warn",
                "engine version",
                "known engine version is required for public leaderboard submissions",
            )

    if selected_engine and selected_engine_ready:
        engine = get_engine(selected_engine)
        try:
            model_ids = engine.list_model_ids()
            detail = f"{len(model_ids)} model(s)" if model_ids else "server returned no models"
            log_validation_check("ok" if model_ids else "warn", "model list", detail)
        except RuntimeError as exc:
            model_ids = []
            failures += 1
            log_validation_check("fail", "model list", str(exc))

        if model:
            resolved_model = engine.resolve_listed_model_id(model, model_ids)
            if resolved_model is None:
                log_validation_check(
                    "warn",
                    "model listed",
                    f"{model} was not found in /models; trying backend/request checks",
                )
            else:
                log_validation_check("ok", "model listed", resolved_model)

            backend_failed = False
            try:
                model_backend_metadata = engine.validate_model_backend(model)
                if engine.requires_model_backend_validation is True:
                    model_format = model_backend_metadata.get("format", "unknown")
                    log_validation_check("ok", "model backend", f"format={model_format}")
            except RuntimeError as exc:
                backend_failed = True
                failures += 1
                log_validation_check("fail", "model backend", str(exc))

            if not backend_failed:
                try:
                    request_model = engine.validate_completion_request(model)
                    log_validation_check("ok", "completion request", request_model)
                except RuntimeError as exc:
                    failures += 1
                    log_validation_check("fail", "completion request", str(exc))
        elif args.publishable:
            failures += 1
            log_validation_check("fail", "model", "--publishable doctor requires --model")

    model_url = getattr(args, "model_url", None)
    if args.publishable:
        if not model_url:
            failures += 1
            log_validation_check("fail", "model reference URL", "pass --model-url")
        else:
            try:
                from mlx_chronos.model_reference import normalize_model_reference_url

                normalized_url = normalize_model_reference_url(model_url)
                log_validation_check("ok", "model reference URL", normalized_url or "")
            except ValueError as exc:
                failures += 1
                log_validation_check("fail", "model reference URL", str(exc))

    logger.info("")
    if args.publishable and failures == 0 and selected_engine and model and model_url:
        logger.info("Ready for a publishable run.")
        logger.info(
            "Next: mlx-chronos run --publishable --engine %s --model %s --model-url %s",
            selected_engine,
            model,
            model_url,
        )
    elif selected_engine and selected_engine_ready and model is None:
        logger.info("Next: mlx-chronos models --engine %s", selected_engine)
    elif selected_engine and selected_engine_ready and model is not None:
        logger.info(
            "Next: mlx-chronos run --engine %s --model %s%s",
            selected_engine,
            model,
            f" --model-url {model_url}" if model_url else "",
        )
    elif running_engines:
        first_running = running_engines[0]
        logger.info("Next: mlx-chronos models --engine %s", first_running)
    else:
        logger.info("Next: start a supported engine server, then run `mlx-chronos doctor` again.")

    if failures:
        logger.info("\nDoctor found %d blocking issue(s).", failures)
        raise SystemExit(1)

    logger.info("\nDoctor completed.")


def cmd_models(args):
    """List model ids exposed by an engine's OpenAI-compatible /models endpoint."""
    engine = get_engine(args.engine)
    if not engine.is_installed():
        print(f"Error: engine '{args.engine}' is not installed.", file=sys.stderr)
        raise SystemExit(1)
    if not engine.is_server_running():
        print(
            f"Error: engine '{args.engine}' server is not running at {engine.base_url()}.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    try:
        model_ids = engine.list_model_ids()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if not model_ids:
        logger.info("No models listed by %s at %s.", args.engine, engine.base_url())
        return

    logger.info("\nModels exposed by %s at %s:\n", args.engine, engine.base_url())
    for model_id in model_ids:
        logger.info("  %s", model_id)
    logger.info("")


def log_validation_check(status: str, label: str, detail: str) -> None:
    logger.info(f"[{status}] {label}: {detail}")


def cmd_validate(args):
    """Validate the local environment before running a benchmark."""
    model = args.model.strip() if args.model is not None else None
    if args.model is not None and not model:
        print("Error: --model must not be empty.", file=sys.stderr)
        raise SystemExit(2)

    failures = 0
    logger.info("\nValidating mlx-chronos setup:\n")

    try:
        hardware = detect_hardware()
        log_validation_check(
            "ok",
            "hardware detection",
            (
                f"{hardware['chip']} / {hardware['memory_gb']} GB / "
                f"macOS {hardware['macos_version']}"
            ),
        )
        for warning in get_benchmark_condition_warnings(hardware):
            log_validation_check("warn", warning.label, warning.detail)
    except Exception as exc:
        failures += 1
        log_validation_check("fail", "hardware detection", str(exc))

    engine = get_engine(args.engine)
    if engine.is_installed():
        engine_version = engine.get_version()
        log_validation_check(
            "ok",
            "engine installed",
            f"{args.engine} ({engine_version})",
        )
        if engine_version == "unknown":
            log_validation_check(
                "warn",
                "engine version",
                "version detection failed; comparisons against other runs are weaker",
            )
    else:
        failures += 1
        log_validation_check("fail", "engine installed", args.engine)

    if engine.is_server_running():
        log_validation_check("ok", "server reachable", engine.base_url())
    else:
        failures += 1
        log_validation_check("fail", "server reachable", engine.base_url())

    model_ids = []
    if failures == 0:
        try:
            model_ids = engine.list_model_ids()
            detail = f"{len(model_ids)} model(s)" if model_ids else "no models listed"
            log_validation_check("ok", "model list", detail)
        except RuntimeError as exc:
            failures += 1
            log_validation_check("fail", "model list", str(exc))

    if model is None:
        log_validation_check("skip", "model request", "pass --model to validate model access")
    elif failures:
        log_validation_check("skip", "model request", "fix failed checks first")
    else:
        resolved_model = engine.resolve_listed_model_id(model, model_ids)
        if resolved_model is None:
            log_validation_check(
                "warn",
                "model listed",
                f"{model} was not found in /models; trying a completion request",
            )
        else:
            log_validation_check("ok", "model listed", resolved_model)

        backend_failed = False
        try:
            model_backend_metadata = engine.validate_model_backend(model)
            if engine.requires_model_backend_validation is True:
                model_format = model_backend_metadata.get("format", "unknown")
                log_validation_check("ok", "model backend", f"format={model_format}")
        except RuntimeError as exc:
            failures += 1
            backend_failed = True
            log_validation_check("fail", "model backend", str(exc))

        if backend_failed:
            log_validation_check("skip", "completion request", "fix failed checks first")
        else:
            try:
                request_model = engine.validate_completion_request(model)
                log_validation_check("ok", "completion request", request_model)
            except RuntimeError as exc:
                failures += 1
                log_validation_check("fail", "completion request", str(exc))

    if failures:
        logger.info(f"\nValidation failed with {failures} error(s).")
        raise SystemExit(1)

    logger.info("\nValidation passed.")


def cmd_submit(args):
    """Validate and submit a benchmark result to the maintainer inbox."""
    if args.timeout <= 0:
        print("Error: --timeout must be greater than 0.", file=sys.stderr)
        raise SystemExit(2)

    try:
        raw, result = load_publishable_result(args.file)
    except SubmissionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    logger.info(
        "Validated result: "
        f"{result.engine.name} / {result.model.name} / "
        f"{result.hardware.chip} / {result.hardware.memory_gb} GB"
    )

    if args.dry_run:
        logger.info("Dry run only; result was not submitted.")
        return

    endpoint = (
        args.endpoint
        or os.environ.get(SUBMIT_ENDPOINT_ENV)
        or DEFAULT_SUBMIT_ENDPOINT
    )
    submitter_email = (
        args.email
        or os.environ.get(SUBMITTER_EMAIL_ENV)
        or DEFAULT_SUBMITTER_EMAIL
    )
    try:
        submit_result_file(
            args.file,
            endpoint,
            timeout=args.timeout,
            submitter_email=submitter_email,
            raw=raw,
            result=result,
        )
    except SubmissionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    logger.info("Submission sent.")


def cmd_upgrade(args):
    """Upgrade mlx-chronos from PyPI when a newer release is available."""
    if args.timeout <= 0:
        print("Error: --timeout must be greater than 0.", file=sys.stderr)
        raise SystemExit(2)

    result = check_for_update(timeout=args.timeout)
    if result.error:
        print(
            f"Error: could not check for {PROJECT_NAME} updates: {result.error}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not result.update_available or result.latest_version is None:
        logger.info("%s is already up to date (%s).", PROJECT_NAME, VERSION)
        return

    logger.info(
        "Updating %s from %s to %s using this Python environment...",
        PROJECT_NAME,
        VERSION,
        result.latest_version,
    )
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        PROJECT_NAME,
    ]
    try:
        completed = subprocess.run(command, check=False)
    except OSError as exc:
        print(f"Error: failed to start pip: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if completed.returncode != 0:
        raise SystemExit(completed.returncode)

    logger.info("Upgrade complete. Run `%s --version` to confirm.", PROJECT_NAME)


def cmd_wizard(args):
    """Start the interactive command wizard."""
    from mlx_chronos.wizard import WizardCallbacks, run_wizard

    callbacks = WizardCallbacks(
        run=cmd_run,
        doctor=cmd_doctor,
        validate=cmd_validate,
        models=cmd_models,
        engines=cmd_engines,
        submit=cmd_submit,
        upgrade=cmd_upgrade,
    )
    run_wizard(args, callbacks)


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        prog="mlx-chronos",
        description="Benchmark suite for MLX inference engines on Apple Silicon.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- run ---
    run_parser = subparsers.add_parser("run", help="Run a benchmark session")
    run_parser.add_argument(
        "--engine",
        choices=list(ENGINES.keys()),
        default="omlx",
        help="Engine to benchmark (default: omlx)",
    )
    run_parser.add_argument(
        "--model",
        required=True,
        help="Model name exactly as shown in the engine (e.g. 'Qwen3.5-4B-OptiQ-4bit')",
    )
    run_parser.add_argument(
        "--quantization",
        default="4bit",
        help="Model quantization format (default: 4bit)",
    )
    run_parser.add_argument(
        "--model-url",
        default=None,
        help=(
            "Reference URL for the model used in this run. Optional for local "
            "runs, required for public leaderboard submission."
        ),
    )
    run_parser.add_argument(
        "--trials",
        type=int,
        default=None,
        help=(
            f"Number of trials per metric (default: {DEFAULT_TRIALS}; "
            f"sustained profile default: {SUSTAINED_TRIALS}; max: {MAX_TRIALS})"
        ),
    )
    run_parser.add_argument(
        "--profile",
        choices=sorted(VALID_BENCHMARK_PROFILES),
        default=BENCHMARK_PROFILE_BASELINE,
        help=(
            "Benchmark profile. 'sustained' defaults to one long throughput "
            f"trial with max_tokens={SUSTAINED_THROUGHPUT_MAX_TOKENS} "
            f"and progress samples every {SUSTAINED_PROGRESS_SAMPLE_INTERVAL_TOKENS} "
            "tokens (default: baseline)."
        ),
    )
    run_parser.add_argument(
        "--notes",
        default=None,
        help="Optional notes to include in the result JSON",
    )
    run_parser.add_argument(
        "--ram-sample-interval",
        type=float,
        default=DEFAULT_RAM_SAMPLE_INTERVAL,
        help=(
            "Seconds between diagnostic engine RSS and system RAM samples "
            f"(default: {DEFAULT_RAM_SAMPLE_INTERVAL})"
        ),
    )
    run_parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help=(
            "Requested max_tokens for throughput trials "
            f"(default: {DEFAULT_THROUGHPUT_MAX_TOKENS}; "
            f"sustained profile default: {SUSTAINED_THROUGHPUT_MAX_TOKENS})"
        ),
    )
    run_parser.add_argument(
        "--min-tokens",
        type=int,
        default=None,
        help=(
            "Optional requested min_tokens for throughput trials. "
            "Use only with engines that support it."
        ),
    )
    run_parser.add_argument(
        "--format",
        choices=["json", "markdown", "all"],
        default="json",
        help="Output format (default: json)",
    )
    run_parser.add_argument(
        "--cooldown-seconds",
        type=float,
        default=0.0,
        help=(
            "Wait until at least this many seconds have elapsed since the latest "
            "prior JSON result in the output directory (default: 0)."
        ),
    )
    run_parser.add_argument(
        "--connection-mode",
        choices=sorted(VALID_CONNECTION_MODES),
        default=CONNECTION_MODE_PERSISTENT,
        help=(
            "HTTP connection behavior for benchmark requests. persistent reuses "
            "one client across the run; per_request opens requests independently "
            "(default: persistent)."
        ),
    )
    run_parser.add_argument(
        "--preflight",
        action="store_true",
        help=(
            "Run an extra model access check before the measured benchmark. "
            "This can fail fast on model errors, but the extra request is not "
            "part of the benchmark protocol."
        ),
    )
    run_parser.add_argument(
        "--publishable",
        action="store_true",
        help=(
            "Fail fast unless the run uses public-leaderboard settings. Requires "
            "--model-url, standard profile defaults, JSON output, persistent "
            "connections, Low Power Mode off, and preflight validation."
        ),
    )
    run_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for result files (default: ./results/local)",
    )
    run_parser.set_defaults(func=cmd_run)

    # --- doctor ---
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Diagnose local setup and print the next useful command",
    )
    doctor_parser.add_argument(
        "--engine",
        choices=list(ENGINES.keys()),
        default=None,
        help="Optional engine to inspect in depth",
    )
    doctor_parser.add_argument(
        "--model",
        default=None,
        help="Optional model name to validate with the selected engine",
    )
    doctor_parser.add_argument(
        "--model-url",
        default=None,
        help="Model reference URL to validate for publishable runs",
    )
    doctor_parser.add_argument(
        "--publishable",
        action="store_true",
        help="Check additional public-leaderboard readiness requirements",
    )
    doctor_parser.set_defaults(func=cmd_doctor)

    # --- engines ---
    engines_parser = subparsers.add_parser(
        "engines",
        help="List available engines and their status",
    )
    engines_parser.set_defaults(func=cmd_engines)

    # --- models ---
    models_parser = subparsers.add_parser(
        "models",
        help="List model ids exposed by a running engine server",
    )
    models_parser.add_argument(
        "--engine",
        choices=list(ENGINES.keys()),
        default="omlx",
        help="Engine to query (default: omlx)",
    )
    models_parser.set_defaults(func=cmd_models)

    # --- validate ---
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate engine, server, and optional model access before a run",
    )
    validate_parser.add_argument(
        "--engine",
        choices=list(ENGINES.keys()),
        default="omlx",
        help="Engine to validate (default: omlx)",
    )
    validate_parser.add_argument(
        "--model",
        default=None,
        help="Optional model name to validate with a tiny completion request",
    )
    validate_parser.set_defaults(func=cmd_validate)

    # --- submit ---
    submit_parser = subparsers.add_parser(
        "submit",
        help="Validate and send a public-leaderboard benchmark result",
    )
    submit_parser.add_argument(
        "--file",
        type=Path,
        required=True,
        help="Path to a benchmark result JSON file",
    )
    submit_parser.add_argument(
        "--endpoint",
        default=None,
        help=(
            "Submission endpoint URL "
            f"(default: project inbox; overrides ${SUBMIT_ENDPOINT_ENV})"
        ),
    )
    submit_parser.add_argument(
        "--email",
        default=None,
        help=(
            "Contact email included in submission metadata "
            f"(default: project no-reply; overrides ${SUBMITTER_EMAIL_ENV})"
        ),
    )
    submit_parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Submission request timeout in seconds (default: 30)",
    )
    submit_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check public leaderboard eligibility without sending the result",
    )
    submit_parser.set_defaults(func=cmd_submit)

    # --- upgrade ---
    upgrade_parser = subparsers.add_parser(
        "upgrade",
        help="Install the latest mlx-chronos release from PyPI",
    )
    upgrade_parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_UPDATE_CHECK_TIMEOUT,
        help=(
            "Seconds to wait while checking PyPI for the latest release "
            f"(default: {DEFAULT_UPDATE_CHECK_TIMEOUT})"
        ),
    )
    upgrade_parser.set_defaults(func=cmd_upgrade)

    # --- wizard ---
    wizard_parser = subparsers.add_parser(
        "wizard",
        help="Open an interactive menu for common mlx-chronos commands",
    )
    wizard_parser.set_defaults(func=cmd_wizard)

    # Parse and dispatch
    args = parser.parse_args()
    _maybe_start_update_check(args.command)
    args.func(args)


if __name__ == "__main__":
    main()
