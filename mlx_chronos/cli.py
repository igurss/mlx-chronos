import argparse
import sys
import logging
import os

from pathlib import Path
from mlx_chronos.benchmark import DEFAULT_RAM_SAMPLE_INTERVAL, run_benchmark
from mlx_chronos.detect import detect_hardware, get_benchmark_condition_warnings
from mlx_chronos.engines import ENGINES, get_engine
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


logger = logging.getLogger("mlx_chronos")


def cmd_run(args):
    """Run a benchmark session."""
    if args.trials < 1:
        print("Error: --trials must be at least 1.", file=sys.stderr)
        raise SystemExit(2)
    if args.ram_sample_interval <= 0:
        print("Error: --ram-sample-interval must be greater than 0.", file=sys.stderr)
        raise SystemExit(2)
    if not args.model.strip():
        print("Error: --model must not be empty.", file=sys.stderr)
        raise SystemExit(2)
    try:
        result = run_benchmark(
            engine_name=args.engine,
            model_name=args.model,
            model_quantization=args.quantization,
            trials=args.trials,
            notes=args.notes,
            ram_sample_interval=args.ram_sample_interval,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
        
    results_dir = args.output_dir or Path.cwd() / "results" / "local"
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
        log_validation_check(
            "ok",
            "engine installed",
            f"{args.engine} ({engine.get_version()})",
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
        _, result = load_publishable_result(args.file)
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
        default=5,
        help="Number of trials per metric (default: 5, min: 1)",
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
            "Seconds between engine RSS and system RAM samples "
            f"(default: {DEFAULT_RAM_SAMPLE_INTERVAL})"
        ),
    )
    run_parser.add_argument(
        "--format",
        choices=["json", "markdown", "all"],
        default="json",
        help="Output format (default: json)",
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
