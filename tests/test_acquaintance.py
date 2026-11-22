#!/usr/bin/env python3
"""Acquaintance (voice enrollment) command: detection, brain path, request."""
import sys
import tempfile
from pathlib import Path

import gi
gi.require_version('GdkPixbuf', '2.0')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yumi import config, speaker as voices, stt_daemon as stt  # noqa: E402
from yumi.brain import Brain, acquaintance_command, named_voice_label  # noqa: E402
from yumi.phrases import Speech  # noqa: E402
from yumi.sprites import Meta  # noqa: E402
from yumi.ui.senses import local_profile_fields  # noqa: E402


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
        'давай знакомиться',
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


def test_generic_labels_are_not_names():
    for label in ('', 'Голос', 'Голос 1', 'voice 2', 'spk_03', 'spk_1'):
        assert voices.is_generic_label(label), label
        assert not named_voice_label(label), label
    assert named_voice_label('Николай') == 'Николай'
    assert named_voice_label('John') == 'John'


def test_placeholder_profile_does_not_block_acquaintance():
    b = brain(ui_lang='ru', speech_lang='ru')
    b._speaker_current = {'id': 'spk_01', 'label': 'Голос 1', 'status': 'known'}
    b.requests.clear()
    b.acquaintance_begin()
    assert ('speaker_acquaintance', None) in b.requests, b.requests


def test_name_question_ignores_placeholder_label():
    b = brain(ui_lang='ru', speech_lang='ru')
    b._speaker_current = {'id': 'spk_01', 'label': 'Голос 1', 'status': 'known'}
    b.heard_text('как меня зовут', wake=True)
    text = str(b.bubble.get('text') or '').lower()
    assert 'не знакомы' in text, b.bubble


def test_wake_does_not_enroll_on_acquaintance_command():
    assert stt.wake_enrollment_allowed('привет') is True
    assert stt.wake_enrollment_allowed('давай познакомимся') is False
    assert stt.wake_enrollment_allowed('как дела', 'запомни мой голос') is False


def test_local_profile_fields_without_llm():
    fields = local_profile_fields('меня зовут николай я живу в городе анапа работает тьюториалс')
    assert fields['name'] == 'Николай', fields
    assert fields['city'] == 'Анапа', fields
    fields = local_profile_fields('My name is John and I live in Ottawa')
    assert fields['name'] == 'John', fields
    assert fields['city'] == 'Ottawa', fields


def test_extract_acquaintance_info_falls_back_to_local(monkeypatch):
    from yumi.ui import senses

    monkeypatch.setattr(senses.chat, 'ask', lambda *_a, **_kw: '')

    class Fake(senses.SensesMixin):
        class brain:
            settings = {}

    info = Fake()._extract_acquaintance_info('Меня зовут Николай, я живу в городе Анапа')
    assert info['name'] == 'Николай', info
    assert info['city'] == 'Анапа', info


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
    # a generated placeholder is never called a name
    assert not any(c[0] == 'say' and c[2] == 'Голос 1' for c in calls), calls
    assert any(c[0] == 'say_text' and 'запомнила твой голос' in str(c[1]) for c in calls), calls
    # recording start/end signals: non-voice bubbles and face
    assert any(c[0] == 'say_text' and c[2] is False and 'Слушаю' in c[1] for c in calls), calls
    assert any(c[0] == 'say_text' and c[2] is False and 'Запись закончена' in c[1] for c in calls), calls
    assert ('face', 'listening') in calls, calls
    assert ('face', 'think') in calls, calls
    assert f.acquaintance['phase'] == 'done'
    assert f.acquaintance['active'] is False


def test_acquaintance_learns_name_on_dedup(monkeypatch):
    """A wake-created «Голос 1» profile must be upgraded, not called «already»."""
    import time
    from yumi.ui import senses

    calls = []
    class FakeBrain:
        now = 0.0
        talk_until = 0.0
        _speaker_current = None
        _speaker_last_event = ''
        _pending_speaker = None
        settings = {'speech_lang': 'ru'}
        conversation = type('C', (), {'add_participant': staticmethod(lambda *_: None),
                                      'remove_participant': staticmethod(lambda *_: None),
                                      'clear_participants': staticmethod(lambda *_: None)})()
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

    monkeypatch.setattr(senses.ears, 'speaker_enroll', lambda **_kw: {
        'ok': True, 'id': 'spk_01', 'created': False,
        'profile': {'id': 'spk_01', 'label': 'Голос 1'},
        'text': 'Меня зовут Николай, я живу в городе Анапа',
    })
    monkeypatch.setattr(senses.ears, 'speaker_update', lambda pid, **kw: {
        'ok': True, 'profile': {'id': pid, 'label': kw.get('label')}, 'profiles': [],
    })
    # No key / no network in the test: the local fallback must supply the name.
    monkeypatch.setattr(senses.chat, 'ask', lambda *_a, **_kw: '')
    monkeypatch.setattr(senses.GLib, 'idle_add', lambda fn, *a: fn(*a) or False)

    f = Fake()
    f.speaker_action('speaker_acquaintance')
    for _ in range(50):
        if ('resume', True) in calls:
            break
        time.sleep(0.02)
    assert ('say', 'acquaintance_ok', 'Николай') in calls, calls
    assert not any(c[0] == 'say' and c[1] == 'acquaintance_already' for c in calls), calls
    assert f.acquaintance['label'] == 'Николай', f.acquaintance
    assert f.acquaintance['already'] is False, f.acquaintance


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


def test_wait_voice_quiet_waits_for_single_line_synthesis():
    """speak() holds a whole line in voice_pending, not in the streaming queue"""
    import threading
    import time
    from yumi.ui import senses

    class FakeBrain:
        now = 0.0
        talk_until = 0.0

    class Fake(senses.SensesMixin):
        brain = FakeBrain()
        voice_queue = []
        _voice_ready = {}
        voice_pending = 1       # the introduction is being synthesized
        voice_streaming = False
        voice_proc = None

    f = Fake()
    t0 = time.time()

    def clear():
        time.sleep(0.25)
        f.voice_pending = 0

    threading.Thread(target=clear, daemon=True).start()
    assert f._wait_voice_quiet(timeout=2.0) is True
    assert time.time() - t0 >= 0.25


def test_wait_voice_quiet_waits_for_playing_line():
    """a line already on the air is not in any queue either"""
    import threading
    import time
    from yumi.ui import senses

    class Proc:
        def poll(self):
            return None         # still playing

    class FakeBrain:
        now = 0.0
        talk_until = 0.0

    class Fake(senses.SensesMixin):
        brain = FakeBrain()
        voice_queue = []
        _voice_ready = {}
        voice_pending = 0
        voice_streaming = False
        voice_proc = Proc()

    f = Fake()
    t0 = time.time()

    def clear():
        time.sleep(0.25)
        f.voice_proc = None

    threading.Thread(target=clear, daemon=True).start()
    assert f._wait_voice_quiet(timeout=2.0) is True
    assert time.time() - t0 >= 0.25


def test_acquaintance_command_shared_with_ears():
    """the wake's fallback router and the brain must agree on the same words"""
    from yumi import addressing, stt_daemon as stt

    for text in ('давай знакомиться', 'давай познакомимся', 'запомни мой голос',
                 'покажи знакомство', 'расскажи анекдот'):
        assert acquaintance_command(text) == addressing.acquaintance_command(text), text
    assert stt.fallback_route('давай знакомиться') == 'command'


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


def test_name_question_helper():
    assert Brain._name_question('как меня зовут')
    assert Brain._name_question('what is my name')
    assert not Brain._name_question('как тебя зовут')
    assert not Brain._name_question('расскажи анекдот')
