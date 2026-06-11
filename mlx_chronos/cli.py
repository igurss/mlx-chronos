import argparse
import sys
import logging
import os
import json
import time

from pathlib import Path
from datetime import datetime, timezone
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
from mlx_chronos.protocol import CONNECTION_MODE_PERSISTENT, VALID_CONNECTION_MODES
from mlx_chronos.reporters import JSONReporter, MarkdownReporter
from mlx_chronos.submit import (
    DEFAULT_SUBMIT_ENDPOINT,
    DEFAULT_SUBMITTER_EMAIL,
    SUBMIT_ENDPOINT_ENV,
    SUBMITTER_EMAIL_ENV,
    SubmissionError,
    load_publishable_result,
    submit_result_file,
)
from mlx_chronos.constants import (
    DEFAULT_RAM_SAMPLE_INTERVAL,
    DEFAULT_THROUGHPUT_MAX_TOKENS,
    MAX_TRIALS,
    RECENT_BENCHMARK_WARNING_SECONDS,
    SUSTAINED_PROGRESS_SAMPLE_INTERVAL_TOKENS,
    SUSTAINED_THROUGHPUT_MAX_TOKENS,
    SUSTAINED_TRIALS,
)


logger = logging.getLogger("mlx_chronos")


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
    if meta.get("cached_ttft_warning"):
        print(
            "Warning: cached TTFT is close to cold TTFT. The engine may not "
            "have reused a prompt/KV cache for this run.",
            file=sys.stderr,
        )


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
    reporters = []
    if args.format in ("json", "all"):
        reporters.append(JSONReporter())
    if args.format in ("markdown", "all"):
        reporters.append(MarkdownReporter())
        
    for reporter in reporters:
        path = reporter.save(result, results_dir)
        logger.info(f"Result saved to: {path}")
        
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
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for result files (default: ./results/local)",
    )
    run_parser.set_defaults(func=cmd_run)

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
        help="Send a validated benchmark result to the maintainer inbox",
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
        help="Validate the result without sending it",
    )
    submit_parser.set_defaults(func=cmd_submit)

    # Parse and dispatch
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
