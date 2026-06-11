from contextlib import contextmanager
import json
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from mlx_chronos.constants import VALID_ENGINE_NAMES
from mlx_chronos.engines import (
    ENGINES, OMLXEngine, MLXLMEngine, RapidMLXEngine, OllamaEngine, get_engine
)
from mlx_chronos.measurements import ThroughputMeasurement

def http_error_response(method: str, url: str, status_code: int, text: str) -> httpx.Response:
    return httpx.Response(
        status_code,
        text=text,
        request=httpx.Request(method, url),
    )

class MockStreamResponse:
    def __init__(
        self,
        lines: list[str] | None = None,
        status_code: int = 200,
        text: str = "",
    ):
        self.lines = lines or []
        self.status_code = status_code
        self.response = http_error_response(
            "POST",
            "http://localhost:8000/v1/chat/completions",
            status_code,
            text,
        )

    def raise_for_status(self):
        self.response.raise_for_status()

    def iter_lines(self):
        yield from self.lines


class MockStreamContext:
    def __init__(self, response: MockStreamResponse):
        self.response = response

    def __enter__(self):
        return self.response

    def __exit__(self, exc_type, exc, tb):
        return False


class SlowCloseStreamContext(MockStreamContext):
    def __exit__(self, exc_type, exc, tb):
        time.perf_counter()
        return False


def stream_response(lines: list[str], status_code: int = 200, text: str = ""):
    return MockStreamContext(MockStreamResponse(lines, status_code, text))


def completion_stream(
    content: str = "hello",
    completion_tokens: int | None = 100,
) -> list[str]:
    lines = [
        'data: {"choices": [{"delta": {"role": "assistant"}}]}',
        f'data: {json.dumps({"choices": [{"delta": {"content": content}}]})}',
    ]
    if completion_tokens is not None:
        lines.append(
            "data: "
            + json.dumps(
                {
                    "choices": [],
                    "usage": {"completion_tokens": completion_tokens},
                }
            )
        )
    lines.append("data: [DONE]")
    return lines


def test_stream_chunk_role_is_not_counted_as_content():
    engine = OMLXEngine()
    chunk = {"choices": [{"delta": {"role": "assistant"}}]}
    assert engine._stream_chunk_has_content(chunk) is False

def test_stream_chunk_whitespace_is_counted_as_content():
    engine = OMLXEngine()
    chunk = {"choices": [{"delta": {"content": "   "}}]}
    assert engine._stream_chunk_has_content(chunk) is True

def test_stream_chunk_text_content_is_counted():
    engine = OMLXEngine()
    chunk = {"choices": [{"delta": {"content": "Hello"}}]}
    assert engine._stream_chunk_has_content(chunk) is True

def test_stream_chunk_invalid_choice_shape_is_ignored():
    engine = OMLXEngine()
    chunk = {"choices": ["not-a-dict"]}
    assert engine._stream_chunk_has_content(chunk) is False

def test_mlx_lm_install_check_does_not_import_mlx_lm(monkeypatch):
    called = {}
    def fake_find_spec(name):
        called["name"] = name
        return None
    monkeypatch.setattr("importlib.util.find_spec", fake_find_spec)
    assert MLXLMEngine().is_installed() is False
    assert called.get("name") == "mlx_lm"

def test_get_engine():
    assert isinstance(get_engine("omlx"), OMLXEngine)
    with pytest.raises(ValueError, match="Unknown engine: 'fake'"):
        get_engine("fake")

def test_engine_registry_matches_schema_constants():
    assert set(ENGINES) == VALID_ENGINE_NAMES


def test_process_match_rejects_generic_python_process(monkeypatch):
    fake_process = MagicMock()
    fake_process.name.return_value = "python"
    fake_process.cmdline.return_value = ["python", "-m", "jupyter"]
    monkeypatch.setattr("mlx_chronos.engines.psutil.Process", lambda _pid: fake_process)

    assert OMLXEngine()._process_matches_engine(12345) is False


def test_process_match_accepts_engine_specific_python_module(monkeypatch):
    fake_process = MagicMock()
    fake_process.name.return_value = "python"
    fake_process.cmdline.return_value = ["python", "-m", "rapid_mlx.server"]
    monkeypatch.setattr("mlx_chronos.engines.psutil.Process", lambda _pid: fake_process)

    assert RapidMLXEngine()._process_matches_engine(12345) is True


def test_process_match_rejects_engine_name_only_in_path(monkeypatch):
    fake_process = MagicMock()
    fake_process.name.return_value = "python"
    fake_process.cmdline.return_value = ["python", "/tmp/omlx-benchmarks/test.py"]
    monkeypatch.setattr("mlx_chronos.engines.psutil.Process", lambda _pid: fake_process)

    assert OMLXEngine()._process_matches_engine(12345) is False


@patch("httpx.stream")
def test_measure_tokens_per_second(mock_stream):
    mock_stream.return_value = stream_response(
        completion_stream(content="hello", completion_tokens=150)
    )
    engine = OMLXEngine()
    with patch("time.perf_counter", side_effect=[0.0, 0.5, 1.5]):
        tps = engine.measure_tokens_per_second("test prompt", "default", 100)
        assert tps == 100.0  # 150 tokens / 1.5s = 100.0

@patch("httpx.stream")
def test_measure_throughput_returns_structured_measurement(mock_stream):
    mock_stream.return_value = stream_response(
        completion_stream(content="hello", completion_tokens=150)
    )
    engine = OMLXEngine()
    with patch("time.perf_counter", side_effect=[0.0, 0.5, 1.5]):
        measurement = engine.measure_throughput("test prompt", "default", 100)

    assert isinstance(measurement, ThroughputMeasurement)
    assert measurement.request_tokens_per_second == 100.0
    assert measurement.completion_tokens == 150
    assert measurement.token_count_source == "usage.completion_tokens"
    assert measurement.elapsed_seconds == 1.5
    assert measurement.decode_tokens_per_second == 149.0
    assert measurement.decode_timing_source == "client_stream"


@patch("httpx.stream")
def test_measure_throughput_uses_provided_http_client(mock_stream):
    client = MagicMock()
    client.stream.return_value = stream_response(
        completion_stream(content="hello", completion_tokens=100)
    )
    engine = OMLXEngine()

    with patch("time.perf_counter", side_effect=[0.0, 0.5, 1.5]):
        measurement = engine.measure_throughput(
            "test prompt",
            "default",
            100,
            client=client,
        )

    assert measurement.request_tokens_per_second == pytest.approx(66.67, abs=0.001)
    client.stream.assert_called_once()
    mock_stream.assert_not_called()


@patch("httpx.stream")
def test_measure_throughput_uses_client_stream_decode_timing(mock_stream):
    mock_stream.return_value = stream_response(
        completion_stream(content="hello", completion_tokens=100)
    )
    engine = OMLXEngine()
    with patch("time.perf_counter", side_effect=[0.0, 0.5, 5.5]):
        measurement = engine.measure_throughput("test prompt", "default", 100)

    assert measurement.request_tokens_per_second == pytest.approx(18.18, abs=0.001)
    assert measurement.decode_tokens_per_second == pytest.approx(19.8, abs=0.001)
    assert measurement.decode_timing_source == "client_stream"


@patch("httpx.stream")
def test_measure_throughput_uses_stored_elapsed_for_request_tps(mock_stream):
    mock_stream.return_value = stream_response(
        completion_stream(content="hello", completion_tokens=100)
    )
    engine = OMLXEngine()
    with patch("time.perf_counter", side_effect=[0.0, 0.1, 0.4995]):
        measurement = engine.measure_throughput("test prompt", "default", 100)

    rounded_elapsed = round(0.4995, 3)
    assert measurement.elapsed_seconds == rounded_elapsed
    assert measurement.request_tokens_per_second == round(100 / rounded_elapsed, 2)


@patch("httpx.stream")
def test_measure_throughput_uses_done_time_not_stream_close(mock_stream):
    mock_stream.return_value = SlowCloseStreamContext(
        MockStreamResponse(
            completion_stream(content="hello", completion_tokens=100)
        )
    )
    engine = OMLXEngine()
    with patch("time.perf_counter", side_effect=[0.0, 0.1, 1.0, 10.0]):
        measurement = engine.measure_throughput("test prompt", "default", 100)

    assert measurement.elapsed_seconds == 1.0
    assert measurement.request_tokens_per_second == 100.0


@patch("httpx.stream")
def test_measure_throughput_records_progress_samples(mock_stream):
    content = " ".join(["token"] * 120)
    mock_stream.return_value = stream_response(
        completion_stream(content=content, completion_tokens=120)
    )
    engine = OMLXEngine()
    with patch("time.perf_counter", side_effect=[0.0, 0.5, 1.0, 2.0]):
        measurement = engine.measure_throughput(
            "test prompt",
            "default",
            120,
            progress_sample_interval_tokens=100,
        )

    assert measurement.request_tokens_per_second == 60.0
    assert measurement.progress_samples == (
        {
            "completion_tokens": 100,
            "elapsed_seconds": 1.0,
            "tokens_per_second": 100.0,
            "token_count_source": "word_fallback",
        },
        {
            "completion_tokens": 120,
            "elapsed_seconds": 2.0,
            "tokens_per_second": 60.0,
            "token_count_source": "usage.completion_tokens",
        },
    )


def test_append_progress_sample_uses_rounded_elapsed_for_tps():
    engine = OMLXEngine()
    samples = []
    elapsed_seconds = 0.4995

    engine._append_progress_sample(
        samples,
        completion_tokens=100,
        elapsed_seconds=elapsed_seconds,
        token_count_source="usage.completion_tokens",
    )

    rounded_elapsed_seconds = round(elapsed_seconds, 3)
    assert samples == [
        {
            "completion_tokens": 100,
            "elapsed_seconds": rounded_elapsed_seconds,
            "tokens_per_second": round(100 / rounded_elapsed_seconds, 2),
            "token_count_source": "usage.completion_tokens",
        }
    ]


def test_append_progress_sample_skips_elapsed_that_rounds_to_zero():
    engine = OMLXEngine()
    samples = []

    engine._append_progress_sample(
        samples,
        completion_tokens=100,
        elapsed_seconds=0.0004,
        token_count_source="usage.completion_tokens",
    )

    assert samples == []

@patch("httpx.stream")
def test_measure_throughput_scales_timeout_for_long_outputs(mock_stream):
    mock_stream.return_value = stream_response(
        completion_stream(content="hello", completion_tokens=1000)
    )
    engine = OMLXEngine()
    with patch("time.perf_counter", side_effect=[0.0, 0.5, 2.0]):
        engine.measure_throughput("test prompt", "default", 1000)

    assert mock_stream.call_args.kwargs["timeout"] == 500.0

@patch("httpx.stream")
def test_measure_tokens_per_second_marks_word_fallback(mock_stream):
    mock_stream.return_value = stream_response(
        completion_stream(content="one two three four", completion_tokens=None)
    )
    engine = OMLXEngine()
    with patch("time.perf_counter", side_effect=[0.0, 0.5, 2.0]):
        tps = engine.measure_tokens_per_second("test prompt", "default", 100)
        assert tps == 2.0

@patch("httpx.stream")
def test_measure_tokens_per_second_includes_optional_min_tokens(mock_stream):
    mock_stream.return_value = stream_response(completion_stream())
    engine = OMLXEngine()
    with patch("time.perf_counter", side_effect=[0.0, 0.5, 1.0]):
        engine.measure_tokens_per_second(
            "test prompt",
            "default",
            max_tokens=100,
            min_tokens=80,
        )

    payload = mock_stream.call_args.kwargs["json"]
    assert payload["max_tokens"] == 100
    assert payload["min_tokens"] == 80
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}

@patch("httpx.stream")
def test_measure_throughput_retries_without_stream_usage_when_unsupported(mock_stream):
    mock_stream.side_effect = [
        stream_response(
            [],
            status_code=400,
            text='{"error":"stream_options include_usage is not supported"}',
        ),
        stream_response(
            completion_stream(content="one two", completion_tokens=None),
        ),
    ]

    engine = OMLXEngine()
    with patch("time.perf_counter", side_effect=[0.0, 1.0, 1.5, 2.0]):
        measurement = engine.measure_throughput("test prompt", "default", 100)

    first_payload = mock_stream.call_args_list[0].kwargs["json"]
    retry_payload = mock_stream.call_args_list[1].kwargs["json"]
    assert first_payload["stream_options"] == {"include_usage": True}
    assert "stream_options" not in retry_payload
    assert measurement.token_count_source == "word_fallback"
    assert measurement.decode_tokens_per_second is None
    assert measurement.decode_timing_source == "unavailable"

@patch("httpx.stream", side_effect=httpx.TimeoutException("timed out"))
def test_measure_tokens_per_second_wraps_http_errors(mock_stream):
    engine = OMLXEngine()
    with pytest.raises(RuntimeError, match="engine=omlx; action=measure throughput"):
        engine.measure_tokens_per_second("test prompt", "default", 100)

@patch("httpx.stream")
def test_measure_tokens_per_second_reports_status_model_and_body(mock_stream):
    mock_stream.return_value = stream_response(
        [],
        status_code=404,
        text='{"error":"model not found"}',
    )

    engine = OMLXEngine()
    with pytest.raises(RuntimeError) as exc:
        engine.measure_tokens_per_second("test prompt", "missing-model", 100)

    message = str(exc.value)
    assert "engine=omlx" in message
    assert "action=measure throughput" in message
    assert "url=http://localhost:8000/v1/chat/completions" in message
    assert "model='missing-model'" in message
    assert "request_model='missing-model'" in message
    assert "status=404" in message
    assert "model not found" in message

@patch("httpx.stream")
def test_measure_tokens_per_second_rejects_empty_stream(mock_stream):
    mock_stream.return_value = stream_response(["data: []", "data: [DONE]"])
    engine = OMLXEngine()
    with patch("time.perf_counter", side_effect=[0.0, 1.0]):
        with pytest.raises(RuntimeError, match="stream ended before"):
            engine.measure_tokens_per_second("test prompt", "default", 100)

@patch("httpx.get")
def test_list_model_ids(mock_get):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {"id": "org/test-model"},
            {"id": ""},
            {"object": "model"},
        ]
    }
    mock_get.return_value = mock_response

    assert OMLXEngine().list_model_ids() == ["org/test-model"]

@patch("httpx.get")
def test_list_model_ids_reports_status_url_and_body(mock_get):
    mock_get.return_value = http_error_response(
        "GET",
        "http://localhost:8000/v1/models",
        500,
        "server exploded",
    )

    with pytest.raises(RuntimeError) as exc:
        OMLXEngine().list_model_ids()

    message = str(exc.value)
    assert "engine=omlx" in message
    assert "action=list models" in message
    assert "url=http://localhost:8000/v1/models" in message
    assert "status=500" in message
    assert "server exploded" in message

@patch("httpx.get")
def test_list_model_ids_rejects_invalid_shape(mock_get):
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": {"id": "org/test-model"}}
    mock_get.return_value = mock_response

    with pytest.raises(RuntimeError, match="invalid model list"):
        OMLXEngine().list_model_ids()

def test_resolve_listed_model_id_matches_suffix():
    engine = OMLXEngine()
    resolved = engine.resolve_listed_model_id(
        "test-model",
        ["org/test-model"],
    )
    assert resolved == "org/test-model"

@patch("httpx.post")
def test_validate_completion_request(mock_post):
    mock_response = MagicMock()
    mock_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    mock_post.return_value = mock_response

    request_model = OMLXEngine().validate_completion_request("org/test-model")

    assert request_model == "org/test-model"
    payload = mock_post.call_args.kwargs["json"]
    assert payload["model"] == "org/test-model"
    assert payload["max_tokens"] == 1
    assert payload["stream"] is False

@patch("httpx.post")
def test_validate_completion_request_reports_status_model_and_body(mock_post):
    mock_post.return_value = http_error_response(
        "POST",
        "http://localhost:8000/v1/chat/completions",
        400,
        '{"error":"unknown model"}',
    )

    with pytest.raises(RuntimeError) as exc:
        OMLXEngine().validate_completion_request("missing-model")

    message = str(exc.value)
    assert "engine=omlx" in message
    assert "action=validate completion" in message
    assert "model='missing-model'" in message
    assert "request_model='missing-model'" in message
    assert "status=400" in message
    assert "unknown model" in message

@patch("httpx.post")
def test_validate_completion_request_rejects_invalid_shape(mock_post):
    mock_response = MagicMock()
    mock_response.json.return_value = []
    mock_post.return_value = mock_response

    with pytest.raises(RuntimeError, match="invalid completion response"):
        OMLXEngine().validate_completion_request("org/test-model")


@patch("httpx.get")
def test_ollama_server_running_requires_ollama_identity(mock_get):
    models_response = MagicMock(status_code=200)
    version_response = MagicMock(status_code=200)
    version_response.json.return_value = {"version": "0.24.0"}
    mock_get.side_effect = [models_response, version_response]

    assert OllamaEngine().is_server_running() is True


@patch("httpx.get")
def test_ollama_server_running_rejects_wrong_server_on_port(mock_get):
    models_response = MagicMock(status_code=200)
    version_response = MagicMock(status_code=404)
    mock_get.side_effect = [models_response, version_response]

    assert OllamaEngine().is_server_running() is False


def test_engine_port_env_override(monkeypatch):
    monkeypatch.setenv("MLX_CHRONOS_MLX_LM_PORT", "8090")
    assert MLXLMEngine().port == 8090

def test_engine_invalid_port_env_uses_default(monkeypatch):
    monkeypatch.setenv("MLX_CHRONOS_MLX_LM_PORT", "invalid")
    assert MLXLMEngine().port == 8080

@patch("subprocess.run")
@patch("mlx_chronos.engines.psutil.Process")
def test_get_server_pid_filters_listening_process(mock_process_cls, mock_run):
    mock_result = MagicMock()
    mock_result.stdout = "123\n"
    mock_run.return_value = mock_result

    mock_process = MagicMock()
    mock_process.name.return_value = "python"
    mock_process.cmdline.return_value = ["omlx", "serve"]
    mock_process_cls.return_value = mock_process

    assert OMLXEngine().get_server_pid() == 123
    assert "-sTCP:LISTEN" in mock_run.call_args.args[0]

@patch("subprocess.run")
def test_omlx_get_version_uses_cli_version_flag(mock_run):
    mock_result = MagicMock()
    mock_result.stdout = "omlx 0.4.1\n"
    mock_result.stderr = ""
    mock_result.returncode = 0
    mock_run.return_value = mock_result

    assert OMLXEngine().get_version() == "0.4.1"
    assert mock_run.call_args.args[0] == ["omlx", "--version"]
    assert mock_run.call_args.kwargs["timeout"] == 3

@patch("subprocess.run")
def test_omlx_get_version_falls_back_to_serve_help(mock_run):
    empty_result = MagicMock()
    empty_result.stdout = ""
    empty_result.stderr = ""
    empty_result.returncode = 2
    help_result = MagicMock()
    help_result.stdout = "Usage: omlx serve\nVersion: 0.3.9\n"
    help_result.stderr = ""
    help_result.returncode = 0
    mock_run.side_effect = [empty_result, help_result]

    assert OMLXEngine().get_version() == "0.3.9"
    assert [call.args[0] for call in mock_run.call_args_list] == [
        ["omlx", "--version"],
        ["omlx", "serve", "--help"],
    ]

@patch("httpx.get")
@patch("subprocess.run")
def test_omlx_get_version_falls_back_to_models_metadata(mock_run, mock_get):
    failed_result = MagicMock()
    failed_result.stdout = ""
    failed_result.stderr = ""
    failed_result.returncode = 2
    mock_run.return_value = failed_result

    mock_response = MagicMock()
    mock_response.json.return_value = {"engine_version": "0.5.1"}
    mock_get.return_value = mock_response

    assert OMLXEngine().get_version() == "0.5.1"
    assert mock_get.call_args.args[0] == "http://localhost:8000/v1/models"

@patch("subprocess.run")
def test_ollama_get_version(mock_run):
    mock_result = MagicMock()
    mock_result.stdout = "ollama version is 0.24.0\n"
    mock_run.return_value = mock_result

    engine = OllamaEngine()
    assert engine.get_version() == "0.24.0"

@patch("subprocess.run")
def test_rapid_mlx_get_version_uses_timeout(mock_run):
    mock_result = MagicMock()
    mock_result.stdout = "rapid-mlx 0.6.68\n"
    mock_result.stderr = ""
    mock_run.return_value = mock_result

    assert RapidMLXEngine().get_version() == "0.6.68"
    assert mock_run.call_args.kwargs["timeout"] == 3


@patch("subprocess.run")
def test_rapid_mlx_get_version_accepts_plain_version(mock_run):
    mock_result = MagicMock()
    mock_result.stdout = "0.6.68\n"
    mock_result.stderr = ""
    mock_run.return_value = mock_result

    assert RapidMLXEngine().get_version() == "0.6.68"

@patch("httpx.get")
def test_rapid_mlx_resolve_model_id(mock_get):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [{"id": "local/model/test"}]
    }
    mock_get.return_value = mock_response

    engine = RapidMLXEngine()
    resolved = engine._resolve_model_id("test")
    assert resolved == "local/model/test"
    assert engine._model_id_cache["test"] == "local/model/test"

@patch("httpx.get")
def test_rapid_mlx_model_id_cache_is_instance_scoped(mock_get):
    shared_cache = {"test": "local/model/test"}

    cached_engine = RapidMLXEngine(model_id_cache=shared_cache)
    assert cached_engine._resolve_model_id("test") == "local/model/test"
    mock_get.assert_not_called()

    fresh_engine = RapidMLXEngine()
    assert fresh_engine._model_id_cache == {}

@patch("mlx_chronos.engines.os.path.exists", return_value=True)
def test_rapid_mlx_request_model_name_caches_local_path_checks(mock_exists):
    engine = RapidMLXEngine()
    engine._resolve_model_id = MagicMock()

    assert engine._request_model_name("/models/test") == "/models/test"
    assert engine._request_model_name("/models/test") == "/models/test"

    mock_exists.assert_called_once_with("/models/test")
    engine._resolve_model_id.assert_not_called()

def test_rapid_mlx_request_model_name_caches_expanded_local_paths(monkeypatch):
    mock_exists = MagicMock(return_value=True)
    mock_expanduser = MagicMock(
        side_effect=lambda value: value.replace("~", "/Users/igor", 1)
    )
    monkeypatch.setattr("mlx_chronos.engines.os.path.exists", mock_exists)
    monkeypatch.setattr("mlx_chronos.engines.os.path.expanduser", mock_expanduser)

    engine = RapidMLXEngine()
    engine._resolve_model_id = MagicMock()

    assert engine._request_model_name("~/models/test") == "/Users/igor/models/test"
    assert (
        engine._request_model_name("/Users/igor/models/test")
        == "/Users/igor/models/test"
    )

    mock_exists.assert_called_once_with("/Users/igor/models/test")
    engine._resolve_model_id.assert_not_called()

@contextmanager
def mock_stream_response(*args, **kwargs):
    class MockResponse:
        def raise_for_status(self):
            pass
        def iter_lines(self):
            yield 'data: {"choices": [{"delta": {"role": "assistant"}}]}'
            yield 'data: {"choices": [{"delta": {"content": "Hello"}}]}'
            yield 'data: [DONE]'
    yield MockResponse()

@patch("httpx.stream", side_effect=mock_stream_response)
def test_measure_ttft_success(mock_stream):
    engine = OMLXEngine()
    with patch("time.perf_counter", side_effect=[0.0, 0.5]):
        ttft = engine.measure_ttft("hello")
        assert ttft == 0.5


@patch("httpx.stream")
def test_measure_ttft_uses_provided_http_client(mock_stream):
    client = MagicMock()
    client.stream.side_effect = mock_stream_response
    engine = OMLXEngine()

    with patch("time.perf_counter", side_effect=[0.0, 0.5]):
        ttft = engine.measure_ttft("hello", client=client)

    assert ttft == 0.5
    client.stream.assert_called_once()
    mock_stream.assert_not_called()


@contextmanager
def mock_stream_response_empty(*args, **kwargs):
    class MockResponse:
        def raise_for_status(self):
            pass
        def iter_lines(self):
            yield 'data: {"choices": [{"delta": {"role": "assistant"}}]}'
            yield 'data: [DONE]'
    yield MockResponse()

@patch("httpx.stream", side_effect=mock_stream_response_empty)
def test_measure_ttft_no_content_raises(mock_stream):
    engine = OMLXEngine()
    with pytest.raises(
        RuntimeError,
        match="stream ended before a valid content token was received",
    ):
        engine.measure_ttft("hello")
