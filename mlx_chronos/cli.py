import argparse
import sys
import logging

from mlx_chronos.benchmark import run_benchmark, save_result
from mlx_chronos.engines import ENGINES


logger = logging.getLogger("mlx_chronos")


def cmd_run(args):
    """Run a benchmark session."""
    if args.trials < 1:
        print("Error: --trials must be at least 1.", file=sys.stderr)
        raise SystemExit(2)
    result = run_benchmark(
        engine_name=args.engine,
        model_name=args.model,
        model_quantization=args.quantization,
        model_size_gb=args.size,
        trials=args.trials,
        notes=args.notes,
    )
    path = save_result(result)
    logger.info(f"\nDone. Result saved to: {path}")


def cmd_engines(args):
    """List available engines and their status."""
    from mlx_chronos.engines import ENGINES, get_engine
    logger.info("\nAvailable engines:\n")
    for name in ENGINES:
        engine = get_engine(name)
        installed = engine.is_installed()
        running = engine.is_server_running() if installed else False
        status = "running" if running else ("installed" if installed else "not installed")
        logger.info(f"  {name:<15} {status}")
    logger.info("")


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
        "--size",
        type=float,
        required=True,
        help="Model size on disk in GB (e.g. 3.2)",
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
    run_parser.set_defaults(func=cmd_run)

    # --- engines ---
    engines_parser = subparsers.add_parser("engines", help="List available engines and their status")
    engines_parser.set_defaults(func=cmd_engines)

    # Parse and dispatch
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()