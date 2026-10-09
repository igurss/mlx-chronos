"""Producer-to-public-loader contracts using real adapters and an in-memory HTTP transport."""
from copy import deepcopy
import json
import math
from unittest.mock import MagicMock

import httpx
import pytest

from mlx_chronos.benchmark import run_benchmark
from mlx_chronos.engines import OMLXEngine, MLXLMEngine, VLLMMLXEngine
from mlx_chronos.examples import EXAMPLE_RESULT
from mlx_chronos.submit import load_publishable_result


@pytest.mark.parametrize('counts', [[24] * 5, [24, None, None, None, None], [None] * 5])
@pytest.mark.parametrize('adapter', [OMLXEngine, MLXLMEngine, VLLMMLXEngine])
def test_adapter_observations_survive_benchmark_seal_and_public_loader(tmp_path, monkeypatch, counts, adapter):
    clock = [0.0]
    observed = iter(counts)

    class Completion(httpx.SyncByteStream):
        def __init__(self, tokens, input_tokens):
            self.tokens, self.input_tokens = tokens, input_tokens

        def __iter__(self):
            clock[0] += 0.0004
            yield b'data: {"choices":[{"delta":{"content":"word"}}],"system_fingerprint":"0.31.2-0.30.2-macOS-26.0-arm64-Metal4"}\n\n'
            clock[0] += 1.0004
            usage = {'completion_tokens': self.tokens}
            if self.input_tokens is not None:
                usage['prompt_tokens'] = self.input_tokens
            yield ('data: ' + json.dumps({'usage': usage}) + '\n\n').encode()
            yield b'data: [DONE]\n\n'

    def respond(request):
        payload = json.loads(request.content)
        tokens = payload['max_tokens']
        count = next(observed) if tokens == 100 else None
        return httpx.Response(200, stream=Completion(tokens, count))

    engine = adapter()
    for name, value in [('is_installed', True), ('is_server_running', True),
                        ('get_client_version', '9.8.7'), ('get_server_pid', None)]:
        monkeypatch.setattr(engine, name, lambda value=value: value)
    if adapter is OMLXEngine:
        monkeypatch.setattr(engine, 'get_version', lambda: '1.2.3')
    else:
        monkeypatch.setattr(engine, '_get_version_from_models_endpoint', lambda **kwargs: None)
        monkeypatch.setattr(engine, '_get_version_from_server_process',
                            lambda: '1.2.3' if adapter is VLLMMLXEngine else None)
    monkeypatch.setattr(engine, 'http_client', lambda: httpx.Client(transport=httpx.MockTransport(respond)))
    monkeypatch.setattr('mlx_chronos.benchmark.get_engine', lambda _: engine)
    monkeypatch.setattr('mlx_chronos.benchmark.detect_hardware', lambda: deepcopy(EXAMPLE_RESULT['hardware']))
    monkeypatch.setattr('mlx_chronos.benchmark.time.perf_counter', lambda: clock[0])

    class Thermal:
        def __init__(self, **kwargs):
            self.started = clock[0]
        def start(self):
            pass
        def set_phase(self, phase):
            pass
        def stop(self):
            summary = deepcopy(EXAMPLE_RESULT['meta']['thermal_monitor'])
            span = clock[0] - self.started
            summary.update(sample_span_seconds=span, samples=math.ceil(span) + 1)
            return summary

    ram = MagicMock(sample_errors=0)
    ram.stop.return_value = (4.0, 50.0)
    ram.occupancy_summary.return_value = {}
    monkeypatch.setattr('mlx_chronos.benchmark.ThermalStateTracker', Thermal)
    monkeypatch.setattr('mlx_chronos.benchmark.SystemRAMTracker', lambda **kwargs: ram)
    model_name = 'default_model' if adapter is MLXLMEngine else 'model'
    result = run_benchmark(engine.name, model_name, '4bit', model_reference_url='https://huggingface.co/org/model')
    path = tmp_path / 'result.json'
    path.write_text(json.dumps(result))
    _, parsed = load_publishable_result(path)
    assert parsed.meta.benchmark_protocol.throughput.input_tokens == (counts if any(counts) else None)
    assert parsed.engine.version == ('0.31.2' if adapter is MLXLMEngine else '1.2.3')
    assert parsed.engine.version_source == ('process_package' if adapter is VLLMMLXEngine else 'server_api')
    assert parsed.engine.client_version == '9.8.7'
    assert parsed.trials.ttft_cold_raw[0] == pytest.approx(0.0004)
    assert parsed.trials.tokens_per_second_raw[0] == pytest.approx(100 / 1.0008)
