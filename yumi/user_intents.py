"""Your own voice rules: one folder per rule under user-intents/<id>/intent.json.

The panel edits these files through a validating API; you can also write them
by hand.  Each folder may hold your own files (scripts and so on): a rule's
command runs with that folder as its working directory.  Nothing here imports
GTK or runs a command: matching and validation are pure functions, and Brain
decides what to do with a hit.

    ~/.config/yumi/user-intents/
      index.json                 # version, revision, the order of the rules
      lights_on/intent.json      # one rule, plus any files you keep beside it
      lights_on/lights.py

An intent file holds the same fields as an entry in an exported document:
    {"id": "lights_on", "name": "Свет", "enabled": true,
     "phrases": ["включи свет"], "keywords": ["свет"],
     "action": {"type": "command", "value": "python3 lights.py"},
     "speak": "Включаю свет", "capture": false, "priority": 10,
     "voice_answer": true, "bubble_answer": true, "bubble_limit": 1000,
     "requires_confirmation": true}

Export/import still use the whole document for backups:
    {"version": 1, "revision": 7, "intents": [...]}

``version`` is the format, ``revision`` is the optimistic lock for the panel.
A command with ``capture: true`` sends its stdout to ``{stdout}`` in ``speak``:
Yumi then shows and voices the answer instead of just running the command.
``voice_answer``/``bubble_answer`` turn those two outputs on independently;
``voice_text``/``bubble_text`` replace the shared ``speak`` template and stay literal
without ``{stdout}`` (a short announcement), while ``bubble_limit`` caps the bubble.
These rules are ordinary nlu entries, not ONNX training data: no restart and
no classifier retraining is needed for a new phrase.

The old single ``user_intents.json`` is moved to ``user_intents.json.migrated``
on the first read: one folder per rule, with the revision preserved.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import config, nlu

INTENTS_DIR = config.INTENTS_DIR       # the live store: one folder per rule
INTENTS_FILE = config.INTENTS_FILE     # the old single document, migrated on first read
INDEX_FILE = 'index.json'
INTENT_FILE = 'intent.json'
BACKUP_SUFFIX = '.migrated'
FORMAT_VERSION = 1
ACTION_TYPES = ('command', 'url', 'say')
ID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')
MAX_INTENTS = 200
MAX_ITEMS = 50
MAX_TEXT = 200
MAX_VALUE = 1000
MAX_PRIORITY = 100
MAX_ANSWER_TEMPLATE = 1000
DEFAULT_BUBBLE_LIMIT = 1000
MIN_BUBBLE_LIMIT = 100
MAX_BUBBLE_LIMIT = 4000


class RevisionConflict(Exception):
    """the store changed since the panel read it: keep both edits, ask for a refresh"""


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


def _limit(value, default=DEFAULT_BUBBLE_LIMIT):
    if value in (None, ''):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(MIN_BUBBLE_LIMIT, min(MAX_BUBBLE_LIMIT, number))


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
    voice_text = _text(raw.get('voice_text'), 'voice_text', MAX_ANSWER_TEMPLATE)
    bubble_text = _text(raw.get('bubble_text'), 'bubble_text', MAX_ANSWER_TEMPLATE)
    if not capture and (voice_text or bubble_text):
        raise ValueError(f'{ident}: separate answer lines need capture')

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
        'voice_text': voice_text, 'bubble_text': bubble_text,
        'voice_answer': _bool(raw.get('voice_answer'), True),
        'bubble_answer': _bool(raw.get('bubble_answer'), True),
        'bubble_limit': _limit(raw.get('bubble_limit')),
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


# ---- the store: index.json + one folder per rule ---------------------------

def root_dir(path=None):
    """the storage root; an old document path maps to its sibling folder"""
    p = Path(path or INTENTS_DIR)
    if p.suffix == '.json' and p.name != INDEX_FILE:
        return p.parent / 'user-intents'
    return p


def intent_dir(ident, root=None):
    """one rule's folder; the id is checked before it ever touches a path"""
    ident = str(ident or '').strip()
    if not ID_RE.fullmatch(ident):
        raise ValueError('bad intent id')
    return root_dir(root) / ident


def _read_json(path):
    try:
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path, payload):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.tmp')
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + '\n',
                   encoding='utf-8')
    tmp.replace(p)


def _migrate(root):
    """move the old user_intents.json into folders once, keeping a backup"""
    legacy = Path(INTENTS_FILE)
    if legacy.name != 'user_intents.json' or legacy.parent != root.parent:
        return
    if not legacy.is_file() or (root / INDEX_FILE).exists():
        return
    old = _read_json(legacy)
    if old is None:
        return
    try:
        data = validate(old)
    except ValueError:
        return
    for item in data['intents']:
        _write_json(root / item['id'] / INTENT_FILE, item)
    _write_json(root / INDEX_FILE, {
        'version': FORMAT_VERSION, 'revision': data['revision'],
        'order': [i['id'] for i in data['intents']],
    })
    backup = legacy.with_name(legacy.name + BACKUP_SUFFIX)
    n = 2
    while backup.exists():
        backup = legacy.with_name(f'{legacy.name}{BACKUP_SUFFIX}.{n}')
        n += 1
    try:
        legacy.replace(backup)
    except OSError:
        pass


def load(path=None):
    """a validated document assembled from index.json and one file per rule"""
    root = root_dir(path)
    _migrate(root)     # a one-time no-op unless the old file sits beside this root
    index = _read_json(root / INDEX_FILE)
    if index is None:
        return empty()
    try:
        revision = int(index.get('revision', 0))
    except (TypeError, ValueError):
        return empty()
    if isinstance(index.get('revision'), bool) or revision < 0:
        return empty()
    order = index.get('order', [])
    if not isinstance(order, list):
        return empty()

    used, intents, seen = set(), [], set()
    files = [(str(ident), root / str(ident) / INTENT_FILE) for ident in order]
    files += [(p.parent.name, p) for p in sorted(root.glob('*/' + INTENT_FILE))]
    for ident, file in files:
        if not ID_RE.fullmatch(ident) or ident in seen:
            continue
        seen.add(ident)
        raw = _read_json(file)
        if raw is None:
            continue
        try:
            # the folder name is the id: a copied file cannot claim another slot
            intents.append(_one({**raw, 'id': ident}, used))
        except ValueError:
            continue
    if len(intents) > MAX_INTENTS:
        return empty()
    return {'version': FORMAT_VERSION, 'revision': revision, 'intents': intents}


def mtime(path=None):
    """the newest change across the index and the rule files (hot reload)"""
    root = root_dir(path)
    newest = 0.0
    for file in (root / INDEX_FILE, *root.glob('*/' + INTENT_FILE)):
        try:
            newest = max(newest, file.stat().st_mtime)
        except OSError:
            pass
    return newest


def info(path=None):
    """the panel's GET view: the document plus the store's mtime"""
    return {**load(path), 'mtime': mtime(path)}


def save(data, path=None):
    """validate, bump the revision and write one folder per rule; return the document"""
    payload = validate(data)
    payload['revision'] += 1
    root = root_dir(path)
    root.mkdir(parents=True, exist_ok=True)
    ids = [i['id'] for i in payload['intents']]
    for item in payload['intents']:
        _write_json(root / item['id'] / INTENT_FILE, item)
    old = _read_json(root / INDEX_FILE) or {}
    old_order = old.get('order') if isinstance(old.get('order'), list) else []
    removed = list(old_order) + [p.parent.name for p in root.glob('*/' + INTENT_FILE)]
    for ident in removed:
        ident = str(ident)
        if ident in ids or not ID_RE.fullmatch(ident):
            continue
        folder = root / ident
        try:
            (folder / INTENT_FILE).unlink()
            folder.rmdir()          # a folder with the user's own files stays
        except OSError:
            pass
    _write_json(root / INDEX_FILE, {
        'version': FORMAT_VERSION, 'revision': payload['revision'], 'order': ids,
    })
    return payload


def import_json(text):
    """validate an exported document without touching the current store"""
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
            'voice_answer': _bool(item.get('voice_answer'), True),
            'bubble_answer': _bool(item.get('bubble_answer'), True),
            'bubble_limit': _limit(item.get('bubble_limit')),
            'voice_text': str(item.get('voice_text') or '')[:MAX_ANSWER_TEMPLATE],
            'bubble_text': str(item.get('bubble_text') or '')[:MAX_ANSWER_TEMPLATE],
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
        'voice_answer': _bool(intent.get('voice_answer'), True),
        'bubble_answer': _bool(intent.get('bubble_answer'), True),
        'bubble_limit': _limit(intent.get('bubble_limit')),
        'voice_text': str(intent.get('voice_text') or '')[:MAX_ANSWER_TEMPLATE],
        'bubble_text': str(intent.get('bubble_text') or '')[:MAX_ANSWER_TEMPLATE],
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
