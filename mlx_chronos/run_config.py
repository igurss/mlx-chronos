"""Portable run settings; loading a configuration never executes an experiment."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from mlx_chronos import __version__
from mlx_chronos.constants import MAX_REPEATS, MAX_TRIALS, VALID_ENGINE_NAMES
from mlx_chronos.protocol import BASELINE_PROTOCOL_VERSION
from mlx_chronos.reporters import _write_text_atomic


MAX_RUN_CONFIG_BYTES = 1024 * 1024


class RunSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    engine: StrictStr
    model: StrictStr
    quantization: StrictStr
    model_url: StrictStr | None
    profile: Literal["baseline", "sustained"]
    trials: StrictInt = Field(ge=1, le=MAX_TRIALS)
    repeat: StrictInt = Field(ge=1, le=MAX_REPEATS)
    max_tokens: StrictInt = Field(ge=1)
    min_tokens: StrictInt | None = Field(ge=1)
    cooldown_seconds: float = Field(ge=0, allow_inf_nan=False)
    ram_sample_interval: float = Field(gt=0, allow_inf_nan=False)
    connection_mode: Literal["persistent", "per_request"]
    preflight: StrictBool
    publishable: StrictBool
    format: Literal["json", "markdown", "all"]
    engine_opt: list[StrictStr]
    notes: StrictStr | None

    @field_validator("engine")
    @classmethod
    def known_engine(cls, value: str) -> str:
        if value not in VALID_ENGINE_NAMES:
            raise ValueError(f"unsupported engine: {value}")
        return value

    @field_validator("model", "quantization")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("engine_opt")
    @classmethod
    def one_setting_per_line(cls, values: list[str]) -> list[str]:
        if any("\n" in value or "\r" in value for value in values):
            raise ValueError("each declared server setting must fit on one line")
        return values

    @model_validator(mode="after")
    def token_bounds(self):
        if self.min_tokens is not None and self.min_tokens > self.max_tokens:
            raise ValueError("min_tokens must be <= max_tokens")
        return self


class RunConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["mlx-chronos-run-config-v1"]
    benchmark_protocol_version: StrictStr
    chronos_version: StrictStr
    run: RunSettings


def build_run_configuration(settings: RunSettings) -> RunConfiguration:
    return RunConfiguration(
        schema_version="mlx-chronos-run-config-v1",
        benchmark_protocol_version=BASELINE_PROTOCOL_VERSION,
        chronos_version=__version__,
        run=settings,
    )


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate configuration key: {key}")
        result[key] = value
    return result


def load_run_configuration(path: Path) -> RunConfiguration:
    if not path.is_file():
        raise ValueError("configuration must be a regular JSON file")
    with path.open("rb") as handle:
        raw = handle.read(MAX_RUN_CONFIG_BYTES + 1)
    if len(raw) > MAX_RUN_CONFIG_BYTES:
        raise ValueError("configuration exceeds the 1 MB limit")
    try:
        data = json.loads(raw, object_pairs_hook=_unique_json_object)
    except RecursionError as exc:
        raise ValueError("configuration JSON is nested too deeply") from exc
    config = RunConfiguration.model_validate(data)
    if config.benchmark_protocol_version != BASELINE_PROTOCOL_VERSION:
        raise ValueError(
            f"saved benchmark protocol {config.benchmark_protocol_version!r} differs "
            f"from current protocol {BASELINE_PROTOCOL_VERSION!r}; review the settings "
            "and save a new configuration with this CLI"
        )
    return config


def save_run_configuration(path: Path, settings: RunSettings) -> None:
    contents = build_run_configuration(settings).model_dump_json(indent=2) + "\n"
    if len(contents.encode("utf-8")) > MAX_RUN_CONFIG_BYTES:
        raise ValueError("configuration exceeds the 1 MB limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_text_atomic(path, contents)


def form_values(settings: RunSettings) -> dict[str, str]:
    """The app receives CLI-validated settings, not its own interpretation."""
    values = {}
    for key, value in settings.model_dump().items():
        if value is None:
            values[key] = ""
        elif isinstance(value, bool):
            values[key] = "true" if value else "false"
        elif isinstance(value, list):
            values[key] = "\n".join(value)
        else:
            values[key] = str(value)
    return values
