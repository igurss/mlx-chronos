"""Read package evidence tied to a server process, without executing its Python.

This identifies an installation, not the modules already loaded into memory.
Only explicit, isolated virtual environments are supported; ambiguous launchers,
editable installs and metadata newer than the process-start time window stay unknown.
"""
from email.parser import Parser
import json
import os
from pathlib import Path
import re
import shlex
import sys
import time

from packaging.version import Version
import psutil


def _read(path: Path, limit: int = 64 * 1024) -> str:
    with path.open('rb') as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError('oversized package evidence')
    return data.decode('utf-8')


def _console_names(name: str) -> set[str]:
    names = {name, name.replace('-', '_')}
    if name == 'mlx-lm':
        names.add('mlx_lm.server')
    return names


def _script_interpreter(script: Path, name: str) -> Path | None:
    if not script.is_absolute() or script.name not in _console_names(name):
        return None
    with script.open('rb') as handle:
        first_line = handle.readline(2049)
    if len(first_line) > 2048 or not first_line.startswith(b'#!'):
        return None
    shebang = shlex.split(first_line[2:].decode('utf-8').strip())
    if len(shebang) != 1 or not Path(shebang[0]).is_absolute():
        return None
    python = Path(shebang[0])
    return python if (python.parent == script.parent and
                      re.fullmatch(r'python(?:\d+(?:\.\d+)?t?)?', python.name)) else None


def _interpreter(command: list[str], name: str) -> Path | None:
    if not command or not Path(command[0]).is_absolute():
        return None
    executable = Path(command[0])
    if executable.name in _console_names(name):
        return _script_interpreter(executable, name)
    if not re.fullmatch(r'(?:python(?:\d+(?:\.\d+)?t?)?|Python)', executable.name):
        return None
    index = 1
    while index < len(command) and command[index] in {'-I', '-B', '-E', '-s', '-u', '-q', '-O', '-OO'}:
        index += 1
    if index >= len(command):
        return None
    module = name.replace('-', '_')
    if command[index] == '-m' and index + 1 < len(command):
        target = command[index + 1]
        return executable if target == module or target.startswith(module + '.') else None
    script = Path(command[index])
    # macOS framework launchers can replace argv[0] with the framework binary;
    # the explicit console script still identifies its own venv via its shebang.
    python = _script_interpreter(script, name)
    if python is not None and executable.parent.name == 'bin':
        # Two venvs often resolve to the same base Python executable. Compare
        # their lexical environment paths too, before following Python symlinks.
        if executable.parent.resolve() != python.parent.resolve():
            return None
    return python


def _matches_executable(python: Path, executable: str) -> bool:
    resolved, actual = python.resolve(), Path(executable).resolve()
    if resolved == actual:
        return True
    framework_version = resolved.parent.parent
    if (resolved.parent.name == 'bin' and framework_version.parent.name == 'Versions'
            and framework_version.parent.parent.name == 'Python.framework'):
        return actual == (framework_version / 'Resources/Python.app/Contents/MacOS/Python').resolve()
    return False


def _environment_version(python: Path, name: str, started: float) -> str | None:
    if python.parent.name != 'bin':
        return None
    environment = python.parent.parent.resolve()
    config = dict(
        (key.strip().lower(), value.strip())
        for line in _read(environment / 'pyvenv.cfg').splitlines()
        if '=' in line for key, value in [line.split('=', 1)]
    )
    if config.get('include-system-site-packages', '').lower() != 'false':
        return None
    # CPython's venv writes "version"; uv writes "version_info".
    interpreter_versions = {config[key] for key in ('version', 'version_info') if key in config}
    if len(interpreter_versions) != 1:
        return None
    match = re.fullmatch(r'(3\.\d+)\.\d+(?:[a-zA-Z0-9.+]*)', interpreter_versions.pop())
    if match is None:
        return None
    site = environment / 'lib' / ('python' + match.group(1)) / 'site-packages'
    if not site.resolve().is_relative_to(environment):
        return None
    normalized = re.sub(r'[-_.]+', '-', name).lower()
    candidates = []
    for index, entry in enumerate(site.iterdir()):
        if index >= 10_000:
            return None
        if (entry.name.endswith('.dist-info') and
                re.sub(r'[-_.]+', '-', entry.name.removesuffix('.dist-info').rsplit('-', 1)[0]).lower() == normalized):
            candidates.append(entry)
    if len(candidates) != 1:
        return None
    distribution = candidates[0]
    metadata = distribution / 'METADATA'
    before = metadata.stat()
    if (not distribution.resolve().is_relative_to(site.resolve())
            or not metadata.resolve().is_relative_to(distribution.resolve())
            or max(before.st_mtime, before.st_ctime) > started):
        return None
    direct_url = distribution / 'direct_url.json'
    if direct_url.exists():
        direct = json.loads(_read(direct_url))
        if not isinstance(direct, dict) or direct.get('dir_info', {}).get('editable') is True:
            return None
    message = Parser().parsestr(_read(metadata))
    after = metadata.stat()
    if any(getattr(after, key) != getattr(before, key)
           for key in ('st_mtime_ns', 'st_ctime_ns', 'st_size', 'st_ino', 'st_dev')):
        return None
    names, versions = message.get_all('Name', []), message.get_all('Version', [])
    if len(names) != 1 or len(versions) != 1 or re.sub(r'[-_.]+', '-', names[0]).lower() != normalized:
        return None
    version = versions[0].strip()
    Version(version)
    return version


def process_package_version(pid: int, name: str) -> str | None:
    """Return indirect evidence only while the same identified process is alive."""
    try:
        # Refresh the epoch origin before Process also for psutil versions that
        # cache Linux boot time when reconstructing process creation timestamps.
        booted = psutil.boot_time() if sys.platform.startswith('linux') else None
        process = psutil.Process(pid)
        started, command = process.create_time(), process.cmdline()
        python = _interpreter(command, name)
        if python is None or not _matches_executable(python, process.exe()):
            return None
        metadata_started = started
        if booted is not None:
            # Linux combines whole-second boot time with a start counter rounded
            # down to clock ticks. Align that counter with the file's epoch clock
            # and compare against the upper edge of its one-tick uncertainty.
            uptime = time.clock_gettime(getattr(time, 'CLOCK_BOOTTIME'))
            epoch = time.time()
            metadata_started = started - booted + (epoch - uptime) + 1 / os.sysconf('SC_CLK_TCK')
        version = _environment_version(python, name, metadata_started)
        if (not process.is_running() or process.create_time() != started
                or process.cmdline() != command):
            return None
        return version
    except (OSError, psutil.Error, ValueError, TypeError, AttributeError):
        return None
