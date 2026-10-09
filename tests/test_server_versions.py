"""Version evidence must belong to the listener, never the benchmark client."""
import os
from pathlib import Path
import select
import subprocess
import sys
import time
from unittest.mock import MagicMock

import psutil
import pytest

from mlx_chronos.server_versions import process_package_version


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / 'server environment'
    (root / 'bin').mkdir(parents=True)
    python = root / 'bin' / 'python'
    python.symlink_to(sys.executable)
    (root / 'pyvenv.cfg').write_text(
        f'include-system-site-packages = false\nversion = {sys.version.split()[0]}\n'
    )
    site = root / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
    distribution = site / 'vllm_mlx-1.2.3.dist-info'
    distribution.mkdir(parents=True)
    metadata = distribution / 'METADATA'
    metadata.write_text('Metadata-Version: 2.1\nName: vllm-mlx\nVersion: 1.2.3\n')
    os.utime(metadata, (time.time() - 60, time.time() - 60))
    script = root / 'bin' / 'vllm-mlx'
    # Spaces in an explicit quoted shebang are supported without executing it.
    script.write_text(f'#!"{python}"\nimport sys\nprint("ready", flush=True)\nsys.stdin.read(1)\n')
    return python, site, distribution


@pytest.fixture
def process(monkeypatch, installation):
    python, _, _ = installation
    process = MagicMock()
    process.create_time.return_value = time.time()
    process.cmdline.return_value = [str(python), '-m', 'vllm_mlx.server', '--port', '8000']
    process.exe.return_value = str(Path(sys.executable).resolve())
    process.is_running.return_value = True
    monkeypatch.setattr('mlx_chronos.server_versions.psutil.Process', lambda _: process)
    return process


@pytest.mark.parametrize('launch', ['module', 'console', 'python-script'])
def test_reads_identified_environment_without_running_its_python(installation, process, launch, monkeypatch):
    python, _, _ = installation
    if launch == 'console':
        process.cmdline.return_value = [str(python.parent / 'vllm-mlx'), 'serve']
    elif launch == 'python-script':
        process.cmdline.return_value = [str(python), str(python.parent / 'vllm-mlx'), 'serve']
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('Must not execute target Python'))
    assert process_package_version(42, 'vllm-mlx') == '1.2.3'
    assert process_package_version(42, 'mlx-lm') is None


@pytest.mark.parametrize('problem', [
    'system-site', 'missing-config', 'duplicate', 'editable', 'changed-after-start',
    'wrong-name', 'invalid-version', 'duplicate-version', 'metadata-symlink', 'oversized',
    'dead', 'pid-reused', 'command-changed', 'wrong-executable', 'relative-python',
    'code-launch', 'no-site', 'different-module', 'malformed-direct-url',
])
def test_ambiguous_or_stale_installations_remain_unknown(installation, process, problem, tmp_path):
    python, site, distribution = installation
    metadata = distribution / 'METADATA'
    root = python.parent.parent
    if problem == 'system-site':
        config = root / 'pyvenv.cfg'
        config.write_text(config.read_text().replace('false', 'true'))
    elif problem == 'missing-config':
        (root / 'pyvenv.cfg').unlink()
    elif problem == 'duplicate':
        (site / 'vllm_mlx-9.8.7.dist-info').mkdir()
    elif problem == 'editable':
        (distribution / 'direct_url.json').write_text('{"dir_info":{"editable":true}}')
    elif problem == 'changed-after-start':
        os.utime(metadata, (time.time() + 100, time.time() + 100))
    elif problem in {'wrong-name', 'invalid-version', 'duplicate-version', 'oversized'}:
        metadata.write_text({
            'wrong-name': 'Name: other\nVersion: 1.2.3\n',
            'invalid-version': 'Name: vllm-mlx\nVersion: latest\n',
            'duplicate-version': 'Name: vllm-mlx\nVersion: 1.2.3\nVersion: 9.8.7\n',
            'oversized': 'x' * 65_537,
        }[problem])
        os.utime(metadata, (time.time() - 60, time.time() - 60))
    elif problem == 'metadata-symlink':
        outside = tmp_path / 'outside'
        metadata.rename(outside)
        metadata.symlink_to(outside)
    elif problem == 'dead':
        process.is_running.return_value = False
    elif problem == 'pid-reused':
        process.create_time.side_effect = [time.time(), time.time() + 1]
    elif problem == 'command-changed':
        process.cmdline.side_effect = [process.cmdline.return_value, ['another-server']]
    elif problem == 'wrong-executable':
        process.exe.return_value = '/bin/sh'
    elif problem == 'relative-python':
        process.cmdline.return_value = ['python', '-m', 'vllm_mlx']
    elif problem == 'code-launch':
        process.cmdline.return_value = [str(python), '-c', 'import vllm_mlx']
    elif problem == 'no-site':
        process.cmdline.return_value = [str(python), '-S', '-m', 'vllm_mlx']
    elif problem == 'different-module':
        process.cmdline.return_value = [str(python), '-m', 'other', 'vllm_mlx']
    elif problem == 'malformed-direct-url':
        (distribution / 'direct_url.json').write_text('{"dir_info":null}')
    assert process_package_version(42, 'vllm-mlx') is None


def test_inaccessible_process_is_unknown(monkeypatch):
    def denied(_):
        raise psutil.AccessDenied(42)
    monkeypatch.setattr('mlx_chronos.server_versions.psutil.Process', denied)
    assert process_package_version(42, 'vllm-mlx') is None


def test_replaced_metadata_with_preserved_mtime_is_not_server_version(installation, process):
    _, _, distribution = installation
    metadata = distribution / 'METADATA'
    # A copied/restored installation can retain an old modification time even
    # though its package metadata was replaced after the listener started.
    process.create_time.return_value = metadata.stat().st_ctime - 1
    original_mtime = metadata.stat().st_mtime
    metadata.write_text('Name: vllm-mlx\nVersion: 9.8.7\n')
    os.utime(metadata, (original_mtime, original_mtime))
    assert metadata.stat().st_mtime < process.create_time.return_value
    assert metadata.stat().st_ctime > process.create_time.return_value
    assert process_package_version(42, 'vllm-mlx') is None


def test_uv_configuration_identifies_the_same_isolated_environment(installation, process):
    python, _, _ = installation
    config = python.parent.parent / 'pyvenv.cfg'
    config.write_text(config.read_text().replace('version =', 'version_info ='))
    assert process_package_version(42, 'vllm-mlx') == '1.2.3'
    config.write_text(config.read_text() + '\nversion = 3.10.0\n')
    assert process_package_version(42, 'vllm-mlx') is None


@pytest.mark.parametrize('name,script_name', [
    ('omlx', 'omlx'), ('rapid-mlx', 'rapid-mlx'), ('vllm-mlx', 'vllm-mlx'),
    ('mlx-lm', 'mlx_lm'), ('mlx-lm', 'mlx_lm.server'),
])
def test_console_entry_points_use_the_corresponding_distribution(installation, process, name, script_name):
    python, site, distribution = installation
    renamed = site / f'{name.replace("-", "_")}-1.2.3.dist-info'
    distribution.rename(renamed)
    metadata = renamed / 'METADATA'
    metadata.write_text(f'Name: {name}\nVersion: 1.2.3\n')
    os.utime(metadata, (time.time() - 60, time.time() - 60))
    script = python.parent / script_name
    script.write_text(f'#!"{python}"\n')
    process.cmdline.return_value = [str(python), str(script)]
    # This listener starts after installing the selected distribution.
    process.create_time.return_value = time.time()
    assert process_package_version(42, name) == '1.2.3'


def test_script_from_another_environment_is_not_misattributed(installation, process, tmp_path):
    python, _, _ = installation
    other = tmp_path / 'other environment' / 'bin' / 'python'
    other.parent.mkdir(parents=True)
    other.symlink_to(sys.executable)
    process.cmdline.return_value = [str(other), str(python.parent / 'vllm-mlx')]
    assert process_package_version(42, 'vllm-mlx') is None


def test_live_process_uses_its_own_environment(installation):
    python, _, _ = installation
    # This controlled fixture has no network listener, dependencies or inference.
    with subprocess.Popen([str(python), '-I', str(python.parent / 'vllm-mlx')], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) as child:
        try:
            assert select.select([child.stdout], [], [], 5)[0], 'Fixture did not start'
            assert child.stdout.readline() == b'ready\n'
            assert process_package_version(child.pid, 'vllm-mlx') == '1.2.3'
        finally:
            child.communicate(b'x', timeout=5)
