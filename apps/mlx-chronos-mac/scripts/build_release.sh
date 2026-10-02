#!/bin/bash
# Reproducible local build only; no Developer ID signing, notarization or upload.
set -euo pipefail
CHRONOS_PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CHRONOS_OUTPUT_DIR="${1:-$CHRONOS_PROJECT_DIR/dist}"
if [[ "$CHRONOS_OUTPUT_DIR" != /* ]]; then
    CHRONOS_OUTPUT_DIR="$PWD/$CHRONOS_OUTPUT_DIR"
fi
CHRONOS_APP="$CHRONOS_OUTPUT_DIR/MLXChronos.app"
if [[ -e "$CHRONOS_APP" ]]; then
    printf 'Refusing to overwrite %s; choose an empty output directory.\n' "$CHRONOS_APP" >&2
    exit 1
fi
CHRONOS_BUILD_DIR="$(mktemp -d -t chronos-release)"
trap 'rm -rf "$CHRONOS_BUILD_DIR"' EXIT
cd "$CHRONOS_PROJECT_DIR"
test -f MLXChronos/Resources/runtime_manifest.json
xcodebuild -quiet -project MLXChronos.xcodeproj -scheme MLXChronos \
    -configuration Release -destination 'generic/platform=macOS' \
    -derivedDataPath "$CHRONOS_BUILD_DIR" ARCHS=arm64 ONLY_ACTIVE_ARCH=NO build
CHRONOS_BUILT_APP="$CHRONOS_BUILD_DIR/Build/Products/Release/MLXChronos.app"
/usr/bin/codesign --verify --strict "$CHRONOS_BUILT_APP"
mkdir -p "$CHRONOS_OUTPUT_DIR"
/usr/bin/ditto "$CHRONOS_BUILT_APP" "$CHRONOS_APP"
/usr/bin/codesign --verify --strict "$CHRONOS_APP"
CHRONOS_VERSION=$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$CHRONOS_APP/Contents/Info.plist")
CHRONOS_BUILD=$(/usr/libexec/PlistBuddy -c 'Print CFBundleVersion' "$CHRONOS_APP/Contents/Info.plist")
CHRONOS_ZIP="$CHRONOS_OUTPUT_DIR/MLXChronos-$CHRONOS_VERSION-$CHRONOS_BUILD-arm64.zip"
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$CHRONOS_APP" "$CHRONOS_ZIP"
/usr/bin/shasum -a 256 "$CHRONOS_ZIP"
printf 'App: %s\nZIP: %s\n' "$CHRONOS_APP" "$CHRONOS_ZIP"
printf 'Local/ad-hoc signature only; this build is not Developer ID notarized.\n'
