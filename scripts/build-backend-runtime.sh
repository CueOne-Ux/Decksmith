#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON="$ROOT/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
  echo "Decksmith's application Python environment is missing." >&2
  exit 1
fi

set -- \
  --noconfirm \
  --clean \
  --onedir \
  --name decksmith-backend \
  --paths "$ROOT/backend" \
  --collect-all mutagen \
  --distpath "$ROOT/release/runtime" \
  --workpath "$ROOT/release/build/backend" \
  --specpath "$ROOT/release/build" \
  "$ROOT/release/backend_entry.py"

PYINSTALLER_CONFIG_DIR="$ROOT/release/build/config" \
PYTHONPATH="$ROOT/backend" \
"$PYTHON" -m PyInstaller "$@"

"$ROOT/release/runtime/decksmith-backend/decksmith-backend" --help >/dev/null

STEM_PYTHON="$ROOT/.venv-stems/bin/python"
if [ ! -x "$STEM_PYTHON" ]; then
  echo "Decksmith's isolated stem environment is missing." >&2
  exit 1
fi

PYINSTALLER_CONFIG_DIR="$ROOT/release/build/config-stems" \
"$STEM_PYTHON" -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --name decksmith-demucs \
  --collect-all demucs \
  --hidden-import backports.tarfile \
  --hidden-import safetensors.torch \
  --hidden-import sphn \
  --distpath "$ROOT/release/runtime" \
  --workpath "$ROOT/release/build/stems" \
  --specpath "$ROOT/release/build" \
  "$ROOT/release/stem_entry.py"

MODEL_CACHE="$HOME/.cache/huggingface/hub/models--adefossez--HTDemucs"
if [ ! -d "$MODEL_CACHE" ]; then
  echo "The local HTDemucs model is missing. Separate one track before making a release." >&2
  exit 1
fi
MODEL_SNAPSHOT=""
for candidate in "$MODEL_CACHE"/snapshots/*; do
  if [ -d "$candidate" ]; then
    MODEL_SNAPSHOT="$candidate"
    break
  fi
done
if [ -z "$MODEL_SNAPSHOT" ]; then
  echo "The local HTDemucs model snapshot is incomplete." >&2
  exit 1
fi
rm -rf "$ROOT/release/model-runtime"
mkdir -p "$ROOT/release/model-runtime"
cp -L "$MODEL_SNAPSHOT/htdemucs.yaml" "$ROOT/release/model-runtime/"
cp -L "$MODEL_SNAPSHOT/955717e8.safetensors" "$ROOT/release/model-runtime/"

"$ROOT/release/runtime/decksmith-demucs/decksmith-demucs" --decksmith-capability >/dev/null
echo "Bundled backend and stem engine are ready."
