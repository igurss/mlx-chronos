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
    """Abstract base class for inference engine integrations."""

    name: str
    port: int

    def base_url(self) -> str:
        return f"http://localhost:{self.port}/v1"

    def endpoint(self) -> str:
        """API endpoint used by the engine."""
        return "/chat/completions"

    def uses_chat_api(self) -> bool:
        """Whether the engine uses OpenAI chat format."""
        return True

    def build_payload(self, prompt: str, model: str, max_tokens: int, stream: bool) -> dict:
        payload = {
            "model": self._request_model_name(model),
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if self.uses_chat_api():
            payload["messages"] = [{"role": "user", "content": prompt}]
        else:
            payload["prompt"] = prompt
        return payload

    def _request_model_name(self, model: str) -> str:
        return model.strip() or "default"

    def is_server_running(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url()}/models", timeout=2.0)
            return r.status_code == 200
        except Exception:
            return False

    def wait_for_server(self, timeout: int = 60) -> bool:
        start = time.perf_counter()
        while time.perf_counter() - start < timeout:
            if self.is_server_running():
                return True
            time.sleep(1.0)
        return False

    def get_server_pid(self) -> int | None:
        """macOS-safe PID lookup using lsof."""
        try:
            result = subprocess.run(
                ["lsof", "-t", f"-i:{self.port}"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            pids = result.stdout.strip().split()
            if pids:
                return int(pids[0])
        except Exception:
            pass
        return None

    def _stream_chunk_has_content(self, chunk: dict) -> bool:
        choices = chunk.get("choices")
        if not choices:  # Corretto: gestisce sia None che lista vuota senza crash
            return False

        choice = choices[0]
        delta = choice.get("delta", {})

        for key in ("content", "reasoning", "reasoning_content"):
            value = delta.get(key)
            if isinstance(value, str) and value.strip():
                return True

        if delta.get("tool_calls"):
            return True

        text = choice.get("text")
        if isinstance(text, str) and text.strip():
            return True

        return False

    def measure_ttft(self, prompt: str, model: str = "default") -> float:
        """Measure Time To First Token."""
        payload = self.build_payload(prompt=prompt, model=model, max_tokens=1, stream=True)
        start = time.perf_counter()

        with httpx.stream(
            "POST", f"{self.base_url()}{self.endpoint()}", json=payload, timeout=30.0
        ) as r:
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
                    return round(time.perf_counter() - start, 3)

        raise RuntimeError(f"No valid token received from {self.name} stream.")

    def measure_tokens_per_second(self, prompt: str, model: str = "default", max_tokens: int = 100) -> float:
        """Measure throughput."""
        payload = self.build_payload(prompt=prompt, model=model, max_tokens=max_tokens, stream=False)
        start = time.perf_counter()

        r = httpx.post(f"{self.base_url()}{self.endpoint()}", json=payload, timeout=60.0)
        r.raise_for_status()

        elapsed = time.perf_counter() - start
        if elapsed <= 0:
            return 0.0

        data = r.json()
        tokens = data.get("usage", {}).get("completion_tokens")

        if tokens is None:
            text = ""
            if "choices" in data and data["choices"]:
                choice = data["choices"][0]
                text = choice.get("text") or choice.get("message", {}).get("content", "")
            tokens = max(1, len(text.split()))

        return round(tokens / elapsed, 2)

    def measure_ram_peak(self) -> tuple[float, bool]:
        """Return (ram_gb, is_fallback)."""
        pid = self.get_server_pid()

        if pid is not None:
            try:
                process = psutil.Process(pid)
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
            f"Could not locate engine process on port {self.port}; returning system memory fallback."
        )
        return round(used_gb, 2), True

    @abstractmethod
    def is_installed(self) -> bool:
        pass

    @abstractmethod
    def get_version(self) -> str:
        pass


# ─── oMLX ─────────────────────────────────────────────────────────────────────

class OMLXEngine(BaseEngine):
    name = "omlx"
    port = 8000

    def is_installed(self) -> bool:
        return shutil.which("omlx") is not None

    def get_version(self) -> str:
        try:
            result = subprocess.run(
                ["omlx", "serve", "--help"], capture_output=True, text=True, timeout=3
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
    
    # Risolto il problema della cache di istanza spostandola a livello di classe
    _global_model_id_cache: dict[str, str] = {}

    def _resolve_model_id(self, model: str) -> str | None:
        if model in self._global_model_id_cache:
            return self._global_model_id_cache[model]

        try:
            r = httpx.get(f"{self.base_url()}/models", timeout=3.0)
            r.raise_for_status()
            data = r.json()

            for item in data.get("data", []):
                model_id = item.get("id")
                if not model_id:
                    continue

                if model_id == model or model_id.endswith(f"/{model}"):
                    self._global_model_id_cache[model] = model_id
                    return model_id

        except Exception:
            return None
        return None

    def _request_model_name(self, model: str) -> str:
        model_name = super()._request_model_name(model)
        model_name = os.path.expanduser(model_name)

        if "/" in model_name and os.path.exists(model_name):
            return model_name

        resolved = self._resolve_model_id(model_name)
        return resolved or model_name

    def is_installed(self) -> bool:
        return shutil.which("rapid-mlx") is not None

    def get_version(self) -> str:
        try:
            result = subprocess.run(["rapid-mlx", "version"], capture_output=True, text=True)
            return result.stdout.strip() or "unknown"
        except Exception:
            return "unknown"


# ─── mlx-lm ───────────────────────────────────────────────────────────────────

class MLXLMEngine(BaseEngine):
    name = "mlx-lm"
    port = 8002

    # Metodi ridondanti rimossi (ereditano correttamente dalla BaseClass)

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
                ["ollama", "--version"], capture_output=True, text=True, timeout=3
            )
            version_str = result.stdout.strip()
            # Estrae solo il numero di versione (es. da "ollama version is 0.24.0" a "0.24.0")
            return version_str.split()[-1] if version_str else "unknown"
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
    if name not in ENGINES:
        raise ValueError(f"Unknown engine: '{name}'. Available: {list(ENGINES.keys())}")
    return ENGINES[name]()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    for name, cls in ENGINES.items():
        engine = cls()
        installed = engine.is_installed()
        running = engine.is_server_running() if installed else False
        status = "running" if running else ("installed" if installed else "not installed")
        logger.info(f"{name:<15} {status}")