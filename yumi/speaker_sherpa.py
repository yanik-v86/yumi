"""3D-Speaker embeddings through the ears venv (no model import at module load).

The system Python and the STT venv usually have different versions, so the
compiled sherpa-onnx module cannot be imported in-process.  When that is the
case the PCM is handed to the venv interpreter through stdin and the embedding
comes back as JSON; no audio or vector is ever logged.  A missing venv/model
simply makes available() false — the old wake/listen path keeps working.
"""
from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import sys
from pathlib import Path

MODEL_NAME = '3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx'
MODEL_SHA256 = '53cab20ba8f2eb2f6e2d89ecc18e88ef3222169b61b4419cbc13666744a4574b'
MODEL_URL = ('https://github.com/k2-fsa/sherpa-onnx/releases/download/'
             'speaker-recongition-models/' + MODEL_NAME)
SAMPLE_RATE = 16000
DEFAULT_MIN_MS = 1200

# the small worker runs inside the ears venv; stdout is JSON, stderr is discarded
_WORKER = r'''
import json, struct, sys
import sherpa_onnx
model = sys.argv[1]
data = sys.stdin.buffer.read()
samples = list(struct.unpack('<%dh' % (len(data) // 2), data))
cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=model, num_threads=1)
try:
    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
except AttributeError:
    extractor = sherpa_onnx.SpeakerEmbeddingExtractor.from_config(cfg)
stream = extractor.create_stream()
stream.accept_waveform(16000, [s / 32768.0 for s in samples])
if not extractor.is_ready(stream):
    print(json.dumps({'error': 'short'})); sys.exit(0)
vec = extractor.compute(stream)
print(json.dumps({'embedding': list(vec)}))
'''

_native = None
_checked = False
_ready = False
_error = None
_backend = None      # tests inject a fake embedding function here


def set_backend(fn):
    """Test hook: ``fn(pcm) -> list[float] | None`` instead of the real model."""
    global _backend, _checked, _ready, _error
    _backend = fn
    _checked, _ready, _error = False, False, None


def venv_dir():
    return Path(os.environ.get('YUMI_STT_HOME') or
                (Path.home() / '.local' / 'share' / 'yumi' / 'stt'))


def python_bin():
    candidate = venv_dir() / 'bin' / 'python'
    return str(candidate) if candidate.is_file() else sys.executable


def model_path():
    """Env override may point at a file or a folder with one .onnx model."""
    override = os.environ.get('YUMI_SPEAKER_MODEL')
    if override:
        path = Path(override).expanduser()
        if path.is_dir():
            found = sorted(path.glob('*.onnx'))
            return found[0] if found else path
        return path
    return venv_dir() / MODEL_NAME


def _load_native():
    global _native
    if _native is not None:
        return _native
    try:
        import sherpa_onnx
        _native = sherpa_onnx
    except Exception:
        _native = False          # compiled for another Python version: use the worker
    return _native


def _check():
    global _checked, _ready, _error
    if _checked:
        return _ready
    _checked = True
    path = model_path()
    if not path.is_file():
        _error = 'speaker model missing'
        return False
    if _load_native() is not False:
        _ready, _error = True, None
        return True
    try:
        result = subprocess.run([python_bin(), '-c', 'import sherpa_onnx'],
                                stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=15)
        if result.returncode == 0:
            _ready, _error = True, None
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    _error = 'sherpa-onnx is not in the ears venv'
    return False


def available():
    """A cheap, cached answer: no model load on a status tick."""
    return bool(_backend is not None or _check())


def model_info():
    """Status for the panel: a name and an error, never a filesystem path."""
    ready = available()
    return {'ready': ready, 'name': MODEL_NAME if ready else None,
            'error': None if ready else _error}


def _samples(pcm, min_ms):
    """s16le mono 16 kHz bytes; None when too short or effectively silence."""
    if isinstance(pcm, memoryview):
        pcm = pcm.tobytes()
    if not isinstance(pcm, (bytes, bytearray)):
        return None
    n = len(pcm) // 2
    if n < int(min_ms) * SAMPLE_RATE // 1000:
        return None
    try:
        values = struct.unpack('<%dh' % n, bytes(pcm[:n * 2]))
    except struct.error:
        return None
    # a rough "there is a voice here" gate: ignore near-silence and a fully
    # clipped signal.  Two talkers cannot be told apart from PCM alone; the
    # daemon passes quality=False when the recogniser reports an overlap.
    energy = math.fsum(float(v) * v for v in values[::16]) / max(1, len(values[::16]))
    rms = math.sqrt(energy)
    if rms < 60.0 or rms > 24000.0:
        return None
    return values


def quality(pcm, min_ms=DEFAULT_MIN_MS):
    """Whether there is enough clean voice for an enrollment (no vector made)."""
    return _samples(pcm, min_ms) is not None


def embedding(pcm, min_ms=DEFAULT_MIN_MS):
    """A 3D-Speaker vector for s16le@16k PCM, or None when unavailable/quiet."""
    values = _samples(pcm, min_ms)
    if values is None:
        return None
    if _backend is not None:
        try:
            result = _backend(bytes(pcm))
            return _clean(result)
        except Exception:
            return None
    if not available():
        return None
    path = str(model_path())
    native = _load_native()
    try:
        if native is not False:
            cfg = native.SpeakerEmbeddingExtractorConfig(model=path, num_threads=1)
            try:
                extractor = native.SpeakerEmbeddingExtractor(cfg)
            except AttributeError:
                extractor = native.SpeakerEmbeddingExtractor.from_config(cfg)
            stream = extractor.create_stream()
            stream.accept_waveform(SAMPLE_RATE,
                                   [v / 32768.0 for v in values])
            if not extractor.is_ready(stream):
                return None
            return _clean(extractor.compute(stream))
        result = subprocess.run([python_bin(), '-c', _WORKER, path],
                                input=bytes(pcm[:len(values) * 2]),
                                capture_output=True, timeout=30)
        if result.returncode:
            return None
        data = json.loads(result.stdout.decode('utf-8', 'replace'))
        return _clean(data.get('embedding'))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError,
            AttributeError, TypeError):
        return None


def _clean(vec):
    if vec is None:
        return None
    try:
        out = [float(x) for x in vec]
    except (TypeError, ValueError):
        return None
    return out if out and all(math.isfinite(x) for x in out) else None
