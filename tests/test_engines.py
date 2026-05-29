from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import httpx
import pytest

from mlx_chronos.constants import VALID_ENGINE_NAMES
from mlx_chronos.engines import (
    ENGINES, OMLXEngine, MLXLMEngine, RapidMLXEngine, OllamaEngine, get_engine
)

def http_error_response(method: str, url: str, status_code: int, text: str) -> httpx.Response:
    return httpx.Response(
        status_code,
        text=text,
        request=httpx.Request(method, url),
    )

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

@patch("httpx.post")
def test_measure_tokens_per_second(mock_post):
    mock_response = MagicMock()
    mock_response.json.return_value = {"usage": {"completion_tokens": 150}}
    mock_post.return_value = mock_response

    engine = OMLXEngine()
    with patch("time.perf_counter", side_effect=[0.0, 1.5]):
        tps = engine.measure_tokens_per_second("test prompt", "default", 100)
        assert tps == 100.0  # 150 tokens / 1.5s = 100.0
        assert engine.last_token_count_source == "usage.completion_tokens"

@patch("httpx.post")
def test_measure_tokens_per_second_marks_word_fallback(mock_post):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "one two three four"}}]
    }
    mock_post.return_value = mock_response

    engine = OMLXEngine()
    with patch("time.perf_counter", side_effect=[0.0, 2.0]):
        tps = engine.measure_tokens_per_second("test prompt", "default", 100)
        assert tps == 2.0
        assert engine.last_token_count_source == "word_fallback"

@patch("httpx.post", side_effect=httpx.TimeoutException("timed out"))
def test_measure_tokens_per_second_wraps_http_errors(mock_post):
    engine = OMLXEngine()
    with pytest.raises(RuntimeError, match="engine=omlx; action=measure throughput"):
        engine.measure_tokens_per_second("test prompt", "default", 100)

@patch("httpx.post")
def test_measure_tokens_per_second_reports_status_model_and_body(mock_post):
    mock_post.return_value = http_error_response(
        "POST",
        "http://localhost:8000/v1/chat/completions",
        404,
        '{"error":"model not found"}',
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

@patch("httpx.post")
def test_measure_tokens_per_second_rejects_invalid_json_shape(mock_post):
    mock_response = MagicMock()
    mock_response.json.return_value = []
    mock_post.return_value = mock_response

    engine = OMLXEngine()
    with patch("time.perf_counter", side_effect=[0.0, 1.0]):
        with pytest.raises(RuntimeError, match="completion response must be a JSON object"):
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
def test_ollama_get_version(mock_run):
    mock_result = MagicMock()
    mock_result.stdout = "ollama version is 0.24.0\n"
    mock_run.return_value = mock_result

    engine = OllamaEngine()
    assert engine.get_version() == "0.24.0"

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
