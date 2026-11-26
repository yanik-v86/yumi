"""A small private JSONL journal of your own intents (no GTK, HTTP or network).

The browser panel reads and clears it; Brain, App and the panel emit events.
Command text and URLs are hashed and never written, at any level.  The heard
phrase and command output are written only with an explicit opt-in.  The file
lives in ``config.STATE_DIR/user-intents.log`` with mode 0600.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

from . import config

LEVELS = ('off', 'error', 'result', 'action', 'match', 'trace')
RANK = {name: i for i, name in enumerate(LEVELS)}
STAGES = frozenset(('heard', 'match', 'decision', 'skip', 'start',
                    'result', 'error', 'panel'))
SEVERITIES = frozenset(('error', 'warning', 'info', 'debug'))
LOGFILE = 'user-intents.log'
MAX_KEEP = 20000

# A stage is written only when the configured level covers it.
_STAGE_LEVEL = {
    'heard': 'trace', 'skip': 'trace',
    'match': 'match',
    'decision': 'action', 'start': 'action', 'panel': 'action',
    'result': 'result', 'error': 'error',
}
# Even a caller that hands us a whole action dict gets no text back: these keys
# are dropped from ``details`` before anything is serialized.
_DENIED = re.compile(
    r'(?i)(value|command|cmd|url|uri|token|secret|password|passwd|api[_-]?key'
    r'|stdout|heard|phrase|text|preview|env|prompt|key)')

_lock = threading.RLock()
_count = None             # cached line count, invalidated by clear() and rotation
_warned = False


def log_path():
    """the current path, resolved on every call so a changed XDG state dir works"""
    return Path(config.STATE_DIR) / LOGFILE


def _level(settings):
    value = str((settings or {}).get('intents_log_level') or 'off').strip().lower()
    return value if value in RANK else 'off'


def _int(value, default, low, high):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError, OverflowError):
        return default


def _word(value, cap):
    """one line, one bounded string: no newlines or huge values in the journal"""
    return ' '.join(str(value or '').split())[:cap]


def _preview(value, settings):
    if not bool((settings or {}).get('intents_log_include_text', False)):
        return None
    text = ' '.join(str(value or '').split())
    if not text:
        return None
    cap = _int((settings or {}).get('intents_log_max_chars'), 200, 100, MAX_KEEP)
    return text[:cap - 1] + '…' if len(text) > cap else text


def _sha(value):
    return 'sha256:' + hashlib.sha256(str(value).encode('utf-8')).hexdigest()


def _details(raw):
    """flat scalars only; anything that may carry text is denied by key name"""
    out = {}
    if not isinstance(raw, dict):
        return out
    for key, value in list(raw.items())[:16]:
        name = str(key)[:40]
        if not name or _DENIED.search(name):
            continue
        if isinstance(value, bool) or isinstance(value, (int, float)):
            out[name] = value
        elif isinstance(value, str):
            out[name] = _word(value, 120)
        elif value is None:
            out[name] = None
        # nested dicts/lists are dropped whole: a child could hold command text
    return out


def _open(path, truncate=False):
    """create private from the start; an existing loose mode is tightened too"""
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if truncate else os.O_APPEND)
    fd = os.open(str(path), flags, 0o600)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return os.fdopen(fd, 'w', encoding='utf-8')


def _count_unlocked(path):
    try:
        with path.open('rb') as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def _warn(exc):
    global _warned
    if not _warned:
        # app.log in the live app; never put a failed write into the journal
        print(f'yumi: intent log: {exc}', file=__import__('sys').stderr)
        _warned = True


def _rotate(path, max_lines):
    """keep the newest lines via a temp file + atomic replace"""
    global _count
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        keep = lines[-max_lines:]
        tmp = path.with_name(path.name + '.tmp')
        with _open(tmp, truncate=True) as fh:
            if keep:
                fh.write('\n'.join(keep) + '\n')
        os.replace(tmp, path)
        _count = len(keep)
    except OSError as exc:
        _warn(exc)


def emit(settings, stage, **fields):
    """write one record when the configured level covers ``stage``.

    ``action_value`` (also accepted as ``command``/``url``/``value``) is reduced
    to a hash and a length; it is never copied into the record.  ``heard_text``
    and ``stdout_preview`` need ``intents_log_include_text``.
    """
    global _count
    level = _level(settings)
    stage = str(stage or '')[:32]
    if RANK[level] == 0 or stage not in _STAGE_LEVEL:
        return None
    if RANK[level] < RANK[_STAGE_LEVEL[stage]]:
        return None
    severity = _word(fields.get('severity'), 16)
    if severity not in SEVERITIES:
        severity = 'error' if stage == 'error' else (
            'debug' if stage in ('heard', 'skip') else 'info')
    value = (fields.get('action_value') or fields.get('command')
             or fields.get('url') or fields.get('value'))
    rec = {
        'v': 1,
        'ts': round(time.time(), 3),
        'level': level,
        'severity': severity,
        'stage': stage,
        'intent_id': _word(fields.get('intent_id'), 64) or None,
        'source': _word(fields.get('source') or 'voice', 32) or 'voice',
        'run_id': _word(fields.get('run_id'), 32) or '',
        'status': _word(fields.get('status'), 32) or None,
        'action_type': _word(fields.get('action_type'), 16) or None,
        'action_sha': _sha(value) if value else None,
        'action_len': len(str(value)) if value else 0,
        'duration_ms': _int(fields.get('duration_ms'), 0, 0, 24 * 60 * 60 * 1000),
        'heard_text': _preview(fields.get('heard_text'), settings),
        'stdout_preview': _preview(fields.get('stdout_preview'), settings),
        'stdout_len': _int(fields.get('stdout_len'), 0, 0, 4 * 1024 * 1024),
        'error': _word(fields.get('error'), 160) or None,
        'details': _details(fields.get('details')),
    }
    line = json.dumps(rec, ensure_ascii=False, separators=(',', ':'))
    max_lines = _int((settings or {}).get('intents_log_max_lines'),
                     2000, 100, MAX_KEEP)
    with _lock:
        path = log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with _open(path) as fh:
                fh.write(line + '\n')
            _count = (_count if _count is not None else
                      _count_unlocked(path) - 1) + 1
            if _count > max_lines:
                _rotate(path, max_lines)
        except OSError as exc:
            _warn(exc)
    return rec


def _records():
    try:
        lines = log_path().read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            rec = json.loads(line)
        except (TypeError, ValueError):
            continue            # a torn line from a crash is not an event
        if isinstance(rec, dict):
            out.append(rec)
    return out


def read(limit=None, intent=None, stage=None):
    """freshest first; ``intent`` is an id, ``stage`` one of STAGES"""
    cap = MAX_KEEP if limit is None else _int(limit, 200, 1, MAX_KEEP)
    items = []
    with _lock:
        records = _records()
    for rec in reversed(records):
        if intent and str(rec.get('intent_id') or '') != str(intent):
            continue
        if stage and str(rec.get('stage') or '') != str(stage):
            continue
        items.append(rec)
        if len(items) >= cap:
            break
    return items


def clear():
    """empty the file; the server writes the audit line, not this module"""
    global _count
    with _lock:
        try:
            path = log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            _open(path, truncate=True).close()
            _count = 0
        except OSError as exc:
            _warn(exc)


def line_count():
    """cheap enough for a tick: count once, then follow our own writes"""
    global _count
    with _lock:
        if _count is None:
            _count = _count_unlocked(log_path())
        return _count


def info(settings=None):
    """safe summary for /api/status and SSE: no phrases, commands or stdout"""
    with _lock:
        records = _records()
    ts = 0.0
    errors = 0
    for rec in records:
        try:
            ts = max(ts, float(rec.get('ts') or 0))
        except (TypeError, ValueError):
            pass
        if rec.get('severity') == 'error':
            errors += 1
        elif rec.get('stage') == 'error':
            errors += 1
    return {
        'level': _level(settings),
        'path': str(log_path()),
        'last_event_at': round(ts, 3),
        'errors': errors,
        'lines': len(records),
    }
