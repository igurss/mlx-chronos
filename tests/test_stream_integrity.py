"""Transport regressions with real keep-alive and adversarial SSE bodies."""
import json
import threading
import time
from contextlib import contextmanager, nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import httpx
import pytest

from mlx_chronos.engines import OMLXEngine


@contextmanager
def keepalive_server():
    class Server(ThreadingHTTPServer):
        daemon_threads = True
        connections = 0
        requests = 0

        def get_request(self):
            value = super().get_request()
            self.connections += 1
            return value

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.server.requests += 1
            if request["messages"][0]["content"] == "reject usage" and "stream_options" in request:
                parts = [b'{"error":"stream_options.include_usage unsupported"}']
                self.send_response(400)
            else:
                parts = [b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n',
                         b'data: {"usage":{"completion_tokens":100,"prompt_tokens":50}}\n\n'
                         b'data: [DONE]\n\n', b': trailing heartbeat\n\n']
                self.send_response(200)
            self.send_header("Content-Length", str(sum(map(len, parts))))
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for index, part in enumerate(parts):
                self.wfile.write(part)
                self.wfile.flush()
                if index + 1 < len(parts):
                    # Neither the first token nor DONE arrives with HTTP EOF.
                    time.sleep(0.005)

    server = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    engine = OMLXEngine(port=server.server_port)
    engine.base_url = lambda: f"http://127.0.0.1:{server.server_port}/v1"
    try:
        yield server, engine
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("method", ["measure_ttft", "measure_ttft_with_input_tokens", "measure_throughput"])
def test_persistent_measurements_reuse_the_tcp_connection(method):
    with keepalive_server() as (server, engine), engine.http_client() as client:
        for _ in range(3):
            value = getattr(engine, method)("normal", model="fake", client=client)
            if method == "measure_throughput":
                assert value.input_tokens == 50
                assert value.completion_tokens == 100
        assert server.requests == 3
        assert server.connections == 1


def test_context_usage_fallback_reads_the_open_http_error_body():
    with keepalive_server() as (server, engine), engine.http_client() as client:
        value = engine.measure_ttft_with_input_tokens("reject usage", model="fake", client=client)
        assert value.input_tokens == 50
        assert server.requests == 2


def stream_client(lines):
    body = "\n\n".join("data: " + line for line in lines).encode()
    return httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body)))


CONTENT = '{"choices":[{"delta":{"content":"hello"}}]}'
USAGE = '{"usage":{"completion_tokens":100}}'


@pytest.mark.parametrize("method", ["measure_ttft", "measure_ttft_with_input_tokens", "measure_throughput"])
@pytest.mark.parametrize("tail,match", [
    ([USAGE], "without a completion marker"),
    ([USAGE, '{"error":{"message":"failed"}}'], "stream error"),
    (["{broken", "[DONE]"], "malformed"),
    (["[DONE]", CONTENT], "after stream completion"),
])
def test_failed_or_partial_stream_never_returns_a_measurement(method, tail, match):
    with stream_client([CONTENT, *tail]) as client:
        with pytest.raises(RuntimeError, match=match):
            getattr(OMLXEngine(), method)("fake", client=client)


def test_finish_reason_allows_a_complete_stream_without_done():
    finish = '{"choices":[{"delta":{},"finish_reason":"stop"}]}'
    response = httpx.Response(200, request=httpx.Request("POST", "http://localhost"),
        content="\n\n".join("data: " + line for line in [CONTENT, USAGE, finish]))
    engine = OMLXEngine()
    with patch.object(engine, "_stream_request", return_value=nullcontext(response)), patch(
        "mlx_chronos.engines.time.perf_counter", side_effect=[0, 0.2, 1],
    ):
        value = engine.measure_throughput("fake")
    assert value.elapsed_seconds == 1
    assert value.finish_reason == "stop"


def test_ttft_clock_stops_before_draining_late_chunks():
    response = httpx.Response(200, request=httpx.Request("POST", "http://localhost"),
        content="\n\n".join("data: " + line for line in [CONTENT, USAGE, "[DONE]"]))
    engine = OMLXEngine()
    with patch.object(engine, "_stream_request", return_value=nullcontext(response)), patch(
        "mlx_chronos.engines.time.perf_counter", side_effect=[0, 0.125],
    ):
        assert engine.measure_ttft("fake") == 0.125


def test_stream_deadline_bounds_continuous_heartbeats():
    response = httpx.Response(200, request=httpx.Request("POST", "http://localhost"),
        content=": heartbeat\n\n: heartbeat\n\n")
    engine = OMLXEngine()
    with patch.object(engine, "_stream_request", return_value=nullcontext(response)), patch(
        "mlx_chronos.engines.time.monotonic", side_effect=[0, 1, 31],
    ):
        with pytest.raises(RuntimeError, match="deadline exceeded"):
            engine.measure_ttft("fake")


def test_estimated_words_preserve_boundaries_between_chunks():
    fragments = ["hel", "lo\tworld", "\u2003", "next", " word\n", "last"]
    lines = [json.dumps({"choices": [{"delta": {"content": text}}]}) for text in fragments]
    with stream_client([*lines, "[DONE]"]) as client:
        value = OMLXEngine().measure_throughput("fake", client=client, progress_sample_interval_tokens=2)
    assert value.completion_tokens == len("".join(fragments).split()) == 5
    assert value.token_count_source == "word_fallback"
