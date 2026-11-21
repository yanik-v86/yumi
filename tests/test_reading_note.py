#!/usr/bin/env python3
"""Two ears, two readings: the mind sees both so a garbled word is not lost.
Run: python3 tests/test_reading_note.py"""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))
from yumi import brain  # noqa: E402

note = brain.reading_note

# the evening of 21 November: Nemotron heard «бапушки», the stop ear «пушкин»
ru = note('кто такой бапушки', 'кто такой пушкин', 'ru')
assert 'бапушки' in ru and 'пушкин' in ru
assert 'осмысленный' in ru.lower()

en = note('who is bapushkin', 'who is pushkin', 'en')
assert 'bapushkin' in en and 'pushkin' in en

# one ear alone, or both agreed: no extra words in the mind's prompt
assert note('кто такой пушкин', '', 'ru') == ''
assert note('кто такой пушкин', 'кто такой пушкин', 'ru') == ''
assert note('кто такой пушкин', None, 'ru') == ''

# a runaway reading cannot grow the prompt without bound
assert len(note('a' * 5000, 'b' * 5000, 'en')) < 700
