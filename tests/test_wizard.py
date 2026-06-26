import shlex
from argparse import Namespace
from pathlib import Path

import pytest

from mlx_chronos.constants import (
    DEFAULT_RAM_SAMPLE_INTERVAL,
    DEFAULT_THROUGHPUT_MAX_TOKENS,
    SUSTAINED_THROUGHPUT_MAX_TOKENS,
    SUSTAINED_TRIALS,
)
from mlx_chronos.wizard import (
    BACK_COMMAND,
    BACK_TO_MENU,
    MANUAL_MODEL_ENTRY,
    RunWizardConfig,
    WizardCallbacks,
    WizardAbort,
    WizardBackToMenu,
    WizardSession,
    build_run_command,
    resolved_run_defaults,
    validate_run_config,
)


class FakeConsole:
    def __init__(self):
        self.messages = []

    def print(self, *args, **kwargs):
        del kwargs
        self.messages.append(" ".join(str(arg) for arg in args))


def test_run_wizard_config_builds_run_namespace():
    config = RunWizardConfig(
        engine="mlx-lm",
        model="mlx-community/test-model",
        quantization="nvfp4",
        model_url="https://huggingface.co/mlx-community/test-model",
        publishable=True,
        profile="sustained",
        trials=2,
        max_tokens=500,
        min_tokens=400,
        output_format="all",
        output_dir=Path("/tmp/mlx results"),
        cooldown_seconds=30.0,
        connection_mode="per_request",
        ram_sample_interval=0.25,
        preflight=True,
        notes="local test",
    )

    args = config.to_namespace()

    assert isinstance(args, Namespace)
    assert args.engine == "mlx-lm"
    assert args.model == "mlx-community/test-model"
    assert args.quantization == "nvfp4"
    assert args.model_url == "https://huggingface.co/mlx-community/test-model"
    assert args.publishable is True
    assert args.profile == "sustained"
    assert args.trials == 2
    assert args.max_tokens == 500
    assert args.min_tokens == 400
    assert args.format == "all"
    assert args.output_dir == Path("/tmp/mlx results")
    assert args.cooldown_seconds == 30.0
    assert args.connection_mode == "per_request"
    assert args.ram_sample_interval == 0.25
    assert args.preflight is True
    assert args.notes == "local test"


def test_resolved_run_defaults_follow_profile():
    baseline = RunWizardConfig(profile="baseline")
    sustained = RunWizardConfig(profile="sustained")

    assert resolved_run_defaults(baseline) == (
        5,
        DEFAULT_THROUGHPUT_MAX_TOKENS,
    )
    assert resolved_run_defaults(sustained) == (
        SUSTAINED_TRIALS,
        SUSTAINED_THROUGHPUT_MAX_TOKENS,
    )


def test_resolved_run_defaults_use_custom_values():
    config = RunWizardConfig(profile="sustained", trials=3, max_tokens=700)

    assert resolved_run_defaults(config) == (3, 700)


def test_validate_run_config_rejects_min_tokens_above_effective_max():
    errors = validate_run_config(
        RunWizardConfig(model="test", min_tokens=200, max_tokens=100)
    )

    assert errors == [
        "min tokens must be less than or equal to the effective max tokens (100)"
    ]


def test_validate_run_config_allows_min_tokens_against_profile_default():
    assert validate_run_config(RunWizardConfig(model="test", min_tokens=80)) == []


def test_validate_run_config_rejects_invalid_model_url():
    errors = validate_run_config(RunWizardConfig(model="test", model_url="not-a-url"))

    assert errors == ["model reference URL must be an http(s) URL"]


def test_validate_run_config_rejects_incomplete_publishable_config():
    errors = validate_run_config(
        RunWizardConfig(
            model="test",
            publishable=True,
            min_tokens=80,
            connection_mode="per_request",
        )
    )

    assert "publishable runs require a model reference URL" in errors
    assert "publishable runs do not allow min tokens" in errors
    assert "publishable runs require persistent HTTP connections" in errors


def test_wizard_model_url_prompt_validates_inline():
    captured = {}

    class FakeQuestionary:
        def text(self, *args, **kwargs):
            del args
            captured.update(kwargs)
            return object()

    session = object.__new__(WizardSession)
    session.questionary = FakeQuestionary()
    session.style = None
    session._ask = lambda _prompt: " https://huggingface.co/org/model "

    assert session._ask_optional_model_url("Model reference URL", None) == (
        "https://huggingface.co/org/model"
    )
    assert captured["validate"]("not-a-url") == (
        "model reference URL must be an http(s) URL"
    )
    assert captured["validate"]("") is True


def test_build_run_command_contains_only_needed_default_flags():
    command = build_run_command(
        RunWizardConfig(
            engine="omlx",
            model="Qwen3.5-4B-OptiQ-4bit",
            quantization="4bit",
            profile="baseline",
        )
    )

    parts = shlex.split(command)
    assert parts == [
        "mlx-chronos",
        "run",
        "--engine",
        "omlx",
        "--model",
        "Qwen3.5-4B-OptiQ-4bit",
        "--quantization",
        "4bit",
        "--profile",
        "baseline",
    ]
    assert "--trials" not in parts
    assert "--max-tokens" not in parts
    assert "--ram-sample-interval" not in parts


def test_build_run_command_includes_publishable_flag():
    command = build_run_command(
        RunWizardConfig(
            engine="omlx",
            model="Qwen3.5-4B-OptiQ-4bit",
            model_url="https://huggingface.co/mlx-community/Qwen3.5-4B-OptiQ-4bit",
            publishable=True,
        )
    )

    parts = shlex.split(command)
    assert "--publishable" in parts
    assert "--model-url" in parts


def test_build_run_command_quotes_paths_and_notes():
    config = RunWizardConfig(
        engine="rapid-mlx",
        model="org/model name",
        quantization="OptiQ 4bit",
        model_url="https://huggingface.co/org/model-name",
        profile="sustained",
        trials=1,
        max_tokens=1000,
        min_tokens=800,
        output_format="all",
        output_dir=Path("/tmp/mlx results"),
        cooldown_seconds=300.0,
        connection_mode="per_request",
        ram_sample_interval=0.1,
        preflight=True,
        notes="fan maxed; cold room",
    )

    assert shlex.split(build_run_command(config)) == [
        "mlx-chronos",
        "run",
        "--engine",
        "rapid-mlx",
        "--model",
        "org/model name",
        "--quantization",
        "OptiQ 4bit",
        "--profile",
        "sustained",
        "--model-url",
        "https://huggingface.co/org/model-name",
        "--trials",
        "1",
        "--max-tokens",
        "1000",
        "--min-tokens",
        "800",
        "--format",
        "all",
        "--output-dir",
        "/tmp/mlx results",
        "--cooldown-seconds",
        "300",
        "--connection-mode",
        "per_request",
        "--ram-sample-interval",
        "0.1",
        "--preflight",
        "--notes",
        "fan maxed; cold room",
    ]


def test_wizard_config_uses_current_ram_default():
    assert RunWizardConfig().ram_sample_interval == pytest.approx(
        DEFAULT_RAM_SAMPLE_INTERVAL
    )


def test_wizard_ask_model_selects_model_from_server():
    session = object.__new__(WizardSession)
    session._load_model_ids = lambda engine: (["model-a", "model-b"], None)
    session._ask_required_text = lambda *_args, **_kwargs: pytest.fail(
        "manual prompt should not be used"
    )

    captured = {}

    def select(message, choices, default=None):
        captured["message"] = message
        captured["choices"] = choices
        captured["default"] = default
        return "model-b"

    session._select = select

    assert session._ask_model("omlx") == "model-b"
    assert captured == {
        "message": "Model exposed by the engine",
        "choices": [
            ("model-a", "model-a"),
            ("model-b", "model-b"),
            ("Enter manually", MANUAL_MODEL_ENTRY),
        ],
        "default": "model-a",
    }


def test_wizard_ask_engine_can_return_to_main_menu():
    session = object.__new__(WizardSession)
    session._engine_choices = lambda: [("oMLX", "omlx")]
    session._select = lambda *_args, **_kwargs: BACK_TO_MENU

    with pytest.raises(WizardBackToMenu):
        session._ask_engine(allow_back=True)


def test_wizard_engine_choices_rank_ready_engines_first(monkeypatch):
    class FakeEngine:
        def __init__(self, installed, running, base_url):
            self._installed = installed
            self._running = running
            self._base_url = base_url

        def is_installed(self):
            return self._installed

        def is_server_running(self):
            return self._running

        def base_url(self):
            return self._base_url

    engines = {
        "omlx": FakeEngine(False, False, "http://localhost:10240/v1"),
        "rapid-mlx": FakeEngine(True, False, "http://localhost:10241/v1"),
        "vllm-mlx": FakeEngine(True, True, "http://localhost:8000/v1"),
        "mlx-lm": FakeEngine(False, False, "http://localhost:8080/v1"),
        "ollama": FakeEngine(False, False, "http://localhost:11434/v1"),
    }
    monkeypatch.setattr("mlx_chronos.wizard.get_engine", engines.__getitem__)

    session = object.__new__(WizardSession)
    choices = session._engine_choices()

    assert choices[0][1] == "vllm-mlx"
    assert "running at http://localhost:8000/v1" in choices[0][0]
    assert choices[1][1] == "rapid-mlx"
    assert "installed, server not running" in choices[1][0]
    assert choices[-1][1] == "ollama"


def test_wizard_ask_model_can_return_from_model_menu():
    session = object.__new__(WizardSession)
    session._load_model_ids = lambda engine: (["model-a"], None)
    session._select = lambda *_args, **_kwargs: BACK_TO_MENU

    with pytest.raises(WizardBackToMenu):
        session._ask_model("omlx", allow_back=True)


def test_wizard_ask_model_can_keep_current_unlisted_value():
    session = object.__new__(WizardSession)
    session._load_model_ids = lambda engine: (["model-a"], None)
    session._ask_required_text = lambda *_args, **_kwargs: pytest.fail(
        "manual prompt should not be used"
    )

    captured = {}

    def select(message, choices, default=None):
        captured["choices"] = choices
        captured["default"] = default
        return "custom-model"

    session._select = select

    assert session._ask_model("omlx", default="custom-model") == "custom-model"
    assert captured["choices"] == [
        ("Keep current value: custom-model", "custom-model"),
        ("model-a", "model-a"),
        ("Enter manually", MANUAL_MODEL_ENTRY),
    ]
    assert captured["default"] == "model-a"


def test_wizard_ask_model_allows_manual_entry_from_model_menu():
    session = object.__new__(WizardSession)
    session._load_model_ids = lambda engine: (["model-a"], None)
    session._select = lambda *_args, **_kwargs: MANUAL_MODEL_ENTRY
    session._ask_required_text = lambda message, default="", **_kwargs: "manual-model"

    assert session._ask_model("omlx") == "manual-model"


def test_wizard_ask_model_falls_back_when_models_cannot_load():
    session = object.__new__(WizardSession)
    session.console = FakeConsole()
    session._load_model_ids = lambda engine: ([], "server is not running")
    session._ask_required_text = lambda message, default="", **_kwargs: "manual-model"

    assert session._ask_model("omlx") == "manual-model"
    assert session.console.messages == [
        "[yellow]Could not load models from omlx: server is not running.[/yellow]"
    ]


def test_wizard_ask_model_can_return_before_manual_fallback():
    session = object.__new__(WizardSession)
    session.console = FakeConsole()
    session._load_model_ids = lambda engine: ([], "server is not running")
    session._select = lambda *_args, **_kwargs: BACK_TO_MENU

    with pytest.raises(WizardBackToMenu):
        session._ask_model("omlx", allow_back=True)


def test_wizard_required_text_supports_back_command():
    class FakeQuestionary:
        def text(self, *args, **kwargs):
            return object()

    session = object.__new__(WizardSession)
    session.questionary = FakeQuestionary()
    session.style = None
    session._ask = lambda _prompt: BACK_COMMAND

    with pytest.raises(WizardBackToMenu):
        session._ask_required_text("Model", allow_back=True)


def test_wizard_required_model_url_prompt_validates_inline():
    captured = {}

    class FakeQuestionary:
        def text(self, *args, **kwargs):
            del args
            captured.update(kwargs)
            return object()

    session = object.__new__(WizardSession)
    session.questionary = FakeQuestionary()
    session.style = None
    session._ask = lambda _prompt: " https://huggingface.co/org/model "

    assert session._ask_required_model_url("Model reference URL", None) == (
        "https://huggingface.co/org/model"
    )
    assert captured["validate"]("") == (
        "Model reference URL is required for public submissions."
    )


def test_wizard_prompt_run_config_prepares_publishable_defaults():
    session = object.__new__(WizardSession)
    session._ask_engine = lambda **_kwargs: "omlx"
    session._ask_model = lambda *_args, **_kwargs: "org/test-model"
    session._ask_required_text = lambda *_args, **_kwargs: "4bit"
    session._ask_profile = lambda **_kwargs: "baseline"
    session._confirm = lambda *_args, **_kwargs: True
    session._ask_required_model_url = lambda *_args, **_kwargs: (
        "https://huggingface.co/org/test-model"
    )
    session._checkbox = lambda *_args, **_kwargs: []

    config = session._prompt_run_config(
        RunWizardConfig(
            trials=1,
            max_tokens=50,
            min_tokens=10,
            connection_mode="per_request",
        )
    )

    assert config.engine == "omlx"
    assert config.model == "org/test-model"
    assert config.publishable is True
    assert config.preflight is True
    assert config.model_url == "https://huggingface.co/org/test-model"
    assert config.trials is None
    assert config.max_tokens is None
    assert config.min_tokens is None
    assert config.connection_mode == "persistent"


def test_wizard_doctor_flow_passes_publishable_context():
    captured = {}
    confirmations = iter([True, True, True])
    session = object.__new__(WizardSession)
    session.callbacks = WizardCallbacks(
        run=lambda _args: None,
        doctor=lambda args: captured.setdefault("args", args),
        validate=lambda _args: None,
        models=lambda _args: None,
        engines=lambda _args: None,
        submit=lambda _args: None,
        upgrade=lambda _args: None,
    )
    session._confirm = lambda *_args, **_kwargs: next(confirmations)
    session._ask_engine = lambda: "omlx"
    session._ask_model = lambda engine: f"{engine}/test-model"
    session._ask_optional_model_url = lambda *_args, **_kwargs: (
        "https://huggingface.co/omlx/test-model"
    )
    session._call_command = lambda callback, args: callback(args)

    session._doctor_flow()

    args = captured["args"]
    assert args.engine == "omlx"
    assert args.model == "omlx/test-model"
    assert args.model_url == "https://huggingface.co/omlx/test-model"
    assert args.publishable is True


def test_wizard_run_flow_catches_cancel_and_returns_to_menu():
    session = object.__new__(WizardSession)
    session.console = FakeConsole()

    def cancel(_config):
        raise WizardAbort

    session._prompt_run_config = cancel

    assert session._run_benchmark_flow() is False
    assert session.console.messages == ["[dim]Benchmark setup cancelled.[/dim]"]


def test_wizard_call_command_catches_nonzero_system_exit():
    session = object.__new__(WizardSession)
    session.console = FakeConsole()

    def fail(_args):
        raise SystemExit(1)

    assert session._call_command(fail, None) is False
    assert session.console.messages == ["[red]Command failed with exit code 1.[/red]"]


def test_wizard_call_command_allows_zero_system_exit():
    session = object.__new__(WizardSession)
    session.console = FakeConsole()

    def ok(_args):
        raise SystemExit(0)

    assert session._call_command(ok, None) is True
    assert session.console.messages == []


def test_wizard_call_command_catches_unexpected_exception():
    session = object.__new__(WizardSession)
    session.console = FakeConsole()

    def fail(_args):
        raise RuntimeError("boom")

    assert session._call_command(fail, None) is False
    assert session.console.messages == ["[red]Command failed:[/red] boom"]
