#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 3 ]; then
  echo "usage: $0 <platform:macos|ios> <work-dir> <output-dir>"
  exit 1
fi

PLATFORM="$1"
WORK_DIR="$2"
OUTPUT_DIR="$3"
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SOURCE_DIR="$ROOT_DIR/build/cmake"

cmake_common=(
  -S "$SOURCE_DIR"
  -DZSTD_BUILD_PROGRAMS=OFF
  -DZSTD_BUILD_TESTS=OFF
)

if [ "$PLATFORM" = "macos" ]; then
  X64_DIR="$WORK_DIR/macos-x86_64"
  ARM64_DIR="$WORK_DIR/macos-arm64"
  cmake -B "$X64_DIR" "${cmake_common[@]}" -DZSTD_BUILD_SHARED=ON -DZSTD_BUILD_STATIC=OFF -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=x86_64
  cmake --build "$X64_DIR" --config Release
  cmake -B "$ARM64_DIR" "${cmake_common[@]}" -DZSTD_BUILD_SHARED=ON -DZSTD_BUILD_STATIC=OFF -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64
  cmake --build "$ARM64_DIR" --config Release

  mkdir -p "$OUTPUT_DIR"
  X64_LIB="$(find "$X64_DIR" -name 'libzstd*.dylib' | head -n 1)"
  ARM64_LIB="$(find "$ARM64_DIR" -name 'libzstd*.dylib' | head -n 1)"
  if [ -z "$X64_LIB" ] || [ -z "$ARM64_LIB" ]; then
    echo "failed to locate macOS dylib outputs"
    exit 1
  fi
  lipo -create "$X64_LIB" "$ARM64_LIB" -output "$OUTPUT_DIR/libzstd.dylib"
  exit 0
fi

if [ "$PLATFORM" = "ios" ]; then
  IOS_DIR="$WORK_DIR/ios"
  cmake -B "$IOS_DIR" -G Xcode "${cmake_common[@]}" -DZSTD_BUILD_SHARED=OFF -DZSTD_BUILD_STATIC=ON -DCMAKE_SYSTEM_NAME=iOS
  cmake --build "$IOS_DIR" --config Release
  mkdir -p "$OUTPUT_DIR"
  IOS_LIB="$(find "$IOS_DIR" -name 'libzstd*.a' | head -n 1)"
  if [ -z "$IOS_LIB" ]; then
    echo "failed to locate iOS static library output"
    exit 1
  fi
  cp "$IOS_LIB" "$OUTPUT_DIR/libzstd.a"
  exit 0
fi

echo "unsupported platform: $PLATFORM"
exit 1
