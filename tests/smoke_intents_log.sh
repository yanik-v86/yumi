#!/usr/bin/env bash
# The action journal through the real HTTP panel: run, read, opt in, clear.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 - "$ROOT" <<'PY'
import http.cookiejar
import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
tmp = Path(tempfile.mkdtemp(prefix='yumi-smoke-intent-log-'))
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
                intents_log_level='trace', intents_log_include_text=False,
                web_panel=True, web_panel_host='127.0.0.1',
                web_panel_port=free_port())
intents_dir = config.INTENTS_DIR

brain = Brain(Meta(config.SPRITES, None), settings, {'intro_done': True},
              Speech(settings), lambda *_a: (10, 10))
brain.actions_path = tmp / 'actions.json'
brain.actions_mtime = 0.0
brain.custom = []
brain.user_intents_path = intents_dir
brain.user_intents_mtime = 0.0
brain.user_intents_data = user_intents.load(intents_dir)


class Bridge:
    """The HTTP face uses the same PanelMixin methods as the live app."""

    def __init__(self):
        self.settings = settings
        self.side = PanelMixin()
        self.side.settings = settings
        self.side.brain = brain

    def user_intents_get(self):
        return self.side._web_user_intents_get()

    def user_intents_put(self, payload):
        return self.side._web_user_intents_put(payload)

    def user_intents_run(self, text):
        return self.side._web_user_intents_run(text)

    def intents_log_get(self, limit=200, intent='', stage=''):
        return self.side._web_intents_log_get(limit, intent, stage)

    def intents_log_clear(self):
        return self.side._web_intents_log_clear()

    def apply_settings(self, patch):
        before = {k: self.settings.get(k) for k in patch}
        self.settings.update(patch)
        return {'saved': patch, 'before': before}

    def logs(self, name, lines):
        return self.side._web_logs(name, lines)

    def snapshot(self):
        return {}

    def __getattr__(self, name):
        return lambda *_a, **_k: {}


jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
panel = server.Panel(settings, Bridge(), config_dir=config.CONFIG_DIR)


def call(method, path, body=None, csrf=None):
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
            return res.status, json.loads(res.read() or b'null')
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b'null')


try:
    assert panel.start(), panel.error
    code, data = call('POST', '/api/login', {'token': panel.auth.token})
    assert code == 200 and data['csrf'], (code, data)
    csrf = data['csrf']

    secret = 'printf SHOULD_NOT_BE_LOGGED'
    phrase = 'журнал проверки'
    rule = {'id': 'logtest', 'name': 'Журнал', 'enabled': True,
            'phrases': [phrase], 'keywords': [],
            'action': {'type': 'command', 'value': secret},
            'speak': '', 'priority': 0, 'requires_confirmation': False}
    code, data = call('PUT', '/api/user-intents',
                      {'version': 1, 'revision': 0, 'intents': [rule]}, csrf=csrf)
    assert code == 200 and data['revision'] == 1, (code, data)

    code, data = call('POST', '/api/user-intents/log/clear', csrf=csrf)
    assert code == 200 and data['cleared'] is True, (code, data)

    code, data = call('POST', '/api/user-intents/run', {'text': phrase}, csrf=csrf)
    assert code == 200 and data['matched'] and data['ran'], (code, data)
    run_id = data['run_id']

    code, data = call('GET', '/api/user-intents/log')
    assert code == 200 and data['items'], (code, data)
    stages = {item['stage'] for item in data['items']}
    assert {'panel', 'heard', 'match', 'start', 'result'} <= stages, stages
    assert all(item['run_id'] == run_id for item in data['items'])
    dump = json.dumps(data['items'], ensure_ascii=False)
    assert secret not in dump and 'SHOULD_NOT_BE_LOGGED' not in dump
    assert phrase not in dump
    assert data['info']['level'] == 'trace' and data['info']['lines'] >= 5

    code, data = call('GET', '/api/logs?name=intents&lines=50')
    assert code == 200 and data['path'].endswith('user-intents.log'), data
    assert '"stage":"start"' in data['text'], data['text'][:200]

    # enabling previews is a deliberate setting change, written to the audit
    code, data = call('PATCH', '/api/settings',
                      {'patch': {'intents_log_include_text': True}}, csrf=csrf)
    assert code == 200 and data['settings']['intents_log_include_text'] is True
    code, audit = call('GET', '/api/audit')
    assert any('text previews enabled' in str(item.get('detail') or '')
               for item in audit['items']), audit['items'][:3]

    code, data = call('POST', '/api/user-intents/run', {'text': phrase}, csrf=csrf)
    assert code == 200 and data['ran'], (code, data)
    code, data = call('GET', '/api/user-intents/log')
    assert code == 200 and any(item.get('heard_text') == phrase
                               for item in data['items']), data['items'][:3]
    assert secret not in json.dumps(data['items'], ensure_ascii=False)

    code, data = call('POST', '/api/user-intents/log/clear', csrf=csrf)
    assert code == 200 and data['cleared'] is True, (code, data)
    code, data = call('GET', '/api/user-intents/log')
    assert code == 200 and data['items'] == [] and data['info']['lines'] == 0

    code, audit = call('GET', '/api/audit')
    assert any(item.get('action') == 'intents-log-clear' for item in audit['items'])
finally:
    panel.stop()

print('tests/smoke_intents_log.sh: ok')
PY
