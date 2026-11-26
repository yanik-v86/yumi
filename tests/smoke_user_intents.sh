#!/usr/bin/env bash
# Your own intents end to end, without a GTK window or a running Yumi.
# Creates a rule through the real HTTP panel, edits intent.json by hand,
# checks that Brain picks the edit up by mtime, then tests/exports/imports/deletes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 - "$ROOT" <<'PY'
import http.cookiejar
import json
import os
import shutil
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
tmp = Path(tempfile.mkdtemp(prefix='yumi-smoke-intents-'))
os.environ['XDG_CONFIG_HOME'] = str(tmp / 'config')
os.environ['XDG_STATE_HOME'] = str(tmp / 'state')
os.environ['XDG_CACHE_HOME'] = str(tmp / 'cache')
for path in (tmp / 'config', tmp / 'state', tmp / 'cache'):
    path.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

import gi  # noqa: E402
gi.require_version('GdkPixbuf', '2.0')
from yumi import config, user_intents  # noqa: E402
from yumi.brain import Brain  # noqa: E402
from yumi.phrases import Speech  # noqa: E402
from yumi.sprites import Meta  # noqa: E402
from yumi.ui.webpanel import PanelMixin  # noqa: E402
from yumi.webpanel import server  # noqa: E402


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


settings = dict(config.DEFAULT_SETTINGS)
settings.update(ui_lang='ru', user_intents=True, nlu_confidence=0.6,
                web_panel=True, web_panel_host='127.0.0.1',
                web_panel_port=free_port())
intents_dir = config.INTENTS_DIR

# A real Brain state machine, but no GTK loop: requests are only collected.
brain = Brain(Meta(config.SPRITES, None), settings, {'intro_done': True},
              Speech(settings), lambda *_a: (10, 10))
brain.actions_path = tmp / 'actions.json'
brain.actions_mtime = 0.0
brain.custom = []
brain.user_intents_path = intents_dir
brain.user_intents_mtime = 0.0
brain.user_intents_data = user_intents.load(intents_dir)


class Bridge:
    """The HTTP face uses the very same PanelMixin methods as the live app."""

    def __init__(self):
        self.settings = settings
        self.side = PanelMixin()
        self.side.settings = settings
        self.side.brain = brain

    def user_intents_get(self):
        return self.side._web_user_intents_get()

    def user_intents_put(self, payload):
        return self.side._web_user_intents_put(payload)

    def user_intents_import(self, text):
        return self.side._web_user_intents_import(text)

    def user_intents_export(self):
        return self.side._web_user_intents_export()

    def user_intents_test(self, text):
        return self.side._web_user_intents_test(text)

    def user_intents_run(self, text):
        return self.side._web_user_intents_run(text)

    def intents_log_get(self, limit=200, intent='', stage=''):
        return self.side._web_intents_log_get(limit, intent, stage)

    def intents_log_clear(self):
        return self.side._web_intents_log_clear()

    def logs(self, name, lines):
        return self.side._web_logs(name, lines)

    def snapshot(self):
        return {}

    def __getattr__(self, name):
        return lambda *_a, **_k: {}


jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
panel = server.Panel(settings, Bridge(), config_dir=config.CONFIG_DIR)


def call(method, path, body=None, csrf=None, raw=False):
    headers = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    if csrf:
        headers['X-Yumi-CSRF'] = csrf
    req = urllib.request.Request(f'http://127.0.0.1:{panel.port}{path}',
                                 data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=10) as res:
            payload = res.read()
            return res.status, (payload if raw else json.loads(payload or b'null')), res.headers
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        try:
            parsed = json.loads(payload or b'null')
        except ValueError:
            parsed = payload
        return exc.code, parsed, exc.headers


try:
    assert panel.start(), panel.error
    code, data, _ = call('POST', '/api/login', {'token': panel.auth.token})
    assert code == 200 and data['csrf'], (code, data)
    csrf = data['csrf']

    # 1. create one rule through the panel
    code, data, _ = call('GET', '/api/user-intents')
    assert code == 200 and data['revision'] == 0 and data['intents'] == []
    intent = {'id': 'lamp', 'name': 'Лампа', 'enabled': True,
              'phrases': ['включи лампу'], 'keywords': [],
              'action': {'type': 'command', 'value': 'noop-one'},
              'speak': '', 'priority': 0, 'requires_confirmation': False}
    answer = {'id': 'answer', 'name': 'Ответ', 'enabled': True,
              'phrases': ['ответь новостями'], 'keywords': [],
              'action': {'type': 'command', 'value': 'noop-answer'},
              'speak': 'Ответ: {stdout}', 'capture': True, 'priority': 0,
              'requires_confirmation': False}
    code, data, _ = call('PUT', '/api/user-intents',
                         {'version': 1, 'revision': 0, 'intents': [intent, answer]},
                         csrf=csrf)
    assert code == 200 and data['revision'] == 1, (code, data)

    brain.requests.clear()
    assert brain.voice_user_intent('включи лампу') is True
    req = next(r for r in brain.requests if r[0] == 'run_in')
    assert req[1] == 'noop-one' and Path(req[2]).name == 'lamp', brain.requests
    assert brain.last_intent == 'lamp'

    brain.requests.clear()
    assert brain.voice_user_intent('ответь новостями') is True
    req = next(r for r in brain.requests if r[0] == 'run_capture')
    assert req[:4] == ('run_capture', 'noop-answer', 'answer', 'Ответ: {stdout}')
    assert Path(req[6]).name == 'answer'
    assert req[4]['bubble_limit'] == 1000
    assert brain.user_intent_answer('свежие заголовки', 'answer', 'Ответ: {stdout}',
                                    options=req[4]) is True
    assert brain.bubble['text'] == 'Ответ: свежие заголовки', brain.bubble

    # the very same launch is available to the browser's card button
    code, data, _ = call('POST', '/api/user-intents/run',
                         {'text': 'ответь новостями'}, csrf=csrf)
    assert code == 200 and data['matched'] and data['ran'] is True, (code, data)
    assert data['intent']['id'] == 'answer'
    assert any(r[0] == 'run_capture' and r[1] == 'noop-answer' for r in brain.requests)

    # 2. edit intent.json and index.json by hand: no restart, no other rule touched
    rule_file = user_intents.intent_dir('lamp', intents_dir) / user_intents.INTENT_FILE
    raw = json.loads(rule_file.read_text(encoding='utf-8'))
    raw['phrases'] = ['включи свет']
    raw['action']['value'] = 'noop-two'
    raw['updated_at'] = '2026-11-25T12:00:00Z'
    rule_file.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding='utf-8')
    index_file = intents_dir / user_intents.INDEX_FILE
    index = json.loads(index_file.read_text(encoding='utf-8'))
    index['revision'] += 1
    index_file.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')

    brain.requests.clear()
    assert brain.voice_user_intent('включи лампу') is False, 'the old phrase must be gone'
    assert brain.voice_user_intent('включи свет') is True, 'the new phrase must fire'
    req = next(r for r in brain.requests if r[0] == 'run_in')
    assert req[1] == 'noop-two' and Path(req[2]).name == 'lamp', brain.requests
    assert not any(r[0] in ('run', 'run_in') and r[1] == 'noop-one'
                   for r in brain.requests)

    # 3. the panel tests the phrase without running anything
    code, data, _ = call('POST', '/api/user-intents/test', {'text': 'включи свет'}, csrf=csrf)
    assert code == 200 and data['matched'] and data['intent']['id'] == 'lamp', (code, data)
    assert data['score'] == 1.0 and data['source'] == 'user-intents'

    # 4. export, import the same document back, then delete the rule
    code, body, headers = call('GET', '/api/user-intents/export', raw=True)
    assert code == 200 and 'attachment' in headers.get('Content-Disposition', '')
    exported = body.decode('utf-8')
    assert 'включи свет' in exported
    code, data, _ = call('POST', '/api/user-intents/import', {'text': exported}, csrf=csrf)
    assert code == 200 and data['revision'] == 3 and data['intents'][0]['id'] == 'lamp', (code, data)

    code, data, _ = call('GET', '/api/user-intents')
    assert code == 200 and data['revision'] == 3
    code, data, _ = call('PUT', '/api/user-intents',
                         {'version': 1, 'revision': 3, 'intents': []}, csrf=csrf)
    assert code == 200 and data['intents'] == [], (code, data)
    brain.requests.clear()
    assert brain.voice_user_intent('включи свет') is False

    # command values are user actions, but they never enter the panel audit
    audit = (config.STATE_DIR / 'web-audit.log').read_text(encoding='utf-8')
    assert 'noop-one' not in audit and 'noop-two' not in audit
finally:
    panel.stop()
    shutil.rmtree(tmp, ignore_errors=True)

print('tests/smoke_user_intents.sh: ok')
PY
