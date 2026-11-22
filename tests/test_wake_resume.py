#!/usr/bin/env python3
"""A panel microphone test must not leave her deaf to her name.

Regression: wake_pause() joins the wake thread with a short timeout.  When the
thread was still inside a /wake call, its handle stayed in ``wake_thread`` and
wake_resume() decided the microphone already had an owner — the flag said
"watching", but no loop was listening any more.
"""
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yumi.ui import senses  # noqa: E402
from yumi.voice_state import VoiceState  # noqa: E402


class FakeApp(senses.SensesMixin):
    def __init__(self):
        self.settings = {'speech_lang': 'ru', 'stt_mic': None, 'stt_size': 'small',
                         'stt_beam': 5, 'stt_engine': 'whisper',
                         'wake_word': 'юми', 'wake_sensitivity': 'normal',
                         'wake_confirm': True, 'wake_model_size': 'small',
                         'wake_judge_log': False, 'wake_ear': 'oww',
                         'conversation_mode': False}
        self.brain = SimpleNamespace(conversation=None, listening=False, thinking=False,
                                     now=time.monotonic(), talk_until=0)
        self.wake_on = False
        self.wake_thread = None
        self.wake_gen = 0
        self.wake_waiting = False
        self.voice_state = VoiceState()

    def _vs(self, method, *args):
        getattr(self.voice_state, method)(*args)

    def ev(self, fn):
        return fn(self.brain)

    def wake_hints(self, b):
        return []


def test_resume_starts_a_fresh_loop_after_a_slow_pause(monkeypatch):
    started = threading.Event()
    calls = []
    lock = threading.Lock()
    gate = threading.Event()

    def fake_wake(*_a, **_kw):
        with lock:
            calls.append(threading.current_thread())
        started.set()
        gate.wait(3)
        return {'woke': False}

    monkeypatch.setattr(senses.ears, 'wake', fake_wake)
    monkeypatch.setattr(senses.ears, 'stop', lambda: None)
    app = FakeApp()

    app.wake_set(True)
    assert started.wait(2), 'the wake loop never started'
    first = calls[0]

    was_on = app.wake_pause(timeout=0.05)
    assert was_on and first.is_alive(), 'the test needs a thread that missed the join'
    assert app.wake_thread is None, 'a stale thread must not be kept as the owner'

    app.wake_resume(was_on)
    # The second /wake proves a new loop took the microphone back.
    deadline = time.monotonic() + 2
    while len(calls) < 2 and time.monotonic() < deadline:
        started.clear()
        time.sleep(0.02)
    assert len(calls) >= 2, 'resume did not start a new wake loop'
    assert calls[1] is not first, 'the stale thread was reused'

    app.wake_set(False)
    gate.set()
    first.join(2)
    assert not first.is_alive(), 'the stale loop must retire after the generation bump'


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__]))
