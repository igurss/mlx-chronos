import time
import subprocess
import shutil
import json
import logging
import httpx
import psutil
from abc import ABC, abstractmethod
from pathlib import Path


logger = logging.getLogger("mlx_chronos")


# ─── Base class ───────────────────────────────────────────────────────────────

class BaseEngine(ABC):
    """Abstract base class for all inference engine integrations."""

    name: str
    port: int

    def base_url(self) -> str:
        return f"http://localhost:{self.port}/v1"

    def _request_model_name(self, model: str) -> str:
        """Normalize the model name used in API payloads."""
        return model.strip() or "default"

    def is_server_running(self) -> bool:
        """Check if the engine server is already running on its port."""
        try:
            r = httpx.get(f"{self.base_url()}/models", timeout=2.0)
            return r.status_code == 200
        except Exception:
            return False

    def wait_for_server(self, timeout: int = 60) -> bool:
        """Poll until the server is ready or timeout is reached."""
        start = time.time()
        while time.time() - start < timeout:
            if self.is_server_running():
                return True
            time.sleep(1.0)
        return False

    def measure_ttft(self, prompt: str, model: str = "default") -> float:
        """
        Measure Time to First Token in seconds.
        Raises RuntimeError if no valid token is received from the stream.
        """
        payload = {
            "model": self._request_model_name(model),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1,
            "stream": True,
        }
        start = time.time()
        with httpx.stream("POST", f"{self.base_url()}/chat/completions",
                          json=payload, timeout=30.0) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="ignore")
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    if delta.get("content") or delta.get("tool_calls") or delta.get("role"):
                        return round(time.time() - start, 3)
        raise RuntimeError(
            f"No valid token received from {self.name} stream. "
            f"Check that the model is loaded and responding correctly."
        )

    def measure_tokens_per_second(self, prompt: str, model: str = "default", max_tokens: int = 100) -> float:
        """Measure generation throughput in tokens per second."""
        payload = {
            "model": self._request_model_name(model),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "stream": False,
        }
        start = time.time()
        r = httpx.post(f"{self.base_url()}/chat/completions",
                       json=payload, timeout=60.0)
        r.raise_for_status()
        elapsed = time.time() - start
        if elapsed <= 0:
            return 0.0
        data = r.json()
        tokens = data.get("usage", {}).get("completion_tokens", max_tokens)
        return round(tokens / elapsed, 2)

    def measure_ram_peak(self) -> tuple[float, bool]:
        """
        Return (ram_gb, is_fallback).
        is_fallback=True means system memory was used instead of process RSS.
        """
        try:
            for connection in psutil.net_connections(kind="inet"):
                if not connection.laddr or connection.laddr.port != self.port:
                    continue
                if connection.pid is None:
                    continue
                process = psutil.Process(connection.pid)
                rss_bytes = process.memory_info().rss
                for child in process.children(recursive=True):
                    try:
                        rss_bytes += child.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                return round(rss_bytes / (1024 ** 3), 2), False
        except (psutil.Error, OSError):
            pass

        mem = psutil.virtual_memory()
        used_gb = (mem.total - mem.available) / (1024 ** 3)
        logger.warning(
            f"Could not locate engine process on port {self.port}; "
            f"returning system used memory as fallback."
        )
        return round(used_gb, 2), True

    @abstractmethod
    def is_installed(self) -> bool:
        """Check if this engine is installed on the system."""
        pass

    @abstractmethod
    def get_version(self) -> str:
        """Return the installed engine version string."""
        pass


# ─── oMLX ─────────────────────────────────────────────────────────────────────

class OMLXEngine(BaseEngine):
    name = "omlx"
    port = 8000

    def is_installed(self) -> bool:
        return shutil.which("omlx") is not None

    def get_version(self) -> str:
        """
        Get oMLX version. oMLX does not expose a --version flag or pip metadata.
        Version appears only in the server startup banner (stdout).
        Returns 'unknown' when server is already running.
        """
        try:
            result = subprocess.run(
                ["omlx", "serve", "--help"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            for line in (result.stdout + result.stderr).splitlines():
                if "Version:" in line:
                    return line.split("Version:")[-1].strip()
        except Exception:
            pass
        return "unknown"


# ─── Rapid-MLX ────────────────────────────────────────────────────────────────

class RapidMLXEngine(BaseEngine):
    name = "rapid-mlx"
    port = 8001

    def is_installed(self) -> bool:
        return shutil.which("rapid-mlx") is not None

    def get_version(self) -> str:
        try:
            result = subprocess.run(
                ["rapid-mlx", "version"],
                capture_output=True,
                text=True
            )
            return result.stdout.strip() or "unknown"
        except Exception:
            return "unknown"


# ─── Registry ─────────────────────────────────────────────────────────────────

ENGINES = {
    "omlx": OMLXEngine,
    "rapid-mlx": RapidMLXEngine,
}


def get_engine(name: str) -> BaseEngine:
    """Return an engine instance by name."""
    if name not in ENGINES:
        raise ValueError(
            f"Unknown engine: '{name}'. Available: {list(ENGINES.keys())}"
        )
    return ENGINES[name]()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for name, cls in ENGINES.items():
        engine = cls()
        installed = engine.is_installed()
        running = engine.is_server_running() if installed else False
        status = "running" if running else ("installed" if installed else "not installed")
        logger.info(f"{name:<15} {status}")