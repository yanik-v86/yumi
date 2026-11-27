#!/bin/sh
# One-time setup of GigaAM-v4 (RNNT) for Yumi's ears.
#   ./tools/gigaam_setup.sh           # download from Hugging Face, export ONNX, verify
#   ./tools/gigaam_setup.sh --force   # replace an existing export
#
# From scratch this script:
#   1. installs onnxruntime + sentencepiece into the ears venv (~/.local/share/yumi/stt);
#   2. creates a THROWAWAY export venv there (gigaam-export) with CPU torch and
#      transformers, unless a suitable venv is already available;
#   3. downloads ai-sage/GigaAM-v4 at a pinned revision from Hugging Face and
#      exports ~0.9 GB of ONNX graphs to $YUMI_STT_HOME/gigaam/full;
#   4. verifies the export with the ears venv. Torch and HF custom code never
#      take part in recognition: Yumi loads only ONNX at runtime.
#
# Useful overrides:
#   YUMI_GIGA_EXPORT_PY=/path/to/python  # an existing venv with torch+transformers
#   YUMI_GIGA_PYTHON=python3.12          # base interpreter for the new export venv
#   GIGAAM_SHA=<sha>                     # use another pinned revision
#   YUMI_STT_HOME=/path/to/stt           # move all model files
#
# Details: docs/gigaam-setup.md. Use tools/gigaam_bench.py to A/B before enabling.
set -e
cd "$(dirname "$0")/.."
DIR="${YUMI_STT_HOME:-$HOME/.local/share/yumi/stt}"
PY="$DIR/bin/python"
SHA="${GIGAAM_SHA:-9fe3ebf50c9e0cce5eed60d546938632238b6a96}"
OUT="$DIR/gigaam/full"
EXPORT_DIR="$DIR/gigaam-export"
FORCE="${1:-}"

case "$FORCE" in
    ''|--force) ;;
    *) echo "usage: $0 [--force]" >&2; exit 2 ;;
esac

if [ ! -x "$PY" ]; then
    echo "The ears venv is missing in $DIR: run ./tools/stt_setup.sh first." >&2
    exit 1
fi

# Runtime side: small pure-onnx dependencies, installed into the ears venv.
if ! "$PY" -c 'import onnxruntime, sentencepiece' >/dev/null 2>&1; then
    echo 'Installing onnxruntime and sentencepiece into the ears venv...'
    if command -v uv >/dev/null 2>&1; then
        uv pip install --python "$PY" onnxruntime sentencepiece
    else
        "$PY" -m pip install --quiet onnxruntime sentencepiece
    fi
fi

if [ -f "$OUT/rnnt_encoder.onnx" ] && [ -f "$OUT/rnnt_advance.onnx" ] \
   && [ "$FORCE" != '--force' ]; then
    echo "GigaAM ONNX is already exported in $OUT"
else
    EXPORT_PY="${YUMI_GIGA_EXPORT_PY:-}"
    if [ -z "$EXPORT_PY" ] && [ -x "$HOME/Projects/Recog/.venv/bin/python" ] \
       && "$HOME/Projects/Recog/.venv/bin/python" -c 'import torch, transformers, onnx' >/dev/null 2>&1; then
        EXPORT_PY="$HOME/Projects/Recog/.venv/bin/python"
    fi
    if [ -z "$EXPORT_PY" ] && [ -x "$EXPORT_DIR/bin/python" ] \
       && "$EXPORT_DIR/bin/python" -c 'import torch, transformers, onnx' >/dev/null 2>&1; then
        EXPORT_PY="$EXPORT_DIR/bin/python"
    fi

    if [ -z "$EXPORT_PY" ]; then
        BASE_PYTHON="${YUMI_GIGA_PYTHON:-}"
        if [ -z "$BASE_PYTHON" ]; then
            for candidate in python3.12 python3.11 python3.10 python3; do
                if command -v "$candidate" >/dev/null 2>&1; then
                    BASE_PYTHON="$candidate"
                    break
                fi
            done
        fi
        if [ -z "$BASE_PYTHON" ] || ! "$BASE_PYTHON" -c \
           'import sys; raise SystemExit(sys.version_info[:2] > (3, 12))'; then
            echo "GigaAM's export needs Python 3.10-3.12 (found ${BASE_PYTHON:-none})." >&2
            echo 'Set YUMI_GIGA_PYTHON to a suitable interpreter and retry.' >&2
            exit 1
        fi
        echo "Creating a throwaway export venv in $EXPORT_DIR (CPU torch, ~2 GB)..."
        if command -v uv >/dev/null 2>&1; then
            uv venv --python "$BASE_PYTHON" "$EXPORT_DIR"
            uv pip install --python "$EXPORT_DIR/bin/python" \
                'torch==2.5.1' 'torchaudio==2.5.1' \
                --index-url https://download.pytorch.org/whl/cpu
            uv pip install --python "$EXPORT_DIR/bin/python" \
                'transformers==4.57.6' 'onnx==1.23.2' 'omegaconf==2.3.1' \
                'sentencepiece==0.2.3' 'soundfile==0.14.0' 'safetensors==0.8.0' tqdm
        else
            "$BASE_PYTHON" -m venv "$EXPORT_DIR"
            "$EXPORT_DIR/bin/python" -m pip install --quiet --upgrade pip
            "$EXPORT_DIR/bin/python" -m pip install --quiet \
                'torch==2.5.1' 'torchaudio==2.5.1' \
                --index-url https://download.pytorch.org/whl/cpu
            "$EXPORT_DIR/bin/python" -m pip install --quiet \
                'transformers==4.57.6' 'onnx==1.23.2' 'omegaconf==2.3.1' \
                'sentencepiece==0.2.3' 'soundfile==0.14.0' 'safetensors==0.8.0' tqdm
        fi
        EXPORT_PY="$EXPORT_DIR/bin/python"
    fi

    # onnx is only needed while exporting; keep it in the export venv, not Yumi's.
    if ! "$EXPORT_PY" -c 'import onnx' >/dev/null 2>&1; then
        if command -v uv >/dev/null 2>&1; then
            uv pip install --python "$EXPORT_PY" 'onnx==1.23.2'
        else
            "$EXPORT_PY" -m pip install --quiet 'onnx==1.23.2'
        fi
    fi
    if ! "$EXPORT_PY" -c 'import torch, transformers, torchaudio, onnx, omegaconf, soundfile, sentencepiece' >/dev/null 2>&1; then
        echo "The export Python cannot import torch/transformers and friends: $EXPORT_PY" >&2
        echo 'Set YUMI_GIGA_EXPORT_PY to a complete venv, or remove' >&2
        echo "$EXPORT_DIR and rerun without that override." >&2
        exit 1
    fi

    mkdir -p "$DIR/gigaam"
    TMP="$(mktemp -d "$DIR/gigaam/.full.XXXXXX")"
    trap 'rm -rf "$TMP"' EXIT
    echo "Downloading ai-sage/GigaAM-v4 @ $SHA from Hugging Face and exporting ONNX (a few minutes)..."
    GIGAAM_SHA="$SHA" "$EXPORT_PY" - "$TMP" <<'PY'
import os
import sys
from pathlib import Path

import torch
from transformers import AutoModel

sha = os.environ['GIGAAM_SHA']
out = Path(sys.argv[1])
print(f'loading the pinned rnnt revision {sha} on cpu ...', flush=True)
model = AutoModel.from_pretrained(
    'ai-sage/GigaAM-v4', revision=sha, trust_remote_code=True,
    device='cpu', torch_dtype=torch.float32,
).eval()
model.to_onnx(str(out), dtype=torch.float32)
print(f'exported: {sorted(p.name for p in out.iterdir())}', flush=True)
PY
    printf '%s\n' "$SHA" > "$TMP/revision.txt"
    rm -rf "$OUT"
    mv "$TMP" "$OUT"
    trap - EXIT
fi

"$PY" - <<'PY'
import os
import sys
sys.path.insert(0, os.getcwd())
from yumi import gigaam_onnx
if not gigaam_onnx.available():
    raise SystemExit('the export is incomplete (graphs or tokenizers are missing)')
print('GigaAM-v4 ONNX is ready for stt_engine = gigaam')
PY
