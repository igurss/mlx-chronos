import time
import subprocess
import shutil
import json
import httpx
import psutil
import warnings
from abc import ABC, abstractmethod


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
        """Measure Time to First Token in seconds."""
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
        return -1.0

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

    def measure_ram_peak(self) -> float:
        """Return the engine process RSS in GB as a proxy for RAM peak."""
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
                return round(rss_bytes / (1024 ** 3), 2)
        except (psutil.Error, OSError):
            pass

        mem = psutil.virtual_memory()
        # Fallback: could not find engine process — warn and return system used memory
        warnings.warn(
            f"Could not locate engine process listening on port {self.port}; returning system used memory as fallback",
            UserWarning,
        )
        used_gb = (mem.total - mem.available) / (1024 ** 3)
        return round(used_gb, 2)

    @abstractmethod
    def is_installed(self) -> bool:
        """Check if this engine is installed on the system."""
        pass

    @abstractmethod
    def run_benchmark(self, model: str) -> dict:
        """Run the full benchmark suite and return a metrics dict."""
        pass


# ─── oMLX ─────────────────────────────────────────────────────────────────────

class OMLXEngine(BaseEngine):
    name = "omlx"
    port = 8000

    # Standard prompts used across all engines for consistency
    COLD_PROMPT = "Explain the concept of unified memory in Apple Silicon in one sentence."
    THROUGHPUT_PROMPT = "Write a detailed explanation of how transformer attention works."

    def is_installed(self) -> bool:
        """Check if omlx CLI is available."""
        return shutil.which("omlx") is not None

    def get_version(self) -> str:
        """Get installed oMLX version."""
        try:
            result = subprocess.run(
                ["omlx", "--help"],
                capture_output=True,
                text=True
            )
            # Version is in the startup banner
            for line in (result.stdout + result.stderr).splitlines():
                if "version" in line.lower() or "0." in line:
                    return line.strip()
            return "0.3.9"  # fallback
        except Exception:
            return "unknown"

    def run_benchmark(self, model: str) -> dict:
        """
        Run the full benchmark suite against oMLX.
        Assumes oMLX server is already running with the specified model.
        """
        if not self.is_server_running():
            raise RuntimeError(
                f"oMLX server not running on port {self.port}. "
                f"Start it with: omlx serve --model-dir ~/models"
            )

        print(f"  Running cold TTFT...")
        ttft_cold = self.measure_ttft(self.COLD_PROMPT, model=model)

        # Warm up to encourage cache population before measuring cached TTFT
        print(f"  Warmup call to populate caches...")
        try:
            _ = self.measure_ttft(self.COLD_PROMPT, model=model)
        except Exception:
            # ignore warmup failures; proceed to cached measurement
            pass

        print(f"  Running cached TTFT...")
        ttft_cached = self.measure_ttft(self.COLD_PROMPT, model=model)  # same prompt = cache hit

        print(f"  Measuring throughput...")
        tps = self.measure_tokens_per_second(self.THROUGHPUT_PROMPT, model=model)

        print(f"  Measuring RAM...")
        ram = self.measure_ram_peak()

        return {
            "ttft_cold": ttft_cold,
            "ttft_cached": ttft_cached,
            "tokens_per_second": tps,
            "tool_calling_rate": None,  # to be implemented
            "ram_peak_gb": ram,
        }


# ─── Registry ─────────────────────────────────────────────────────────────────

ENGINES = {
    "omlx": OMLXEngine,
}


def get_engine(name: str) -> BaseEngine:
    """Return an engine instance by name."""
    if name not in ENGINES:
        raise ValueError(f"Unknown engine: '{name}'. Available: {list(ENGINES.keys())}")
    return ENGINES[name]()


if __name__ == "__main__":
    engine = OMLXEngine()
    print(f"oMLX installed: {engine.is_installed()}")
    print(f"oMLX server running: {engine.is_server_running()}")