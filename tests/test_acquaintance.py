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
        class conversation:
            @staticmethod
            def add_participant(pid): calls.append(('add', pid))
            @staticmethod
            def remove_participant(pid): calls.append(('remove', pid))
            @staticmethod
            def clear_participants(): calls.append(('clear',))
        def _speaker_remember(self, spk): calls.append(('remember', spk.get('id')))
        def say(self, event, **kw): calls.append(('say', event, kw.get('label'))); return True
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

    monkeypatch.setattr(senses.ears, 'speaker_enroll', lambda: {'ok': True, 'id': 'spk_01', 'profiles': [{'id': 'spk_01', 'label': 'Голос 1'}]})
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
