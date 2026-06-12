import time
import subprocess
import shutil
import json
import logging
import os
import re
import importlib.metadata
import importlib.util
import httpx
import psutil
from abc import ABC, abstractmethod

from mlx_chronos.constants import (
    BENCHMARK_REQUEST_TEMPERATURE,
    BENCHMARK_REQUEST_TOP_P,
    ENGINE_NAME_MLX_LM,
    ENGINE_NAME_OLLAMA,
    ENGINE_NAME_OMLX,
    ENGINE_NAME_RAPID_MLX,
    ENGINE_NAME_VLLM_MLX,
    ERROR_RESPONSE_BODY_LIMIT,
    TOKEN_COUNT_SOURCE_USAGE,
    TOKEN_COUNT_SOURCE_WORD_FALLBACK,
)
from mlx_chronos.measurements import (
    DECODE_TIMING_CLIENT_STREAM,
    DECODE_TIMING_UNAVAILABLE,
    ThroughputMeasurement,
)

logger = logging.getLogger("mlx_chronos")

THROUGHPUT_STREAM_TIMEOUT_SECONDS = 60.0
THROUGHPUT_TIMEOUT_SECONDS_PER_TOKEN = 0.5


# ─── Base class ───────────────────────────────────────────────────────────────

class BaseEngine(ABC):
    """Abstract base class for inference engine integrations."""

    name: str
    default_port: int
    expected_process_names: tuple[str, ...] = ()

    def __init__(self, port: int | None = None):
        self.port = port if port is not None else self._configured_port()

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

    def root_url(self) -> str:
        return f"http://localhost:{self.port}"

    def http_client(self) -> httpx.Client:
        """Return a reusable HTTP client for benchmark request loops."""
        return httpx.Client()

    def endpoint(self) -> str:
        """API endpoint used by the engine."""
        return "/chat/completions"

    def uses_chat_api(self) -> bool:
        """Whether the engine uses OpenAI chat format."""
        return True

    def build_payload(
        self,
        prompt: str,
        model: str,
        max_tokens: int,
        stream: bool,
        min_tokens: int | None = None,
    ) -> dict:
        payload = {
            "model": self._request_model_name(model),
            "max_tokens": max_tokens,
            "stream": stream,
            "temperature": BENCHMARK_REQUEST_TEMPERATURE,
            "top_p": BENCHMARK_REQUEST_TOP_P,
        }
        if min_tokens is not None:
            payload["min_tokens"] = min_tokens
        if self.uses_chat_api():
            payload["messages"] = [{"role": "user", "content": prompt}]
        else:
            payload["prompt"] = prompt
        return payload

    def _request_model_name(self, model: str) -> str:
        return model.strip() or "default"

    def _request_context(
        self,
        action: str,
        url: str,
        model: str | None = None,
        request_model: str | None = None,
    ) -> str:
        parts = [f"engine={self.name}", f"action={action}", f"url={url}"]
        if model is not None:
            parts.append(f"model={model!r}")
        if request_model is not None:
            parts.append(f"request_model={request_model!r}")
        return "; ".join(parts)

    def _response_body_excerpt(self, response: httpx.Response | None) -> str | None:
        if response is None:
            return None
        try:
            try:
                response.read()
            except Exception:
                pass
            body = response.text.strip()
        except Exception:
            return None
        if not body:
            return None
        body = " ".join(body.split())
        if len(body) > ERROR_RESPONSE_BODY_LIMIT:
            body = f"{body[:ERROR_RESPONSE_BODY_LIMIT]}..."
        return body

    def _request_error_message(
        self,
        action: str,
        url: str,
        exc: httpx.HTTPError,
        model: str | None = None,
        request_model: str | None = None,
    ) -> str:
        context = self._request_context(
            action=action,
            url=url,
            model=model,
            request_model=request_model,
        )
        response = getattr(exc, "response", None)
        if response is not None:
            details = [context, f"status={response.status_code}"]
            reason = getattr(response, "reason_phrase", "")
            if reason:
                details.append(f"reason={reason}")
            body = self._response_body_excerpt(response)
            if body:
                details.append(f"response={body!r}")
            return "; ".join(details)
        return f"{context}; error={exc}"

    def _invalid_json_message(
        self,
        action: str,
        url: str,
        model: str | None = None,
        request_model: str | None = None,
    ) -> str:
        context = self._request_context(
            action=action,
            url=url,
            model=model,
            request_model=request_model,
        )
        return f"{context}; error=invalid JSON response"

    def _invalid_response_message(
        self,
        action: str,
        url: str,
        reason: str,
        model: str | None = None,
        request_model: str | None = None,
    ) -> str:
        context = self._request_context(
            action=action,
            url=url,
            model=model,
            request_model=request_model,
        )
        return f"{context}; error={reason}"

    def is_server_running(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url()}/models", timeout=2.0)
            return r.status_code == 200 and self._server_identity_matches()
        except Exception:
            return False

    def _server_identity_matches(self) -> bool:
        return True

    def list_model_ids(self) -> list[str]:
        """Return model ids exposed by the OpenAI-compatible /models endpoint."""
        url = f"{self.base_url()}/models"
        action = "list models"
        try:
            r = httpx.get(url, timeout=5.0)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(self._request_error_message(action, url, exc)) from exc
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(self._invalid_json_message(action, url)) from exc

        if not isinstance(data, dict):
            raise RuntimeError(
                self._invalid_response_message(
                    action,
                    url,
                    "invalid model list: response must be a JSON object",
                )
            )

        models = []
        items = data.get("data", [])
        if not isinstance(items, list):
            raise RuntimeError(
                self._invalid_response_message(
                    action,
                    url,
                    "invalid model list: response field 'data' must be a list",
                )
            )

        for item in items:
            if isinstance(item, dict):
                model_id = item.get("id")
                if isinstance(model_id, str) and model_id.strip():
                    models.append(model_id)
        return models

    def resolve_listed_model_id(self, model: str, model_ids: list[str] | None = None) -> str | None:
        """Return a matching listed model id for user input when one is available."""
        requested = model.strip()
        if not requested:
            return None

        model_ids = self.list_model_ids() if model_ids is None else model_ids
        request_model = self._request_model_name(requested)
        return self._match_listed_model_id(requested, request_model, model_ids)

    def _match_listed_model_id(
        self,
        requested: str,
        request_model: str,
        model_ids: list[str],
    ) -> str | None:
        """Return a model id matching either user input or request payload id."""
        candidates = {requested, request_model}

        for model_id in model_ids:
            if model_id in candidates:
                return model_id
            if any(model_id.endswith(f"/{candidate}") for candidate in candidates):
                return model_id
        return None

    def validate_completion_request(self, model: str) -> str:
        """Send a tiny non-streaming completion request and return the request model id."""
        payload = self.build_payload(
            prompt="Reply with one word: ok",
            model=model,
            max_tokens=1,
            stream=False,
        )
        url = f"{self.base_url()}{self.endpoint()}"
        request_model = str(payload["model"])
        action = "validate completion"
        try:
            r = httpx.post(url, json=payload, timeout=30.0)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(
                self._request_error_message(
                    action,
                    url,
                    exc,
                    model=model,
                    request_model=request_model,
                )
            ) from exc
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(
                self._invalid_json_message(
                    action,
                    url,
                    model=model,
                    request_model=request_model,
                )
            ) from exc

        if not isinstance(data, dict):
            raise RuntimeError(
                self._invalid_response_message(
                    action,
                    url,
                    "invalid completion response: completion response must be a JSON object",
                    model=model,
                    request_model=request_model,
                )
            )

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError(
                self._invalid_response_message(
                    action,
                    url,
                    "invalid completion response: field 'choices' must be a non-empty list",
                    model=model,
                    request_model=request_model,
                )
            )
        return request_model

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
            process_tokens = [
                os.path.basename(token).lower()
                for token in [process.name(), *process.cmdline()]
                if token
            ]
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return False

        for name in self.expected_process_names:
            normalized_names = {
                name.lower(),
                name.lower().replace("-", "_"),
                name.lower().replace("_", "-"),
            }
            for token in process_tokens:
                if any(
                    token == expected or token.startswith(f"{expected}.")
                    for expected in normalized_names
                ):
                    return True
        return False

    def _parse_version_output(self, output: str) -> str | None:
        match = re.search(r"\bv?(\d+(?:\.\d+)+(?:[-+._a-zA-Z0-9]*)?)\b", output)
        return match.group(1) if match else None

    def _stream_chunk_has_content(self, chunk: dict) -> bool:
        choices = chunk.get("choices")
        if not choices:
            return False

        choice = choices[0]
        if not isinstance(choice, dict):
            return False
        delta = choice.get("delta", {})
        if not isinstance(delta, dict):
            delta = {}

        for key in ("content", "reasoning", "reasoning_content"):
            value = delta.get(key)
            if isinstance(value, str) and value:
                return True

        if delta.get("tool_calls"):
            return True

        text = choice.get("text")
        if isinstance(text, str) and text:
            return True

        return False

    def _extract_stream_text(self, chunk: dict) -> str:
        choices = chunk.get("choices")
        if not choices:
            return ""

        choice = choices[0]
        if not isinstance(choice, dict):
            return ""
        delta = choice.get("delta", {})
        if not isinstance(delta, dict):
            delta = {}

        parts = []
        for key in ("content", "reasoning", "reasoning_content"):
            value = delta.get(key)
            if isinstance(value, str) and value:
                parts.append(value)

        text = choice.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
        return "".join(parts)

    def _extract_stream_usage_tokens(self, chunk: dict) -> int | None:
        usage = chunk.get("usage")
        if not isinstance(usage, dict):
            return None
        tokens = usage.get("completion_tokens")
        if isinstance(tokens, (int, float)) and tokens > 0:
            return int(tokens)
        return None

    def _estimated_completion_words(self, text_parts: list[str]) -> int:
        completion_text = "".join(text_parts)
        return len(completion_text.split())

    def _append_progress_sample(
        self,
        samples: list[dict],
        completion_tokens: int,
        elapsed_seconds: float,
        token_count_source: str,
    ) -> None:
        if completion_tokens <= 0 or elapsed_seconds <= 0:
            return
        rounded_elapsed_seconds = round(elapsed_seconds, 3)
        if rounded_elapsed_seconds <= 0:
            return
        samples.append(
            {
                "completion_tokens": completion_tokens,
                "elapsed_seconds": rounded_elapsed_seconds,
                "tokens_per_second": round(
                    completion_tokens / rounded_elapsed_seconds, 2
                ),
                "token_count_source": token_count_source,
            }
        )

    def _version_from_mapping(
        self,
        mapping: dict,
        version_keys: tuple[str, ...],
    ) -> str | None:
        for key in version_keys:
            value = mapping.get(key)
            if isinstance(value, (str, int, float)):
                version = str(value).strip()
                if version:
                    return version

        for nested_key in ("metadata", "meta"):
            nested = mapping.get(nested_key)
            if isinstance(nested, dict):
                version = self._version_from_mapping(nested, version_keys)
                if version:
                    return version
        return None

    def _get_version_from_models_endpoint(
        self,
        version_keys: tuple[str, ...] = (
            "engine_version",
            "server_version",
            "omlx_version",
            "version",
        ),
    ) -> str | None:
        """Try to read an engine/server version from /v1/models metadata."""
        url = f"{self.base_url()}/models"
        try:
            response = httpx.get(url, timeout=2.0)
            response.raise_for_status()
            data = response.json()
        except Exception:
            return None

        if not isinstance(data, dict):
            return None

        version = self._version_from_mapping(data, version_keys)
        if version:
            return version

        items = data.get("data")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    version = self._version_from_mapping(item, version_keys)
                    if version:
                        return version
        return None

    def _should_retry_without_stream_usage(self, exc: httpx.HTTPError) -> bool:
        response = getattr(exc, "response", None)
        if response is None or response.status_code not in {400, 422}:
            return False
        body = self._response_body_excerpt(response) or ""
        body = body.lower()
        return "stream_options" in body or "include_usage" in body

    def _throughput_timeout(self, max_tokens: int) -> float:
        return max(
            THROUGHPUT_STREAM_TIMEOUT_SECONDS,
            max_tokens * THROUGHPUT_TIMEOUT_SECONDS_PER_TOKEN,
        )

    def _stream_request(
        self,
        client: httpx.Client | None,
        method: str,
        url: str,
        **kwargs,
    ):
        if client is not None:
            return client.stream(method, url, **kwargs)
        return httpx.stream(method, url, **kwargs)

    def measure_ttft(
        self,
        prompt: str,
        model: str = "default",
        client: httpx.Client | None = None,
    ) -> float:
        """Measure Time To First Token."""
        payload = self.build_payload(prompt=prompt, model=model, max_tokens=1, stream=True)
        start = time.perf_counter()

        url = f"{self.base_url()}{self.endpoint()}"
        request_model = str(payload["model"])
        action = "measure TTFT"
        try:
            with self._stream_request(
                client,
                "POST",
                url,
                json=payload,
                timeout=30.0,
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
        except httpx.HTTPError as exc:
            raise RuntimeError(
                self._request_error_message(
                    action,
                    url,
                    exc,
                    model=model,
                    request_model=request_model,
                )
            ) from exc

        raise RuntimeError(
            self._invalid_response_message(
                action,
                url,
                "stream ended before a valid content token was received",
                model=model,
                request_model=request_model,
            )
        )

    def measure_throughput(
        self,
        prompt: str,
        model: str = "default",
        max_tokens: int = 100,
        min_tokens: int | None = None,
        progress_sample_interval_tokens: int | None = None,
        client: httpx.Client | None = None,
    ) -> ThroughputMeasurement:
        """Measure request throughput and client-observed decode throughput."""
        if (
            progress_sample_interval_tokens is not None
            and progress_sample_interval_tokens <= 0
        ):
            raise ValueError("progress_sample_interval_tokens must be greater than 0")

        base_payload = self.build_payload(
            prompt=prompt,
            model=model,
            max_tokens=max_tokens,
            min_tokens=min_tokens,
            stream=True,
        )

        url = f"{self.base_url()}{self.endpoint()}"
        request_model = str(base_payload["model"])
        action = "measure throughput"
        for include_usage in (True, False):
            payload = dict(base_payload)
            if include_usage:
                payload["stream_options"] = {"include_usage": True}
            start = time.perf_counter()
            first_token_at = None
            stream_finished_at = None
            completion_text_parts = []
            completion_tokens = None
            progress_samples = []
            next_progress_sample_at = progress_sample_interval_tokens

            try:
                with self._stream_request(
                    client,
                    "POST",
                    url,
                    json=payload,
                    timeout=self._throughput_timeout(max_tokens),
                ) as r:
                    if r.status_code >= 400:
                        try:
                            r.read()
                        except Exception:
                            pass
                    r.raise_for_status()

                    for line in r.iter_lines():
                        if not line:
                            continue
                        if isinstance(line, bytes):
                            line = line.decode("utf-8", errors="ignore")
                        if not line.startswith("data:"):
                            continue

                        raw_chunk = line.removeprefix("data:").strip()
                        if not raw_chunk:
                            continue
                        if raw_chunk == "[DONE]":
                            stream_finished_at = time.perf_counter()
                            break

                        try:
                            chunk = json.loads(raw_chunk)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(chunk, dict):
                            continue

                        usage_tokens = self._extract_stream_usage_tokens(chunk)
                        if usage_tokens is not None:
                            completion_tokens = usage_tokens

                        if self._stream_chunk_has_content(chunk):
                            if first_token_at is None:
                                first_token_at = time.perf_counter()
                            text = self._extract_stream_text(chunk)
                            if text:
                                completion_text_parts.append(text)
                                if next_progress_sample_at is not None:
                                    estimated_tokens = self._estimated_completion_words(
                                        completion_text_parts
                                    )
                                    while estimated_tokens >= next_progress_sample_at:
                                        self._append_progress_sample(
                                            progress_samples,
                                            next_progress_sample_at,
                                            time.perf_counter() - start,
                                            TOKEN_COUNT_SOURCE_WORD_FALLBACK,
                                        )
                                        next_progress_sample_at += (
                                            progress_sample_interval_tokens
                                        )
                break
            except httpx.HTTPError as exc:
                if include_usage and self._should_retry_without_stream_usage(exc):
                    continue
                raise RuntimeError(
                    self._request_error_message(
                        action,
                        url,
                        exc,
                        model=model,
                        request_model=request_model,
                    )
                ) from exc

        elapsed = (
            stream_finished_at - start
            if stream_finished_at is not None
            else time.perf_counter() - start
        )
        rounded_elapsed = round(max(elapsed, 0.0), 3)
        if rounded_elapsed <= 0:
            rounded_elapsed = 0.001

        if first_token_at is None:
            raise RuntimeError(
                self._invalid_response_message(
                    action,
                    url,
                    "stream ended before a valid content token was received",
                    model=model,
                    request_model=request_model,
                )
            )

        if completion_tokens is not None:
            token_count_source = TOKEN_COUNT_SOURCE_USAGE
        else:
            completion_text = "".join(completion_text_parts)
            completion_tokens = max(1, len(completion_text.split()))
            token_count_source = TOKEN_COUNT_SOURCE_WORD_FALLBACK

        request_tps = round(completion_tokens / rounded_elapsed, 2)
        decode_tps = None
        decode_source = DECODE_TIMING_UNAVAILABLE
        decode_elapsed = elapsed - (first_token_at - start)
        if (
            token_count_source == TOKEN_COUNT_SOURCE_USAGE
            and completion_tokens > 1
            and decode_elapsed > 0
        ):
            decode_tps = round((completion_tokens - 1) / decode_elapsed, 2)
            decode_source = DECODE_TIMING_CLIENT_STREAM
        finalized_progress_samples = []
        if progress_sample_interval_tokens is not None:
            finalized_progress_samples = list(progress_samples)
            if token_count_source == TOKEN_COUNT_SOURCE_USAGE:
                finalized_progress_samples = [
                    sample
                    for sample in finalized_progress_samples
                    if sample["completion_tokens"] < completion_tokens
                ]
            if (
                not finalized_progress_samples
                or finalized_progress_samples[-1]["completion_tokens"]
                != completion_tokens
            ):
                self._append_progress_sample(
                    finalized_progress_samples,
                    completion_tokens,
                    max(elapsed, 0.0),
                    token_count_source,
                )
        return ThroughputMeasurement(
            request_tokens_per_second=request_tps,
            completion_tokens=completion_tokens,
            token_count_source=token_count_source,
            elapsed_seconds=rounded_elapsed,
            decode_tokens_per_second=decode_tps,
            decode_timing_source=decode_source,
            progress_samples=tuple(finalized_progress_samples),
        )

    def measure_tokens_per_second(
        self,
        prompt: str,
        model: str = "default",
        max_tokens: int = 100,
        min_tokens: int | None = None,
        client: httpx.Client | None = None,
    ) -> float:
        """Measure client-observed total request throughput."""
        return self.measure_throughput(
            prompt=prompt,
            model=model,
            max_tokens=max_tokens,
            min_tokens=min_tokens,
            client=client,
        ).request_tokens_per_second

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
    expected_process_names = ("omlx", "omlx-server")

    def is_installed(self) -> bool:
        return shutil.which("omlx") is not None

    def _server_identity_matches(self) -> bool:
        return self.get_server_pid() is not None

    def get_version(self) -> str:
        version_commands = [
            ["omlx", "--version"],
            ["omlx", "serve", "--help"],
        ]
        for command in version_commands:
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
            except Exception:
                continue

            if result.returncode != 0:
                continue

            output = f"{result.stdout}\n{result.stderr}"
            parsed = self._parse_version_output(output)
            if parsed:
                return parsed

            for line in output.splitlines():
                if "Version:" in line:
                    version = line.split("Version:")[-1].strip()
                    if version:
                        return version
        http_version = self._get_version_from_models_endpoint()
        if http_version:
            return http_version
        return "unknown"


# ─── Rapid-MLX ────────────────────────────────────────────────────────────────

class RapidMLXEngine(BaseEngine):
    name = ENGINE_NAME_RAPID_MLX
    default_port = 8001
    expected_process_names = ("rapid-mlx", "rapid_mlx")

    def __init__(
        self,
        port: int | None = None,
        model_id_cache: dict[str, str] | None = None,
    ):
        super().__init__(port=port)
        self._model_id_cache = model_id_cache if model_id_cache is not None else {}
        self._request_model_cache: dict[str, str] = {}

    def _resolve_model_id(self, model: str) -> str | None:
        if model in self._model_id_cache:
            return self._model_id_cache[model]

        try:
            resolved = self._match_listed_model_id(
                requested=model,
                request_model=model,
                model_ids=self.list_model_ids(),
            )
        except RuntimeError:
            return None
        if resolved is not None:
            self._model_id_cache[model] = resolved
        return resolved

    def _request_model_name(self, model: str) -> str:
        model_name = os.path.expanduser(super()._request_model_name(model))
        cache_key = model_name
        if cache_key in self._request_model_cache:
            return self._request_model_cache[cache_key]

        if "/" in model_name and os.path.exists(model_name):
            request_model = model_name
        else:
            resolved = self._resolve_model_id(model_name)
            request_model = resolved or model_name

        self._request_model_cache[cache_key] = request_model
        return request_model

    def is_installed(self) -> bool:
        return shutil.which("rapid-mlx") is not None

    def get_version(self) -> str:
        try:
            result = subprocess.run(
                ["rapid-mlx", "version"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            output = f"{result.stdout}\n{result.stderr}"
            return (
                self._parse_version_output(output)
                or result.stdout.strip()
                or "unknown"
            )
        except Exception:
            return "unknown"


# ─── vLLM-MLX ────────────────────────────────────────────────────────────────

class VLLMMLXEngine(BaseEngine):
    name = ENGINE_NAME_VLLM_MLX
    default_port = 8000
    expected_process_names = ("vllm-mlx", "vllm_mlx")

    def is_installed(self) -> bool:
        return (
            shutil.which("vllm-mlx") is not None
            or importlib.util.find_spec("vllm_mlx") is not None
        )

    def _server_identity_matches(self) -> bool:
        try:
            response = httpx.get(f"{self.root_url()}/health", timeout=2.0)
            if response.status_code != 200:
                return False
            data = response.json()
        except Exception:
            return False

        return (
            isinstance(data, dict)
            and isinstance(data.get("available_models"), list)
            and isinstance(data.get("model_loaded"), bool)
            and data.get("model_type") in {"llm", "mllm"}
        )

    def get_version(self) -> str:
        try:
            return importlib.metadata.version("vllm-mlx")
        except Exception:
            pass

        try:
            import vllm_mlx

            version = getattr(vllm_mlx, "__version__", None)
            if isinstance(version, str) and version.strip():
                return version.strip()
        except Exception:
            pass

        http_version = self._get_version_from_models_endpoint(
            version_keys=(
                "vllm_mlx_version",
                "engine_version",
                "server_version",
                "version",
            )
        )
        if http_version:
            return self._parse_version_output(http_version) or http_version
        return "unknown"


# ─── mlx-lm ───────────────────────────────────────────────────────────────────

class MLXLMEngine(BaseEngine):
    name = ENGINE_NAME_MLX_LM
    default_port = 8080
    expected_process_names = ("mlx_lm", "mlx-lm")

    def __init__(
        self,
        port: int | None = None,
        model_id_cache: dict[str, str] | None = None,
    ):
        super().__init__(port=port)
        self._model_id_cache = model_id_cache if model_id_cache is not None else {}
        self._request_model_cache: dict[str, str] = {}

    def _resolve_model_id(self, model: str) -> str | None:
        if model in self._model_id_cache:
            return self._model_id_cache[model]

        try:
            model_ids = self.list_model_ids()
        except RuntimeError:
            return None

        matches = [
            model_id
            for model_id in model_ids
            if model_id == model
            or model_id.endswith(f"/{model}")
            or os.path.basename(model_id.rstrip("/")) == model
        ]
        if len(matches) != 1:
            return None

        resolved = matches[0]
        self._model_id_cache[model] = resolved
        return resolved

    def _request_model_name(self, model: str) -> str:
        model_name = os.path.expanduser(super()._request_model_name(model))
        if model_name in self._request_model_cache:
            return self._request_model_cache[model_name]

        if model_name == "default_model" or os.path.exists(model_name):
            request_model = model_name
        else:
            resolved = self._resolve_model_id(model_name)
            request_model = (
                "default_model"
                if resolved and os.path.exists(os.path.expanduser(resolved))
                else resolved or model_name
            )

        self._request_model_cache[model_name] = request_model
        return request_model

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

    def _server_identity_matches(self) -> bool:
        try:
            response = httpx.get(f"{self.root_url()}/api/version", timeout=2.0)
            if response.status_code != 200:
                return False
            data = response.json()
        except Exception:
            return False
        return isinstance(data, dict) and isinstance(data.get("version"), str)

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
    ENGINE_NAME_VLLM_MLX: VLLMMLXEngine,
    ENGINE_NAME_MLX_LM: MLXLMEngine,
    ENGINE_NAME_OLLAMA: OllamaEngine,
}

def get_engine(name: str) -> BaseEngine:
    if name not in ENGINES:
        raise ValueError(f"Unknown engine: '{name}'. Available: {list(ENGINES.keys())}")
    return ENGINES[name]()
