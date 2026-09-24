import os
import threading
import time

import psutil

from mlx_chronos.constants import DEFAULT_RAM_SAMPLE_INTERVAL, THERMAL_STATE_ORDER
from mlx_chronos.detect import get_thermal_state_from_foundation
from mlx_chronos.numeric import require_finite_positive

DEFAULT_CHILD_PROCESS_REFRESH_INTERVAL = 30.0


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
        child_refresh_interval: float | None = DEFAULT_CHILD_PROCESS_REFRESH_INTERVAL,
    ):
        require_finite_positive(interval, name="interval")
        self.pid = target_pid if target_pid is not None else os.getpid()
        self.interval = interval
        if child_refresh_interval is not None:
            require_finite_positive(
                child_refresh_interval,
                name="child_refresh_interval",
            )
        self.child_refresh_interval = child_refresh_interval
        self._process = psutil.Process(self.pid)
        self._child_processes: list[psutil.Process] = []
        self._children_refreshed = False
        self._last_child_refresh_at = 0.0
        self.peak_ram_bytes = 0
        self.sample_count = 0
        self.sample_errors = 0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _refresh_child_processes(self) -> None:
        try:
            self._child_processes = self._process.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self._child_processes = []
        self._children_refreshed = True
        self._last_child_refresh_at = time.monotonic()

    def _should_refresh_child_processes(self) -> bool:
        if not self._children_refreshed:
            return True
        if self.child_refresh_interval is None:
            return False
        return (
            time.monotonic() - self._last_child_refresh_at
            >= self.child_refresh_interval
        )

    def _sample_rss(self) -> int:
        rss_bytes = self._process.memory_info().rss
        if self._should_refresh_child_processes():
            self._refresh_child_processes()
        for child in self._child_processes:
            try:
                rss_bytes += child.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        with self._lock:
            self.sample_count += 1
        return rss_bytes

    def _monitor(self):
        while not self._stop_event.wait(self.interval):
            try:
                current_ram = self._sample_rss()
                with self._lock:
                    if current_ram > self.peak_ram_bytes:
                        self.peak_ram_bytes = current_ram
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                with self._lock:
                    self.sample_errors += 1
                try:
                    is_running = self._process.is_running()
                except psutil.Error:
                    break
                if not is_running:
                    break
                continue

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
    """Continuously samples total system RAM usage during the benchmark.

    Peak occupancy answers "how close to the wall did this Mac get", which is a
    property of the whole machine and is exactly what a device-stress metric
    should report. It is not an engine-specific metric. The first sample is
    recorded so the whole-system rise can be inspected, but activity by other
    processes and preloaded models limit its comparability.

    System-wide swap growth is tracked alongside it as a warning sign, without
    claiming the benchmark caused it or that timings were necessarily affected.
    """

    def __init__(self, interval: float = DEFAULT_RAM_SAMPLE_INTERVAL):
        require_finite_positive(interval, name="interval")
        self.interval = interval
        self.total_bytes = 0
        self.baseline_used_bytes: int | None = None
        self.peak_used_bytes = 0
        self.peak_percent = 0.0
        self.baseline_swap_used_bytes: int | None = None
        self.peak_swap_used_bytes = 0
        self.sample_count = 0
        self.sample_errors = 0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample_system_ram(self) -> tuple[int, float, int]:
        mem = psutil.virtual_memory()
        used_bytes = max(0, mem.total - mem.available)
        percent = (used_bytes / mem.total * 100) if mem.total else 0.0
        return used_bytes, percent, mem.total

    def _sample_swap_used(self) -> int | None:
        """Return swap bytes in use, or None where the platform cannot report it."""
        try:
            return max(0, int(psutil.swap_memory().used))
        except Exception:
            return None

    def _record_sample(self) -> None:
        used_bytes, percent, total_bytes = self._sample_system_ram()
        swap_used_bytes = self._sample_swap_used()
        with self._lock:
            self.sample_count += 1
            self.total_bytes = total_bytes
            if self.baseline_used_bytes is None:
                self.baseline_used_bytes = used_bytes
            if used_bytes > self.peak_used_bytes:
                self.peak_used_bytes = used_bytes
                self.peak_percent = percent
            if swap_used_bytes is not None:
                if self.baseline_swap_used_bytes is None:
                    self.baseline_swap_used_bytes = swap_used_bytes
                if swap_used_bytes > self.peak_swap_used_bytes:
                    self.peak_swap_used_bytes = swap_used_bytes

    def _monitor(self):
        while not self._stop_event.wait(self.interval):
            try:
                self._record_sample()
            except Exception:
                with self._lock:
                    self.sample_errors += 1

    def start(self):
        try:
            self._record_sample()
        except Exception:
            with self._lock:
                self.sample_errors += 1
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()

    def stop(self) -> tuple[float, float]:
        self._stop_event.set()
        if self._thread:
            self._thread.join()
        with self._lock:
            if self.sample_count == 0:
                raise RuntimeError("system RAM monitor collected no valid samples")
            peak_used = self.peak_used_bytes
            peak_pct = self.peak_percent
        return peak_used / (1024 ** 3), peak_pct

    def occupancy_summary(self) -> dict[str, float | None]:
        """Return baseline, whole-system rise and swap growth, in GiB.

        Safe to call after stop(); values are None when the tracker never
        collected a usable sample for that quantity.
        """
        with self._lock:
            baseline_used = self.baseline_used_bytes
            peak_used = self.peak_used_bytes
            baseline_swap = self.baseline_swap_used_bytes
            peak_swap = self.peak_swap_used_bytes

        gibibyte = 1024 ** 3
        baseline_gb = None if baseline_used is None else baseline_used / gibibyte
        delta_gb = (
            None
            if baseline_used is None
            else max(0.0, (peak_used - baseline_used) / gibibyte)
        )
        swap_growth_gb = (
            None
            if baseline_swap is None
            else max(0.0, (peak_swap - baseline_swap) / gibibyte)
        )
        return {
            "system_ram_baseline_gb": baseline_gb,
            "system_ram_delta_gb": delta_gb,
            "swap_growth_gb": swap_growth_gb,
        }


class ThermalStateTracker:
    """
    Continuously samples macOS thermal state using the Foundation path.

    The tracker intentionally does not loop over powermetrics because that would
    add avoidable subprocess overhead during the benchmark itself.
    """

    def __init__(self, interval: float = 1.0, sampler=None):
        require_finite_positive(interval, name="interval")
        self.interval = interval
        self.sampler = sampler or get_thermal_state_from_foundation
        self._phase = "setup"
        self._samples: list[tuple[str, str]] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.sample_errors = 0

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
            try:
                self._record_sample()
            except Exception:
                with self._lock:
                    self.sample_errors += 1

    def set_phase(self, phase: str) -> None:
        with self._lock:
            self._phase = phase

    def start(self):
        with self._lock:
            self._samples = []
        self._stop_event.clear()
        try:
            self._record_sample()
        except Exception:
            with self._lock:
                self.sample_errors += 1
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()

    def stop(self) -> dict:
        self._stop_event.set()
        if self._thread:
            self._thread.join()
        try:
            self._record_sample()
        except Exception:
            with self._lock:
                self.sample_errors += 1

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
            "sampling_errors": self.sample_errors,
        }
