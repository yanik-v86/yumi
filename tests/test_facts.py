#!/usr/bin/env python3
"""The vetted fact book and her chatter lines. Run: python3 tests/test_facts.py"""
import json
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yumi import config, facts, phrases  # noqa: E402
from yumi.webpanel import catalog  # noqa: E402

# ---- the built-in book is checked, not generated
assert len(facts.BUILTIN) >= 20
assert len({f.id for f in facts.BUILTIN}) == len(facts.BUILTIN)
for fact in facts.BUILTIN:
    assert fact.ru and fact.en and fact.source and fact.url, fact
    assert len(fact.ru) <= facts.MAX_TEXT and len(fact.en) <= facts.MAX_TEXT, fact
    assert fact.url.startswith('https://'), fact

book = facts.FactBook()
info = book.info()
assert info['ok'] and info['error'] == ''
assert info['builtin'] == len(facts.BUILTIN) and info['custom'] == 0
assert len(book.items('ru')) == len(facts.BUILTIN)
assert book.items('ru')[0]['text'] == facts.BUILTIN[0].ru
assert book.items('en')[0]['text'] == facts.BUILTIN[0].en

# a few facts in a row never repeat until the short memory wraps
seen = [book.pick('ru', random.Random(7)).id for _ in range(facts.KEEP_RECENT + 1)]
assert len(set(seen[:facts.KEEP_RECENT])) == facts.KEEP_RECENT, seen
assert seen[-1] not in seen[:-1], seen
assert book.last.id == seen[-1]
assert book.find(seen[0]).id == seen[0]

# ---- an optional book of your own, and graceful fallback when it is broken
tmp = Path(tempfile.mkdtemp(prefix='yumi-facts-'))
custom = tmp / 'my-facts.json'
custom.write_text(json.dumps({'facts': [
    {'id': 'mine-1', 'ru': 'Мой проверенный факт.', 'en': 'My checked fact.',
     'source': 'My notes', 'url': 'https://example.org/fact'},
    {'id': 'mine-2', 'ru': 'Второй факт.', 'en': 'Another fact.'},
]}), encoding='utf-8')
mine = facts.FactBook(str(custom))
assert mine.info()['custom'] == 2 and mine.info()['ok']
assert 'Мой проверенный факт.' in [f['text'] for f in mine.items('ru')]
assert mine.find('mine-2').source == 'Your fact book'
assert mine.find('missing') is None

custom.write_text('{not json', encoding='utf-8')
assert not mine.info()['ok'] and mine.info()['custom'] == 0
assert mine.info()['error'], mine.info()
assert len(mine.items('ru')) == len(facts.BUILTIN)   # the built-in book still works

custom.write_text(json.dumps({'facts': [
    {'id': 'mine-3', 'ru': 'Третий факт.', 'en': 'Third fact.'},
]}), encoding='utf-8')
assert mine.info()['ok'] and mine.info()['custom'] == 1  # mtime/size change is noticed
assert any(f['id'] == 'mine-3' for f in mine.items('en'))

for bad in ('{"facts": [{"ru": "only russian"}]}', '{"facts": "not a list"}',
            '{"facts": [{"ru": "x", "en": "y", "url": "javascript:alert(1)"}]}'):
    bad_file = tmp / 'bad.json'
    bad_file.write_text(bad, encoding='utf-8')
    broken = facts.FactBook(str(bad_file))
    assert not broken.info()['ok'] and broken.info()['custom'] == 0, bad

# ---- chatter picks facts, respects its switch and the ten-minute gap
facts.clear_cache()
settings = dict(config.DEFAULT_SETTINGS)
settings.update({'speech_lang': 'ru', 'chatter': True, 'chatter_facts': 'mixed'})
speech = phrases.Speech(settings, clock=lambda: 1000.0, rng=random.Random(3))
speech.last_chatter = -1e9
line = speech.say('fact')
assert line is not None and speech.last_fact['text'] == line[0], line
assert speech.last_fact['source'] and speech.last_fact['url']

speech = phrases.Speech(settings, clock=lambda: 1000.0, rng=random.Random(3))
speech.last_chatter = -1e9
assert speech.say('fact', fact_id='moth-hearing')[0] == facts.BUILTIN[2].ru

settings['chatter'] = False
speech = phrases.Speech(settings, clock=lambda: 1000.0)
speech.last_chatter = -1e9
assert speech.say('fact') is None
assert speech.say('fact', force=True) is not None   # the panel's explicit action

settings['chatter'] = True
speech = phrases.Speech(settings, clock=lambda: 1000.0)
speech.last_chatter = 999.0                        # spoke a moment ago
assert speech.say('fact') is None
assert speech.say('fact', force=True) is not None

# the panel form knows both new keys
keys = {entry['key'] for entry in catalog.schema()['settings']}
assert {'chatter_facts', 'chatter_facts_file'} <= keys
facts.clear_cache()
print('ok')
