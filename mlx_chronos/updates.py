"""Best-effort update checks for the mlx-chronos CLI."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mlx_chronos import __version__ as VERSION


PROJECT_NAME = "mlx-chronos"
PYPI_JSON_URL = f"https://pypi.org/pypi/{PROJECT_NAME}/json"
DEFAULT_UPDATE_CHECK_TIMEOUT = 1.5
DISABLE_UPDATE_CHECK_ENV = "MLX_CHRONOS_DISABLE_UPDATE_CHECK"

_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}
_NUMERIC_VERSION_PREFIX_RE = re.compile(r"^\s*v?(\d+(?:\.\d+)*)")


@dataclass(frozen=True)
class UpdateCheckResult:
    """Result of checking the installed version against PyPI."""

    current_version: str
    latest_version: str | None
    update_available: bool
    error: str | None = None


class UpdateCheckError(RuntimeError):
    """Raised when the latest release cannot be discovered."""


def update_check_disabled(environ: dict[str, str] | None = None) -> bool:
    """Return whether automatic update checks are disabled by the environment."""
    values = os.environ if environ is None else environ
    return (
        values.get(DISABLE_UPDATE_CHECK_ENV, "").strip().lower()
        in _TRUTHY_ENV_VALUES
    )


def _release_tuple(version: str) -> tuple[int, ...] | None:
    match = _NUMERIC_VERSION_PREFIX_RE.match(version)
    if match is None:
        return None
    try:
        return tuple(int(part) for part in match.group(1).split("."))
    except ValueError:
        return None


def is_newer_version(latest_version: str, current_version: str) -> bool:
    """Compare standard release versions without adding a packaging dependency."""
    latest = _release_tuple(latest_version)
    current = _release_tuple(current_version)
    if latest is None or current is None:
        return False

    width = max(len(latest), len(current))
    latest_padded = latest + (0,) * (width - len(latest))
    current_padded = current + (0,) * (width - len(current))
    return latest_padded > current_padded


def fetch_latest_version(
    *,
    timeout: float = DEFAULT_UPDATE_CHECK_TIMEOUT,
    url: str = PYPI_JSON_URL,
) -> str:
    """Fetch the latest published version from PyPI's JSON API."""
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": f"{PROJECT_NAME}/{VERSION}",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise UpdateCheckError(str(exc)) from exc

    info = payload.get("info") if isinstance(payload, dict) else None
    version = info.get("version") if isinstance(info, dict) else None
    if not isinstance(version, str) or not version.strip():
        raise UpdateCheckError("PyPI response did not include info.version")
    return version.strip()


def check_for_update(
    *,
    current_version: str = VERSION,
    timeout: float = DEFAULT_UPDATE_CHECK_TIMEOUT,
    url: str = PYPI_JSON_URL,
) -> UpdateCheckResult:
    """Return update availability, converting transient failures into a result."""
    try:
        latest_version = fetch_latest_version(timeout=timeout, url=url)
    except Exception as exc:
        return UpdateCheckResult(
            current_version=current_version,
            latest_version=None,
            update_available=False,
            error=str(exc),
        )

    return UpdateCheckResult(
        current_version=current_version,
        latest_version=latest_version,
        update_available=is_newer_version(latest_version, current_version),
        error=None,
    )


def _emit_update_notification(result: UpdateCheckResult, stream) -> None:
    if not result.update_available or result.latest_version is None:
        return
    try:
        print(
            f"Update available: {PROJECT_NAME} {result.latest_version} is available "
            f"(installed {result.current_version}). Run `{PROJECT_NAME} upgrade` "
            "to update.",
            file=stream,
        )
    except Exception:
        return


def start_background_update_check(
    *,
    current_version: str = VERSION,
    timeout: float = DEFAULT_UPDATE_CHECK_TIMEOUT,
    stream=None,
) -> threading.Thread:
    """Start a non-blocking update check and notify only when an update exists."""
    output = sys.stderr if stream is None else stream

    def worker() -> None:
        result = check_for_update(current_version=current_version, timeout=timeout)
        _emit_update_notification(result, output)

    thread = threading.Thread(target=worker, name="mlx-chronos-update-check", daemon=True)
    thread.start()
    return thread
