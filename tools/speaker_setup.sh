#!/bin/sh
# The optional voice-print ear: 3D-Speaker CAMPPlus zh/en 16 kHz (~28 MB).
#   ./tools/speaker_setup.sh
# The model is downloaded from the official sherpa-onnx release into the ears
# venv (tools/nemotron_setup.sh creates it).  Nothing is installed system-wide.
# The checksum is the one published with that release asset; a bad download is
# discarded instead of being used as a voice print.
set -e
cd "$(dirname "$0")/.."
DIR="${YUMI_STT_HOME:-$HOME/.local/share/yumi/stt}"
NAME=3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx
URL=https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/$NAME
SHA=53cab20ba8f2eb2f6e2d89ecc18e88ef3222169b61b4419cbc13666744a4574b

if [ ! -x "$DIR/bin/python" ]; then
    echo "The ears venv is not in $DIR: run tools/stt_setup.sh first." >&2
    exit 1
fi

if "$DIR/bin/python" -c 'import sherpa_onnx' >/dev/null 2>&1; then
    echo 'sherpa-onnx is already in the ears venv.'
else
    echo 'Installing sherpa-onnx into the ears venv...'
    if command -v uv >/dev/null 2>&1; then
        uv pip install --python "$DIR/bin/python" sherpa-onnx
    else
        "$DIR/bin/python" -m pip install --quiet sherpa-onnx
    fi
fi

if [ -f "$DIR/$NAME" ] && echo "$SHA  $DIR/$NAME" | sha256sum -c - >/dev/null 2>&1; then
    echo 'The 3D-Speaker model is already in.'
else
    echo "Downloading the 3D-Speaker model ($NAME)..."
    tmp="$DIR/$NAME.part"
    curl -fL --retry 3 -o "$tmp" "$URL"
    if ! echo "$SHA  $tmp" | sha256sum -c - >/dev/null 2>&1; then
        echo 'The download failed the checksum; nothing was installed.' >&2
        rm -f "$tmp"
        exit 1
    fi
    mv "$tmp" "$DIR/$NAME"
fi

echo "The model is in $DIR/$NAME. Set \"speaker_verify\": true in settings.json and restart Yumi."
