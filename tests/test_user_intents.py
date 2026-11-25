#!/usr/bin/env python3
"""Your own intents: storage, validation, scoring and the actions.json import.
Run: python3 tests/test_user_intents.py"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yumi import config, nlu, user_intents  # noqa: E402

assert (config.CONFIG_DIR / 'user_intents.json').name == 'user_intents.json'
assert user_intents.FORMAT_VERSION == 1

_tmp = tempfile.TemporaryDirectory()
_original = user_intents.INTENTS_FILE
user_intents.INTENTS_FILE = Path(_tmp.name) / 'user_intents.json'

COMMAND = {
    'id': 'lights_on', 'name': 'Свет', 'enabled': True,
    'phrases': ['включи свет', 'свет включи'], 'keywords': ['свет', 'лампа'],
    'action': {'type': 'command', 'value': 'lights on'},
    'speak': 'Включаю свет', 'priority': 10, 'requires_confirmation': True,
}
URL = {
    'id': 'web_search', 'name': 'Поиск', 'enabled': True,
    'phrases': [], 'keywords': ['найди'],
    'action': {'type': 'url', 'value': 'https://example.org/?q={query}'},
    'speak': 'Ищу {query}', 'priority': 0,
}
SAY = {
    'id': 'hello_back', 'name': 'Привет в ответ', 'enabled': True,
    'phrases': ['привет'], 'keywords': [],
    'action': {'type': 'say', 'value': ''}, 'speak': 'Привет-привет',
}
CAPTURE = dict(COMMAND, id='news', name='Новости', phrases=['новости'],
               keywords=[], action={'type': 'command', 'value': 'news'},
               speak='Новости: {stdout}', capture=True,
               requires_confirmation=False)


def payload(*items, revision=0):
    return {'version': 1, 'revision': revision, 'intents': list(items)}


try:
    # ---- a full save/load/export/import cycle, with an atomic write
    assert user_intents.load() == user_intents.empty()   # a missing file is not an error
    stored = user_intents.save(payload(COMMAND, URL, SAY))
    assert stored['revision'] == 1
    assert not user_intents.INTENTS_FILE.with_suffix('.tmp').exists()
    assert user_intents.load() == stored
    text = user_intents.export_json(stored)
    assert '\n  "intents": [' in text
    assert user_intents.import_json(text) == stored
    again = user_intents.save(user_intents.import_json(text))
    assert again['revision'] == 2 and again['intents'] == stored['intents']
    assert user_intents.info()['mtime'] > 0

    # ---- defaults and safety rules
    one = user_intents.validate(payload({
        'name': 'Teminal', 'phrases': ['открой терминал'],
        'action': {'type': 'command', 'value': 'foot'},
    }))['intents'][0]
    assert one['id'] == 'teminal' and one['enabled'] is True
    assert one['requires_confirmation'] is True
    assert one['capture'] is False
    captured = user_intents.validate(payload(CAPTURE))['intents'][0]
    assert captured['capture'] is True and captured['speak'] == 'Новости: {stdout}'
    url = user_intents.validate(payload({
        'phrases': ['найди'], 'action': {'type': 'url', 'value': 'https://example.org/'},
    }))['intents'][0]
    assert url['requires_confirmation'] is False
    say = user_intents.validate(payload({
        'phrases': ['Привет'], 'action': {'type': 'say', 'value': ''}, 'speak': 'Здравствуй',
    }))['intents'][0]
    assert say['speak'] == 'Здравствуй'
    from_value = user_intents.validate(payload({
        'phrases': ['Привет'], 'action': {'type': 'say', 'value': 'Само слово'},
    }))['intents'][0]
    assert from_value['speak'] == 'Само слово'

    bad = [
        payload(COMMAND, COMMAND),
        payload({'id': 'x!', 'phrases': ['фраза'], 'action': {'type': 'say', 'value': 'x'}}),
        payload({'id': 'x', 'phrases': [], 'keywords': [],
                 'action': {'type': 'say', 'value': 'x'}}),
        payload({'id': 'x', 'phrases': ['ф'], 'action': {'type': 'url',
                                                         'value': 'javascript:alert(1)'}}),
        payload({'id': 'x', 'phrases': ['ф'], 'action': {'type': 'shell',
                                                         'value': 'x'}}),
        payload({'id': 'x', 'phrases': ['ф'], 'action': {'type': 'say', 'value': 'x'},
                 'capture': True}),
        payload({'id': 'x', 'phrases': ['ф' * 201], 'action': {'type': 'command', 'value': 'x'}}),
        payload({'id': 'x', 'phrases': ['ф'], 'action': {'type': 'command', 'value': ''}}),
        payload({'id': 'x', 'phrases': ['ф'], 'action': {'type': 'command',
                                                         'value': 'x'}}, revision=-1),
        {'version': 2, 'revision': 0, 'intents': []},
        {'version': 1, 'revision': 0, 'intents': {}},
        [],
    ]
    for item in bad:
        try:
            user_intents.validate(item)
        except ValueError:
            pass
        else:
            raise AssertionError(f'accepted bad document: {item}')
    try:
        user_intents.import_json('{oops')
    except ValueError:
        pass
    else:
        raise AssertionError('broken JSON was accepted')
    assert user_intents.load() == again, 'a failed import must not touch the file'

    # ---- the nlu adapter: exact / keyword / fuzzy, enabled, priority as a tie-break
    ITEMS = [COMMAND]
    hit = user_intents.match('включи свет', ITEMS)
    assert hit and hit.confidence == nlu.SCORE_PHRASE and hit.intent == 'lights_on'
    hit = user_intents.match('ну свет пожалуйста', ITEMS)
    assert hit and hit.confidence == nlu.SCORE_KEYWORD, hit
    hit = user_intents.match('включи свит', ITEMS)
    assert hit and hit.confidence == nlu.SCORE_FUZZY, hit
    assert user_intents.match('включи окно', ITEMS) is None
    assert user_intents.match('не включай свет', ITEMS) is None
    assert user_intents.match('включи свет', [{**COMMAND, 'enabled': False}]) is None

    tied = [dict(COMMAND, id='first', priority=0), dict(COMMAND, id='second', priority=5)]
    assert user_intents.match('включи свет', tied).intent == 'second'
    tied[1]['priority'] = 0
    assert user_intents.match('включи свет', tied).intent == 'first'
    loud = [dict(COMMAND, id='phrase', priority=0),
            dict(COMMAND, id='keyword', phrases=[], keywords=['свет'], priority=100)]
    assert user_intents.match('включи свет', loud).intent == 'phrase'

    entries = user_intents.to_nlu_entries([SAY, URL, COMMAND, CAPTURE])
    assert entries[0]['user_intent'] is True and not entries[0].get('command')
    assert entries[1]['url'] == URL['action']['value']
    assert entries[2]['command'] == 'lights on' and entries[2]['capture'] is False
    assert entries[3]['command'] == 'news' and entries[3]['capture'] is True
    assert nlu.recognize('привет', user_intents.to_nlu_entries([SAY]),
                         use_intents=False).intent == 'hello_back'

    # ---- the panel's test button: a result, never an execution
    result = user_intents.test_phrase('включи свет', payload(COMMAND))
    assert result == {'matched': True, 'intent': user_intents.public(COMMAND),
                      'score': 1.0, 'source': 'user-intents'}
    assert user_intents.test_phrase('совсем другое', payload(COMMAND))['matched'] is False
    assert user_intents.test_phrase('включи свет', payload(COMMAND),
                                    min_confidence=0.9)['matched'] is True
    assert user_intents.test_phrase('свет', payload(COMMAND),
                                    min_confidence=0.9)['matched'] is False

    # ---- import from actions.json: explicit, no twins on a second import
    buttons = json.loads((Path(__file__).resolve().parent.parent
                          / 'actions.example.json').read_text(encoding='utf-8'))
    imported = user_intents.from_actions(buttons)
    assert imported and imported[0]['id'] == 'foot'
    assert imported[0]['phrases'] and imported[0]['action']['type'] == 'command'
    again = user_intents.from_actions(buttons, existing=imported)
    assert again == [], again
    imported_again = user_intents.from_actions(buttons)
    assert [i['id'] for i in imported_again] == [i['id'] for i in imported]
    assert user_intents.from_actions([{'command': 'x'}]) == []
finally:
    user_intents.INTENTS_FILE = _original
    _tmp.cleanup()

print('tests/test_user_intents.py: ok')
