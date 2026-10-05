"""ddalcu/mlx-serve contracts: exact routing, native backend and SSE usage.

Model/load/version shapes follow upstream server.zig at
0f01d299d3d7759a7222b2117567053b6d350b89. No inference is needed for discovery.
"""
from copy import deepcopy
import json
from subprocess import CompletedProcess
from unittest.mock import patch

import httpx
import pytest

from mlx_chronos.engines import MLXServeEngine, get_engine
from mlx_chronos.examples import EXAMPLE_RESULT
from mlx_chronos.measurements import validate_throughput_measurement
from mlx_chronos.schema import BenchmarkResult
from mlx_chronos.submit import SubmissionError, validate_publishable_result


MODEL = "mlx-community/test-model-4bit"


def model_entry(backend="mlx", *, loaded=True):
    return {
        "id": MODEL, "object": "model", "owned_by": "mlx-serve",
        "loaded": loaded, "state": "ready" if loaded else "unloaded",
        "capabilities": ["chat", "streaming"], "input_modalities": ["text"],
        "batched_decode": False,
        "meta": {
            "engine": backend, "quantization": "4-bit", "context_length": 8192,
            "model_max_tokens": 32768, "drafter_loaded": False,
            "drafter_path": "/private/model/drafter", "mtp_loaded": False,
            "mtp_available": True, "spec_exact": True, "kv_quant": "8",
            "gen_temperature": 0.7, "gen_top_p": 0.8, "gen_top_k": 20,
        },
    }


def test_ready_safetensors_backend_and_configuration(monkeypatch):
    engine = get_engine("mlx-serve")
    entry = model_entry()
    monkeypatch.setattr(engine, "_model_entries", lambda: [entry])
    with patch.object(engine, "_http_post", side_effect=AssertionError("already loaded")):
        assert engine.validate_model_backend(MODEL) == {"format": "safetensors", "quantization": "4-bit"}
    assert engine.observed_serving_configuration(MODEL) == {
        "backend": "mlx", "context_length": 8192, "model_max_tokens": 32768,
        "drafter_loaded": False, "mtp_loaded": False, "mtp_available": True,
        "spec_exact": True, "batched_decode": False, "kv_quant": "8",
    }
    assert engine.observed_serving_configuration("different-model") == {}
    assert engine.clear_cache_for_benchmark() is False
    assert engine.prefix_cache_hit_count() is None


@pytest.mark.parametrize("backend", ["gguf", "mlx-gguf", "llama", "ds4", "unknown", None, [], {}])
@pytest.mark.parametrize("loaded", [False, True])
def test_gguf_non_mlx_or_missing_backend_rejected_before_loading_or_inference(monkeypatch, backend, loaded):
    engine = MLXServeEngine()
    monkeypatch.setattr(engine, "_model_entries", lambda: [model_entry(backend, loaded=loaded)])
    with patch.object(engine, "_http_post", side_effect=AssertionError("must not load")), \
         patch.object(engine, "_stream_request", side_effect=AssertionError("must not infer")), \
         pytest.raises(RuntimeError, match="only MLX safetensors"):
        engine.validate_model_backend(MODEL)
    assert engine.observed_serving_configuration(MODEL) == {}


@pytest.mark.parametrize("changes", [
    {"lan_peer": "another-mac"}, {"provider": "remote-provider"},
    {"owned_by": "other-server"}, {"state": "remote"},
    {"capabilities": ["embedding"]}, {"capabilities": None},
])
def test_remote_and_non_chat_entries_rejected(monkeypatch, changes):
    engine = MLXServeEngine()
    entry = model_entry(loaded=False)
    entry.update(changes)
    monkeypatch.setattr(engine, "_model_entries", lambda: [entry])
    with patch.object(engine, "_http_post", side_effect=AssertionError("must not load")), \
         pytest.raises(RuntimeError, match="local MLX|chat capability"):
        engine.validate_model_backend(MODEL)


@pytest.mark.parametrize("entries,requested", [
    ([model_entry()], "test-model-4bit"), ([model_entry()], "default"),
    ([model_entry(), model_entry()], MODEL), ([], MODEL),
])
def test_aliases_default_and_ambiguous_ids_cannot_silently_route(monkeypatch, entries, requested):
    engine = MLXServeEngine()
    monkeypatch.setattr(engine, "_model_entries", lambda: entries)
    assert engine.resolve_listed_model_id(requested, [e["id"] for e in entries]) is None
    with pytest.raises(RuntimeError, match="exact, unambiguous ID"):
        engine.validate_model_backend(requested)


@pytest.mark.parametrize("backend", ["mlx", "mlx-gguf", "gguf", "llama", "ds4"])
def test_unloaded_mlx_requires_safetensors_backend_after_strict_load(monkeypatch, backend):
    engine = MLXServeEngine()
    with patch.object(engine, "_model_entries", side_effect=[
        [model_entry("mlx", loaded=False)], [model_entry(backend)],
    ]), patch.object(engine, "_server_json", return_value={"model": {"id": MODEL}}) as load:
        if backend != "mlx":
            with pytest.raises(RuntimeError, match="no ready local MLX safetensors"):
                engine.validate_model_backend(MODEL)
        else:
            assert engine.validate_model_backend(MODEL)["format"] == "safetensors"
    load.assert_called_once_with(
        "/v1/load-model", action="load exact model", model=MODEL, payload={"model": MODEL},
    )


@pytest.mark.parametrize("load_response", [{}, {"model": []}, {"model": {"id": "wrong-model"}}])
def test_load_response_must_confirm_requested_id(monkeypatch, load_response):
    engine = MLXServeEngine()
    monkeypatch.setattr(engine, "_model_entries", lambda: [model_entry(loaded=False)])
    monkeypatch.setattr(engine, "_server_json", lambda *a, **kw: load_response)
    with pytest.raises(RuntimeError, match="exact requested model"):
        engine.validate_model_backend(MODEL)


def test_still_unloaded_after_load_and_stale_evidence_rejected(monkeypatch):
    engine = MLXServeEngine()
    entry = model_entry()
    monkeypatch.setattr(engine, "_model_entries", lambda: [entry])
    engine.validate_model_backend(MODEL)
    entry = model_entry(loaded=False)
    monkeypatch.setattr(engine, "_server_json", lambda *a, **kw: {"model": {"id": MODEL}})
    with pytest.raises(RuntimeError, match="no ready local MLX"):
        engine.validate_model_backend(MODEL)
    assert engine.observed_serving_configuration(MODEL) == {}


@pytest.mark.parametrize("quantization", ["0-bit", "16-bit", "Q4_K_M", None])
def test_metadata_does_not_invent_fp16_bf16_or_gguf_quantization(monkeypatch, quantization):
    engine = MLXServeEngine()
    entry = model_entry()
    entry["meta"]["quantization"] = quantization
    monkeypatch.setattr(engine, "_model_entries", lambda: [entry])
    assert engine.validate_model_backend(MODEL) == {"format": "safetensors"}


def test_optional_metadata_does_not_turn_unknown_values_into_observations(monkeypatch):
    engine = MLXServeEngine()
    entry = model_entry()
    entry["batched_decode"] = 1
    entry["meta"] = {
        "engine": "mlx", "context_length": True, "model_max_tokens": 0,
        "drafter_loaded": "false", "mtp_available": 1, "kv_quant": "unverified",
    }
    monkeypatch.setattr(engine, "_model_entries", lambda: [entry])
    engine.validate_model_backend(MODEL)
    assert engine.observed_serving_configuration(MODEL) == {"backend": "mlx"}


@pytest.mark.parametrize("body,error", [
    ("not JSON", "invalid JSON"), ("[]", "JSON object"),
    ('{"data": {}}', "must be a list"),
    ('{"data": [false]}', "model objects"),
])
def test_bad_models_response_has_engine_endpoint_context(monkeypatch, body, error):
    engine = MLXServeEngine()
    response = httpx.Response(200, text=body, request=httpx.Request("GET", engine.base_url() + "/models"))
    monkeypatch.setattr(engine, "_http_get", lambda *a, **kw: response)
    with pytest.raises(RuntimeError, match=error) as caught:
        engine.validate_model_backend(MODEL)
    assert "engine=mlx-serve" in str(caught.value)
    assert "/v1/models" in str(caught.value)
    assert engine._server_identity_matches() is False


def test_load_memory_failure_preserves_server_reason_and_no_observation(monkeypatch):
    engine = MLXServeEngine()
    monkeypatch.setattr(engine, "_model_entries", lambda: [model_entry(loaded=False)])
    response = httpx.Response(503, json={"error": {
        "type": "out_of_memory", "message": "Not enough free memory to load model",
    }}, request=httpx.Request("POST", engine.base_url() + "/load-model"))
    monkeypatch.setattr(engine, "_http_post", lambda *a, **kw: response)
    with pytest.raises(RuntimeError, match="Not enough free memory") as caught:
        engine.validate_model_backend(MODEL)
    assert "status=503" in str(caught.value)
    assert MODEL in str(caught.value)
    assert engine.observed_serving_configuration(MODEL) == {}


def test_live_version_uses_api_and_never_substitutes_path_binary(monkeypatch):
    engine = MLXServeEngine()
    monkeypatch.setattr(engine, "_model_entries", lambda: [model_entry()])
    with patch("mlx_chronos.engines.subprocess.run", side_effect=AssertionError("wrong binary")):
        monkeypatch.setattr(engine, "_server_json", lambda *a, **kw: {"version": "26.10.1"})
        assert engine.get_version() == "26.10.1"
        monkeypatch.setattr(engine, "_server_json", lambda *a, **kw: {})
        assert engine.get_version() == "unknown"
        monkeypatch.setattr(engine, "_server_json", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("offline")))
        assert engine.get_version() == "unknown"


@pytest.mark.parametrize("output,expected", [
    ("mlx-serve 26.10.1\nmlx 0.32.0\nllama.cpp b9999\n", "26.10.1"),
    ("mlx-serve unknown\nmlx 0.32.0\n", "unknown"),
    ("mlx 0.32.0\n", "unknown"),
])
def test_offline_version_does_not_take_mlx_library_version(monkeypatch, output, expected):
    engine = MLXServeEngine()
    monkeypatch.setattr(engine, "_server_identity_matches", lambda: False)
    monkeypatch.setattr(engine, "_binary_path", lambda: "/tmp/mlx-serve")
    with patch("mlx_chronos.engines.subprocess.run", return_value=CompletedProcess([], 0, output, "")):
        assert engine.get_version() == expected


def test_installation_and_server_identity_use_native_evidence(monkeypatch):
    engine = MLXServeEngine()
    monkeypatch.setattr(engine, "_binary_path", lambda: None)
    monkeypatch.setattr(engine, "_model_entries", lambda: [{"owned_by": "other-engine"}])
    assert engine.is_installed() is False
    monkeypatch.setattr(engine, "_model_entries", lambda: [model_entry()])
    assert engine.is_installed() is True
    monkeypatch.setattr(engine, "_model_entries", lambda: [])
    monkeypatch.setattr(engine, "get_server_pid", lambda: None)
    assert engine._server_identity_matches() is False
    monkeypatch.setattr(engine, "get_server_pid", lambda: 42)
    assert engine._server_identity_matches() is True


def test_app_bundle_binary_can_be_detected_without_path(monkeypatch):
    engine = MLXServeEngine()
    expected = "/Applications/MLX-Serve.app/Contents/MacOS/mlx-serve"
    monkeypatch.setattr("mlx_chronos.engines.shutil.which", lambda *a: None)
    monkeypatch.setattr("mlx_chronos.engines.os.path.isfile", lambda path: path == expected)
    monkeypatch.setattr("mlx_chronos.engines.os.access", lambda *a: True)
    assert engine._binary_path() == expected


def test_loaded_inventory_is_read_only_and_excludes_remote_rows(monkeypatch):
    engine = MLXServeEngine()
    unloaded = model_entry(loaded=False)
    unloaded["id"] = "unloaded"
    remote = model_entry()
    remote.update(id="model@peer", lan_peer="peer")
    monkeypatch.setattr(engine, "_model_entries", lambda: [model_entry(), unloaded, remote])
    with patch.object(engine, "_http_post", side_effect=AssertionError("must not load")):
        assert engine.list_loaded_model_ids() == [MODEL]
        del unloaded["loaded"]
        assert engine.list_loaded_model_ids() is None
        monkeypatch.setattr(engine, "_model_entries", lambda: [])
        assert engine.list_loaded_model_ids() == []


@pytest.mark.parametrize("backend,format_,accepted", [
    ("mlx", "safetensors", True), ("mlx-gguf", "gguf", False),
    ("mlx", "gguf", False), ("mlx-gguf", "safetensors", False),
    ("gguf", "gguf", False), ("llama", "gguf", False), ("ds4", "gguf", False), (None, "safetensors", False),
])
def test_public_submission_requires_observed_native_backend_and_matching_format(backend, format_, accepted):
    data = deepcopy(EXAMPLE_RESULT)
    data["engine"].update(name="mlx-serve", version="26.10.1", serving_config={
        "observed": {"backend": backend} if backend else {},
        "declared": {"backend": "mlx"},
    })
    data["model"]["format"] = format_
    result = BenchmarkResult.model_validate(data)
    if accepted:
        validate_publishable_result(result)
    else:
        with pytest.raises(SubmissionError, match="API-observed native MLX"):
            validate_publishable_result(result)


@pytest.fixture
def mlx_serve_contract_transport():
    """Upstream HTTP contract via HTTPX, portable without a socket/GPU dependency."""
    state = {"loaded": False, "requests": []}
    engine = MLXServeEngine()

    def handle(request):
        payload = json.loads(request.content) if request.content else None
        path = request.url.path
        state["requests"].append((request.method, path, payload))
        if path == "/api/version":
            return httpx.Response(200, json={"version": "26.10.1"})
        if path == "/v1/models":
            return httpx.Response(200, json={"object": "list", "data": [model_entry(loaded=state["loaded"])]})
        if path == "/v1/load-model":
            state["loaded"] = True
            return httpx.Response(200, json={"model": {"id": MODEL, "loaded": True, "state": "ready"}})
        if path == "/v1/chat/completions":
            if not payload.get("stream"):
                return httpx.Response(200, json={"model": MODEL, "system_fingerprint": "mlx-serve",
                                               "choices": [{"message": {"content": "ok"}}]})
            chunks = [
                {"choices": [{"delta": {"role": "assistant"}}]},
                {"choices": [{"delta": {"reasoning_content": "think "}}]},
                {"choices": [{"delta": {"content": "ok"}}]},
                {"choices": [{"delta": {}, "finish_reason": "length"}]},
                {"choices": [], "usage": {"completion_tokens": 7, "prompt_tokens": 11}},
            ]
            return httpx.Response(200, text="".join("data: " + json.dumps(c) + "\n\n" for c in chunks)
                                  + "data: [DONE]\n\n", headers={"Content-Type": "text/event-stream"})
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client, \
         patch("mlx_chronos.engines.httpx.get", side_effect=client.get), \
         patch("mlx_chronos.engines.httpx.post", side_effect=client.post):
        yield engine, client, state["requests"]


def test_http_discovery_load_and_measurement_flow(mlx_serve_contract_transport):
    engine, client, requests = mlx_serve_contract_transport
    assert engine.is_server_running() is True
    assert engine.list_model_ids() == [MODEL]
    assert not any(method == "POST" for method, _, _ in requests)
    assert engine.get_version() == "26.10.1"
    assert engine.validate_model_backend(MODEL)["format"] == "safetensors"
    assert engine.validate_completion_request(MODEL) == MODEL
    throughput = engine.measure_throughput("A prompt", MODEL, max_tokens=7, client=client)
    context_ttft = engine.measure_ttft_with_input_tokens("A prompt", MODEL, client=client)
    validate_throughput_measurement(throughput, max_tokens=7)
    assert throughput.completion_tokens == 7
    assert throughput.token_count_source == "usage.completion_tokens"
    assert throughput.finish_reason == "length"
    assert context_ttft.input_tokens == 11
    assert context_ttft.input_token_count_source == "engine"
    loads = [payload for _, path, payload in requests if path == "/v1/load-model"]
    assert loads == [{"model": MODEL}]
    streams = [payload for _, path, payload in requests
               if path == "/v1/chat/completions" and payload["stream"]]
    assert all(p["model"] == MODEL and p["temperature"] == 0 and p["top_p"] == 1 for p in streams)
    assert all(p["stream_options"] == {"include_usage": True} for p in streams)
