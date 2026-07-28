#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
rm -rf \
  "$ROOT/src-tauri/target" \
  "$ROOT/release/build" \
  "$ROOT/release/runtime" \
  "$ROOT/release/model-cache" \
  "$ROOT/release/model-runtime"

echo "Reproducible build artifacts removed. release/Decksmith.app was preserved."
