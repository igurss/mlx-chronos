import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest

from mlx_chronos.concurrency_profile import run_concurrency_profile
from mlx_chronos.engines import OMLXEngine


class LocalOMLXEngine(OMLXEngine):
    def __init__(self, base_url: str):
        super().__init__(port=1)
        self._base_url = base_url

    def base_url(self) -> str:
        return self._base_url

    def _server_identity_matches(self) -> bool:
        return True


@contextmanager
def openai_mock_server(
    models_payload: dict | None = None,
    models_status: int = 200,
    completion_payload: dict | None = None,
    completion_status: int = 200,
):
    requests = []
    state = {
        "models_payload": models_payload or {"data": [{"id": "org/test-model"}]},
        "models_status": models_status,
        "completion_payload": completion_payload
        or {
            "choices": [{"message": {"content": "ok from mock server"}}],
            "usage": {"completion_tokens": 7},
        },
        "completion_status": completion_status,
        "requests": requests,
    }

    class MockOpenAIHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_stream(self) -> None:
            body = (
                'data: {"choices": [{"delta": {"role": "assistant"}}]}\n\n'
                'data: {"choices": [{"delta": {"content": "hello"}}]}\n\n'
                'data: {"choices": [], "usage": {"completion_tokens": 7}}\n\n'
                "data: [DONE]\n\n"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            state["requests"].append({"method": "GET", "path": self.path})
            if self.path == "/v1/models":
                self._send_json(state["models_status"], state["models_payload"])
            else:
                self._send_json(404, {"error": "not found"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw_body.decode("utf-8"))
            state["requests"].append(
                {"method": "POST", "path": self.path, "payload": payload}
            )

            if self.path != "/v1/chat/completions":
                self._send_json(404, {"error": "not found"})
                return

            if state["completion_status"] != 200:
                self._send_json(
                    state["completion_status"],
                    {"error": "server exploded"},
                )
                return

            if payload.get("stream") is True:
                self._send_stream()
            else:
                self._send_json(200, state["completion_payload"])

    server = ThreadingHTTPServer(("127.0.0.1", 0), MockOpenAIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", requests
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_mock_openai_server_model_listing_and_completion_flow():
    with openai_mock_server() as (base_url, requests):
        engine = LocalOMLXEngine(base_url)

        assert engine.is_server_running() is True
        assert engine.list_model_ids() == ["org/test-model"]
        assert engine.validate_completion_request("org/test-model") == "org/test-model"

        tps = engine.measure_tokens_per_second("test prompt", "org/test-model")
        ttft = engine.measure_ttft("test prompt", "org/test-model")

    assert tps > 0
    assert ttft >= 0
    assert any(request["path"] == "/v1/models" for request in requests)
    assert any(
        request["path"] == "/v1/chat/completions"
        and request["payload"]["stream"] is False
        for request in requests
        if request["method"] == "POST"
    )
    assert any(
        request["path"] == "/v1/chat/completions"
        and request["payload"]["stream"] is True
        for request in requests
        if request["method"] == "POST"
    )


def test_concurrency_profile_sends_distinct_requests_to_a_real_http_server():
    with openai_mock_server() as (base_url, requests):
        engine = LocalOMLXEngine(base_url)
        with (
            patch("mlx_chronos.concurrency_profile.get_engine", return_value=engine),
            patch.object(engine, "is_installed", return_value=True),
            patch("mlx_chronos.concurrency_profile.detect_hardware", return_value={
                "chip": "Apple test", "memory_gb": 64, "macos_version": "test",
            }),
            patch("mlx_chronos.concurrency_profile.get_thermal_state", return_value="nominal"),
        ):
            report = run_concurrency_profile(
                "omlx", "org/test-model", levels=[2], trials_per_level=1,
                request_max_tokens=8,
            )

    post_requests = [
        request for request in requests
        if request["method"] == "POST" and request["path"] == "/v1/chat/completions"
    ]
    prompts = [request["payload"]["messages"][0]["content"] for request in post_requests]
    assert len(post_requests) == 4  # two unmeasured warm-up, two measured
    assert len(set(prompts)) == 4
    assert report["levels"][0]["waves"][0]["total_completion_tokens"] == 14
    assert report["levels"][0]["waves"][0]["cache_clear_confirmed"] is False


def test_mock_openai_server_malformed_model_response_raises():
    with openai_mock_server(models_payload={"data": {"id": "org/test-model"}}) as (
        base_url,
        _requests,
    ):
        engine = LocalOMLXEngine(base_url)

        with pytest.raises(RuntimeError, match="invalid model list"):
            engine.list_model_ids()


def test_mock_openai_server_malformed_completion_response_raises():
    with openai_mock_server(completion_payload={"choices": []}) as (
        base_url,
        _requests,
    ):
        engine = LocalOMLXEngine(base_url)

        with pytest.raises(RuntimeError, match="field 'choices' must be a non-empty list"):
            engine.validate_completion_request("org/test-model")


def test_mock_openai_server_completion_error_includes_context():
    with openai_mock_server(completion_status=500) as (base_url, _requests):
        engine = LocalOMLXEngine(base_url)

        with pytest.raises(RuntimeError) as exc:
            engine.measure_tokens_per_second("test prompt", "org/test-model")

    message = str(exc.value)
    assert "engine=omlx" in message
    assert "action=measure throughput" in message
    assert "url=" in message
    assert "status=500" in message
    assert "server exploded" in message
