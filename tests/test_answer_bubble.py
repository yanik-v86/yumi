#!/usr/bin/env python3
"""An answer's bubble must outlive TTS preparation, or her voice is dropped."""
import sys
from pathlib import Path

import gi
gi.require_version('GdkPixbuf', '2.0')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yumi.ui.app import App            # noqa: E402
from yumi.ui import senses             # noqa: E402


def test_speak_keeps_bubble_alive_while_line_is_made(monkeypatch):
    """speak() is called before the WAV exists; its bubble gets a safety floor"""
    class Brain:
        now = 100.0
        bubble = {'id': 7, 'text': 'анекдот', 'until': 104.0}

    class Fake(senses.SensesMixin):
        brain = Brain()
        settings = {'voice_kind': 'blips'}
        voice_queue = []
        _voice_ready = {}
        voice_pending = 0
        voice_streaming = False
        voice_proc = None
        voice_preview = False
        voice_id = None
        _voice_seq = 0
        _voice_next = 1
        _voice_state = lambda self: None
        hush = lambda self: None

    monkeypatch.setattr(senses.voice, 'render', lambda *a, **kw: None)
    f = Fake()
    f.speak([0.1], 7, 0, 0.5, 'расскажи анекдот')
    assert f.voice_id == 7
    assert f.brain.bubble['until'] >= 160.0, f.brain.bubble


def test_frame_does_not_shorten_bubble_during_synthesis():
    """the 'voice is over' clamp must wait for voice_pending to clear"""
    class Brain:
        now = 100.0
        chat_streaming = False
        bubble = {'id': 7, 'text': 'анекдот', 'until': 160.0}
        form = False

        def update(self, _now):
            pass

        def scene(self):
            return {}

        def fps(self):
            return 60

    class Fake:
        brain = Brain()
        voice_proc = None
        voice_preview = False
        voice_id = 7
        voice_queue = []
        _voice_ready = {}
        voice_streaming = False
        voice_pending = 1
        _voice_next = 1
        _voice_seq = 0
        ops = None
        windows = []
        active = None
        timer = (1, 16)
        form_picking = False

        def handle_requests(self):
            pass

        def talking(self):
            return False

        def _voice_pump(self):
            pass

        def hush(self):
            raise AssertionError('the voice must not be cut while it is being made')

        def _conversation_tick(self):
            pass

        def web_tick(self):
            pass

    class Painter:
        old = None

    f = Fake()
    f.painter = Painter()
    App.frame(f)
    assert f.brain.bubble['until'] == 160.0

    # once synthesis is over and nothing is playing, the clamp may shorten it
    f.voice_pending = 0
    App.frame(f)
    assert f.brain.bubble['until'] == 102.0
