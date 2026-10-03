"""Versioned compatibility declaration for the independently released macOS app.

This is separate from the benchmark measurement protocol. Keep its capabilities
and command list consistent with the public runtime catalog before releasing.
"""
from copy import deepcopy

APP_CONTRACT = {
    "api_version": 1,
    "minimum_app_version": "0.2.0",
    "required_capabilities": [
        "cli-options-v1", "snapshot-v1", "benchmark-json-v1",
        "thermal-foundation-v1", "command-safety-v1",
    ],
    "supported_commands": [
        "run", "matrix", "context", "concurrency", "energy", "doctor",
        "validate", "models", "engines", "history", "compare", "submit",
        "upgrade", "wizard",
    ],
}


def describe_app_contract() -> dict:
    return deepcopy(APP_CONTRACT)
