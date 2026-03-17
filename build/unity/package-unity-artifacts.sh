#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 3 ]; then
  echo "usage: $0 <artifacts-dir> <output-dir> <version>"
  exit 1
fi

ARTIFACTS_DIR="$1"
OUTPUT_DIR="$2"
VERSION="$3"
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PACKAGE_ROOT="$OUTPUT_DIR/zstd-unity-$VERSION"

rm -rf "$PACKAGE_ROOT"
mkdir -p "$PACKAGE_ROOT"

copy_required() {
  local source="$1"
  local destination="$2"
  if [ ! -f "$source" ]; then
    echo "missing required file: $source"
    exit 1
  fi
  mkdir -p "$(dirname "$destination")"
  cp "$source" "$destination"
}

copy_optional() {
  local source="$1"
  local destination="$2"
  if [ -f "$source" ]; then
    mkdir -p "$(dirname "$destination")"
    cp "$source" "$destination"
  fi
}

copy_required "$ARTIFACTS_DIR/android-arm64-v8a/libzstd.so" "$PACKAGE_ROOT/Plugins/Android/libs/arm64-v8a/libzstd.so"
copy_required "$ARTIFACTS_DIR/android-armeabi-v7a/libzstd.so" "$PACKAGE_ROOT/Plugins/Android/libs/armeabi-v7a/libzstd.so"
copy_required "$ARTIFACTS_DIR/android-x86_64/libzstd.so" "$PACKAGE_ROOT/Plugins/Android/libs/x86_64/libzstd.so"
copy_required "$ARTIFACTS_DIR/ios/libzstd.a" "$PACKAGE_ROOT/Plugins/iOS/libzstd.a"
copy_required "$ARTIFACTS_DIR/linux-amd64/libzstd.so" "$PACKAGE_ROOT/Plugins/Linux/x86_64/libzstd.so"
copy_required "$ARTIFACTS_DIR/linux-arm64/libzstd.so" "$PACKAGE_ROOT/Plugins/Linux/arm64/libzstd.so"
copy_required "$ARTIFACTS_DIR/macos/libzstd.dylib" "$PACKAGE_ROOT/Plugins/macOS/libzstd.dylib"
copy_required "$ARTIFACTS_DIR/windows-amd64/zstd.dll" "$PACKAGE_ROOT/Plugins/Windows/x86_64/zstd.dll"
copy_required "$ARTIFACTS_DIR/csharp/ZstdNative.cs" "$PACKAGE_ROOT/Bindings/ZstdNative.cs"

cat > "$PACKAGE_ROOT/README-unity.txt" <<EOF
Unity packaging for zstd.

Contents:
- Native libraries for Android, iOS, Linux, macOS, and Windows
- Generated C# bridge in Bindings/ZstdNative.cs

Notes:
- This package contains only the minimum files required for Unity consumption.
- Static-linking-only experimental APIs are intentionally excluded.
EOF

mkdir -p "$OUTPUT_DIR"
ARCHIVE_PATH="$OUTPUT_DIR/zstd-unity-$VERSION.zip"
rm -f "$ARCHIVE_PATH"
(
  cd "$OUTPUT_DIR"
  python - <<'PY' "$(basename "$ARCHIVE_PATH")" "$(basename "$PACKAGE_ROOT")"
import os
import sys
import zipfile

archive_name = sys.argv[1]
root_dir = sys.argv[2]
with zipfile.ZipFile(archive_name, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for base, _, files in os.walk(root_dir):
        for file_name in files:
            full_path = os.path.join(base, file_name)
            zf.write(full_path, full_path)
PY
)

python - <<'PY' "$PACKAGE_ROOT"
import os
import sys
root = sys.argv[1]
for base, _, files in os.walk(root):
    for file_name in sorted(files):
        print(os.path.relpath(os.path.join(base, file_name), root))
PY

echo "Created $ARCHIVE_PATH"
