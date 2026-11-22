#!/usr/bin/env python3
"""Voice prints: store, dedup, verification, fake and optional real model."""
import json
import math
import os
import struct
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))
from yumi import speaker, speaker_sherpa  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('YUMI_SPEAKER_FILE', str(tmp_path / 'speakers.json'))
    return speaker.SpeakerStore()


def tone(seconds=1.5, freq=220.0, amp=9000):
    """Fake s16le@16k voice: a steady tone with a little variation."""
    n = int(seconds * 16000)
    return struct.pack('<%dh' % n, *(
        int(amp * (0.8 + 0.2 * math.sin(i / 800.0)) * math.sin(2 * math.pi * freq * i / 16000))
        for i in range(n)))


def unit(vec):
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def test_store_roundtrip(store):
    pid = store.enroll([1.0, 0.0, 0.0], 'Аня', source='wake')
    assert pid == 'spk_01'
    assert store.verify([1.0, 0.0, 0.0], 0.65)['status'] == 'known'
    assert store.verify([0.0, 1.0, 0.0], 0.65)['status'] == 'unknown'
    assert store.list()[0]['label'] == 'Аня'
    assert store.rename(pid, 'Голос Ани') is True
    assert store.verify([1.0, 0.0, 0.0])['id'] == pid
    reloaded = speaker.SpeakerStore()
    assert reloaded.list()[0]['label'] == 'Голос Ани'
    assert reloaded.verify([1.0, 0.0, 0.0])['status'] == 'known'
    assert reloaded.delete(pid) is True
    assert speaker.SpeakerStore().list() == []
    assert store.delete('nope') is False


def test_dedup_refreshes_instead_of_copying(store):
    first = store.enroll([1.0, 0.0], source='join')
    again = store.enroll([0.99, 0.01], source='wake')
    assert again == first
    assert len(store.list()) == 1
    second = store.enroll([0.0, 1.0], label='Голос 2', source='join')
    assert second != first
    assert len(store.list()) == 2


def test_broken_and_empty_files(monkeypatch, tmp_path):
    path = tmp_path / 'speakers.json'
    monkeypatch.setenv('YUMI_SPEAKER_FILE', str(path))
    path.write_text('')
    store = speaker.SpeakerStore()
    assert store.list() == [] and store.diag
    assert (tmp_path / 'speakers.json.bad').exists()
    path.write_text(json.dumps({'version': 2, 'profiles': []}))
    assert speaker.SpeakerStore().list() == []
    path.write_text(json.dumps({'version': 1, 'profiles': [
        {'id': 'ok', 'label': 'x', 'embedding': [1.0, 0.0], 'source': 'wake'},
        {'id': 'bad', 'embedding': 'junk'},
    ]}))
    store = speaker.SpeakerStore()
    assert [p['id'] for p in store.list()] == ['ok']
    assert 'bad' in store.diag
    # a missing file and bad vectors are harmless
    path.unlink()
    assert speaker.SpeakerStore().verify(None)['status'] == 'disabled'
    assert speaker.verify([1.0])['status'] == 'unknown'


def test_snapshot_has_no_vectors(store):
    store.enroll([0.1, 0.2, 0.3])
    snap = store.snapshot()
    assert snap['count'] == 1 and snap['profiles'][0]['id'] == 'spk_01'
    assert 'embedding' not in json.dumps(snap)


def test_cosine_fallback(store, monkeypatch):
    monkeypatch.setattr(speaker, '_np', None)
    assert speaker.cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert speaker.cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert speaker.cosine([1, 0], [1]) == 0.0
    assert speaker.cosine([], []) == 0.0


def test_fake_backend(tmp_path, monkeypatch):
    monkeypatch.delenv('YUMI_SPEAKER_MODEL', raising=False)
    fake = unit([0.2, 0.7, -0.1])
    speaker_sherpa.set_backend(lambda pcm: fake if len(pcm) > 20000 else None)
    try:
        assert speaker_sherpa.available() is True
        assert speaker_sherpa.model_info()['ready'] is True
        got = speaker_sherpa.embedding(tone())
        assert got == pytest.approx(fake)
        assert speaker_sherpa.embedding(b'\x00' * 100) is None   # too short
        assert speaker_sherpa.embedding(b'\x00' * 40000) is None  # silence
        assert speaker_sherpa.quality(tone()) is True
        pid = speaker.enroll(got, source='wake')
        assert speaker.verify(fake)['id'] == pid
    finally:
        speaker_sherpa.set_backend(None)


def test_missing_backend_is_soft(monkeypatch, tmp_path):
    monkeypatch.setenv('YUMI_STT_HOME', str(tmp_path / 'no-venv'))
    monkeypatch.setenv('YUMI_SPEAKER_MODEL', str(tmp_path / 'no-model.onnx'))
    speaker_sherpa.set_backend(None)
    assert speaker_sherpa.available() is False
    assert speaker_sherpa.model_info()['ready'] is False
    assert speaker_sherpa.embedding(tone()) is None


@pytest.mark.skipif(os.environ.get('YUMI_SPEAKER_SMOKE') != '1',
                    reason='optional real-model smoke (needs tools/speaker_setup.sh)')
def test_real_model_smoke():
    """Three dataset clips: same file scores above the threshold, other voice below."""
    from yumi import config
    import wave
    base = config.HERE / 'dataset' / 'yumi_clean'
    assert speaker_sherpa.available(), speaker_sherpa.model_info()
    vecs = []
    for name in ('irina', 'ruslan'):
        clips = sorted((base / name).glob('*.wav'))[:8]
        if len(clips) < 8:
            pytest.skip('no dataset clips')
        pcm = b''
        for path in clips:                  # the clips are shorter than speaker_min_ms
            with wave.open(str(path)) as w:
                assert w.getframerate() == 16000
                pcm += w.readframes(w.getnframes())
        vec = speaker_sherpa.embedding(pcm)
        assert vec is not None, name
        vecs.append(vec)
    same = speaker_sherpa.embedding(pcm)
    assert speaker.cosine(same, vecs[-1]) >= speaker.DEDUP_SCORE
    assert speaker.cosine(vecs[0], vecs[1]) < speaker.DEDUP_SCORE
