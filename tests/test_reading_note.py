#!/usr/bin/env python3
"""The second ear is a local hint, never a line in the mind's prompt.

The old crosscheck note listed both readings as a system message.  The model
started discussing «первое/второе ухо» instead of answering — the diary still
holds replies like «второе ухо мозги включило, а первое тупит».  Only the
primary reading may reach the chat; Vosk's reading stays for local commands.
Run: python3 tests/test_reading_note.py"""
import sys
import tempfile
from pathlib import Path

import gi
gi.require_version('GdkPixbuf', '2.0')
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

from yumi import brain as brain_mod, config  # noqa: E402
from yumi.phrases import Speech  # noqa: E402
from yumi.sprites import Meta  # noqa: E402


def brain(**settings):
    s = dict(config.DEFAULT_SETTINGS)
    s.update(settings)
    b = brain_mod.Brain(Meta(config.SPRITES, None), s,
                        {'intro_done': True}, Speech(s), lambda *_a: (10, 10))
    b.actions_path = Path(tempfile.gettempdir()) / 'yumi-no-actions-reading.json'
    b.actions_mtime = 0.0
    b.custom = []
    return b


def test_only_primary_reading_reaches_the_mind():
    b = brain(ui_lang='ru', speech_lang='ru')
    b.requests.clear()
    b.heard_text('расскажи мне кто это все', wake=True,
                 alt='хорошее имя расскажи анекдот')
    asks = [r for r in b.requests if r[0] == 'chat_ask']
    assert len(asks) == 1, b.requests
    whole = str(asks[0][1])
    assert 'расскажи мне кто это все' in whole
    assert 'расскажи анекдот' not in whole          # the other ear stayed out
    assert 'ухо' not in whole.lower()               # no meta-talk about the ears
    assert all(m['role'] != 'system' for m in asks[0][1])


def test_alt_still_routes_a_local_command():
    """Dropping the prompt note must not blind the local command matcher."""
    b = brain(ui_lang='ru', speech_lang='ru')
    b.requests.clear()
    b.heard_text('непонятно', wake=True, alt='запомни мой голос')
    assert ('speaker_acquaintance', None) in b.requests, b.requests


def test_no_two_ear_note_helper_left():
    assert not hasattr(brain_mod, 'reading_note')


if __name__ == '__main__':
    test_only_primary_reading_reaches_the_mind()
    test_alt_still_routes_a_local_command()
    test_no_two_ear_note_helper_left()
    print('reading note checks: ok')
