"""Local speech models: where they live and an explicit integrity check (no GTK here).

A model gets a fingerprint and is not trusted until it matches.  Yumi's models
are fetched by her setup scripts, so this module does not guess hashes — it keeps
them in
``~/.config/yumi/model_hashes.json``, filled by an explicit "record" call.  A
model with no recorded hash is reported as ``unknown`` (present, unverified),
never as a failure.  Hashing is done only on demand: several models are huge and
``engines.status()`` runs on every status tick.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from . import config, engines

HASH_FILE = config.CONFIG_DIR / 'model_hashes.json'
CACHE_TTL = 30.0          # s: a cached answer for the status snapshot


def specs():
    """{name: path} for the models Yumi can check (paths may not exist yet)"""
    stt = Path(os.environ.get('YUMI_STT_HOME') or engines.STT_HOME)
    return {
        'oww': Path(engines.OWW_MODEL),
        'vosk_ru_small': stt / 'vosk-model-small-ru-0.22',
        'vosk_ru_big': stt / 'vosk-model-ru-0.42',
        'vosk_en_small': stt / 'vosk-model-small-en-us-0.15',
        'vosk_en_big': stt / 'vosk-model-en-us-0.22',
        'whisper': stt / 'whisper',
        'nemotron': Path(engines.NEMO_MODEL),
    }


def hashes():
    """the recorded SHA-256 values, {name: {'sha256': str, 'files': int}}"""
    try:
        data = json.loads(HASH_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _sha(path):
    """SHA-256 of one file, or of a directory's sorted files (names and bytes)"""
    h = hashlib.sha256()
    if path.is_dir():
        files = sorted((p for p in path.rglob('*') if p.is_file()),
                       key=lambda p: str(p.relative_to(path)))
        if not files:
            return '', 0
        for item in files:
            h.update(str(item.relative_to(path)).encode('utf-8', 'replace'))
            with item.open('rb') as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b''):
                    h.update(chunk)
        return h.hexdigest(), len(files)
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest(), 1


def record(names=None):
    """hash the models that are here now and save them; returns what was saved"""
    known = specs()
    want = list(known) if not names else [str(n) for n in names if str(n) in known]
    out = dict(hashes())
    for name in want:
        path = known[name]
        if not path.exists():
            continue
        try:
            sha, count = _sha(path)
        except OSError:
            continue
        if sha:
            out[name] = {'sha256': sha, 'files': count, 'recorded': time.time()}
    try:
        HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = HASH_FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps(out, indent=1, ensure_ascii=False) + '\n')
        tmp.replace(HASH_FILE)
    except OSError:
        return {'saved': [], 'path': str(HASH_FILE)}
    return {'saved': want, 'path': str(HASH_FILE)}


def verify(names=None, use_cache=False):
    """{name: {'exists', 'size', 'sha256', 'status', 'note'}} for the known models.

    status is ``ok`` (hash matches), ``bad`` (hash differs), ``unknown`` (no
    recorded hash) or ``missing``.  A bad hash is the only failing state.
    """
    known = specs()
    want = list(known) if not names else [str(n) for n in names if str(n) in known]
    saved = hashes()
    out = {}
    for name in want:
        path = known[name]
        item = {'path': str(path), 'exists': path.exists(), 'size': 0,
                'sha256': '', 'status': 'missing', 'note': ''}
        if item['exists']:
            try:
                item['size'] = (sum(p.stat().st_size for p in path.rglob('*') if p.is_file())
                                if path.is_dir() else path.stat().st_size)
            except OSError:
                pass
            want_hash = (saved.get(name) or {}).get('sha256')
            if want_hash:
                try:
                    got, _count = _sha(path)
                except OSError as exc:
                    item['status'] = 'unknown'
                    item['note'] = str(exc)[:160]
                else:
                    item['sha256'] = got
                    item['status'] = 'ok' if got == want_hash else 'bad'
                    if item['status'] == 'bad':
                        item['note'] = 'the model changed since the hash was recorded'
            else:
                item['status'] = 'unknown'
                item['note'] = 'no recorded hash; use "Record hashes" to trust this copy'
        out[name] = item
    return out


_last = None


def cached():
    """a cheap copy of the last verify() for the status snapshot (never rehashes)"""
    global _last
    if _last and time.time() - _last[0] < CACHE_TTL:
        return _last[1]
    return {'checked': None, 'models': {}}


def verify_cached(force=False):
    """explicit verify: refresh the cache so /api/status can show the result"""
    global _last
    if force or not _last or time.time() - _last[0] >= CACHE_TTL:
        _last = (time.time(), {'checked': time.time(), 'models': verify()})
    return _last[1]
