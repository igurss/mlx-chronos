#!/bin/bash
# Package an already-built local app. Never changes signatures or macOS policy.
set -euo pipefail
CHRONOS_PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CHRONOS_SOURCE_APP="${1:-$CHRONOS_PROJECT_DIR/dist/MLXChronos.app}"
CHRONOS_OUTPUT_DIR="${2:-$CHRONOS_PROJECT_DIR/dist}"
if [[ "$CHRONOS_SOURCE_APP" != /* ]]; then
    CHRONOS_SOURCE_APP="$PWD/$CHRONOS_SOURCE_APP"
fi
if [[ "$CHRONOS_OUTPUT_DIR" != /* ]]; then
    CHRONOS_OUTPUT_DIR="$PWD/$CHRONOS_OUTPUT_DIR"
fi
if [[ ! -d "$CHRONOS_SOURCE_APP" || -L "$CHRONOS_SOURCE_APP" ]]; then
    printf 'Pass a built MLXChronos.app directory, not a symlink.\n' >&2
    exit 1
fi
CHRONOS_INFO="$CHRONOS_SOURCE_APP/Contents/Info.plist"
CHRONOS_IDENTIFIER=$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$CHRONOS_INFO")
CHRONOS_VERSION=$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$CHRONOS_INFO")
CHRONOS_BUILD=$(/usr/libexec/PlistBuddy -c 'Print CFBundleVersion' "$CHRONOS_INFO")
if [[ "$CHRONOS_IDENTIFIER" != 'com.igurss.mlxchronos' ||
      ! "$CHRONOS_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ||
      ! "$CHRONOS_BUILD" =~ ^[0-9]+(\.[0-9]+){0,2}$ ]]; then
    printf 'Unexpected app identity, version or build; refusing to package.\n' >&2
    exit 1
fi
if [[ "$(/usr/bin/lipo -archs "$CHRONOS_SOURCE_APP/Contents/MacOS/MLXChronos")" != 'arm64' ]]; then
    printf 'This package is labelled arm64; supply an Apple Silicon-only build.\n' >&2
    exit 1
fi
/usr/bin/codesign --verify --strict "$CHRONOS_SOURCE_APP"
CHRONOS_SIGNATURE=$(/usr/bin/codesign -dv --verbose=4 "$CHRONOS_SOURCE_APP" 2>&1)
if [[ "$CHRONOS_SIGNATURE" != *'Signature=adhoc'* ]]; then
    printf 'This free-release recipe expects an ad-hoc build; review the signing/distribution instructions for other signatures.\n' >&2
    exit 1
fi
# The public download uses the release version; the app retains its build ID.
CHRONOS_NAME="MLXChronos-$CHRONOS_VERSION-arm64.dmg"
CHRONOS_DMG="$CHRONOS_OUTPUT_DIR/$CHRONOS_NAME"
CHRONOS_CHECKSUM="$CHRONOS_DMG.sha256"
if [[ -e "$CHRONOS_DMG" || -L "$CHRONOS_DMG" || -e "$CHRONOS_CHECKSUM" || -L "$CHRONOS_CHECKSUM" ]]; then
    printf 'Refusing to overwrite an existing DMG or checksum; choose an empty output directory.\n' >&2
    exit 1
fi
test -f "$CHRONOS_PROJECT_DIR/INSTALLATION.txt"
CHRONOS_STAGE_DIR="$(mktemp -d -t chronos-dmg)"
trap 'rm -rf "$CHRONOS_STAGE_DIR"' EXIT
/usr/bin/ditto "$CHRONOS_SOURCE_APP" "$CHRONOS_STAGE_DIR/MLXChronos.app"
/usr/bin/codesign --verify --strict "$CHRONOS_STAGE_DIR/MLXChronos.app"
ln -s /Applications "$CHRONOS_STAGE_DIR/Applications"
cp "$CHRONOS_PROJECT_DIR/INSTALLATION.txt" "$CHRONOS_STAGE_DIR/Install and first launch.txt"
mkdir -p "$CHRONOS_OUTPUT_DIR"
# hdiutil remains available on the minimum supported macOS, unlike newer APIs.
/usr/bin/hdiutil create -srcfolder "$CHRONOS_STAGE_DIR" -volname "MLX Chronos $CHRONOS_VERSION" \
    -fs HFS+ -format UDZO -nospotlight -srcowners off "$CHRONOS_DMG"
/usr/bin/hdiutil verify "$CHRONOS_DMG"
(
    cd "$CHRONOS_OUTPUT_DIR"
    /usr/bin/shasum -a 256 "$CHRONOS_NAME" > "$CHRONOS_NAME.sha256"
    /usr/bin/shasum -a 256 -c "$CHRONOS_NAME.sha256"
)
printf 'DMG: %s\nChecksum: %s\n' "$CHRONOS_DMG" "$CHRONOS_CHECKSUM"
printf 'Local/ad-hoc signature; NOT Developer ID signed or Apple notarized.\n'
