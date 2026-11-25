#!/usr/bin/env python3
"""Her own voice commands end to end: entities, confidence, confirmation.
Run: python3 tests/test_voice_intent.py"""
import sys
import tempfile
from pathlib import Path

import gi
gi.require_version('GdkPixbuf', '2.0')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yumi import config  # noqa: E402
from yumi.brain import Brain  # noqa: E402
from yumi.phrases import Speech  # noqa: E402
from yumi.sprites import Meta  # noqa: E402


def action(**kw):
    """one button as actions.json keeps it"""
    out = {'label': 'Button', 'label_ru': 'Кнопка', 'icon': 'star',
           'command': 'noop', 'phrases': [], 'keywords': [],
           'speak': '', 'url': '', 'id': '', 'priority': 0,
           'requires_confirmation': False, 'entities': {}}
    out.update(kw)
    return out


def brain(actions, **settings):
    s = dict(config.DEFAULT_SETTINGS)
    s['ui_lang'] = 'ru'          # the confirmation prompts are then the Russian ones
    s.update(settings)
    b = Brain(Meta(config.SPRITES, None), s,
              {'intro_done': True}, Speech(s), lambda *_a: (10, 10))
    # never read the real actions.json while this test runs
    b.actions_path = Path(tempfile.gettempdir()) / 'yumi-no-actions-test.json'
    b.actions_mtime = 0.0
    b.custom = actions
    return b


# ---- a plain phrase runs its command, and she says the «speak» line
b = brain([action(command='foot', phrases=['открой терминал'])])
b.requests.clear()
assert b.voice_intent('открой терминал') is True
assert ('run', 'foot') in b.requests, b.requests
assert b.last_intent == 'custom:foot' and b.last_confidence == 1.0
assert b.voice_intent('совсем другая фраза') is False

# ---- entities are shared: the button declares «volume» and {volume} gets 50
b = brain([action(command='vol', phrases=['громкость половина'],
                  speak='Ставлю {volume}', entities={'volume': True})])
b.requests.clear()
assert b.voice_intent('громкость половина') is True
assert ('run', 'vol') in b.requests
assert b.bubble['text'] == 'Ставлю 50', b.bubble

# ---- a url fills {query}, and commands are never built from heard words
b = brain([action(command='', keywords=['найди'],
                  url='https://example.org/?q={query}')])
b.requests.clear()
assert b.voice_intent('найди котики') is True
assert ('url', 'https://example.org/?q=%D0%BA%D0%BE%D1%82%D0%B8%D0%BA%D0%B8') in b.requests, b.requests

# ---- the confidence line: a keyword (0.80) can be left to the chat
ACTIONS = [action(command='foot', phrases=['открой терминал'], keywords=['терминал'])]
b = brain(ACTIONS, nlu_confidence=1.0)
b.requests.clear()
assert b.voice_intent('терминал') is False and not b.requests
assert b.voice_intent('открой терминал') is True
assert ('run', 'foot') in b.requests
# switching voice commands off keeps them off at any threshold
b = brain(ACTIONS, nlu=False)
assert b.voice_intent('открой терминал') is False

# ---- requires_confirmation: she asks first and waits for the next word
DANGER = action(command='rm -rf', id='wipe', phrases=['удали всё'],
                requires_confirmation=True, speak='Удаляю')
b = brain([DANGER])
b.requests.clear()
assert b.voice_intent('удали всё') is True
assert b.intent_confirm and b.intent_confirm['action'] is DANGER
assert ('run', 'rm -rf') not in b.requests, 'must not run before the answer'
assert b.bubble['text'] == config.UI['ru']['confirm_ask'], b.bubble
assert ('listen', 15) in b.requests

# the spoken «да» runs exactly the pending command, with its slots
b.heard_text('да')
assert b.intent_confirm is None
assert ('run', 'rm -rf') in b.requests, b.requests
assert b.bubble['text'] == 'Удаляю'

# «нет» cancels, and nothing runs
b = brain([DANGER])
b.requests.clear()
b.voice_intent('удали всё')
b.heard_text('нет')
assert b.intent_confirm is None
assert ('run', 'rm -rf') not in b.requests
assert b.bubble['text'] == config.UI['ru']['confirm_no']

# the browser answers the very same pending command
b = brain([DANGER])
b.requests.clear()
b.voice_intent('удали всё')
assert b._voice_confirm_web(True) is True
assert ('run', 'rm -rf') in b.requests
assert b._voice_confirm_web(True) is False, 'nothing is pending twice'
b = brain([DANGER])
b.requests.clear()
b.voice_intent('удали всё')
b._voice_confirm_web(False)
assert ('run', 'rm -rf') not in b.requests

# «стоп» drops a waiting command too
b = brain([DANGER])
b.voice_intent('удали всё')
b.stop_all()
assert b.intent_confirm is None

# ---- your own intents: the new layer after buttons, with hot reload
import os  # noqa: E402
from yumi import user_intents  # noqa: E402

_intent_seq = 0


def intents_brain(items, **settings):
    """a Brain whose custom layer lives in a temporary user_intents.json"""
    global _intent_seq
    _intent_seq += 1
    b = brain([], **settings)
    b.user_intents_path = (Path(tempfile.gettempdir())
                           / f'yumi-user-intents-{os.getpid()}-{_intent_seq}.json')
    if b.user_intents_path.exists():
        b.user_intents_path.unlink()
    b.user_intents_data = user_intents.save(
        {'version': 1, 'revision': 0, 'intents': items}, b.user_intents_path)
    b.user_intents_mtime = b.user_intents_path.stat().st_mtime
    return b


RULE = {'id': 'lamp', 'name': 'Лампа', 'enabled': True,
        'phrases': ['включи лампу'], 'keywords': ['лампа'],
        'action': {'type': 'command', 'value': 'lamp on'}, 'speak': 'Включаю лампу'}
b = intents_brain([RULE])
b.requests.clear()
assert b.voice_user_intent('включи лампу') is True
assert b.intent_confirm and b.last_intent == 'lamp', 'a command asks first by default'
assert ('run', 'lamp on') not in b.requests
b.heard_text('да')
assert ('run', 'lamp on') in b.requests and b.bubble['text'] == 'Включаю лампу'

# the same phrase through heard_text() reaches the new layer (after the music guess)
QUIET = dict(RULE, phrases=['сделай свет'], keywords=[], requires_confirmation=False)
b = intents_brain([QUIET])
b.requests.clear()
assert b.heard_text('сделай свет') is None
assert ('run', 'lamp on') in b.requests and b.last_intent == 'lamp'

# a keyword and the ears' slip work too, with the same confidence line
b = intents_brain([dict(RULE, requires_confirmation=False)], nlu_confidence=1.0)
b.requests.clear()
assert b.voice_user_intent('лампа') is False       # 0.80 is under the line
assert b.voice_user_intent('включи лампу') is True

# "say" speaks a line; a url opens; nothing goes to a shell
b = intents_brain([{'id': 'wave', 'name': ' Wave ', 'enabled': True,
                    'phrases': ['помочи'], 'keywords': [],
                    'action': {'type': 'say', 'value': ''}, 'speak': 'Привет'}])
b.requests.clear()
assert b.voice_user_intent('помочи') is True
assert b.bubble['text'] == 'Привет' and not any(r[0] in ('run', 'url') for r in b.requests), b.requests
b = intents_brain([{'id': 'find', 'name': 'Поиск', 'enabled': True,
                    'phrases': [], 'keywords': ['найди'],
                    'action': {'type': 'url', 'value': 'https://example.org/?q={query}'},
                    'speak': ''}])
b.requests.clear()
assert b.voice_user_intent('найди мотыльков') is True
assert ('url', 'https://example.org/?q=%D0%BC%D0%BE%D1%82%D1%8B%D0%BB%D1%8C%D0%BA%D0%BE%D0%B2') in b.requests

# a captured command answers in the bubble and through her normal voice path
CAPTURE = dict(RULE, id='news', name='Новости', phrases=['новости'], keywords=[],
               action={'type': 'command', 'value': 'news'},
               speak='Новости: {stdout}', capture=True, requires_confirmation=False)
b = intents_brain([CAPTURE])
b.requests.clear()
assert b.voice_user_intent('новости') is True
assert ('run_capture', 'news', 'news', 'Новости: {stdout}') in b.requests, b.requests
assert not any(r[0] in ('run', 'voice') for r in b.requests), 'no early bubble or command'
assert b.user_intent_answer('Мир: новость', 'news', 'Новости: {stdout}') is True
assert b.bubble['text'] == 'Новости: Мир: новость', b.bubble
assert any(r[0] == 'voice' and r[5] == 'Новости: Мир: новость' for r in b.requests)

# the same captured answer still waits for «да» when confirmation is on
b = intents_brain([dict(CAPTURE, requires_confirmation=True)])
b.requests.clear()
assert b.voice_user_intent('новости') is True
assert not any(r[0] == 'run_capture' for r in b.requests)
b.heard_text('да')
assert ('run_capture', 'news', 'news', 'Новости: {stdout}') in b.requests, b.requests
assert b.user_intent_answer('Мир: новость', 'news', 'Новости: {stdout}', failed=True) is True

# the setting turns the whole layer off
b = intents_brain([dict(RULE, requires_confirmation=False)], user_intents=False)
b.requests.clear()
assert b.voice_user_intent('включи лампу') is False and not b.requests

# an edit of the JSON by hand is picked up on the next phrase, no restart
b = intents_brain([dict(RULE, requires_confirmation=False)])
b.requests.clear()
fresh = {'id': 'fan', 'name': 'Вентилятор', 'enabled': True,
         'phrases': ['включи вентилятор'], 'keywords': [],
         'action': {'type': 'command', 'value': 'fan on'}, 'requires_confirmation': False}
stored = user_intents.save({'version': 1, 'revision': b.user_intents_data['revision'],
                            'intents': [fresh]}, b.user_intents_path)
os.utime(b.user_intents_path, (b.user_intents_mtime + 2, b.user_intents_mtime + 2))
assert b.voice_user_intent('включи вентилятор') is True
assert ('run', 'fan on') in b.requests and b.user_intents_data['revision'] == stored['revision']

# a button from actions.json wins a phrase claimed by both layers
b = brain([action(command='button', phrases=['включи лампу'])], user_intents=True)
b.user_intents_path = (Path(tempfile.gettempdir())
                       / f'yumi-user-intents-both-{os.getpid()}.json')
if b.user_intents_path.exists():
    b.user_intents_path.unlink()
b.user_intents_data = user_intents.save(
    {'version': 1, 'revision': 0, 'intents': [dict(RULE, requires_confirmation=False)]},
    b.user_intents_path)
b.user_intents_mtime = b.user_intents_path.stat().st_mtime
b.requests.clear()
assert b.voice_intent('включи лампу') is True and ('run', 'button') in b.requests
assert b.last_intent != 'lamp'

print('tests/test_voice_intent.py: ok')
