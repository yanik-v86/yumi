#!/usr/bin/env python3
"""Появление, текст и рот идут вместе со звуком. Run: python3 tests/test_answer_sync.py

- имя будит, но не выводит её раньше ответа;
- пустой пузырь и 30-секундный «оговор» рта убраны из reply_stream_begin;
- первый чанк создаёт пузырь с текстом, но не шевелит ртом;
- reveal_answer перед play_file выводит её и ставит talk_until по длине WAV.
"""
import sys
from pathlib import Path

import gi
gi.require_version('GdkPixbuf', '2.0')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yumi import config  # noqa: E402
from yumi.brain import Brain  # noqa: E402
from yumi.phrases import Speech  # noqa: E402
from yumi.sprites import Meta  # noqa: E402
from yumi.ui import senses  # noqa: E402


def brain(settings=None):
    s = {'voice_vol': 50, 'voice_kind': 'tts', 'speech_lang': 'ru'}
    s.update(settings or {})
    return Brain(Meta(config.SPRITES, None), s, {'intro_done': True},
                 Speech(s), lambda *_a: (10, 10))


# эхо услышанной фразы больше не шевелит ртом и не вызывает её
b = brain()
assert b.say_text('погода', voice=False, appear=False)
assert b.bubble and b.bubble['text'] == 'погода', b.bubble
assert not b.out and b.talk_until == 0.0, 'quiet echo must not open her mouth'

# имя будит, но оставляет её у края до готового ответа
b = brain()
b.heard_text = lambda *a, **kw: None
b.wake_up('погода')
assert not b.sleeping, 'the name still wakes her'
assert not b.out, 'she must not come out before the answer is ready'
assert b.talk_until == 0.0

# начало стрима — только состояние: никакого пустого пузыря и аванса рту
b = brain()
b.reply_stream_begin()
assert b.chat_streaming and b.thinking
assert b.bubble is None and not b.out and b.talk_until == 0.0

# первый реальный чанк создаёт пузырь с текстом и ждёт звука
b.reply_stream_chunk('Привет, как дела?')
assert b.bubble and b.bubble['text'].startswith('Привет'), b.bubble
assert b._reveal_bid == b.bubble['id']
assert not b.out and b.talk_until == 0.0, 'no text-only mouth animation'
assert b.thinking, 'the wake loop must not take the mic back before the sound'
assert any(r[0] == 'voice_stream' for r in b.requests), b.requests

# первый кусок уходит в голос рано, но не обрезает слово
b = brain()
b.reply_stream_begin()
b.reply_stream_chunk('Сейчас погода в Мо')
first = [r for r in b.requests if r[0] == 'voice_stream']
assert first and first[0][1] == 'Сейчас погода', b.requests
assert b._stream_spoken.strip() == 'в Мо', b._stream_spoken

# перед play_file: она выходит, текст начинает печататься, рот идёт за WAV
start = b.bubble['start']
now = b.now
assert b.reveal_answer(b.bubble['id'], 1.5)
assert b.out and b._reveal_bid is None and not b.thinking
assert abs(b.talk_until - (now + 1.5)) < 1e-6, b.talk_until
assert b.bubble['start'] >= start, 'text must not run ahead of the sound'
assert not b.reveal_answer(b.bubble['id'], 2.0), 'reveal happens once'

# обычная реплика: текст сразу, рот — только когда WAV зазвучит
b = brain()
assert b.say_text('Привет')
assert b.out and b.talk_until == 0.0
assert any(r[0] == 'voice' for r in b.requests), b.requests

# нестриминговый ответ тоже ждёт WAV
b = brain()
b.chat_history.append({'role': 'user', 'content': 'вопрос'})
b.replied('Ответ')
assert not b.out and b._reveal_bid == b.bubble['id']
b.reveal_answer(b.bubble['id'], 1.0)
assert b.out

# голос выключен: ждать нечего, показываем сразу
b = brain({'voice_vol': 0})
b.reply_stream_begin()
b.reply_stream_chunk('Привет, как дела?')
assert b.out and b._reveal_bid is None and b.talk_until == 0.0

# стоп сбрасывает отложенное появление
b = brain()
b.reply_stream_begin()
b.reply_stream_chunk('Привет, как дела?')
b.stop_all()
assert b._reveal_bid is None and b.talk_until <= b.now


def test_voice_started_sets_mouth_to_wav_length():
    class B:
        now = 100.0
        bubble = {'id': 7, 'text': 'ответ', 'until': 200.0, 'start': 99.0}
        talk_until = 0.0

        def reveal_answer(self, bid, secs=0.0):
            return False

    f = object.__new__(senses.SensesMixin)
    f.brain = B()
    f._voice_started(7, 2.0)
    assert f.brain.talk_until == 102.0
    assert f.brain.bubble['until'] >= 103.2


print('test_answer_sync: ok')
