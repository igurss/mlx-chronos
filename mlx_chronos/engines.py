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

from mlx_chronos.constants import (
    ENGINE_NAME_MLX_LM,
    ENGINE_NAME_OLLAMA,
    ENGINE_NAME_OMLX,
    ENGINE_NAME_RAPID_MLX,
    TOKEN_COUNT_SOURCE_USAGE,
    TOKEN_COUNT_SOURCE_WORD_FALLBACK,
)

logger = logging.getLogger("mlx_chronos")


# ─── Base class ───────────────────────────────────────────────────────────────

class BaseEngine(ABC):
    """Abstract base class for inference engine integrations."""

    name: str
    default_port: int
    expected_process_names: tuple[str, ...] = ()

    def __init__(self, port: int | None = None):
        self.port = port if port is not None else self._configured_port()
        self.last_token_count_source = TOKEN_COUNT_SOURCE_USAGE

    def port_env_var(self) -> str:
        normalized_name = self.name.upper().replace("-", "_")
        return f"MLX_CHRONOS_{normalized_name}_PORT"

    def _configured_port(self) -> int:
        raw_port = os.getenv(self.port_env_var())
        if raw_port is None:
            return self.default_port

        try:
            port = int(raw_port)
            if 1 <= port <= 65535:
                return port
        except ValueError:
            pass

        logger.warning(
            "Invalid %s=%r; using default port %s.",
            self.port_env_var(),
            raw_port,
            self.default_port,
        )
        return self.default_port

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
        """Return the listening server PID for this engine port when available."""
        try:
            result = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{self.port}", "-sTCP:LISTEN", "-t"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            pids = result.stdout.strip().split()
            for pid_text in pids:
                try:
                    pid = int(pid_text)
                except ValueError:
                    continue
                if self._process_matches_engine(pid):
                    return pid
        except Exception:
            pass
        return None

    def _process_matches_engine(self, pid: int) -> bool:
        if not self.expected_process_names:
            return True

        try:
            process = psutil.Process(pid)
            process_text = " ".join(
                [
                    process.name(),
                    " ".join(process.cmdline()),
                ]
            ).lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return False

        return any(name.lower() in process_text for name in self.expected_process_names)

    def _stream_chunk_has_content(self, chunk: dict) -> bool:
        choices = chunk.get("choices")
        if not choices:
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

        url = f"{self.base_url()}{self.endpoint()}"
        try:
            with httpx.stream("POST", url, json=payload, timeout=30.0) as r:
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
        except httpx.HTTPError as exc:
            raise RuntimeError(f"{self.name} request failed at {url}: {exc}") from exc

        raise RuntimeError(f"No valid token received from {self.name} stream.")

    def measure_tokens_per_second(self, prompt: str, model: str = "default", max_tokens: int = 100) -> float:
        """Measure throughput."""
        payload = self.build_payload(prompt=prompt, model=model, max_tokens=max_tokens, stream=False)
        start = time.perf_counter()

        url = f"{self.base_url()}{self.endpoint()}"
        try:
            r = httpx.post(url, json=payload, timeout=60.0)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"{self.name} request failed at {url}: {exc}") from exc

        elapsed = time.perf_counter() - start
        if elapsed <= 0:
            return 0.0

        try:
            data = r.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{self.name} returned invalid JSON at {url}") from exc

        tokens = data.get("usage", {}).get("completion_tokens")

        if isinstance(tokens, (int, float)) and tokens > 0:
            self.last_token_count_source = TOKEN_COUNT_SOURCE_USAGE
        else:
            text = ""
            if "choices" in data and data["choices"]:
                choice = data["choices"][0]
                text = choice.get("text") or choice.get("message", {}).get("content", "")
            tokens = max(1, len(text.split()))
            self.last_token_count_source = TOKEN_COUNT_SOURCE_WORD_FALLBACK

        return round(tokens / elapsed, 2)

    @abstractmethod
    def is_installed(self) -> bool:
        pass

    @abstractmethod
    def get_version(self) -> str:
        pass


# ─── oMLX ─────────────────────────────────────────────────────────────────────

class OMLXEngine(BaseEngine):
    name = ENGINE_NAME_OMLX
    default_port = 8000
    expected_process_names = ("omlx", "python")

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
    name = ENGINE_NAME_RAPID_MLX
    default_port = 8001
    expected_process_names = ("rapid-mlx", "python")

    def __init__(
        self,
        port: int | None = None,
        model_id_cache: dict[str, str] | None = None,
    ):
        super().__init__(port=port)
        self._model_id_cache = model_id_cache if model_id_cache is not None else {}

    def _resolve_model_id(self, model: str) -> str | None:
        if model in self._model_id_cache:
            return self._model_id_cache[model]

        try:
            r = httpx.get(f"{self.base_url()}/models", timeout=3.0)
            r.raise_for_status()
            data = r.json()

            for item in data.get("data", []):
                model_id = item.get("id")
                if not model_id:
                    continue

                if model_id == model or model_id.endswith(f"/{model}"):
                    self._model_id_cache[model] = model_id
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
    name = ENGINE_NAME_MLX_LM
    default_port = 8080
    expected_process_names = ("mlx_lm", "mlx-lm", "python")

    def is_installed(self) -> bool:
        return importlib.util.find_spec("mlx_lm") is not None

    def get_version(self) -> str:
        try:
            return importlib.metadata.version("mlx-lm")
        except Exception:
            return "unknown"


# ─── Ollama ───────────────────────────────────────────────────────────────────

class OllamaEngine(BaseEngine):
    name = ENGINE_NAME_OLLAMA
    default_port = 11434
    expected_process_names = ("ollama",)

    def is_installed(self) -> bool:
        return shutil.which("ollama") is not None

    def get_version(self) -> str:
        try:
            result = subprocess.run(
                ["ollama", "--version"], capture_output=True, text=True, timeout=3
            )
            version_str = result.stdout.strip()
            return version_str.split()[-1] if version_str else "unknown"
        except Exception:
            return "unknown"


# ─── Registry ─────────────────────────────────────────────────────────────────

ENGINES = {
    ENGINE_NAME_OMLX: OMLXEngine,
    ENGINE_NAME_RAPID_MLX: RapidMLXEngine,
    ENGINE_NAME_MLX_LM: MLXLMEngine,
    ENGINE_NAME_OLLAMA: OllamaEngine,
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
