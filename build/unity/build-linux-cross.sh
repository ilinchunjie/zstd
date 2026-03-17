#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 3 ]; then
  echo "usage: $0 <arch:amd64|arm64> <work-dir> <output-dir>"
  exit 1
fi

ARCH="$1"
WORK_DIR="$2"
OUTPUT_DIR="$3"
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SOURCE_DIR="$ROOT_DIR/build/cmake"
BUILD_DIR="$WORK_DIR/$ARCH"

cmake_args=(
  -S "$SOURCE_DIR"
  -B "$BUILD_DIR"
  -DCMAKE_BUILD_TYPE=Release
  -DZSTD_BUILD_SHARED=ON
  -DZSTD_BUILD_STATIC=OFF
  -DZSTD_BUILD_PROGRAMS=OFF
  -DZSTD_BUILD_TESTS=OFF
)

if [ "$ARCH" = "arm64" ]; then
  cmake_args+=(
    -DCMAKE_SYSTEM_NAME=Linux
    -DCMAKE_SYSTEM_PROCESSOR=aarch64
    -DCMAKE_C_COMPILER=aarch64-linux-gnu-gcc
    -DCMAKE_CXX_COMPILER=aarch64-linux-gnu-g++
  )
elif [ "$ARCH" != "amd64" ]; then
  echo "unsupported arch: $ARCH"
  exit 1
fi

cmake "${cmake_args[@]}"
cmake --build "$BUILD_DIR" --config Release

mkdir -p "$OUTPUT_DIR"
SO_PATH="$(find "$BUILD_DIR" -name 'libzstd.so*' | sort | head -n 1)"
if [ -z "$SO_PATH" ]; then
  echo "failed to locate Linux shared library output"
  exit 1
fi
cp "$SO_PATH" "$OUTPUT_DIR/libzstd.so"
