import os
import threading
import time

import psutil

from mlx_chronos.constants import DEFAULT_RAM_SAMPLE_INTERVAL
from mlx_chronos.detect import get_thermal_state_from_foundation


THERMAL_STATE_ORDER = {
    "nominal": 0,
    "fair": 1,
    "serious": 2,
    "critical": 3,
}


def _is_non_nominal_thermal_state(state: str) -> bool:
    return not state.startswith("unavailable") and state != "nominal"


class RAMTracker:
    """
    Continuously samples the RAM (RSS) of the target process in a separate thread.
    Solves the issue of missing a memory peak between the start and end of inference.
    """

    def __init__(
        self,
        interval: float = DEFAULT_RAM_SAMPLE_INTERVAL,
        target_pid: int | None = None,
    ):
        self.pid = target_pid or os.getpid()
        self.interval = interval
        self._process = psutil.Process(self.pid)
        self._child_processes: list[psutil.Process] = []
        self._children_refreshed = False
        self.peak_ram_bytes = 0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None

    def _refresh_child_processes(self) -> None:
        try:
            self._child_processes = self._process.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self._child_processes = []
        self._children_refreshed = True

    def _sample_rss(self) -> int:
        rss_bytes = self._process.memory_info().rss
        if not self._children_refreshed:
            self._refresh_child_processes()
        for child in self._child_processes:
            try:
                rss_bytes += child.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return rss_bytes

    def _monitor(self):
        while not self._stop_event.is_set():
            try:
                current_ram = self._sample_rss()
                with self._lock:
                    if current_ram > self.peak_ram_bytes:
                        self.peak_ram_bytes = current_ram
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                try:
                    is_running = self._process.is_running()
                except psutil.Error:
                    break
                if not is_running:
                    break
                time.sleep(self.interval)
                continue
            time.sleep(self.interval)

    def start(self):
        """Run the sampling."""
        self._refresh_child_processes()
        self.peak_ram_bytes = self._sample_rss()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()

    def stop(self) -> float:
        """Stop sampling and return the peak RAM in GB."""
        self._stop_event.set()
        if self._thread:
            self._thread.join()

        with self._lock:
            peak = self.peak_ram_bytes
        return peak / (1024 ** 3)


class SystemRAMTracker:
    """Continuously samples total system RAM usage during the benchmark."""

    def __init__(self, interval: float = DEFAULT_RAM_SAMPLE_INTERVAL):
        self.interval = interval
        self.peak_used_bytes = 0
        self.peak_percent = 0.0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None

    def _sample_system_ram(self) -> tuple[int, float]:
        mem = psutil.virtual_memory()
        used_bytes = max(0, mem.total - mem.available)
        percent = (used_bytes / mem.total * 100) if mem.total else 0.0
        return used_bytes, percent

    def _monitor(self):
        while not self._stop_event.is_set():
            used_bytes, percent = self._sample_system_ram()
            with self._lock:
                if used_bytes > self.peak_used_bytes:
                    self.peak_used_bytes = used_bytes
                    self.peak_percent = percent
            time.sleep(self.interval)

    def start(self):
        self.peak_used_bytes, self.peak_percent = self._sample_system_ram()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()

    def stop(self) -> tuple[float, float]:
        self._stop_event.set()
        if self._thread:
            self._thread.join()
        with self._lock:
            peak_used = self.peak_used_bytes
            peak_pct = self.peak_percent
        return peak_used / (1024 ** 3), peak_pct


class ThermalStateTracker:
    """
    Continuously samples macOS thermal state using the Foundation path.

    The tracker intentionally does not loop over powermetrics because that would
    add avoidable subprocess overhead during the benchmark itself.
    """

    def __init__(self, interval: float = 1.0, sampler=None):
        self.interval = interval
        self.sampler = sampler or get_thermal_state_from_foundation
        self._phase = "setup"
        self._samples: list[tuple[str, str]] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None

    def _sample_thermal_state(self) -> str:
        state = self.sampler()
        if isinstance(state, str) and state.strip():
            return state.strip()
        return "unavailable_foundation"

    def _record_sample(self):
        state = self._sample_thermal_state()
        with self._lock:
            self._samples.append((self._phase, state))

    def _monitor(self):
        while not self._stop_event.wait(self.interval):
            self._record_sample()

    def set_phase(self, phase: str) -> None:
        with self._lock:
            self._phase = phase

    def start(self):
        self._samples = []
        self._stop_event.clear()
        self._record_sample()
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()

    def stop(self) -> dict:
        self._stop_event.set()
        if self._thread:
            self._thread.join()
        self._record_sample()

        with self._lock:
            samples = list(self._samples)

        states = [state for _phase, state in samples]
        start_state = states[0] if states else "unavailable_foundation"
        end_state = states[-1] if states else "unavailable_foundation"
        observed_known_states = [
            state for state in states if state in THERMAL_STATE_ORDER
        ]
        if observed_known_states:
            worst_state = max(
                observed_known_states,
                key=lambda state: THERMAL_STATE_ORDER[state],
            )
            source = "foundation"
        else:
            worst_state = start_state
            source = "unavailable"

        non_nominal_phases = sorted(
            {
                phase
                for phase, state in samples
                if _is_non_nominal_thermal_state(state)
            }
        )
        return {
            "sample_interval_seconds": self.interval,
            "source": source,
            "start_state": start_state,
            "end_state": end_state,
            "worst_state": worst_state,
            "samples": len(samples),
            "changed_during_run": len(set(states)) > 1,
            "non_nominal_observed": any(
                _is_non_nominal_thermal_state(state) for state in states
            ),
            "non_nominal_phases": non_nominal_phases,
        }
