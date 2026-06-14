"""Interactive CLI wizard for mlx-chronos.

The wizard builds the same argparse Namespace objects used by the classic CLI
commands. That keeps the interactive path close to the tested command path.
"""

from __future__ import annotations

from argparse import Namespace
from dataclasses import dataclass, replace
from pathlib import Path
import shlex
import sys
from typing import Any, Callable

from mlx_chronos.benchmark import (
    BENCHMARK_PROFILE_BASELINE,
    BENCHMARK_PROFILE_SUSTAINED,
    DEFAULT_TRIALS,
)
from mlx_chronos.constants import (
    DEFAULT_RAM_SAMPLE_INTERVAL,
    DEFAULT_THROUGHPUT_MAX_TOKENS,
    MAX_TRIALS,
    SUSTAINED_THROUGHPUT_MAX_TOKENS,
    SUSTAINED_TRIALS,
)
from mlx_chronos.engines import ENGINES
from mlx_chronos.protocol import CONNECTION_MODE_PERSISTENT, VALID_CONNECTION_MODES
from mlx_chronos.updates import DEFAULT_UPDATE_CHECK_TIMEOUT


CommandCallback = Callable[[Namespace], None]


ENGINE_DESCRIPTIONS = {
    "omlx": "oMLX OpenAI-compatible server",
    "rapid-mlx": "Rapid-MLX OpenAI-compatible server",
    "vllm-mlx": "vllm-mlx OpenAI-compatible server",
    "mlx-lm": "mlx-lm OpenAI-compatible server",
    "ollama": "Ollama local server",
}

PROFILE_DESCRIPTIONS = {
    BENCHMARK_PROFILE_BASELINE: (
        f"Baseline, public profile default: {DEFAULT_TRIALS} trials, "
        f"{DEFAULT_THROUGHPUT_MAX_TOKENS} max tokens"
    ),
    BENCHMARK_PROFILE_SUSTAINED: (
        f"Sustained, heat-sensitive profile default: {SUSTAINED_TRIALS} trial, "
        f"{SUSTAINED_THROUGHPUT_MAX_TOKENS} max tokens"
    ),
}

FORMAT_DESCRIPTIONS = {
    "json": "JSON result only",
    "markdown": "Markdown report only",
    "all": "JSON result and Markdown report",
}

OPTIONAL_RUN_SETTINGS = {
    "trials": "Trials per metric",
    "token_bounds": "Throughput token bounds",
    "format": "Output format",
    "output_dir": "Output directory",
    "connection_mode": "HTTP connection mode",
    "ram_sample_interval": "RAM sample interval",
    "cooldown_seconds": "Cooldown before run",
    "preflight": "Preflight model check",
    "notes": "Result notes",
}


class WizardAbort(RuntimeError):
    """Raised when the user cancels the interactive wizard."""


@dataclass(frozen=True)
class RunWizardConfig:
    engine: str = "omlx"
    model: str = ""
    quantization: str = "4bit"
    profile: str = BENCHMARK_PROFILE_BASELINE
    trials: int | None = None
    max_tokens: int | None = None
    min_tokens: int | None = None
    output_format: str = "json"
    output_dir: Path | None = None
    cooldown_seconds: float = 0.0
    connection_mode: str = CONNECTION_MODE_PERSISTENT
    ram_sample_interval: float = DEFAULT_RAM_SAMPLE_INTERVAL
    preflight: bool = False
    notes: str | None = None

    def to_namespace(self) -> Namespace:
        return Namespace(
            engine=self.engine,
            model=self.model,
            quantization=self.quantization,
            trials=self.trials,
            notes=self.notes,
            ram_sample_interval=self.ram_sample_interval,
            profile=self.profile,
            cooldown_seconds=self.cooldown_seconds,
            max_tokens=self.max_tokens,
            min_tokens=self.min_tokens,
            format=self.output_format,
            output_dir=self.output_dir,
            connection_mode=self.connection_mode,
            preflight=self.preflight,
        )


@dataclass(frozen=True)
class WizardCallbacks:
    run: CommandCallback
    validate: CommandCallback
    models: CommandCallback
    engines: CommandCallback
    submit: CommandCallback
    upgrade: CommandCallback


def resolved_run_defaults(config: RunWizardConfig) -> tuple[int, int]:
    if config.profile == BENCHMARK_PROFILE_SUSTAINED:
        default_trials = SUSTAINED_TRIALS
        default_max_tokens = SUSTAINED_THROUGHPUT_MAX_TOKENS
    else:
        default_trials = DEFAULT_TRIALS
        default_max_tokens = DEFAULT_THROUGHPUT_MAX_TOKENS
    return (
        default_trials if config.trials is None else config.trials,
        default_max_tokens if config.max_tokens is None else config.max_tokens,
    )


def validate_run_config(config: RunWizardConfig) -> list[str]:
    _, effective_max_tokens = resolved_run_defaults(config)
    errors = []
    if config.engine not in ENGINES:
        errors.append(f"engine must be one of {', '.join(ENGINES)}")
    if not config.model.strip():
        errors.append("model must not be empty")
    if not config.quantization.strip():
        errors.append("quantization must not be empty")
    if config.profile not in PROFILE_DESCRIPTIONS:
        errors.append(
            "profile must be one of "
            f"{', '.join(sorted(PROFILE_DESCRIPTIONS))}"
        )
    if config.trials is not None and not 1 <= config.trials <= MAX_TRIALS:
        errors.append(f"trials must be between 1 and {MAX_TRIALS}")
    if config.max_tokens is not None and config.max_tokens < 1:
        errors.append("max tokens must be at least 1")
    if config.min_tokens is not None and config.min_tokens < 1:
        errors.append("min tokens must be at least 1")
    if config.min_tokens is not None and config.min_tokens > effective_max_tokens:
        errors.append(
            "min tokens must be less than or equal to the effective max tokens "
            f"({effective_max_tokens})"
        )
    if config.connection_mode not in VALID_CONNECTION_MODES:
        errors.append(
            "connection mode must be one of "
            f"{', '.join(sorted(VALID_CONNECTION_MODES))}"
        )
    if config.ram_sample_interval <= 0:
        errors.append("RAM sample interval must be greater than 0")
    if config.cooldown_seconds < 0:
        errors.append("cooldown seconds must be non-negative")
    return errors


def build_run_command(config: RunWizardConfig) -> str:
    parts = [
        "mlx-chronos",
        "run",
        "--engine",
        config.engine,
        "--model",
        config.model,
        "--quantization",
        config.quantization,
        "--profile",
        config.profile,
    ]
    if config.trials is not None:
        parts.extend(["--trials", str(config.trials)])
    if config.max_tokens is not None:
        parts.extend(["--max-tokens", str(config.max_tokens)])
    if config.min_tokens is not None:
        parts.extend(["--min-tokens", str(config.min_tokens)])
    if config.output_format != "json":
        parts.extend(["--format", config.output_format])
    if config.output_dir is not None:
        parts.extend(["--output-dir", str(config.output_dir)])
    if config.cooldown_seconds != 0.0:
        parts.extend(["--cooldown-seconds", _format_number(config.cooldown_seconds)])
    if config.connection_mode != CONNECTION_MODE_PERSISTENT:
        parts.extend(["--connection-mode", config.connection_mode])
    if config.ram_sample_interval != DEFAULT_RAM_SAMPLE_INTERVAL:
        parts.extend(
            ["--ram-sample-interval", _format_number(config.ram_sample_interval)]
        )
    if config.preflight:
        parts.append("--preflight")
    if config.notes:
        parts.extend(["--notes", config.notes])
    return " ".join(shlex.quote(part) for part in parts)


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value)


def _format_optional(value: object, fallback: str = "default") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def _load_interactive_dependencies():
    try:
        import questionary
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
    except ImportError as exc:
        print(
            "Error: mlx-chronos wizard requires questionary and rich. "
            "Reinstall with `pip install --upgrade mlx-chronos`.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    return questionary, Console, Panel, Table


def run_wizard(args: Namespace, callbacks: WizardCallbacks) -> None:
    del args
    if not sys.stdin.isatty():
        print("Error: mlx-chronos wizard requires an interactive terminal.", file=sys.stderr)
        raise SystemExit(2)

    questionary, console_cls, panel_cls, table_cls = _load_interactive_dependencies()
    session = WizardSession(
        questionary=questionary,
        console=console_cls(),
        panel_cls=panel_cls,
        table_cls=table_cls,
        callbacks=callbacks,
    )
    session.run()


class WizardSession:
    def __init__(
        self,
        *,
        questionary: Any,
        console: Any,
        panel_cls: Any,
        table_cls: Any,
        callbacks: WizardCallbacks,
    ) -> None:
        self.questionary = questionary
        self.console = console
        self.Panel = panel_cls
        self.Table = table_cls
        self.callbacks = callbacks
        self.style = questionary.Style(
            [
                ("qmark", "fg:#38bdf8 bold"),
                ("question", "bold"),
                ("answer", "fg:#22c55e bold"),
                ("pointer", "fg:#f59e0b bold"),
                ("highlighted", "fg:#f59e0b bold"),
                ("selected", "fg:#22c55e"),
                ("separator", "fg:#64748b"),
                ("instruction", "fg:#94a3b8"),
            ]
        )

    def run(self) -> None:
        self._render_header()
        try:
            while True:
                action = self._select(
                    "What do you want to do?",
                    [
                        ("Run benchmark", "run"),
                        ("Validate setup", "validate"),
                        ("List models for an engine", "models"),
                        ("List engine status", "engines"),
                        ("Submit a result JSON", "submit"),
                        ("Upgrade mlx-chronos", "upgrade"),
                        ("Exit", "exit"),
                    ],
                )
                if action == "run":
                    self._run_benchmark_flow()
                    return
                if action == "validate":
                    self._validate_flow()
                    self._pause()
                elif action == "models":
                    self._models_flow()
                    self._pause()
                elif action == "engines":
                    self.callbacks.engines(Namespace())
                    self._pause()
                elif action == "submit":
                    self._submit_flow()
                    self._pause()
                elif action == "upgrade":
                    self._upgrade_flow()
                    self._pause()
                elif action == "exit":
                    return
        except WizardAbort:
            self.console.print("\n[dim]Wizard cancelled.[/dim]")

    def _render_header(self) -> None:
        body = (
            "[bold]mlx-chronos wizard[/bold]\n"
            "Configure benchmarks and common CLI actions without memorizing flags."
        )
        self.console.print(self.Panel(body, border_style="cyan"))

    def _run_benchmark_flow(self) -> None:
        config = self._prompt_run_config(RunWizardConfig())
        while True:
            self._render_run_summary(config)
            action = self._select(
                "Next step",
                [
                    ("Run benchmark now", "run"),
                    ("Edit options", "edit"),
                    ("Print command and exit", "print"),
                    ("Cancel", "cancel"),
                ],
            )
            if action == "run":
                errors = validate_run_config(config)
                if errors:
                    self._render_run_errors(errors)
                    config = self._edit_run_config(config)
                    continue
                self.callbacks.run(config.to_namespace())
                return
            if action == "print":
                self.console.print(build_run_command(config))
                return
            if action == "edit":
                config = self._edit_run_config(config)
                continue
            return

    def _prompt_run_config(self, config: RunWizardConfig) -> RunWizardConfig:
        config = replace(
            config,
            engine=self._ask_engine(default=config.engine),
            model=self._ask_required_text(
                "Model name as exposed by the engine",
                default=config.model,
            ),
            quantization=self._ask_required_text(
                "Quantization / format label",
                default=config.quantization,
            ),
            profile=self._ask_profile(default=config.profile),
        )

        optional_settings = self._checkbox(
            "Customize optional run settings",
            [
                (label, key)
                for key, label in OPTIONAL_RUN_SETTINGS.items()
            ],
        )
        for setting in optional_settings:
            config = self._prompt_run_setting(config, setting)
        return config

    def _edit_run_config(self, config: RunWizardConfig) -> RunWizardConfig:
        while True:
            field = self._select(
                "Select an option to edit",
                [
                    ("Engine", "engine"),
                    ("Model", "model"),
                    ("Quantization / format label", "quantization"),
                    ("Profile", "profile"),
                    *[
                        (label, key)
                        for key, label in OPTIONAL_RUN_SETTINGS.items()
                    ],
                    ("Done editing", "done"),
                ],
            )
            if field == "done":
                return config
            config = self._prompt_run_setting(config, field)

    def _prompt_run_setting(
        self,
        config: RunWizardConfig,
        setting: str,
    ) -> RunWizardConfig:
        if setting == "engine":
            return replace(config, engine=self._ask_engine(default=config.engine))
        if setting == "model":
            return replace(
                config,
                model=self._ask_required_text(
                    "Model name as exposed by the engine",
                    default=config.model,
                ),
            )
        if setting == "quantization":
            return replace(
                config,
                quantization=self._ask_required_text(
                    "Quantization / format label",
                    default=config.quantization,
                ),
            )
        if setting == "profile":
            return replace(config, profile=self._ask_profile(default=config.profile))
        if setting == "trials":
            return replace(
                config,
                trials=self._ask_optional_int(
                    f"Trials per metric (blank = profile default, max {MAX_TRIALS})",
                    default=config.trials,
                    min_value=1,
                    max_value=MAX_TRIALS,
                ),
            )
        if setting == "token_bounds":
            max_tokens = self._ask_optional_int(
                "Throughput max tokens (blank = profile default)",
                default=config.max_tokens,
                min_value=1,
            )
            min_tokens = self._ask_optional_int(
                "Throughput min tokens (blank = disabled)",
                default=config.min_tokens,
                min_value=1,
            )
            return replace(config, max_tokens=max_tokens, min_tokens=min_tokens)
        if setting == "format":
            return replace(
                config,
                output_format=self._select(
                    "Output format",
                    [
                        (f"{name} - {FORMAT_DESCRIPTIONS[name]}", name)
                        for name in ("json", "markdown", "all")
                    ],
                    default=config.output_format,
                ),
            )
        if setting == "output_dir":
            return replace(
                config,
                output_dir=self._ask_optional_path(
                    "Output directory (blank = ./results/local)",
                    default=config.output_dir,
                ),
            )
        if setting == "connection_mode":
            return replace(
                config,
                connection_mode=self._select(
                    "HTTP connection mode",
                    [
                        (mode, mode)
                        for mode in sorted(VALID_CONNECTION_MODES)
                    ],
                    default=config.connection_mode,
                ),
            )
        if setting == "ram_sample_interval":
            return replace(
                config,
                ram_sample_interval=self._ask_float(
                    "RAM sample interval in seconds",
                    default=config.ram_sample_interval,
                    min_value=0.000001,
                ),
            )
        if setting == "cooldown_seconds":
            return replace(
                config,
                cooldown_seconds=self._ask_float(
                    "Cooldown seconds before starting",
                    default=config.cooldown_seconds,
                    min_value=0.0,
                ),
            )
        if setting == "preflight":
            return replace(
                config,
                preflight=self._confirm(
                    "Run preflight model access check before benchmark?",
                    default=config.preflight,
                ),
            )
        if setting == "notes":
            notes = self._ask_optional_text("Notes saved in result JSON", config.notes)
            return replace(config, notes=notes)
        raise ValueError(f"unknown wizard setting: {setting}")

    def _render_run_summary(self, config: RunWizardConfig) -> None:
        resolved_trials, resolved_max_tokens = resolved_run_defaults(config)
        table = self.Table(title="Benchmark configuration", show_header=True)
        table.add_column("Setting", style="bold cyan")
        table.add_column("Value")
        rows = [
            ("Engine", config.engine),
            ("Model", config.model),
            ("Quantization", config.quantization),
            ("Profile", config.profile),
            (
                "Trials",
                (
                    f"profile default ({resolved_trials})"
                    if config.trials is None
                    else str(config.trials)
                ),
            ),
            (
                "Max tokens",
                (
                    f"profile default ({resolved_max_tokens})"
                    if config.max_tokens is None
                    else str(config.max_tokens)
                ),
            ),
            ("Min tokens", _format_optional(config.min_tokens, "disabled")),
            ("Output format", config.output_format),
            ("Output dir", _format_optional(config.output_dir, "./results/local")),
            ("Connection mode", config.connection_mode),
            ("RAM sample interval", f"{config.ram_sample_interval:g}s"),
            ("Cooldown", f"{config.cooldown_seconds:g}s"),
            ("Preflight", "yes" if config.preflight else "no"),
            ("Notes", _format_optional(config.notes, "none")),
        ]
        for key, value in rows:
            table.add_row(key, value)
        self.console.print(table)
        self.console.print(
            self.Panel(
                build_run_command(config),
                title="Equivalent command",
                border_style="green",
            )
        )

    def _render_run_errors(self, errors: list[str]) -> None:
        message = "\n".join(f"- {error}" for error in errors)
        self.console.print(
            self.Panel(
                message,
                title="Configuration needs attention",
                border_style="red",
            )
        )

    def _validate_flow(self) -> None:
        engine = self._ask_engine()
        model = None
        if self._confirm("Validate model access too?", default=True):
            model = self._ask_required_text("Model name")
        self.callbacks.validate(Namespace(engine=engine, model=model))

    def _models_flow(self) -> None:
        engine = self._ask_engine()
        self.callbacks.models(Namespace(engine=engine))

    def _submit_flow(self) -> None:
        file_path = self._ask_required_path("Result JSON file")
        dry_run = self._confirm("Dry run only?", default=True)
        endpoint = None
        email = None
        timeout = 30.0
        if self._confirm("Customize submit endpoint, email, or timeout?", default=False):
            endpoint = self._ask_optional_text("Submission endpoint URL", None)
            email = self._ask_optional_text("Contact email", None)
            timeout = self._ask_float("Submission timeout in seconds", 30.0, 0.000001)
        self.callbacks.submit(
            Namespace(
                file=file_path,
                endpoint=endpoint,
                email=email,
                timeout=timeout,
                dry_run=dry_run,
            )
        )

    def _upgrade_flow(self) -> None:
        if not self._confirm(
            "Check PyPI and upgrade this Python environment if needed?",
            default=True,
        ):
            return
        self.callbacks.upgrade(Namespace(timeout=DEFAULT_UPDATE_CHECK_TIMEOUT))

    def _ask_engine(self, default: str = "omlx") -> str:
        return self._select(
            "Engine",
            [
                (f"{name} - {ENGINE_DESCRIPTIONS.get(name, 'engine')}", name)
                for name in ENGINES
            ],
            default=default,
        )

    def _ask_profile(self, default: str = BENCHMARK_PROFILE_BASELINE) -> str:
        return self._select(
            "Benchmark profile",
            [
                (f"{name} - {PROFILE_DESCRIPTIONS[name]}", name)
                for name in (BENCHMARK_PROFILE_BASELINE, BENCHMARK_PROFILE_SUSTAINED)
            ],
            default=default,
        )

    def _select(
        self,
        message: str,
        choices: list[tuple[str, str]],
        default: str | None = None,
    ) -> str:
        prompt_choices = [
            self.questionary.Choice(title=title, value=value)
            for title, value in choices
        ]
        value = self._ask(
            self.questionary.select(
                message,
                choices=prompt_choices,
                default=default,
                style=self.style,
            )
        )
        return str(value)

    def _checkbox(
        self,
        message: str,
        choices: list[tuple[str, str]],
    ) -> list[str]:
        prompt_choices = [
            self.questionary.Choice(title=title, value=value)
            for title, value in choices
        ]
        value = self._ask(
            self.questionary.checkbox(
                message,
                choices=prompt_choices,
                style=self.style,
            )
        )
        return list(value)

    def _confirm(self, message: str, default: bool = False) -> bool:
        value = self._ask(
            self.questionary.confirm(message, default=default, style=self.style)
        )
        return bool(value)

    def _ask_required_text(self, message: str, default: str = "") -> str:
        value = self._ask(
            self.questionary.text(
                message,
                default=default,
                validate=lambda text: True
                if text.strip()
                else "This value is required.",
                style=self.style,
            )
        )
        return str(value).strip()

    def _ask_optional_text(self, message: str, default: str | None) -> str | None:
        value = self._ask(
            self.questionary.text(
                message,
                default=default or "",
                style=self.style,
            )
        )
        stripped = str(value).strip()
        return stripped or None

    def _ask_optional_int(
        self,
        message: str,
        *,
        default: int | None,
        min_value: int,
        max_value: int | None = None,
    ) -> int | None:
        value = self._ask(
            self.questionary.text(
                message,
                default="" if default is None else str(default),
                validate=self._optional_int_validator(min_value, max_value),
                style=self.style,
            )
        )
        stripped = str(value).strip()
        return None if not stripped else int(stripped)

    def _ask_float(
        self,
        message: str,
        default: float,
        min_value: float,
    ) -> float:
        value = self._ask(
            self.questionary.text(
                message,
                default=_format_number(float(default)),
                validate=self._float_validator(min_value),
                style=self.style,
            )
        )
        return float(str(value).strip())

    def _ask_optional_path(self, message: str, default: Path | None) -> Path | None:
        value = self._ask(
            self.questionary.text(
                message,
                default="" if default is None else str(default),
                style=self.style,
            )
        )
        stripped = str(value).strip()
        return None if not stripped else Path(stripped).expanduser()

    def _ask_required_path(self, message: str) -> Path:
        value = self._ask(
            self.questionary.text(
                message,
                validate=lambda text: True
                if text.strip()
                else "This path is required.",
                style=self.style,
            )
        )
        return Path(str(value).strip()).expanduser()

    def _ask(self, prompt: Any) -> Any:
        try:
            value = prompt.ask()
        except KeyboardInterrupt as exc:
            raise WizardAbort from exc
        if value is None:
            raise WizardAbort
        return value

    def _pause(self) -> None:
        self._ask(
            self.questionary.text(
                "Press Enter to return to the wizard menu",
                default="",
                style=self.style,
            )
        )

    @staticmethod
    def _optional_int_validator(
        min_value: int,
        max_value: int | None,
    ) -> Callable[[str], bool | str]:
        def validate(text: str) -> bool | str:
            stripped = text.strip()
            if not stripped:
                return True
            try:
                value = int(stripped)
            except ValueError:
                return "Enter an integer."
            if value < min_value:
                return f"Enter a value >= {min_value}."
            if max_value is not None and value > max_value:
                return f"Enter a value <= {max_value}."
            return True

        return validate

    @staticmethod
    def _float_validator(min_value: float) -> Callable[[str], bool | str]:
        def validate(text: str) -> bool | str:
            stripped = text.strip()
            try:
                value = float(stripped)
            except ValueError:
                return "Enter a number."
            if value < min_value:
                return f"Enter a value >= {min_value:g}."
            return True

        return validate
