from mlx_chronos.engines import MLXLMEngine, OMLXEngine


def test_stream_chunk_role_is_not_counted_as_content():
    engine = OMLXEngine()
    chunk = {"choices": [{"delta": {"role": "assistant"}}]}

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
    assert called["name"] == "mlx_lm"
