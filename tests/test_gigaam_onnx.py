#!/usr/bin/env python3
"""The GigaAM ONNX reader: files it needs, and a torch-free read of a tape.

The real export is ~900 MB, so this checks the contract with tiny fake sessions:
one mel frontend, one encoder, one RNN-T advance graph, two SentencePiece files.
No torch may appear in Yumi's ears venv; the module imports only numpy at load.
Run: python3 tests/test_gigaam_onnx.py"""
import sys
import tempfile
import types
from pathlib import Path

import numpy as np

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

from yumi import gigaam_onnx as g  # noqa: E402


class FakeOptions:
    intra_op_num_threads = 0
    inter_op_num_threads = 0
    log_severity_level = 0


class FakeSession:
    def __init__(self, path, options, providers=None):
        self.path = str(path)

    def run(self, names, feeds):
        if 'audio_signal' in feeds:
            frames = int(feeds['audio_signal'].shape[-1])
            return (np.array([frames], dtype=np.int64),
                    np.zeros((2, 1025, frames), dtype=np.float32))
        # three positions, two heads, one beam: -1 is padding
        return (np.array([[[10], [20]], [[11], [21]], [[-1], [-1]]],
                         dtype=np.int64),)


class FakeSentencePiece:
    def load(self, path):
        self.path = str(path)

    def decode(self, ids):
        assert ids, 'the padding must be stripped before decoding'
        return 'e2e ok' if 'e2e' in self.path else 'raw ok'


def test_available_needs_the_whole_export():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        assert g.available(d) is False
        for name in ('rnnt_encoder.onnx', 'rnnt_advance.onnx',
                     'rnnt_e2e_tokenizer.model', 'rnnt_raw_tokenizer.model'):
            (d / name).touch()
        assert g.available(d) is True


def test_read_without_torch():
    saved = {name: sys.modules.get(name) for name in ('onnxruntime', 'sentencepiece')}
    sys.modules['onnxruntime'] = types.SimpleNamespace(
        SessionOptions=FakeOptions, InferenceSession=FakeSession)
    sys.modules['sentencepiece'] = types.SimpleNamespace(
        SentencePieceProcessor=FakeSentencePiece)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for name in ('rnnt_encoder.onnx', 'rnnt_advance.onnx',
                         'rnnt_e2e_tokenizer.model', 'rnnt_raw_tokenizer.model'):
                (d / name).touch()
            model = g.GigaAM(d, threads=1)
            feats, lengths = model.features(np.zeros(16000, dtype=np.float32))
            assert feats.shape == (1, 64, 99), feats.shape
            assert lengths.tolist() == [99]
            assert model.transcribe_pcm(b'\0\0' * 16000) == {
                'e2e': 'e2e ok', 'raw': 'raw ok'}
            assert 'import torch' not in Path(g.__file__).read_text()
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


print('test_gigaam_onnx: ok')
if __name__ == '__main__':
    sys.exit(0)
