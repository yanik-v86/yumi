"""GigaAM-v4 read through exported ONNX graphs, without torch in the ears' venv.

tools/gigaam_setup.sh exports a pinned ``rnnt`` revision into
``$YUMI_STT_HOME/gigaam/full`` (the encoder, the RNN-T advance graph and the two
SentencePiece tokenizers). This module reads those files with onnxruntime, builds
the same log-mel frontend as torchaudio and runs the advance graph — no custom
model code from Hugging Face is executed at inference time. A phrase takes about
0.2 s of CPU on a laptop; the model is meant to be loaded once and kept warm.
"""
import os
import wave
from pathlib import Path

import numpy as np

HOME = Path(os.environ.get('YUMI_STT_HOME') or Path.home() / '.local/share/yumi/stt')
MODEL_DIR = HOME / 'gigaam' / 'full'

# The exporter's config; PyYAML is optional, these are GigaAM-v4's fixed values.
DEFAULT_PRE = {'features': 64, 'hop_length': 160, 'n_fft': 320,
               'lowfreq': 0, 'highfreq': 8000, 'sample_rate': 16000}
RATE = 16000


def available(directory=None):
    """True when the exported graphs and both tokenizers are on disk"""
    d = Path(directory or MODEL_DIR)
    return (any(d.glob('*_encoder.onnx')) and any(d.glob('*_advance.onnx'))
            and any(d.glob('*_e2e_tokenizer.model'))
            and any(d.glob('*_raw_tokenizer.model')))


def _mel_filterbank(n_mels, n_fft, low, high, rate):
    """torchaudio's HTK mel bank, with continuous frequencies and no normalisation"""
    def hz_to_mel(hz):
        return 2595.0 * np.log10(1.0 + hz / 700.0)

    def mel_to_hz(mel):
        return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

    all_freqs = np.linspace(0, rate // 2, n_fft // 2 + 1)
    points = np.linspace(hz_to_mel(low), hz_to_mel(high), n_mels + 2)
    f_pts = mel_to_hz(points)
    diff = f_pts[1:] - f_pts[:-1]
    slopes = f_pts[None, :] - all_freqs[:, None]
    down = -slopes[:, :-2] / diff[:-1]
    up = slopes[:, 2:] / diff[1:]
    return np.maximum(0.0, np.minimum(down, up)).T.astype(np.float32)


class GigaAM:
    """One warm ONNX session pair; call transcribe_* with 16 kHz mono sound"""

    def __init__(self, directory=None, threads=2):
        import onnxruntime as rt
        import sentencepiece as spm

        d = Path(directory or MODEL_DIR)
        pre = dict(DEFAULT_PRE)
        cfg_file = next(d.glob('*.yaml'), None)
        if cfg_file:
            try:
                import yaml
                pre.update(yaml.safe_load(cfg_file.read_text()).get('preprocessor') or {})
            except (ImportError, OSError, ValueError, AttributeError):
                pass
        self.hop, self.n_fft = int(pre['hop_length']), int(pre['n_fft'])
        self.fb = _mel_filterbank(int(pre['features']), self.n_fft,
                                  int(pre['lowfreq']), int(pre['highfreq']),
                                  int(pre.get('sample_rate') or RATE))
        self.window = (0.5 - 0.5 * np.cos(
            2 * np.pi * np.arange(self.n_fft) / self.n_fft)).astype(np.float32)
        opts = rt.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        opts.log_severity_level = 3
        provider = ['CPUExecutionProvider']
        self.encoder = rt.InferenceSession(str(next(d.glob('*_encoder.onnx'))),
                                           opts, providers=provider)
        self.advance = rt.InferenceSession(str(next(d.glob('*_advance.onnx'))),
                                           opts, providers=provider)
        self.names = ('e2e', 'raw')     # the dual head of the rnnt revision
        self.sp = {}
        for name in self.names:
            tok = next(d.glob(f'*_{name}_tokenizer.model'))
            processor = spm.SentencePieceProcessor()
            processor.load(str(tok))
            self.sp[name] = processor

    def features(self, audio):
        """float32 waveform -> (log-mel [1, 64, frames], frame lengths)"""
        audio = np.asarray(audio, dtype=np.float32)
        if len(audio) < self.n_fft:
            return np.zeros((1, self.fb.shape[0], 0), np.float32), np.zeros(1, np.int64)
        frames = np.lib.stride_tricks.sliding_window_view(audio, self.n_fft)[::self.hop]
        spec = np.abs(np.fft.rfft(frames * self.window, n=self.n_fft, axis=1)).T
        mel = np.log(np.clip(self.fb @ (spec * spec), 1e-9, 1e9)).astype(np.float32)
        return mel[None], np.array([mel.shape[-1]], dtype=np.int64)

    def transcribe(self, audio):
        """16 kHz mono float32 array -> {'e2e': formatted, 'raw': unformatted}"""
        feats, lengths = self.features(audio)
        lens, labels = self.encoder.run(None, {'audio_signal': feats,
                                               'length': lengths})
        tokens = self.advance.run(None, {'projected': labels, 'lengths': lens})[0]
        out = {}
        for i, name in enumerate(self.names):
            row = tokens[:, i, 0]
            row = row[row >= 0]         # -1 is padding; blanks are handled in the graph
            out[name] = self.sp[name].decode(row.astype(int).tolist())
        return out

    def transcribe_pcm(self, pcm):
        """s16 mono bytes RATE -> the same two readings"""
        return self.transcribe(np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0)

    def transcribe_file(self, path):
        """a 16 kHz mono wav -> the same two readings"""
        with wave.open(str(path), 'rb') as f:
            if f.getframerate() != RATE or f.getnchannels() != 1:
                raise ValueError(f'GigaAM needs {RATE} Hz mono wav: {path}')
            return self.transcribe_pcm(f.readframes(f.getnframes()))


_model = None


def load(directory=None, threads=2):
    """the shared warm model, loaded on the first need"""
    global _model
    if _model is None:
        _model = GigaAM(directory, threads)
    return _model
