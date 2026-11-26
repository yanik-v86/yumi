#!/usr/bin/env python3
"""Her own voice commands end to end: entities, confidence, confirmation.
Run: python3 tests/test_voice_intent.py"""
import json
import shutil
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
from yumi import intent_log, user_intents  # noqa: E402

_intent_seq = 0


def intents_brain(items, **settings):
    """a Brain whose custom layer lives in a temporary user-intents folder"""
    global _intent_seq
    _intent_seq += 1
    b = brain([], **settings)
    b.user_intents_path = (Path(tempfile.gettempdir())
                           / f'yumi-user-intents-{os.getpid()}-{_intent_seq}')
    shutil.rmtree(b.user_intents_path, ignore_errors=True)
    b.user_intents_data = user_intents.save(
        {'version': 1, 'revision': 0, 'intents': items}, b.user_intents_path)
    b.user_intents_mtime = user_intents.mtime(b.user_intents_path)
    return b


def run_req(requests, command):
    """the launch request, from a button ('run') or a custom rule ('run_in')"""
    return next((r for r in requests if r[0] in ('run', 'run_in')
                 and r[1] == command), None)


RULE = {'id': 'lamp', 'name': 'Лампа', 'enabled': True,
        'phrases': ['включи лампу'], 'keywords': ['лампа'],
        'action': {'type': 'command', 'value': 'lamp on'}, 'speak': 'Включаю лампу'}
b = intents_brain([RULE])
b.requests.clear()
assert b.voice_user_intent('включи лампу') is True
assert b.intent_confirm and b.last_intent == 'lamp', 'a command asks first by default'
assert run_req(b.requests, 'lamp on') is None
b.heard_text('да')
req = run_req(b.requests, 'lamp on')
assert req and req[0] == 'run_in' and Path(req[2]).name == 'lamp'
assert b.bubble['text'] == 'Включаю лампу'

# the same phrase through heard_text() reaches the new layer (after the music guess)
QUIET = dict(RULE, phrases=['сделай свет'], keywords=[], requires_confirmation=False)
b = intents_brain([QUIET])
b.requests.clear()
assert b.heard_text('сделай свет') is None
assert run_req(b.requests, 'lamp on') and b.last_intent == 'lamp'

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
assert b.bubble['text'] == 'Привет' and not any(r[0] in ('run', 'run_in', 'url')
                                                 for r in b.requests), b.requests
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
req = next(r for r in b.requests if r[0] == 'run_capture')
assert req[:4] == ('run_capture', 'news', 'news', 'Новости: {stdout}'), b.requests
assert req[6] == str(user_intents.intent_dir('news', b.user_intents_path)), req
assert req[4]['voice'] is True and req[4]['bubble'] is True
assert req[4]['bubble_limit'] == 1000
assert req[4]['voice_text'] == '' and req[4]['bubble_text'] == ''
assert len(req[4]['run_id']) == 8 and req[4]['source'] == 'voice'
assert 'started_at' in req[4]
assert req[5] == {'YUMI_INTENT_TEXT': 'новости'}, 'the heard words still reach the command'
assert not any(r[0] in ('run', 'run_in', 'voice') for r in b.requests), 'no early bubble or command'
assert b.user_intent_answer('Мир: новость', 'news', 'Новости: {stdout}',
                            options=req[4]) is True
assert b.bubble['text'] == 'Новости: Мир: новость', b.bubble
assert any(r[0] == 'voice' and r[5] == 'Новости: Мир: новость' for r in b.requests)

# the same captured answer still waits for «да» when confirmation is on
b = intents_brain([dict(CAPTURE, requires_confirmation=True)])
b.requests.clear()
assert b.voice_user_intent('новости') is True
assert not any(r[0] == 'run_capture' for r in b.requests)
b.heard_text('да')
req = next(r for r in b.requests if r[0] == 'run_capture')
assert req[:4] == ('run_capture', 'news', 'news', 'Новости: {stdout}'), b.requests
assert b.user_intent_answer('Мир: новость', 'news', 'Новости: {stdout}',
                            failed=True, options=req[4]) is True

# voice and bubble are independent: a long answer can be voiced without a bubble
b = intents_brain([dict(CAPTURE, voice_answer=False, bubble_answer=True, speak='{stdout}')])
b.requests.clear()
assert b.voice_user_intent('новости') is True
req = next(r for r in b.requests if r[0] == 'run_capture')
assert req[4]['voice'] is False and req[4]['bubble'] is True
assert b.user_intent_answer('Только текст', 'news', '{stdout}', options=req[4]) is True
assert b.bubble['text'] == 'Только текст' and not b.bubble.get('hidden'), b.bubble
assert not any(r[0] == 'voice' for r in b.requests), b.requests

b = intents_brain([dict(CAPTURE, voice_answer=True, bubble_answer=False)])
b.requests.clear()
assert b.voice_user_intent('новости') is True
req = next(r for r in b.requests if r[0] == 'run_capture')
assert req[4]['voice'] is True and req[4]['bubble'] is False
assert b.user_intent_answer('Только голос', 'news', 'Новости: {stdout}',
                            options=req[4]) is True
assert b.bubble.get('hidden') is True and b.bubble['text'] == '', b.bubble
assert any(r[0] == 'voice' and r[5] == 'Новости: Только голос' for r in b.requests)

# separate lines and a short bubble limit: the voice still gets the whole answer
LONG = 'СЛОВО ' * 40
b = intents_brain([dict(CAPTURE, speak='Новости: {stdout}',
                        voice_text='Коротко: {stdout}', bubble_text='Подробно: {stdout}',
                        bubble_limit=120)])
b.requests.clear()
assert b.voice_user_intent('новости') is True
req = next(r for r in b.requests if r[0] == 'run_capture')
assert req[4]['bubble_limit'] == 120
assert req[4]['voice_text'] == 'Коротко: {stdout}'
assert req[4]['bubble_text'] == 'Подробно: {stdout}'
assert b.user_intent_answer(LONG, 'news', 'Новости: {stdout}', options=req[4]) is True
assert b.bubble['text'].startswith('Подробно: '), b.bubble
assert len(b.bubble['text']) <= 120, len(b.bubble['text'])
voice = next(r for r in b.requests if r[0] == 'voice')
assert voice[5].startswith('Коротко: '), voice
assert len(voice[5]) > len(b.bubble['text']) + 40, (voice[5], b.bubble['text'])

# a separate line without {stdout} is literal: short voice, full bubble
b = intents_brain([dict(CAPTURE, voice_text='Свежие новости в бабле')])
b.requests.clear()
assert b.voice_user_intent('новости') is True
req = next(r for r in b.requests if r[0] == 'run_capture')
assert b.user_intent_answer(LONG, 'news', 'Новости: {stdout}', options=req[4]) is True
voice = next(r for r in b.requests if r[0] == 'voice')
assert voice[5] == 'Свежие новости в бабле', voice
assert 'СЛОВО' in b.bubble['text'], b.bubble

# the default limit also clips answers that use one shared line
b = intents_brain([CAPTURE])
b.requests.clear()
assert b.voice_user_intent('новости') is True
req = next(r for r in b.requests if r[0] == 'run_capture')
huge = 'слово ' * 900
assert b.user_intent_answer(huge, 'news', 'Новости: {stdout}', options=req[4]) is True
assert len(b.bubble['text']) <= 1000, len(b.bubble['text'])
assert len(next(r for r in b.requests if r[0] == 'voice')[5]) < 4100

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
item_file = user_intents.intent_dir('fan', b.user_intents_path) / user_intents.INTENT_FILE
future = b.user_intents_mtime + 10
os.utime(item_file, (future, future))
assert b.voice_user_intent('включи вентилятор') is True
req = run_req(b.requests, 'fan on')
assert req and req[0] == 'run_in' and Path(req[2]).name == 'fan'
assert b.user_intents_data['revision'] == stored['revision']

# a button from actions.json wins a phrase claimed by both layers
b = brain([action(command='button', phrases=['включи лампу'])], user_intents=True)
b.user_intents_path = (Path(tempfile.gettempdir())
                       / f'yumi-user-intents-both-{os.getpid()}')
shutil.rmtree(b.user_intents_path, ignore_errors=True)
b.user_intents_data = user_intents.save(
    {'version': 1, 'revision': 0, 'intents': [dict(RULE, requires_confirmation=False)]},
    b.user_intents_path)
b.user_intents_mtime = user_intents.mtime(b.user_intents_path)
b.requests.clear()
assert b.voice_intent('включи лампу') is True and ('run', 'button') in b.requests
assert b.last_intent != 'lamp'

# ---- the action journal: one run_id ties the heard phrase to the decision,
# the command start and its answer; the command itself is never serialized
with tempfile.TemporaryDirectory() as tmp:
    old_state = config.STATE_DIR
    config.STATE_DIR = Path(tmp)
    try:
        journal_rule = dict(CAPTURE, id='journal', name='Журнал',
                            phrases=['журнал проверки'], keywords=[],
                            action={'type': 'command', 'value': 'super_secret_command'},
                            requires_confirmation=True)
        jb = intents_brain([journal_rule], intents_log_level='trace',
                           intents_log_include_text=True)
        jb.requests.clear()
        assert jb.voice_user_intent('журнал проверки') is True
        run = jb.last_user_intent_run_id
        assert len(run) == 8
        assert jb.answer_permission('once', 'panel')['decided'] is True
        req = next(r for r in jb.requests if r[0] == 'run_capture')
        assert req[4]['run_id'] == run and req[4]['source'] == 'voice'
        assert jb.user_intent_answer('готово', 'journal', '', options=req[4]) is True
        records = [r for r in intent_log.read() if r['run_id'] == run]
        stages = {r['stage'] for r in records}
        assert {'heard', 'match', 'decision', 'start', 'result'} <= stages, stages
        assert any(r['heard_text'] == 'журнал проверки' for r in records)
        dump = json.dumps(records, ensure_ascii=False)
        assert 'super_secret_command' not in dump and 'run_capture' not in dump
        assert all(r['action_sha'] is None or r['action_sha'].startswith('sha256:')
                   for r in records)
    finally:
        config.STATE_DIR = old_state

print('tests/test_voice_intent.py: ok')
