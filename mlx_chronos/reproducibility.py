"""Client dependency versions, without installation paths or personal metadata."""
from __future__ import annotations

import importlib.metadata

CLIENT_DISTRIBUTIONS = (
    'httpx', 'httpcore', 'h11', 'anyio', 'certifi', 'idna', 'psutil',
    'pydantic', 'pydantic-core', 'packaging', 'questionary', 'prompt-toolkit',
    'rich', 'pyobjc-core', 'pyobjc-framework-Cocoa',
)


def client_environment() -> dict:
    versions = {}
    for name in CLIENT_DISTRIBUTIONS:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    # The result's existing integrity seal already covers this mapping.
    return {'dependencies': versions}
