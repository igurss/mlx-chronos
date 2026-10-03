#!/bin/bash
set -euo pipefail
CHRONOS_PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CHRONOS_CHECK_DIR="$(mktemp -d -t chronos-bootstrap-check)"
trap 'rm -rf "$CHRONOS_CHECK_DIR"' EXIT
cd "$CHRONOS_PROJECT_DIR"
swiftc -module-cache-path "$CHRONOS_CHECK_DIR/modules" -parse-as-library \
    MLXChronos/Models.swift MLXChronos/CommandBuilder.swift \
    MLXChronos/RuntimeDiscovery.swift MLXChronos/RuntimeManager.swift \
    MLXChronos/ProcessRunner.swift Tests/BootstrapChecks.swift -o "$CHRONOS_CHECK_DIR/bootstrap"
"$CHRONOS_CHECK_DIR/bootstrap" "$CHRONOS_PROJECT_DIR/../../docs/app-runtime.json" \
    "$CHRONOS_PROJECT_DIR/MLXChronos/Resources/chronos_bridge.py"
