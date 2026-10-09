from hashlib import sha256
import json
from unittest.mock import patch

from mlx_chronos.numeric import is_finite_number
from mlx_chronos.reproducibility import client_environment
from mlx_chronos.schema import ClientEnvironment
from mlx_chronos.stats import compute_stats


def test_client_environment_contains_versions_without_paths_or_a_second_seal():
    with patch('mlx_chronos.reproducibility.importlib.metadata.version', return_value='1.2.3'):
        result = client_environment()
    assert set(result) == {'dependencies'}
    assert all('/' not in name + version for name, version in result['dependencies'].items())
    ClientEnvironment.model_validate(result)


def test_early_client_fingerprints_remain_readable():
    dependencies = {'httpx': '0.28.1'}
    digest = sha256(json.dumps(dependencies, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    ClientEnvironment.model_validate({'dependencies': dependencies, 'sha256': digest})


def test_numeric_predicate_handles_oversized_integers():
    assert not is_finite_number(10 ** 10000)
    assert not is_finite_number(True)
    assert is_finite_number(0.0004)


def test_unrounded_summary_preserves_submillisecond_dispersion():
    result = compute_stats([0.0004, 0.0005], round_digits=None)
    assert result['mean'] > 0
    assert result['stddev'] > 0
    assert result['min'] == 0.0004 and result['max'] == 0.0005
