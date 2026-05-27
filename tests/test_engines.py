import pytest
from unittest.mock import MagicMock, patch
from mlx_chronos.engines import (
    OMLXEngine, MLXLMEngine, RapidMLXEngine, OllamaEngine, get_engine
)

def test_stream_chunk_role_is_not_counted_as_content():
    engine = OMLXEngine()
    chunk = {"choices": [{"delta": {"role": "assistant"}}]}
    assert engine._stream_chunk_has_content(chunk) is False

def test_stream_chunk_whitespace_is_not_counted_as_content():
    engine = OMLXEngine()
    chunk = {"choices": [{"delta": {"content": "   "}}]}
    assert engine._stream_chunk_has_content(chunk) is False

def test_stream_chunk_text_content_is_counted():
    engine = OMLXEngine()
    chunk = {"choices": [{"delta": {"content": "Hello"}}]}
    assert engine._stream_chunk_has_content(chunk) is True

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

@patch("httpx.post")
def test_measure_tokens_per_second(mock_post):
    mock_response = MagicMock()
    mock_response.json.return_value = {"usage": {"completion_tokens": 150}}
    mock_post.return_value = mock_response
    
    engine = OMLXEngine()
    with patch("time.perf_counter", side_effect=[0.0, 1.5]):
        tps = engine.measure_tokens_per_second("test prompt", "default", 100)
        assert tps == 100.0  # 150 tokens / 1.5s = 100.0

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
    assert RapidMLXEngine._global_model_id_cache["test"] == "local/model/test"
