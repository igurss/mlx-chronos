import time
import subprocess
import shutil
import json
import logging
import os
import importlib.metadata
import importlib.util
import httpx
import psutil
from abc import ABC, abstractmethod

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

    def _connection_port(self, connection) -> int | None:
        """Return a psutil connection local port across tuple/namedtuple variants."""
        if not connection.laddr:
            return None
        port = getattr(connection.laddr, "port", None)
        if port is None and isinstance(connection.laddr, tuple):
            port = connection.laddr[1] if len(connection.laddr) > 1 else None
        return port

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

    def get_server_pid(self) -> int | None:
        """Return the PID of the engine server bound to this port, if available."""
        try:
            for connection in psutil.net_connections(kind="inet"):
                if self._connection_port(connection) != self.port:
                    continue
                if connection.pid is None:
                    continue
                return connection.pid
        except (psutil.Error, OSError):
            return None
        return None

    def _stream_chunk_has_content(self, chunk: dict) -> bool:
        """Return True only when a streamed chat chunk contains generated text."""
        choices = chunk.get("choices", [])
        if not choices:
            return False

        delta = choices[0].get("delta", {})
        content = delta.get("content")
        return isinstance(content, str) and content != ""

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
                if self._stream_chunk_has_content(chunk):
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
                if self._connection_port(connection) != self.port:
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

    def _resolve_model_id(self, model: str) -> str | None:
        cache = getattr(self, "_model_id_cache", None)
        if cache is None:
            cache = {}
            self._model_id_cache = cache

        if model in cache:
            return cache[model]

        try:
            r = httpx.get(f"{self.base_url()}/models", timeout=3.0)
            r.raise_for_status()
            data = r.json()
            for item in data.get("data", []):
                model_id = item.get("id")
                if not model_id:
                    continue
                if model_id == model or model_id.endswith(f"/{model}"):
                    cache[model] = model_id
                    return model_id
        except Exception:
            return None
        return None

    def _request_model_name(self, model: str) -> str:
        model_name = super()._request_model_name(model)
        model_name = os.path.expanduser(model_name)
        if "/" in model_name:
            return model_name

        resolved = self._resolve_model_id(model_name)
        return resolved or model_name

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


# ─── mlx-lm ───────────────────────────────────────────────────────────────────

class MLXLMEngine(BaseEngine):
    name = "mlx-lm"
    port = 8002

    def is_installed(self) -> bool:
        return importlib.util.find_spec("mlx_lm") is not None

    def get_version(self) -> str:
        try:
            return importlib.metadata.version("mlx-lm")
        except Exception:
            return "unknown"


# ─── Ollama ───────────────────────────────────────────────────────────────────

class OllamaEngine(BaseEngine):
    name = "ollama"
    port = 11434

    def is_installed(self) -> bool:
        return shutil.which("ollama") is not None

    def get_version(self) -> str:
        try:
            result = subprocess.run(
                ["ollama", "--version"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            return result.stdout.strip() or "unknown"
        except Exception:
            return "unknown"


# ─── Registry ─────────────────────────────────────────────────────────────────

ENGINES = {
    "omlx": OMLXEngine,
    "rapid-mlx": RapidMLXEngine,
    "mlx-lm": MLXLMEngine,
    "ollama": OllamaEngine,
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
