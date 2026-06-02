import os
import threading
import time

import psutil


class RAMTracker:
    """
    Continuously samples the RAM (RSS) of the target process in a separate thread.
    Solves the issue of missing a memory peak between the start and end of inference.
    """

    def __init__(self, interval: float = 0.05, target_pid: int = None):
        self.pid = target_pid or os.getpid()
        self.interval = interval
        self._process = psutil.Process(self.pid)
        self.peak_ram_bytes = 0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None

    def _sample_rss(self) -> int:
        rss_bytes = self._process.memory_info().rss
        try:
            for child in self._process.children(recursive=True):
                try:
                    rss_bytes += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
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

    def __init__(self, interval: float = 0.05):
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

