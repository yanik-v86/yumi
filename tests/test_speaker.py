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


def test_multiple_samples_match_different_phrases(store):
    """One person says different things; the closest stored sample must win."""
    # two quite different readings of the same voice (real 3D-Speaker scores
    # vary 0.35-0.95).  dedup at 0.75 still folds them into one profile.
    a = unit([1.0, 0.0, 0.0])
    b = unit([0.7, 0.7, 0.0])       # cos(a,b) = 0.70 < dedup: a new profile
    c = unit([0.7, 0.72, 0.0])      # cos(b,c) ~ 0.999 > dedup: same as b
    first = store.enroll(a, 'Николай', source='manual')
    second = store.enroll(b, 'Николай', source='wake')
    assert second != first          # too far to dedup on its own
    merged = store.merge([first, second], label='Николай')
    assert merged == first
    assert len(store.list()) == 1
    # a third reading close to the second now recognises the merged profile
    third = store.enroll(c, 'Николай', source='manual')
    assert third == first
    raw = json.loads(store.path.read_text())
    assert len(raw['profiles'][0]['embeddings']) == 3
    assert store.verify(a)['id'] == first
    assert store.verify(b)['id'] == first


def test_wake_near_miss_joins_existing_profile(monkeypatch, tmp_path):
    """A phrase scoring 0.60 must add a sample, not spawn «Голос 2».

    Real 3D-Speaker readings of one person range 0.35-0.95.  A wake phrase just
    under the verify threshold used to auto-enroll a generic profile, so asking
    «как меня зовут» answered «мы ещё не знакомы» right after her own name.
    """
    from yumi import stt_daemon

    monkeypatch.setenv('YUMI_SPEAKER_FILE', str(tmp_path / 'speakers.json'))
    cfg = tmp_path / 'cfg' / 'yumi'
    cfg.mkdir(parents=True)
    (cfg / 'settings.json').write_text(json.dumps({
        'speaker_verify': True, 'speaker_threshold': 0.65,
        'speaker_min_ms': 1200, 'speaker_join_policy': 'addressed'}))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'cfg'))

    base = unit([1.0, 0.0, 0.0])
    near = unit([0.6, 0.8, 0.0])       # cos = 0.60: below 0.65, above SOFT_MATCH
    monkeypatch.setattr(speaker_sherpa, 'quality', lambda pcm, min_ms=1200: True)
    monkeypatch.setattr(speaker_sherpa, 'embedding',
                        lambda pcm, min_ms=1200: near)

    pid = speaker.enroll(base, 'Николай', source='manual')
    field = stt_daemon.speaker_voice(tone(2.0), 'привет', wake=True)
    assert field['status'] == 'known'
    assert field['id'] == pid
    assert field['score'] == pytest.approx(0.6, abs=0.01)
    s = speaker.store()
    assert len(s.profiles) == 1                  # no generic duplicate
    assert len(s.profiles[0]['embeddings']) == 2  # the new reading was kept
    assert s.profiles[0]['label'] == 'Николай'


def test_followup_near_miss_stays_in_dialogue(monkeypatch, tmp_path):
    """The second phrase of a dialogue has no name: a near-miss must still be
    the same participant, not «speaker gate: not for me» and silence."""
    from yumi import stt_daemon

    monkeypatch.setenv('YUMI_SPEAKER_FILE', str(tmp_path / 'speakers.json'))
    cfg = tmp_path / 'cfg' / 'yumi'
    cfg.mkdir(parents=True)
    (cfg / 'settings.json').write_text(json.dumps({
        'speaker_verify': True, 'speaker_threshold': 0.65,
        'speaker_min_ms': 1200, 'speaker_join_policy': 'strict'}))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'cfg'))

    base = unit([1.0, 0.0, 0.0])
    near = unit([0.6, 0.8, 0.0])       # cos = 0.60: below 0.65, above SOFT_MATCH
    monkeypatch.setattr(speaker_sherpa, 'quality', lambda pcm, min_ms=1200: True)
    monkeypatch.setattr(speaker_sherpa, 'embedding',
                        lambda pcm, min_ms=1200: near)

    pid = speaker.enroll(base, 'Николай', source='manual')
    field = stt_daemon.speaker_voice(tone(2.0), 'расскажи мне анекдот', join=True)
    assert field['status'] == 'known'
    assert field['id'] == pid
    assert field['joined_id'] is None  # he was already in the dialogue
    assert field['score'] == pytest.approx(0.6, abs=0.01)
    assert len(speaker.store().profiles) == 1
    assert len(speaker.store().profiles[0]['embeddings']) == 2  # sample kept


def test_wake_new_voice_still_gets_own_profile(monkeypatch, tmp_path):
    """Below SOFT_MATCH a genuinely different voice must not join the profile."""
    from yumi import stt_daemon

    monkeypatch.setenv('YUMI_SPEAKER_FILE', str(tmp_path / 'speakers.json'))
    cfg = tmp_path / 'cfg' / 'yumi'
    cfg.mkdir(parents=True)
    (cfg / 'settings.json').write_text(json.dumps({
        'speaker_verify': True, 'speaker_threshold': 0.65,
        'speaker_min_ms': 1200, 'speaker_join_policy': 'addressed'}))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'cfg'))

    far = unit([0.0, 1.0, 0.0])
    monkeypatch.setattr(speaker_sherpa, 'quality', lambda pcm, min_ms=1200: True)
    monkeypatch.setattr(speaker_sherpa, 'embedding',
                        lambda pcm, min_ms=1200: far)
    speaker.enroll(unit([1.0, 0.0, 0.0]), 'Николай', source='manual')
    field = stt_daemon.speaker_voice(tone(2.0), 'привет', wake=True)
    assert field['status'] == 'known'
    assert field['joined_id'] == 'spk_02'
    assert len(speaker.store().profiles) == 2


def test_old_schema_single_vector_still_loads(monkeypatch, tmp_path):
    path = tmp_path / 'speakers.json'
    monkeypatch.setenv('YUMI_SPEAKER_FILE', str(path))
    path.write_text(json.dumps({'version': 2, 'profiles': [
        {'id': 'spk_01', 'label': 'Аня', 'embedding': [1.0, 0.0, 0.0], 'source': 'wake'},
    ]}))
    s = speaker.SpeakerStore()
    assert s.verify([1.0, 0.0, 0.0])['id'] == 'spk_01'
    assert len(s.profiles[0]['embeddings']) == 1


def test_snapshot_reloads_daemon_edits(store):
    """The panel and the ears daemon are different processes: the GTK cache must re-read."""
    pid = store.enroll([1.0, 0.0], 'Аня', source='wake')
    assert [p['id'] for p in speaker.snapshot()['profiles']] == [pid]
    other = speaker.SpeakerStore()          # simulates the daemon's own store
    assert other.delete(pid) is True
    assert [p['id'] for p in speaker.store().list()] == [pid], 'the cached copy is stale'
    assert speaker.snapshot()['profiles'], 'a plain snapshot is the cached view'
    assert speaker.snapshot(reload=True)['profiles'] == []
    after = speaker.SpeakerStore()
    after.enroll([0.0, 1.0], 'Борис', source='join')
    assert [p['label'] for p in speaker.snapshot(reload=True)['profiles']] == ['Борис']


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


def test_daemon_api_wrappers(monkeypatch, tmp_path):
    """The STT daemon calls these module functions; a missing kwarg kills enrollment."""
    monkeypatch.setenv('YUMI_SPEAKER_FILE', str(tmp_path / 'speakers.json'))
    pid = speaker.enroll([1.0, 0.0], 'Николай', source='manual',
                         info={'name': 'Николай', 'city': 'Анапа'})
    assert pid
    row = speaker.profile(pid)
    assert row['label'] == 'Николай'
    assert row['info']['city'] == 'Анапа'
    assert speaker.update_info(pid, {'music': 'инди'}, label='Коля') is True
    row = speaker.profile(pid)
    assert row['label'] == 'Коля'
    assert row['info']['city'] == 'Анапа' and row['info']['music'] == 'инди'
    assert 'embedding' not in json.dumps(row)


def test_cosine_fallback(store, monkeypatch):
    monkeypatch.setattr(speaker, '_np', None)
    assert speaker.cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert speaker.cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert speaker.cosine([1, 0], [1]) == 0.0
    assert speaker.cosine([], []) == 0.0


def test_fake_backend(tmp_path, monkeypatch):
    monkeypatch.setenv('YUMI_SPEAKER_FILE', str(tmp_path / 'speakers.json'))
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
