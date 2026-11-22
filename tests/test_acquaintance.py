#!/usr/bin/env python3
"""Acquaintance (voice enrollment) command: detection, brain path, request."""
import sys
import tempfile
from pathlib import Path

import gi
gi.require_version('GdkPixbuf', '2.0')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yumi import config  # noqa: E402
from yumi.brain import Brain, acquaintance_command  # noqa: E402
from yumi.phrases import Speech  # noqa: E402
from yumi.sprites import Meta  # noqa: E402


def brain(**settings):
    s = dict(config.DEFAULT_SETTINGS)
    s.update(settings)
    b = Brain(Meta(config.SPRITES, None), s,
              {'intro_done': True}, Speech(s), lambda *_a: (10, 10))
    b.actions_path = Path(tempfile.gettempdir()) / 'yumi-no-actions-acq.json'
    b.actions_mtime = 0.0
    b.custom = []
    return b


def test_acquaintance_command_matches_explicit_phrases():
    for text in [
        'давай познакомимся',
        'Юми, давай познакомимся',
        'запомни мой голос',
        'запиши мой голос',
        'хочу познакомиться',
        "let's get acquainted",
        'remember my voice',
        'enroll my voice',
        'learn my voice',
    ]:
        assert acquaintance_command(text), text


def test_acquaintance_command_rejects_tour_and_noise():
    for text in [
        'покажи знакомство',
        'показать знакомство',
        'открой знакомство',
        'show the tour',
        'расскажи анекдот',
        'включи музыку',
        'какая погода',
        'hello there',
        '',
        None,
    ]:
        assert not acquaintance_command(text), text


def test_heard_text_starts_acquaintance():
    b = brain(ui_lang='ru', speech_lang='ru')
    b.requests.clear()
    b.heard_text('давай познакомимся', wake=True)
    kinds = [r[0] for r in b.requests]
    assert 'speaker_acquaintance' in kinds, b.requests
    assert b.bubble is not None
    text = str(b.bubble.get('text') or '').lower()
    assert 'голос' in text or 'познаком' in text, b.bubble


def test_heard_text_acquaintance_from_alt():
    b = brain(ui_lang='ru', speech_lang='ru')
    b.requests.clear()
    b.heard_text('непонятно', wake=True, alt='запомни мой голос')
    kinds = [r[0] for r in b.requests]
    assert 'speaker_acquaintance' in kinds, b.requests


def test_acquaintance_begin_emits_request():
    b = brain()
    b.requests.clear()
    b.acquaintance_begin()
    assert ('speaker_acquaintance', None) in b.requests, b.requests


def test_speaker_acquaintance_action_path_mock(monkeypatch):
    """GTK path: speaker_action('speaker_acquaintance') waits for TTS then enrolls."""
    import time
    import threading
    from yumi.ui import senses

    calls = []
    class FakeBrain:
        now = 0.0
        talk_until = 0.0
        _speaker_current = None
        _speaker_last_event = ''
        _pending_speaker = None
        settings = {'speech_lang': 'ru'}
        class conversation:
            @staticmethod
            def add_participant(pid): calls.append(('add', pid))
            @staticmethod
            def remove_participant(pid): calls.append(('remove', pid))
            @staticmethod
            def clear_participants(): calls.append(('clear',))
        def _speaker_remember(self, spk): calls.append(('remember', spk.get('id')))
        def say(self, event, **kw): calls.append(('say', event, kw.get('label'))); return True
        def say_text(self, text, **kw): calls.append(('say_text', text, kw.get('voice'))); return True
        def set_face(self, face, ttl=None): calls.append(('face', face))
        def _voice_label(self, pid): return str(pid)

    class Fake(senses.SensesMixin):
        brain = FakeBrain()
        voice_queue = []
        _voice_ready = {}
        voice_pending = 0
        voice_streaming = False
        def wake_pause(self): calls.append(('pause',)); return True
        def wake_resume(self, was_on): calls.append(('resume', was_on))
        def web_sync_soon(self): calls.append(('sync',))

    monkeypatch.setattr(senses.ears, 'speaker_enroll', lambda **_kw: {'ok': True, 'id': 'spk_01', 'created': True, 'profiles': [{'id': 'spk_01', 'label': 'Голос 1'}]})
    # run GLib.idle_add callbacks immediately
    monkeypatch.setattr(senses.GLib, 'idle_add', lambda fn, *a: fn(*a) or False)

    f = Fake()
    f.speaker_action('speaker_acquaintance')
    # worker thread runs; wait a bit
    for _ in range(50):
        if ('resume', True) in calls:
            break
        time.sleep(0.02)
    assert ('pause',) in calls, calls
    assert ('resume', True) in calls, calls
    assert ('remember', 'spk_01') in calls, calls
    assert ('say', 'acquaintance_ok', 'Голос 1') in calls, calls
    # recording start/end signals: non-voice bubbles and face
    assert any(c[0] == 'say_text' and c[2] is False and 'Слушаю' in c[1] for c in calls), calls
    assert any(c[0] == 'say_text' and c[2] is False and 'Запись закончена' in c[1] for c in calls), calls
    assert ('face', 'listening') in calls, calls
    assert ('face', 'think') in calls, calls
    assert f.acquaintance['phase'] == 'done'
    assert f.acquaintance['active'] is False


def test_acquaintance_fail_on_noisy_or_short_voice(monkeypatch):
    import time
    from yumi.ui import senses

    calls = []
    class FakeBrain:
        now = 0.0; talk_until = 0.0
        _speaker_current = None; _speaker_last_event = ''; _pending_speaker = None
        settings = {'speech_lang': 'ru'}
        conversation = type('C', (), {'add_participant': staticmethod(lambda *_: None),
                                      'remove_participant': staticmethod(lambda *_: None),
                                      'clear_participants': staticmethod(lambda *_: None)})()
        def _speaker_remember(self, spk): calls.append(('remember', spk))
        def say(self, event, **kw): calls.append(('say', event)); return True
        def say_text(self, text, **kw): calls.append(('say_text', text, kw.get('voice'))); return True
        def set_face(self, face, ttl=None): calls.append(('face', face))
        def _voice_label(self, pid): return str(pid)

    class Fake(senses.SensesMixin):
        brain = FakeBrain()
        voice_queue = []; _voice_ready = {}; voice_pending = 0; voice_streaming = False
        def wake_pause(self): calls.append(('pause',)); return True
        def wake_resume(self, was_on): calls.append(('resume', was_on))
        def web_sync_soon(self): calls.append(('sync',))

    monkeypatch.setattr(senses.ears, 'speaker_enroll',
                        lambda **_kw: {'ok': False, 'error': 'not enough clear voice'})
    monkeypatch.setattr(senses.GLib, 'idle_add', lambda fn, *a: fn(*a) or False)
    f = Fake(); f.speaker_action('speaker_acquaintance')
    for _ in range(50):
        if ('resume', True) in calls: break
        time.sleep(0.02)
    assert ('say', 'acquaintance_fail') in calls, calls
    assert ('sync',) in calls, calls
    assert f.acquaintance['phase'] == 'error'
    assert f.acquaintance['active'] is False


def test_acquaintance_nomodel(monkeypatch):
    import time
    from yumi.ui import senses

    calls = []
    class FakeBrain:
        now = 0.0; talk_until = 0.0
        _speaker_current = None; _speaker_last_event = ''; _pending_speaker = None
        settings = {'speech_lang': 'ru'}
        conversation = type('C', (), {'add_participant': staticmethod(lambda *_: None),
                                      'remove_participant': staticmethod(lambda *_: None),
                                      'clear_participants': staticmethod(lambda *_: None)})()
        def _speaker_remember(self, spk): pass
        def say(self, event, **kw): calls.append(('say', event)); return True
        def say_text(self, text, **kw): calls.append(('say_text', text, kw.get('voice'))); return True
        def set_face(self, face, ttl=None): calls.append(('face', face))
        def _voice_label(self, pid): return str(pid)

    class Fake(senses.SensesMixin):
        brain = FakeBrain()
        voice_queue = []; _voice_ready = {}; voice_pending = 0; voice_streaming = False
        def wake_pause(self): return True
        def wake_resume(self, was_on): calls.append(('resume', was_on))
        def web_sync_soon(self): pass

    monkeypatch.setattr(senses.ears, 'speaker_enroll',
                        lambda **_kw: {'ok': False, 'error': 'speaker model is not available'})
    monkeypatch.setattr(senses.GLib, 'idle_add', lambda fn, *a: fn(*a) or False)
    f = Fake(); f.speaker_action('speaker_acquaintance')
    for _ in range(50):
        if ('resume', True) in calls: break
        time.sleep(0.02)
    assert ('say', 'acquaintance_nomodel') in calls, calls
    assert f.acquaintance['phase'] == 'error'


def test_wait_voice_quiet_blocks_until_tts_drains():
    import time
    from yumi.ui import senses

    class FakeBrain:
        now = 0.0; talk_until = 0.0

    class Fake(senses.SensesMixin):
        brain = FakeBrain()
        voice_queue = ['chunk']
        _voice_ready = {}
        voice_pending = 0
        voice_streaming = True

    f = Fake()
    t0 = time.time()
    def clear():
        time.sleep(0.25)
        f.voice_queue = []
        f.voice_streaming = False
    import threading
    threading.Thread(target=clear, daemon=True).start()
    ok = f._wait_voice_quiet(timeout=2.0)
    dt = time.time() - t0
    assert ok is True
    assert dt >= 0.25


def test_acquaintance_begin_skips_if_already_known():
    b = brain()
    b._speaker_current = {'id': 'spk_1', 'label': 'Николас', 'status': 'known', 'score': 0.9}
    b.requests.clear()
    b.acquaintance_begin()
    kinds = [r[0] for r in b.requests]
    assert 'speaker_acquaintance' not in kinds, b.requests
    text = str((b.bubble or {}).get('text') or '').lower()
    assert 'знаком' in text or 'николас' in text.lower(), b.bubble


def test_acquaintance_already_known_on_dedup(monkeypatch):
    import time
    from yumi.ui import senses

    calls = []
    class FakeBrain:
        now = 0.0; talk_until = 0.0
        _speaker_current = None; _speaker_last_event = ''; _pending_speaker = None
        settings = {'speech_lang': 'ru'}
        conversation = type('C', (), {'add_participant': staticmethod(lambda *_: None),
                                      'remove_participant': staticmethod(lambda *_: None),
                                      'clear_participants': staticmethod(lambda *_: None)})()
        def _speaker_remember(self, spk): calls.append(('remember', spk.get('id')))
        def say(self, event, **kw): calls.append(('say', event, kw.get('label'))); return True
        def say_text(self, text, **kw): calls.append(('say_text', text)); return True
        def set_face(self, face, ttl=None): pass
        def _voice_label(self, pid): return str(pid)

    class Fake(senses.SensesMixin):
        brain = FakeBrain()
        voice_queue = []; _voice_ready = {}; voice_pending = 0; voice_streaming = False
        def wake_pause(self): return True
        def wake_resume(self, was_on): calls.append(('resume', was_on))
        def web_sync_soon(self): calls.append(('sync',))

    monkeypatch.setattr(senses.ears, 'speaker_enroll',
                        lambda **_kw: {'ok': True, 'id': 'spk_01', 'created': False,
                                       'profile': {'id': 'spk_01', 'label': 'Николас'},
                                       'profiles': [{'id': 'spk_01', 'label': 'Николас'}]})
    monkeypatch.setattr(senses.GLib, 'idle_add', lambda fn, *a: fn(*a) or False)
    f = Fake(); f.speaker_action('speaker_acquaintance')
    for _ in range(50):
        if ('resume', True) in calls: break
        time.sleep(0.02)
    assert ('say', 'acquaintance_already', 'Николас') in calls, calls
    assert f.acquaintance['phase'] == 'done'
    assert f.acquaintance.get('already') is True


def test_acquaintance_extracts_profile_info(monkeypatch):
    import time
    from yumi.ui import senses

    calls = []
    class FakeBrain:
        now = 0.0; talk_until = 0.0
        _speaker_current = None; _speaker_last_event = ''; _pending_speaker = None
        settings = {'speech_lang': 'ru'}
        conversation = type('C', (), {'add_participant': staticmethod(lambda *_: None),
                                      'remove_participant': staticmethod(lambda *_: None),
                                      'clear_participants': staticmethod(lambda *_: None)})()
        def _speaker_remember(self, spk): calls.append(('remember', spk.get('id')))
        def say(self, event, **kw): calls.append(('say', event, kw.get('label'))); return True
        def say_text(self, text, **kw): calls.append(('say_text', text)); return True
        def set_face(self, face, ttl=None): pass
        def _voice_label(self, pid): return str(pid)

    class Fake(senses.SensesMixin):
        brain = FakeBrain()
        voice_queue = []; _voice_ready = {}; voice_pending = 0; voice_streaming = False
        def wake_pause(self): return True
        def wake_resume(self, was_on): calls.append(('resume', was_on))
        def web_sync_soon(self): pass

    monkeypatch.setattr(senses.ears, 'speaker_enroll',
                        lambda **_kw: {'ok': True, 'id': 'spk_01', 'created': True,
                                       'text': 'Меня зовут Николас, живу в Ялте, слушаю рок, работаю программистом, хобби шахматы',
                                       'profile': {'id': 'spk_01', 'label': 'Голос 1'},
                                       'profiles': [{'id': 'spk_01', 'label': 'Голос 1'}]})
    monkeypatch.setattr(senses.chat, 'ask',
                        lambda *a, **k: '{"name":"Николас","city":"Ялта","music":"рок","work":"программист","hobbies":"шахматы","about":""}')
    def fake_update(pid, label=None, info=None):
        calls.append(('update', pid, label, info))
        return {'ok': True, 'profile': {'id': pid, 'label': label, 'info': info},
                'profiles': [{'id': pid, 'label': label, 'info': info}]}
    monkeypatch.setattr(senses.ears, 'speaker_update', fake_update)
    monkeypatch.setattr(senses.GLib, 'idle_add', lambda fn, *a: fn(*a) or False)

    f = Fake(); f.speaker_action('speaker_acquaintance')
    for _ in range(50):
        if ('resume', True) in calls: break
        time.sleep(0.02)
    assert any(c[0] == 'update' and c[2] == 'Николас' and c[3].get('city') == 'Ялта' for c in calls), calls
    assert ('say', 'acquaintance_ok', 'Николас') in calls, calls
