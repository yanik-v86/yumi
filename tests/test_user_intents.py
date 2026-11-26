#!/usr/bin/env python3
"""Your own intents: storage, validation, scoring and the actions.json import.
Run: python3 tests/test_user_intents.py"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yumi import config, nlu, user_intents  # noqa: E402

assert config.INTENTS_DIR.name == 'user-intents'
assert config.INTENTS_FILE.name == 'user_intents.json'   # the old document, migrated once
assert user_intents.FORMAT_VERSION == 1

_tmp = tempfile.TemporaryDirectory()
_original_dir = user_intents.INTENTS_DIR
_original_file = user_intents.INTENTS_FILE
user_intents.INTENTS_DIR = Path(_tmp.name) / 'user-intents'
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
    root = user_intents.INTENTS_DIR
    assert (root / 'lights_on' / 'intent.json').is_file()
    assert (root / 'web_search' / 'intent.json').is_file()
    index = json.loads((root / user_intents.INDEX_FILE).read_text(encoding='utf-8'))
    assert index == {'version': 1, 'revision': 1,
                     'order': ['lights_on', 'web_search', 'hello_back']}, index
    assert not list(root.glob('*.tmp')) and not list(root.glob('*/*.tmp'))
    assert not user_intents.INTENTS_FILE.exists()   # no more single document
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
    assert captured['voice_answer'] is True and captured['bubble_answer'] is True
    assert captured['bubble_limit'] == 1000 == user_intents.DEFAULT_BUBBLE_LIMIT
    assert captured['voice_text'] == '' and captured['bubble_text'] == ''
    tuned = user_intents.validate(payload(dict(
        CAPTURE, bubble_limit=50, voice_text='Голос: {stdout}',
        bubble_text='Бабла: {stdout}')))['intents'][0]
    assert tuned['bubble_limit'] == 100          # clamped to the allowed range
    assert tuned['voice_text'] == 'Голос: {stdout}'
    assert tuned['bubble_text'] == 'Бабла: {stdout}'
    assert user_intents.validate(payload(dict(
        CAPTURE, bubble_limit=9999)))['intents'][0]['bubble_limit'] == 4000
    assert user_intents.validate(payload(dict(
        CAPTURE, bubble_limit='nope')))['intents'][0]['bubble_limit'] == 1000
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
        payload(dict(COMMAND, voice_text='Голос: {stdout}')),
        payload(dict(COMMAND, bubble_text='Бабла: {stdout}')),
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

    # ---- one folder per rule: hand edits, extra files and orphan folders
    folder = user_intents.intent_dir('lights_on')
    raw = json.loads((folder / 'intent.json').read_text(encoding='utf-8'))
    raw['phrases'] = ['включи лампочку']
    (folder / 'intent.json').write_text(json.dumps(raw, ensure_ascii=False, indent=2),
                                        encoding='utf-8')
    (folder / 'lights.py').write_text('# my helper\n', encoding='utf-8')
    assert user_intents.info()['mtime'] > 0
    hand = user_intents.load()
    assert hand['intents'][0]['phrases'] == ['включи лампочку'], hand
    assert user_intents.intent_dir('lights_on', root) == folder
    try:
        user_intents.intent_dir('../escape')
    except ValueError:
        pass
    else:
        raise AssertionError('a bad id escaped into a filesystem path')
    manual = root / 'manual'
    manual.mkdir()
    (manual / 'intent.json').write_text(json.dumps({
        'id': 'manual', 'phrases': ['ручное правило'],
        'action': {'type': 'say', 'value': 'готово'},
    }, ensure_ascii=False), encoding='utf-8')
    assert [i['id'] for i in user_intents.load()['intents']][-1] == 'manual'
    # deleting a rule removes intent.json but keeps the user's own files
    kept = user_intents.save({'version': 1, 'revision': hand['revision'],
                              'intents': [dict(COMMAND, id='manual',
                                               phrases=['ручное правило'])]})
    assert [i['id'] for i in kept['intents']] == ['manual']
    assert (manual / 'intent.json').is_file() and (folder / 'lights.py').is_file()
    assert not (folder / 'intent.json').exists(), 'a removed rule must lose its intent.json'

    # ---- the old single document migrates once, with a backup
    with tempfile.TemporaryDirectory() as mig:
        mig = Path(mig)
        legacy = mig / 'user_intents.json'
        legacy.write_text(json.dumps(payload(COMMAND), ensure_ascii=False), encoding='utf-8')
        old_dir, old_file = user_intents.INTENTS_DIR, user_intents.INTENTS_FILE
        user_intents.INTENTS_DIR, user_intents.INTENTS_FILE = mig / 'user-intents', legacy
        try:
            # the live app passes the folder explicitly: migration still runs
            data = user_intents.load(user_intents.INTENTS_DIR)
            assert data['revision'] == 0 and [i['id'] for i in data['intents']] == ['lights_on']
            assert (user_intents.INTENTS_DIR / 'lights_on' / 'intent.json').is_file()
            assert legacy.with_name('user_intents.json.migrated').is_file()
            assert not legacy.exists()
            assert user_intents.load() == data, 'migration must run only once'
        finally:
            user_intents.INTENTS_DIR, user_intents.INTENTS_FILE = old_dir, old_file

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
    assert entries[3]['voice_answer'] is True and entries[3]['bubble_answer'] is True
    assert entries[3]['bubble_limit'] == 1000
    assert entries[3]['voice_text'] == '' and entries[3]['bubble_text'] == ''
    assert nlu.recognize('привет', user_intents.to_nlu_entries([SAY]),
                         use_intents=False).intent == 'hello_back'

    # ---- the panel's test button: a result, never an execution
    result = user_intents.test_phrase('включи свет', payload(COMMAND))
    assert result == {'matched': True, 'intent': user_intents.public(COMMAND),
                      'score': 1.0, 'source': 'user-intents'}
    assert result['intent']['bubble_limit'] == 1000
    assert user_intents.public(captured)['voice_answer'] is True
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
    user_intents.INTENTS_DIR = _original_dir
    user_intents.INTENTS_FILE = _original_file
    _tmp.cleanup()

print('tests/test_user_intents.py: ok')
