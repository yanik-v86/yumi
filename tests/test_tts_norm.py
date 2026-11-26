#!/usr/bin/env python3
"""TTS text normalization: percent pronunciation and EN->RU translit."""
import os
import sys
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp()
os.environ['XDG_CACHE_HOME'] = tmp
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ['YUMI_TTS_PY'] = '/nonexistent'

from yumi import tts  # noqa: E402


# ---- percent ----

assert tts._convert_digits_for_tts('Загрузка 71%') == 'Загрузка семьдесят один процент'
assert tts._convert_digits_for_tts('Скидка 2%') == 'Скидка два процента'
assert tts._convert_digits_for_tts('Скидка 5%') == 'Скидка пять процентов'
assert tts._convert_digits_for_tts('Уже 21%') == 'Уже двадцать один процент'
assert tts._convert_digits_for_tts('100 % готово') == 'сто процентов готово'
assert tts._convert_digits_for_tts('Loading 50%') == 'Loading fifty percent'
# percent should not break normal numbers around it
assert 'процент' in tts._convert_digits_for_tts('Батарея 100% заряжена')

# ---- translit ----

assert tts.translit_en_to_ru('Ollama') == 'Оллама'
assert tts.translit_en_to_ru('Good morning') == 'Гуд морнинг'
assert tts.translit_en_to_ru('Привет, Ollama!') == 'Привет, Оллама!'
# mixed text keeps Cyrillic and punctuation
mixed = tts.translit_en_to_ru('Привет, OpenCode! Как дела?')
assert mixed.startswith('Привет, ')
assert '!' in mixed and 'Как дела?' in mixed
# acronyms spell out
assert tts.translit_en_to_ru('API') == 'эй пи ай'
assert tts.translit_en_to_ru('USB') == 'ю эс би'
# no latin letters after translit of plain latin words
for src in ['Ollama', 'Good morning', 'Hello world']:
    out = tts.translit_en_to_ru(src)
    assert not any('A' <= c <= 'Z' or 'a' <= c <= 'z' for c in out), (src, out)
# empty / no latin
assert tts.translit_en_to_ru('') == ''
assert tts.translit_en_to_ru('Привет мир') == 'Привет мир'

# ---- speak signature accepts en_ru ----

import inspect
sig = inspect.signature(tts.speak)
assert 'en_ru' in sig.parameters
assert sig.parameters['en_ru'].default is False

print('ok')
