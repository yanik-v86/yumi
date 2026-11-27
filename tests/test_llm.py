#!/usr/bin/env python3
"""The provider registry on a fake HTTP server: both dialects, keys, validation.
Run: python3 tests/test_llm.py"""
import json
import os
import stat
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yumi import llm, llm_keys  # noqa: E402

SEEN = {}


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload, content_type='application/json'):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        SEEN.setdefault('get', []).append((self.path, self.headers.get('Authorization')))
        if self.path == '/api/tags':
            return self._send({'models': [{'name': 'm2'}, {'name': 'm1'}]})
        if self.path == '/empty/api/tags':
            return self._send({'models': []})
        if self.path == '/api/version':
            return self._send({'version': 'test'})
        if self.path == '/models':
            if self.headers.get('Authorization') == 'Bearer secret':
                return self._send({'data': [{'id': 'z-model'}]})
            return self._send({'error': 'unauthorized'})
        self.send_error(404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        SEEN.setdefault('post', []).append((self.path, body, self.headers.get('Authorization')))
        if self.path == '/api/chat':
            if not body.get('stream'):
                return self._send({'message': {'content': ' <think>quiet</think> Hello! '}})
            chunks = ['<thi', 'nk>quiet</thi', 'nk>Hel', 'lo!', '']
            raw = b''.join(json.dumps({'message': {'content': c}, 'done': i == 4}).encode() + b'\n'
                           for i, c in enumerate(chunks))
            return self._send(raw, 'application/x-ndjson')
        if self.path == '/chat/completions':
            if not body.get('stream'):
                return self._send({'choices': [{'message': {'content': '<think>quiet</think> Hi!'}}]})
            chunks = ['<think>qu', 'iet</think>He', 'llo', '[DONE]']
            raw = b''.join((('data: ' + json.dumps(
                {'choices': [{'delta': {'content': c}}]}) + '\n\n').encode()
                if c != '[DONE]' else b'data: [DONE]\n\n') for c in chunks)
            return self._send(raw, 'text/event-stream')
        self.send_error(404)

    def log_message(self, *_args):
        pass


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{server.server_address[1]}'
SETTINGS = {
    'llm_providers': [
        {'id': 'local', 'name': 'Local', 'kind': 'ollama', 'url': base,
         'default_model': 'm1', 'enabled': True, 'models': []},
        {'id': 'remote', 'name': 'Remote', 'kind': 'openai', 'url': base,
         'default_model': 'z-model', 'enabled': True, 'models': []},
    ],
    'chat_provider': 'local',
    'chat_model': 'm1',
    'chat_think': False,
}

# ---- key storage: private file, atomic, no value in a repr or an error ----
_tmp = tempfile.TemporaryDirectory()
_original_keys_file = llm_keys.KEYS_FILE
llm_keys.KEYS_FILE = Path(_tmp.name) / 'llm_keys.json'
assert llm_keys.get('remote') == ''
assert llm_keys.set('remote', 'secret') is True
assert llm_keys.get('remote') == 'secret'
assert llm_keys.load() == {'remote': 'secret'}
assert stat.S_IMODE(os.stat(llm_keys.KEYS_FILE).st_mode) == 0o600
assert 'secret' not in repr(llm_keys.load().keys())
assert llm_keys.delete('remote') is True and llm_keys.get('remote') == ''
assert llm_keys.set('remote', 'secret') is True

# ---- validation lives in one place ----
good = {'id': 'my_provider', 'name': 'Mine', 'kind': 'openai', 'url': 'https://x/v1',
        'default_model': 'a-model', 'enabled': True}
assert llm.validate_record(good)['id'] == 'my_provider'
for bad in ({**good, 'id': 'Bad ID'}, {**good, 'url': 'ftp://x'},
            {**good, 'api_key': 'secret'}, {**good, 'enabled': 'yes'},
            {**good, 'kind': 'other'}):
    try:
        llm.validate_record(bad)
        raise AssertionError(f'bad record accepted: {bad}')
    except ValueError:
        pass
try:
    llm.validate_record(good, ['my_provider'])
    raise AssertionError('duplicate id accepted')
except ValueError:
    pass
assert [r['id'] for r in llm.normalize_list([good, good, {'id': 'BAD!'}])] == ['my_provider']
assert llm.providers(SETTINGS) == SETTINGS['llm_providers']

# ---- listing models through both dialects ----
info = llm.models(SETTINGS, 'local')
assert info == {'provider': 'local', 'models': ['m1', 'm2'], 'error': ''}, info
assert llm.models(SETTINGS, 'remote') == {'provider': 'remote', 'models': ['z-model'], 'error': ''}
assert SEEN['get'][0][1] is None
assert ('/models', 'Bearer secret') in SEEN['get']
assert llm.test(SETTINGS, 'local')['ok'] is True
assert llm.alive(SETTINGS, 'local') is True and llm.alive(SETTINGS, 'remote') is True
assert llm.models(SETTINGS, 'missing')['error'] == 'unknown provider'
assert llm.models({'llm_providers': [good]}, 'my_provider')['error'] == 'no api key'
assert llm_keys.set('my_provider', 'secret') is True
down = {'llm_providers': [{**good, 'url': 'http://127.0.0.1:1/v1'}], 'chat_provider': 'my_provider'}
assert llm.models(down)['error'] == 'the provider did not answer'
assert llm.test(down) == {'provider': 'my_provider', 'ok': False, 'models': [],
                          'error': 'the provider did not answer'}
assert llm.models({'llm_providers': [{'id': 'empty', 'name': 'Empty', 'kind': 'ollama',
                                      'url': base + '/empty', 'default_model': 'm1'}],
                   'chat_provider': 'empty'})['error'] == 'the provider has no models'

# ---- one-shot answers, Bearer and max_tokens, <think> stripped ----
assert llm.ask(SETTINGS, [{'role': 'user', 'content': 'hi'}]) == 'Hello!'
assert llm.ask(SETTINGS, [], provider='remote') == 'Hi!'
assert ('/api/chat', {'model': 'm1', 'messages': [{'role': 'user', 'content': 'hi'}],
                      'stream': False, 'options': {'num_predict': 220},
                      'think': False}, None) in SEEN['post']
remote_post = [p for p in SEEN['post'] if p[0] == '/chat/completions'][-1]
assert remote_post[2] == 'Bearer secret'
assert remote_post[1]['max_tokens'] == 220 and remote_post[1]['stream'] is False
assert llm.ask(down, []) == ''
nokey = {'llm_providers': [{**good, 'id': 'nokey'}], 'chat_provider': 'nokey'}
assert llm.ask(nokey, []) == ''
assert llm.strip_think('<think>hidden</think> answer') == 'answer'

# ---- streams: NDJSON and SSE, reasoning held back even across chunks ----
assert ''.join(llm.ask_stream(SETTINGS, [{'role': 'user', 'content': 'hi'}])) == 'Hello!'
assert ''.join(llm.ask_stream(SETTINGS, [], provider='remote')) == 'Hello'
assert list(llm.ask_stream(nokey, [])) == []
assert list(llm.ask_stream(down, [])) == []

# ---- selection is shared: the model follows the provider ----
llm.select(SETTINGS, 'remote')
assert SETTINGS['chat_provider'] == 'remote' and SETTINGS['chat_model'] == 'z-model'
try:
    llm.select(SETTINGS, 'missing')
    raise AssertionError('unknown provider selected')
except ValueError:
    pass

llm_keys.KEYS_FILE = _original_keys_file
_tmp.cleanup()
server.shutdown()
print('ok')
