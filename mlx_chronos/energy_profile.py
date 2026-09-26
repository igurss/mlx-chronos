"""Local macmon system-power diagnostic; never a public benchmark result.

The no-request window is separate from throughput. macmon's sys_power is an
SMC reading sampled at discrete times; clipped trapezoids are estimates, not
calibrated wall-plug energy or energy attributable to one model.
"""

from __future__ import annotations

import json
import math
import secrets
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

from mlx_chronos import __version__ as VERSION
from mlx_chronos.detect import detect_hardware, get_thermal_state
from mlx_chronos.engines import get_engine
from mlx_chronos.model_reference import normalize_model_reference_url
from mlx_chronos.measurements import ThroughputMeasurement
from mlx_chronos.protocol import THROUGHPUT_PROMPTS
from mlx_chronos.reporters import _write_text_atomic
from mlx_chronos.schema import normalize_model_quantization

ENERGY_PROFILE_VERSION = "1"
DEFAULT_SAMPLE_INTERVAL_MS = 500
DEFAULT_SETTLE_SECONDS = 5.0
DEFAULT_IDLE_SECONDS = 5.0
DEFAULT_ENERGY_TRIALS = 3
DEFAULT_ENERGY_MAX_TOKENS = 100
MAX_ENERGY_TRIALS = len(THROUGHPUT_PROMPTS)


def _now() -> float:
    return time.monotonic()


def _pause(seconds: float) -> None:
    time.sleep(seconds)


def _memory_snapshot() -> dict:
    snapshot: dict[str, float | None] = {"available_gb": None, "swap_used_gb": None}
    try:
        snapshot["available_gb"] = round(psutil.virtual_memory().available / 1024**3, 3)
    except Exception:
        pass
    try:
        snapshot["swap_used_gb"] = round(psutil.swap_memory().used / 1024**3, 3)
    except Exception:
        pass
    return snapshot


class MacmonPowerSampler:
    """One long-lived macmon process, with receive-time monotonic timestamps."""

    def __init__(self, interval_ms: int = DEFAULT_SAMPLE_INTERVAL_MS):
        if (isinstance(interval_ms, bool) or not isinstance(interval_ms, int)
                or not 100 <= interval_ms <= 1000):
            raise ValueError("sample interval must be an integer between 100 and 1000 ms")
        self.interval_ms = interval_ms
        self._process: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self._condition = threading.Condition()
        self._samples: list[tuple[float, float, str]] = []
        self.invalid_samples = 0

    def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("macmon sampler is already running")
        executable = shutil.which("macmon")
        if executable is None:
            raise RuntimeError("macmon is not installed or is not on PATH")
        self._process = subprocess.Popen(
            [executable, "pipe", "-s", "0", "-i", str(self.interval_ms)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            received_at = time.monotonic()
            try:
                item = json.loads(line)
                watts = item["sys_power"]
                component_watts = item["all_power"]
                timestamp = item["timestamp"]
                if (
                    isinstance(watts, bool)
                    or not isinstance(watts, (int, float))
                    or not math.isfinite(watts)
                    or watts <= 0
                    or isinstance(component_watts, bool)
                    or not isinstance(component_watts, (int, float))
                    or not math.isfinite(component_watts)
                    or component_watts < 0
                    # macmon can floor sys_power at all_power if the SMC value
                    # is lower; an equal value has ambiguous provenance.
                    or watts <= component_watts
                    or not isinstance(timestamp, str)
                ):
                    raise ValueError("invalid power or timestamp")
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise ValueError("timestamp has no timezone")
            except (ValueError, TypeError, KeyError, AttributeError):
                with self._condition:
                    self.invalid_samples += 1
                    self._condition.notify_all()
                continue
            with self._condition:
                self._samples.append((received_at, float(watts), timestamp))
                self._condition.notify_all()
        with self._condition:
            self._condition.notify_all()

    def wait_for_sample_after(self, after: float, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        with self._condition:
            while not self._samples or self._samples[-1][0] <= after:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("macmon did not produce a valid power sample in time")
                if self._process is not None and self._process.poll() is not None:
                    raise RuntimeError("macmon exited before providing enough samples")
                self._condition.wait(timeout=min(remaining, 0.2))

    def samples(self) -> list[tuple[float, float, str]]:
        with self._condition:
            return list(self._samples)

    def stop(self) -> None:
        process = self._process
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        if self._thread is not None:
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                raise RuntimeError("macmon reader thread did not stop")
        if process is not None and process.stdout is not None:
            process.stdout.close()
        self._process = None
        self._thread = None


def integrate_power_window(
    samples: list[tuple[float, float, str]],
    start: float,
    end: float,
    *,
    interval_ms: int,
) -> dict:
    """Integrate only a fully bracketed window; never extrapolate missing edges."""
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise ValueError("power window must have finite, increasing bounds")
    if len(samples) < 2 or samples[0][0] > start or samples[-1][0] < end:
        raise RuntimeError("power samples do not cover the entire phase")
    energy = 0.0
    contributing = 0
    largest_gap = 0.0
    max_allowed_gap = max(1.0, 2.5 * interval_ms / 1000)
    for (t0, p0, _), (t1, p1, _) in zip(samples, samples[1:]):
        if not all(math.isfinite(v) for v in (t0, t1, p0, p1)) or min(p0, p1) < 0:
            raise RuntimeError("power samples contain non-finite or negative values")
        delta = t1 - t0
        if delta <= 0:
            raise RuntimeError("power sample timestamps are not increasing")
        left, right = max(start, t0), min(end, t1)
        if right <= left:
            continue
        largest_gap = max(largest_gap, delta)
        if delta > max_allowed_gap:
            raise RuntimeError("power sampling gap is too large for this phase")
        left_power = p0 + (p1 - p0) * (left - t0) / delta
        right_power = p0 + (p1 - p0) * (right - t0) / delta
        energy += (left_power + right_power) * (right - left) / 2
        if not math.isfinite(energy):
            raise RuntimeError("integrated energy is not finite")
        contributing += 1
    if contributing < 2:
        raise RuntimeError("too few power intervals cover this phase")
    return {
        "duration_seconds": round(end - start, 3),
        "estimated_system_energy_joules": round(energy, 4),
        "estimated_mean_system_power_watts": round(energy / (end - start), 4),
        "contributing_intervals": contributing,
        "largest_interval_seconds": round(largest_gap, 3),
        "coverage": "full_bracketed_window",
    }


def _macmon_version() -> str:
    try:
        completed = subprocess.run(
            ["macmon", "--version"], capture_output=True, text=True, timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def _validate_measurement(measurement: ThroughputMeasurement) -> None:
    if (
        not isinstance(measurement, ThroughputMeasurement)
        or isinstance(measurement.completion_tokens, bool)
        or not isinstance(measurement.completion_tokens, int)
        or measurement.completion_tokens <= 0
        or isinstance(measurement.request_tokens_per_second, bool)
        or not isinstance(measurement.request_tokens_per_second, (int, float))
        or not math.isfinite(measurement.request_tokens_per_second)
        or measurement.request_tokens_per_second <= 0
        or isinstance(measurement.elapsed_seconds, bool)
        or not isinstance(measurement.elapsed_seconds, (int, float))
        or not math.isfinite(measurement.elapsed_seconds)
        or measurement.elapsed_seconds <= 0
        or not isinstance(measurement.token_count_source, str)
        or not measurement.token_count_source
    ):
        raise RuntimeError("engine returned an invalid throughput measurement")


def run_energy_profile(
    engine_name: str,
    model_name: str,
    *,
    model_quantization: str | None = None,
    model_reference_url: str | None = None,
    trials: int = DEFAULT_ENERGY_TRIALS,
    max_tokens: int = DEFAULT_ENERGY_MAX_TOKENS,
    settle_seconds: float = DEFAULT_SETTLE_SECONDS,
    idle_seconds: float = DEFAULT_IDLE_SECONDS,
    interval_ms: int = DEFAULT_SAMPLE_INTERVAL_MS,
) -> dict:
    sampler = MacmonPowerSampler(interval_ms)
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("model name must not be empty")
    if isinstance(trials, bool) or not isinstance(trials, int) or not 1 <= trials <= MAX_ENERGY_TRIALS:
        raise ValueError(f"trials must be between 1 and {MAX_ENERGY_TRIALS}")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
        raise ValueError("max_tokens must be a positive integer")
    if (isinstance(settle_seconds, bool) or not isinstance(settle_seconds, (int, float))
            or not math.isfinite(settle_seconds) or settle_seconds < 0):
        raise ValueError("settle_seconds must be finite and non-negative")
    minimum_phase_seconds = max(5.0, 8 * interval_ms / 1000)
    if (isinstance(idle_seconds, bool) or not isinstance(idle_seconds, (int, float))
            or not math.isfinite(idle_seconds) or idle_seconds < minimum_phase_seconds):
        raise ValueError("idle_seconds is too short for reliable power sampling")
    if shutil.which("macmon") is None:
        raise RuntimeError("macmon is not installed or is not on PATH")
    model_name = model_name.strip()
    model_reference_url = normalize_model_reference_url(model_reference_url)
    if model_quantization is not None:
        model_quantization = normalize_model_quantization(model_quantization)

    engine = get_engine(engine_name)
    if not engine.is_installed():
        raise RuntimeError(f"Engine '{engine_name}' is not installed")
    if not engine.is_server_running():
        raise RuntimeError(f"Engine '{engine_name}' server is not running")
    backend = engine.validate_model_backend(model_name)
    if not isinstance(backend, dict):
        backend = {}
    reported_quantization = backend.get("quantization")
    if reported_quantization:
        reported = normalize_model_quantization(reported_quantization)
        if model_quantization is not None and model_quantization != reported:
            raise RuntimeError("declared quantization differs from engine metadata")
        model_quantization = reported
    engine.validate_completion_request(model_name)
    hardware = detect_hardware()
    memory_before = _memory_snapshot()
    nonce = secrets.token_hex(8)
    measurements = []
    power_samples: list[tuple[float, float, str]] = []
    thermal_before = get_thermal_state()
    with engine.http_client() as client:
        warmup = engine.measure_throughput(
            f"Energy diagnostic warm-up {nonce}. {THROUGHPUT_PROMPTS[0]}",
            model=model_name, max_tokens=min(max_tokens, 16), client=client,
        )
        _validate_measurement(warmup)
        started = _now()
        try:
            sampler.start()
            sampler.wait_for_sample_after(started)
            _pause(settle_seconds)
            idle_start = _now()
            _pause(idle_seconds)
            idle_end = _now()
            active_start = _now()
            for index in range(trials):
                measurement = engine.measure_throughput(
                    f"Energy diagnostic {nonce}-{index:03d}. {THROUGHPUT_PROMPTS[index]}",
                    model=model_name, max_tokens=max_tokens, client=client,
                )
                _validate_measurement(measurement)
                measurements.append(measurement)
            active_end = _now()
            sampler.wait_for_sample_after(active_end)
            power_samples = sampler.samples()
        finally:
            sampler.stop()
    thermal_after = get_thermal_state()
    memory_after = _memory_snapshot()
    if active_end - active_start < minimum_phase_seconds:
        raise RuntimeError("throughput window was too short for a credible power estimate")
    idle = integrate_power_window(
        power_samples, idle_start, idle_end, interval_ms=interval_ms,
    )
    active = integrate_power_window(
        power_samples, active_start, active_end, interval_ms=interval_ms,
    )
    return {
        "kind": "local_energy_diagnostic",
        "version": ENERGY_PROFILE_VERSION,
        "chronos_version": VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hardware": hardware,
        "engine": {"name": engine_name, "version": engine.get_version()},
        "model": {
            "name": model_name, "quantization": model_quantization,
            "reference_url": model_reference_url, "format": backend.get("format"),
        },
        "protocol": {
            "name": "separate_no_request_and_throughput_energy",
            "sample_interval_ms": interval_ms,
            "settle_seconds": settle_seconds,
            "idle_seconds": idle_seconds,
            "trials": trials,
            "max_tokens": max_tokens,
            "prompt_strategy": "early_run_nonce_and_unique_trial_number",
        },
        "power_source": "macmon_sys_power_smc",
        "macmon_version": _macmon_version(),
        "pre_throughput_no_request": idle,
        "throughput": {
            **active,
            "completion_tokens": [m.completion_tokens for m in measurements],
            "token_count_sources": [m.token_count_source for m in measurements],
            "request_tokens_per_second": [
                m.request_tokens_per_second for m in measurements
            ],
        },
        "sampling": {
            "valid_samples": len(power_samples),
            "invalid_samples": sampler.invalid_samples,
            "first_sensor_timestamp": power_samples[0][2],
            "last_sensor_timestamp": power_samples[-1][2],
            "power_trace": [
                {
                    "offset_from_idle_start_seconds": round(received - idle_start, 4),
                    "system_power_watts": watts,
                    "sensor_timestamp": timestamp,
                }
                for received, watts, timestamp in power_samples
            ],
            "phase_boundaries_from_idle_start_seconds": {
                "no_request": [0.0, round(idle_end - idle_start, 4)],
                "throughput": [
                    round(active_start - idle_start, 4),
                    round(active_end - idle_start, 4),
                ],
            },
        },
        "memory_before_warmup": memory_before,
        "memory_after_measurement": memory_after,
        "thermal_state_before": thermal_before,
        "thermal_state_after": thermal_after,
        "warning": (
            "Estimated macmon-reported system energy only; no model-only "
            "attribution, idle subtraction, calibrated wall-plug accuracy or "
            "leaderboard ranking. Samples near phase boundaries are approximate."
        ),
    }


def save_energy_report(report: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    path = output_dir / f"energy_{timestamp}_{secrets.token_hex(4)}.json"
    _write_text_atomic(
        path, json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
    )
    return path
