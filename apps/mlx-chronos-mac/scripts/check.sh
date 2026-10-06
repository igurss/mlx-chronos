#!/bin/bash
set -euo pipefail
CHRONOS_PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CHRONOS_PYTHON="${1:?Pass the absolute path to a Python environment with mlx-chronos[thermal] installed}"
CHRONOS_CHECK_DIR="$(mktemp -d -t chronos-checks)"
trap 'rm -rf "$CHRONOS_CHECK_DIR"' EXIT
cd "$CHRONOS_PROJECT_DIR"
"$CHRONOS_PYTHON" -I -B -m unittest discover -s Tests -p 'test_*.py' -v
swiftc -module-cache-path "$CHRONOS_CHECK_DIR/modules" -parse-as-library \
    MLXChronos/Models.swift MLXChronos/CommandBuilder.swift \
    MLXChronos/RuntimeDiscovery.swift MLXChronos/RuntimeManager.swift MLXChronos/ProcessRunner.swift \
    MLXChronos/ResultRepository.swift MLXChronos/BenchmarkTrialData.swift Tests/CoreTests.swift -o "$CHRONOS_CHECK_DIR/core-checks"
"$CHRONOS_CHECK_DIR/core-checks" "$CHRONOS_PYTHON" "$CHRONOS_PROJECT_DIR/MLXChronos/Resources/chronos_bridge.py"
