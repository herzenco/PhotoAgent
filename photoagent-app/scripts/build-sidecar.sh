#!/bin/bash
set -e

PHOTOAGENT_DIR="$HOME/Desktop/PhotoAgent"
APP_DIR="$HOME/Desktop/photoagent-app"
TARGET_TRIPLE=$(source "$HOME/.cargo/env" && rustc --print host-tuple)

echo "Building PhotoAgent sidecar for $TARGET_TRIPLE..."

# Activate venv and build with PyInstaller
cd "$PHOTOAGENT_DIR"
source .venv/bin/activate

# Build single-file binary - core CLI only (no heavy ML models)
pyinstaller --onefile \
  --name photoagent \
  --distpath "$APP_DIR/src-tauri/binaries" \
  --specpath /tmp \
  --workpath /tmp/pyinstaller-build \
  --exclude-module torch \
  --exclude-module open_clip \
  --exclude-module insightface \
  --exclude-module transformers \
  --exclude-module pkg_resources \
  --hidden-import typer \
  --hidden-import rich \
  --hidden-import exifread \
  --hidden-import imagehash \
  --hidden-import PIL \
  --hidden-import pillow_heif \
  --hidden-import reverse_geocoder \
  --hidden-import anthropic \
  --hidden-import keyring \
  --hidden-import setuptools \
  --collect-submodules typer \
  --collect-submodules click \
  src/photoagent/cli.py

# Rename with target triple
mv "$APP_DIR/src-tauri/binaries/photoagent" "$APP_DIR/src-tauri/binaries/photoagent-$TARGET_TRIPLE"

# Remove quarantine attribute on macOS
xattr -d com.apple.quarantine "$APP_DIR/src-tauri/binaries/photoagent-$TARGET_TRIPLE" 2>/dev/null || true

# Test the binary
echo "Testing sidecar binary..."
"$APP_DIR/src-tauri/binaries/photoagent-$TARGET_TRIPLE" --help

echo "Sidecar built successfully: photoagent-$TARGET_TRIPLE"
