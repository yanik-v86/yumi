"""Provider registry, adapters and question/answer requests (no GTK, no panel).

A provider is data: a record in ``settings['llm_providers']``.  Two dialects are
supported — ``ollama`` (native API, NDJSON stream) and ``openai`` (OpenAI-compatible
API, SSE stream).  New providers are added by creating a record, not by editing
this file.  Secrets are read from :mod:`yumi.llm_keys` at request time; neither a
key nor an endpoint ever appears in an error, a log line or an API answer.
"""
import json
import re
import urllib.error
import urllib.request

from . import llm_keys

KINDS = ('ollama', 'openai')
ID_RE = re.compile(r'^[a-z0-9_-]{1,32}$')
URL_RE = re.compile(r'^https?://', re.I)
DEFAULT_URL = 'http://127.0.0.1:11434'
LOCAL_MODEL = 'lakomoor/vikhr-llama-3.2-1b-instruct:1b'
DEFAULT_EMBED_URL = DEFAULT_URL
DEFAULT_PROVIDERS = [
    {'id': 'local', 'name': 'Local Ollama', 'kind': 'ollama', 'url': DEFAULT_URL,
     'default_model': LOCAL_MODEL, 'enabled': True, 'models': []},
]
_FIELDS = ('id', 'name', 'kind', 'url', 'default_model', 'enabled', 'models')
ERRORS = ('no api key', 'the provider did not answer', 'the provider has no models',
          'unknown provider')


def validate_record(record, existing_ids=()):
    """one normalized record; ValueError on a bad field or a duplicate id.

    The only place that validates a provider.  A key is never a record field.
    """
    if not isinstance(record, dict):
        raise ValueError('a provider must be an object')
    for field in record:
        low = str(field).lower()
        if 'key' in low or 'secret' in low:
            raise ValueError('the key is not part of a provider record')
    pid = str(record.get('id') or '').strip()
    if not ID_RE.match(pid):
        raise ValueError('bad provider id')
    if pid in {str(x) for x in (existing_ids or ())}:
        raise ValueError('duplicate provider id')
    name = str(record.get('name') or pid).strip()
    if not name or len(name) > 60:
        raise ValueError('bad provider name')
    kind = str(record.get('kind') or '').strip()
    if kind not in KINDS:
        raise ValueError('unknown provider kind')
    url = str(record.get('url') or '').strip().rstrip('/')
    if not URL_RE.match(url) or len(url) > 400:
        raise ValueError('bad provider address')
    model = str(record.get('default_model') or '').strip()
    if len(model) > 200:
        raise ValueError('bad default model')
    enabled = record.get('enabled', True)
    if not isinstance(enabled, bool):
        raise ValueError('enabled must be a boolean')
    models = record.get('models') or []
    if not isinstance(models, list):
        raise ValueError('models must be a list')
    names = []
    for row in models[:200]:
        item = str(row or '').strip()
        if item and len(item) <= 200:
            names.append(item)
    return {'id': pid, 'name': name[:60], 'kind': kind, 'url': url,
            'default_model': model, 'enabled': bool(enabled), 'models': names}


def normalize_list(value, settings=None):
    """a clean list of records from settings or a JSON textarea.

    Bad rows are dropped rather than crashing every caller: the panel edits the
    registry through validate_record(), which is strict.  Never returns secrets.
    """
    if value is None or value == '':
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise ValueError('providers must be a JSON list')
    if not isinstance(value, list):
        raise ValueError('providers must be a list')
    out, seen = [], set()
    for row in value:
        try:
            rec = validate_record(row, seen)
        except ValueError:
            continue
        out.append(rec)
        seen.add(rec['id'])
    return out


def providers(settings):
    """copies of the records, safe to hand to a browser (no keys)"""
    try:
        return [dict(r) for r in normalize_list((settings or {}).get('llm_providers'))]
    except (TypeError, ValueError):
        return []


def get(settings, provider_id):
    """one record by id, or None"""
    pid = str(provider_id or '')
    for rec in providers(settings):
        if rec['id'] == pid:
            return rec
    return None


def select(settings, provider_id):
    """the one selection routine GTK and the panel both call.

    Sets the active provider and resets the answer model to its default.
    """
    rec = get(settings, provider_id)
    if not rec:
        raise ValueError('unknown provider')
    settings['chat_provider'] = rec['id']
    settings['chat_model'] = rec['default_model']
    return dict(rec)


def resolve(settings, provider_id=None):
    """what a request needs: url, key, kind, model and the record's default"""
    pid = str(provider_id or (settings or {}).get('chat_provider') or 'local')
    rec = get(settings, pid) or {}
    model = str((settings or {}).get('chat_model') or rec.get('default_model') or '')
    return {'provider': pid, 'url': str(rec.get('url') or ''),
            'key': llm_keys.get(pid), 'kind': str(rec.get('kind') or ''),
            'default_model': str(rec.get('default_model') or ''), 'model': model}


# ---- the <think> filter: both the one-shot answer and the stream use it ----
def strip_think(text):
    """remove a leaked «<think>…</think>» block from a finished answer"""
    return re.sub(r'<think\b[^>]*>.*?</think\s*>\s*', '', str(text or ''),
                  flags=re.S | re.I).strip()


def think_filter():
    """a streaming filter: hold back reasoning split across several chunks"""
    tag, end, buf, inside = '<think>', '</think>', '', False

    def feed(chunk):
        nonlocal buf, inside
        buf += str(chunk or '')
        out = []
        while buf:
            if inside:
                i = buf.lower().find(end)
                if i < 0:
                    keep = len(end) - 1
                    buf = buf[-keep:] if len(buf) > keep else buf
                    break
                buf = buf[i + len(end):]
                inside = False
            else:
                i = buf.lower().find(tag)
                if i < 0:
                    keep = len(tag) - 1
                    if len(buf) > keep:
                        out.append(buf[:-keep])
                        buf = buf[-keep:]
                    break
                if i:
                    out.append(buf[:i])
                buf = buf[i + len(tag):]
                inside = True
        return ''.join(out)

    def flush():
        nonlocal buf, inside
        if inside:
            buf = ''
            return ''
        out, buf = buf, ''
        return out

    return feed, flush


# ---- HTTP plumbing (stdlib only) ----
def _get_json(url, timeout, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8', errors='replace'))


def _post(url, body, headers, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'),
                                 headers=headers)
    return urllib.request.urlopen(req, timeout=timeout)


def _post_json(url, body, headers, timeout):
    with _post(url, body, headers, timeout) as resp:
        return json.loads(resp.read().decode('utf-8', errors='replace'))


def _endpoint(res, kind_of_call):
    base = str(res.get('url') or '').rstrip('/')
    if res.get('kind') == 'ollama':
        return base + ('/api/tags' if kind_of_call == 'models' else '/api/chat')
    return base + ('/models' if kind_of_call == 'models' else '/chat/completions')


def _headers(res):
    headers = {'Content-Type': 'application/json'}
    if res.get('kind') == 'openai':
        headers['Authorization'] = 'Bearer ' + str(res.get('key') or '')
    return headers


def _body(res, messages, model, opts, stream):
    tokens = opts.get('max_tokens', 220)
    try:
        tokens = max(1, min(8192, int(tokens)))
    except (TypeError, ValueError):
        tokens = 220
    history = [dict(m) for m in (messages or []) if isinstance(m, dict)]
    if res.get('kind') == 'ollama':
        body = {'model': model, 'messages': history, 'stream': stream,
                'options': {'num_predict': tokens},
                'think': bool(opts.get('think', False))}
    else:
        body = {'model': model, 'messages': history, 'stream': stream,
                'max_tokens': tokens}
    if opts.get('temperature') is not None:
        try:
            temp = float(opts['temperature'])
        except (TypeError, ValueError):
            temp = None
        if temp is not None:
            if res.get('kind') == 'ollama':
                body['options']['temperature'] = temp
            else:
                body['temperature'] = temp
    return body


def _content(data, kind):
    if not isinstance(data, dict):
        return ''
    if kind == 'ollama':
        return str(((data.get('message') or {}).get('content') or ''))
    choices = data.get('choices')
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ''
    return str(((choices[0].get('message') or {}).get('content') or ''))


# ---- public request API ----
def models(settings, provider_id=None, timeout=4, key=None):
    """{'provider', 'models', 'error'} — never raises, never leaks an endpoint.

    `key` is an explicit secret for an unsaved draft; ``None`` reads the private
    key file.  It is used for this call only: never stored, logged or returned.
    """
    pid = str(provider_id or (settings or {}).get('chat_provider') or 'local')
    out = {'provider': pid, 'models': [], 'error': ''}
    rec = get(settings, pid)
    if not rec:
        out['error'] = 'unknown provider'
        return out
    secret = llm_keys.get(pid) if key is None else str(key)
    if rec['kind'] == 'openai' and not secret:
        out['error'] = 'no api key'
        return out
    try:
        data = _get_json(_endpoint(rec, 'models'), timeout, _headers(rec | {'key': secret}))
        if rec['kind'] == 'ollama':
            rows = data.get('models') if isinstance(data, dict) else None
            field = 'name'
        else:
            rows = data.get('data') if isinstance(data, dict) else None
            field = 'id'
        if not isinstance(rows, list):
            out['error'] = 'the provider did not answer'
            return out
        names = {str(row.get(field)) for row in rows
                 if isinstance(row, dict) and row.get(field)}
    except (OSError, ValueError, TypeError, urllib.error.URLError):
        out['error'] = 'the provider did not answer'
        return out
    out['models'] = sorted(names)
    if not out['models']:
        out['error'] = 'the provider has no models'
    return out


def test(settings, provider_id=None, timeout=4, key=None):
    """a cheap reachability check: list models, no chat completion, no prompt"""
    info = models(settings, provider_id, timeout, key)
    return {'provider': info['provider'], 'ok': not bool(info['error']),
            'models': info['models'], 'error': info['error']}


def alive(settings, provider_id=None, timeout=0.8):
    """cheap pulse for diagnostics; an OpenAI-compatible provider needs a key"""
    rec = get(settings, provider_id or (settings or {}).get('chat_provider'))
    if not rec:
        return False
    if rec['kind'] == 'openai':
        return not bool(models(settings, rec['id'], timeout)['error'])
    try:
        return isinstance(_get_json(rec['url'].rstrip('/') + '/api/version', timeout), dict)
    except (OSError, ValueError, TypeError, urllib.error.URLError):
        return False


def ask(settings, messages, *, provider=None, model=None, timeout=90,
        tools=None, **opts):
    """one answer to `messages` ([{role, content}, …]); '' when it did not work"""
    res = resolve(settings, provider)
    if not res['kind'] or (res['kind'] == 'openai' and not res['key']):
        return ''
    name = str(model or res['model'] or res['default_model'])
    if not name:
        return ''
    options = dict(opts)
    options.setdefault('think', bool((settings or {}).get('chat_think', False)))
    try:
        data = _post_json(_endpoint(res, 'chat'),
                          _body(res, messages, name, options, False),
                          _headers(res), timeout)
    except (OSError, ValueError, TypeError, urllib.error.URLError):
        return ''
    return strip_think(' '.join(_content(data, res['kind']).split()))


def ask_stream(settings, messages, *, provider=None, model=None, timeout=90,
               tools=None, **opts):
    """the answer as text chunks; yields nothing at once for an empty key"""
    res = resolve(settings, provider)
    if not res['kind'] or (res['kind'] == 'openai' and not res['key']):
        return
    name = str(model or res['model'] or res['default_model'])
    if not name:
        return
    options = dict(opts)
    options.setdefault('think', bool((settings or {}).get('chat_think', False)))
    try:
        resp = _post(_endpoint(res, 'chat'),
                     _body(res, messages, name, options, True),
                     _headers(res), timeout)
    except (OSError, ValueError, TypeError, urllib.error.URLError):
        return
    feed, flush = think_filter()
    try:
        try:
            for raw in resp:
                try:
                    line = raw.decode('utf-8', errors='replace').strip()
                except Exception:
                    continue
                if not line:
                    continue
                if res['kind'] == 'ollama':
                    chunk = _ndjson_chunk(line)
                    done = _ndjson_done(line)
                else:
                    if not line.startswith('data:'):
                        continue
                    payload = line[5:].strip()
                    if payload == '[DONE]':
                        break
                    chunk, done = _sse_chunk(payload), False
                out = feed(chunk)
                if out:
                    yield out
                if done:
                    break
        except (OSError, ValueError, TypeError, urllib.error.URLError):
            pass
        tail = flush()
        if tail:
            yield tail
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _ndjson_chunk(line):
    try:
        data = json.loads(line)
    except ValueError:
        return ''
    return str(((data.get('message') or {}).get('content') or '')) if isinstance(data, dict) else ''


def _ndjson_done(line):
    try:
        data = json.loads(line)
    except ValueError:
        return False
    return bool(isinstance(data, dict) and data.get('done'))


def _sse_chunk(payload):
    try:
        data = json.loads(payload)
    except ValueError:
        return ''
    if not isinstance(data, dict):
        return ''
    choices = data.get('choices')
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ''
    return str(((choices[0].get('delta') or {}).get('content') or ''))
