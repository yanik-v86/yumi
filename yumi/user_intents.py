"""Your own voice rules: a small, versioned JSON file beside actions.json.

The panel edits this file through a validating API; you can also write it by
hand.  Nothing here imports GTK or runs a command: matching and validation are
pure functions, and Brain decides what to do with a hit.

    {"version": 1, "revision": 7, "intents": [
      {"id": "lights_on", "name": "Свет", "enabled": true,
       "phrases": ["включи свет"], "keywords": ["свет"],
       "action": {"type": "command", "value": "lights on"},
       "speak": "Включаю свет", "capture": false, "priority": 10,
       "requires_confirmation": true}]}

``version`` is the format, ``revision`` is the optimistic lock for the panel.
A command with ``capture: true`` sends its stdout to ``{stdout}`` in ``speak``:
Yumi then shows and voices the answer instead of just running the command.
These rules are ordinary nlu entries, not ONNX training data: no restart and
no classifier retraining is needed for a new phrase.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import config, nlu

INTENTS_FILE = config.INTENTS_FILE   # tests may point this at a temporary file
FORMAT_VERSION = 1
ACTION_TYPES = ('command', 'url', 'say')
ID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')
MAX_INTENTS = 200
MAX_ITEMS = 50
MAX_TEXT = 200
MAX_VALUE = 1000
MAX_PRIORITY = 100


class RevisionConflict(Exception):
    """the file changed since the panel read it: keep both edits, ask for a refresh"""


def _stamp():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def empty():
    """a fresh, valid document (never a shared mutable default)"""
    return {'version': FORMAT_VERSION, 'revision': 0, 'intents': []}


def _text(value, field, limit=MAX_TEXT, required=False):
    text = str(value or '').strip()
    if len(text) > limit:
        raise ValueError(f'{field} is too long (max {limit})')
    if required and not text:
        raise ValueError(f'{field} is empty')
    return text


def _bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'on', 'yes')
    return bool(value)


def _int(value, default=0):
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        number = 0
    return max(-MAX_PRIORITY, min(MAX_PRIORITY, number))


def _list(value, field):
    if value in (None, ''):
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError(f'{field} must be a list')
    out = []
    seen = set()
    for item in value:
        text = _text(item, field)
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append(text)
    if len(out) > MAX_ITEMS:
        raise ValueError(f'at most {MAX_ITEMS} {field} are allowed')
    return out


def _slug(value):
    """a stable id from a button's target, for an import without explicit ids"""
    text = re.sub(r'[^a-zA-Z0-9_-]+', '_', str(value or '').lower()).strip('_')
    return text[:64] or 'intent'


def _http_url(value):
    url = _text(value, 'url', MAX_VALUE)
    low = url.lower()
    if not (low.startswith('http://') or low.startswith('https://')):
        raise ValueError('url must start with http:// or https://')
    return url


def _one(raw, used):
    """normalize one intent; `used` collects ids already assigned in the file"""
    if not isinstance(raw, dict):
        raise ValueError('each intent must be an object')
    ident = str(raw.get('id') or '').strip()
    if ident:
        if not ID_RE.match(ident):
            raise ValueError('id may hold only letters, digits, _ and - (1..64)')
        if ident in used:
            raise ValueError(f'duplicate id: {ident}')
    else:
        base = _slug(raw.get('name') or (raw.get('phrases') or [''])[0]
                     or (raw.get('action') or {}).get('value'))
        ident = base
        n = 2
        while ident in used:
            ident = f'{base[:60]}_{n}'
            n += 1
    used.add(ident)

    phrases = _list(raw.get('phrases'), 'phrases')
    keywords = _list(raw.get('keywords'), 'keywords')
    if not phrases and not keywords:
        raise ValueError(f'{ident}: add phrases or keywords')
    name = _text(raw.get('name') or (phrases or keywords)[0], 'name')[:MAX_TEXT]
    speak = _text(raw.get('speak'), 'speak')

    action = raw.get('action')
    if not isinstance(action, dict):
        raise ValueError(f'{ident}: action must be an object')
    kind = str(action.get('type') or '').strip().lower()
    if kind not in ACTION_TYPES:
        raise ValueError(f'{ident}: action type must be one of {", ".join(ACTION_TYPES)}')
    value = str(action.get('value') or '').strip()
    if kind == 'command':
        value = _text(value, 'command', MAX_VALUE, required=True)
    elif kind == 'url':
        value = _http_url(value)
    else:
        if not speak:
            speak = _text(value, 'speak', MAX_VALUE)  # say without speak: value is the line
        value = _text(value, 'value', MAX_VALUE)
        if not speak:
            raise ValueError(f'{ident}: a "say" intent needs a line to speak')

    capture = _bool(raw.get('capture'))
    if capture and kind != 'command':
        raise ValueError(f'{ident}: capture needs a command action')

    if 'requires_confirmation' in raw:
        confirm = _bool(raw['requires_confirmation'])
    else:
        confirm = kind == 'command'   # a shell command asks first by default
    created = str(raw.get('created_at') or '').strip()[:40] or _stamp()
    updated = str(raw.get('updated_at') or '').strip()[:40] or created
    return {
        'id': ident, 'name': name, 'enabled': _bool(raw.get('enabled'), True),
        'phrases': phrases, 'keywords': keywords,
        'action': {'type': kind, 'value': value}, 'speak': speak, 'capture': capture,
        'priority': _int(raw.get('priority')), 'requires_confirmation': confirm,
        'created_at': created, 'updated_at': updated,
    }


def validate(payload):
    """a normalized copy of a whole document; raises ValueError on bad data"""
    if not isinstance(payload, dict):
        raise ValueError('user intents must be an object')
    version = payload.get('version', FORMAT_VERSION)
    try:
        version = int(version)
    except (TypeError, ValueError):
        raise ValueError('bad format version') from None
    if version != FORMAT_VERSION:
        raise ValueError(f'unsupported user intents version: {version}')
    revision = payload.get('revision', 0)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError('revision must be a non-negative integer')
    raw_intents = payload.get('intents', [])
    if not isinstance(raw_intents, list):
        raise ValueError('intents must be a list')
    if len(raw_intents) > MAX_INTENTS:
        raise ValueError(f'at most {MAX_INTENTS} intents are allowed')
    used, intents = set(), []
    for raw in raw_intents:
        intents.append(_one(raw, used))
    return {'version': FORMAT_VERSION, 'revision': revision, 'intents': intents}


def load(path=None):
    """a validated document; a missing or damaged file is treated as empty"""
    p = Path(path or INTENTS_FILE)
    try:
        payload = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeDecodeError):
        return empty()
    try:
        return validate(payload)
    except ValueError:
        return empty()


def info(path=None):
    """the panel's GET view: the document plus the file's mtime"""
    p = Path(path or INTENTS_FILE)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = 0.0
    return {**load(p), 'mtime': mtime}


def save(data, path=None):
    """validate, bump the revision and write atomically; return what was stored"""
    payload = validate(data)
    payload['revision'] += 1
    p = Path(path or INTENTS_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + '\n',
                   encoding='utf-8')
    tmp.replace(p)
    return payload


def import_json(text):
    """validate an exported document without touching the current file"""
    if isinstance(text, dict):
        payload = text
    else:
        try:
            payload = json.loads(str(text or ''))
        except (TypeError, ValueError):
            raise ValueError('the file must contain JSON') from None
    return validate(payload)


def export_json(data):
    """a stable, human-readable document for a file download or a backup"""
    return json.dumps(validate(data), indent=2, ensure_ascii=False) + '\n'


def to_nlu_entries(intents):
    """flat entries nlu.recognize() already understands (no ONNX call here)"""
    out = []
    for item in intents or []:
        if not isinstance(item, dict) or not _bool(item.get('enabled'), True):
            continue
        action = item.get('action') or {}
        kind = str(action.get('type') or '').strip().lower()
        entry = {
            'id': str(item.get('id') or '')[:64],
            'phrases': list(item.get('phrases') or []),
            'keywords': list(item.get('keywords') or []),
            'priority': _int(item.get('priority')),
            'speak': str(item.get('speak') or ''),
            'capture': kind == 'command' and _bool(item.get('capture')),
        }
        if kind == 'say':
            entry['user_intent'] = True   # never be mistaken for a shell command
        elif kind == 'url':
            entry['url'] = str(action.get('value') or '')
        else:
            entry['command'] = str(action.get('value') or '')
        out.append(entry)
    return out


def match(text, intents, min_confidence=None):
    """nlu.recognize() over the enabled custom rules; no execution, no ONNX"""
    entries = to_nlu_entries(intents)
    if not entries:
        return None
    return nlu.recognize(text, entries, use_intents=False,
                         min_confidence=min_confidence)


def public(intent):
    """the safe card for the panel: no command value is shown as ordinary text"""
    if not isinstance(intent, dict):
        return None
    action = intent.get('action') or {}
    return {
        'id': str(intent.get('id') or ''),
        'name': str(intent.get('name') or ''),
        'enabled': bool(intent.get('enabled', True)),
        'action_type': str(action.get('type') or ''),
        'capture': str(action.get('type') or '').strip().lower() == 'command'
                   and _bool(intent.get('capture')),
        'phrases': list(intent.get('phrases') or []),
        'keywords': list(intent.get('keywords') or []),
        'priority': _int(intent.get('priority')),
        'requires_confirmation': bool(intent.get('requires_confirmation')),
    }


def test_phrase(text, intents=None, min_confidence=None):
    """check a phrase without running anything: the button behind the match"""
    data = intents if intents is not None else load()
    hit = match(text, data.get('intents') or [], min_confidence=min_confidence)
    if not hit:
        return {'matched': False, 'intent': None, 'score': 0.0,
                'source': 'user-intents'}
    by_id = {str(i.get('id') or ''): i for i in (data.get('intents') or [])
             if isinstance(i, dict)}
    return {'matched': True, 'intent': public(by_id.get(hit.intent)),
            'score': round(float(hit.confidence), 3), 'source': 'user-intents'}


def from_actions(actions, existing=None):
    """convert buttons from actions.json into custom intents (explicit import only)"""
    intents = []
    used = {str(i.get('id') or '') for i in (existing or []) if isinstance(i, dict)}
    for raw in actions or []:
        if not isinstance(raw, dict):
            continue
        phrases = [str(p) for p in (raw.get('phrases') or []) if str(p).strip()]
        keywords = [str(k) for k in (raw.get('keywords') or []) if str(k).strip()]
        if not phrases and not keywords:
            continue      # a button without voice fields is not an intent
        url = str(raw.get('url') or '').strip()
        command = str(raw.get('command') or '').strip()
        if url:
            try:
                url = _http_url(url)
            except ValueError:
                continue
            kind, value, source = 'url', url, url
        elif command:
            kind, value, source = 'command', command[:MAX_VALUE], command
        else:
            continue
        ident = str(raw.get('id') or '').strip() or _slug(source)
        if not ID_RE.match(ident) or ident in used:
            continue      # a repeated import must not create a twin
        used.add(ident)
        intents.append({
            'id': ident,
            'name': str(raw.get('label_ru') or raw.get('label') or source)[:MAX_TEXT],
            'enabled': True, 'phrases': phrases[:MAX_ITEMS], 'keywords': keywords[:MAX_ITEMS],
            'action': {'type': kind, 'value': value},
            'speak': str(raw.get('speak') or '')[:MAX_TEXT],
            'priority': _int(raw.get('priority')),
            'requires_confirmation': _bool(raw.get('requires_confirmation'),
                                            kind == 'command'),
        })
    return validate({'version': FORMAT_VERSION, 'revision': 0, 'intents': intents})['intents']
