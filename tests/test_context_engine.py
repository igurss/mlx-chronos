from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import httpx
import pytest

from mlx_chronos.engines import OMLXEngine


def _stream_response(lines):
    response = MagicMock()
    response.iter_lines.return_value = lines
    return nullcontext(response)


def test_engine_reads_trailing_usage_without_moving_first_token_clock():
    engine = OMLXEngine()
    lines = [
        'data: {"choices": [{"delta": {"content": "a"}}]}',
        'data: {"usage": {"prompt_tokens": 512}}',
        'data: [DONE]',
    ]
    with patch.object(engine, "_stream_request", return_value=_stream_response(lines)) as req, \
         patch("mlx_chronos.engines.time.perf_counter", side_effect=[1.0, 1.4]):
        result = engine.measure_ttft_with_input_tokens("test")
    assert result.ttft_seconds == pytest.approx(0.4)
    assert result.input_tokens == 512
    assert result.input_token_count_source == "engine"
    assert req.call_args.kwargs["json"]["stream_options"] == {"include_usage": True}


def test_engine_rejects_noninteger_usage_instead_of_truncating_it():
    engine = OMLXEngine()
    lines = [
        'data: {"choices": [{"delta": {"content": "a"}}]}',
        'data: {"usage": {"prompt_tokens": 512.5}}',
    ]
    with patch.object(engine, "_stream_request", return_value=_stream_response(lines)), \
         patch("mlx_chronos.engines.time.perf_counter", side_effect=[1.0, 1.4]):
        result = engine.measure_ttft_with_input_tokens("test")
    assert result.input_tokens is None
    assert result.input_token_count_source == "unavailable"


def test_engine_retries_only_when_stream_usage_option_is_explicitly_rejected():
    engine = OMLXEngine()
    request = httpx.Request("POST", "http://localhost/v1/chat/completions")
    response = httpx.Response(
        400, json={"error": "unsupported stream_options"}, request=request,
    )
    rejected = MagicMock()
    rejected.raise_for_status.side_effect = httpx.HTTPStatusError(
        "unsupported stream_options", request=request, response=response,
    )
    accepted = _stream_response([
        'data: {"choices": [{"delta": {"content": "a"}}]}',
        'data: [DONE]',
    ])
    with patch.object(engine, "_stream_request", side_effect=[
        nullcontext(rejected), accepted,
    ]) as stream, patch("mlx_chronos.engines.time.perf_counter",
                        side_effect=[1.0, 2.0, 2.4]):
        result = engine.measure_ttft_with_input_tokens("test")
    assert result.ttft_seconds == pytest.approx(0.4)
    assert result.input_tokens is None
    assert stream.call_count == 2
    assert "stream_options" in stream.call_args_list[0].kwargs["json"]
    assert "stream_options" not in stream.call_args_list[1].kwargs["json"]
