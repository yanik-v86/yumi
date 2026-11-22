"""Voice profiles: a small, local store of speaker embeddings (no GTK, no network).

The embeddings are biometric data: they stay in ``speakers.json``, are never
logged and never leave this process except as a score.  ``numpy`` is used when
it is already there, but the pure-Python cosine works without it.  The ears
daemon imports this module too, so keep the imports standard-library only.
"""
from __future__ import annotations

import builtins
import json
import math
import os
import sys
import time
import uuid
from pathlib import Path

from yumi import config

SCHEMA_VERSION = 1
DEFAULT_THRESHOLD = 0.65
DEFAULT_MIN_MS = 1200
DEDUP_SCORE = 0.95          # a second enroll of the same voice updates the profile
SOURCES = frozenset(('wake', 'join', 'manual'))

try:                                    # an already installed numpy is enough
    import numpy as _np
except ImportError:                     # pragma: no cover - depends on the machine
    _np = None


def speaker_file():
    """Where the profiles live; tests set YUMI_SPEAKER_FILE to a scratch file."""
    return Path(os.environ.get('YUMI_SPEAKER_FILE') or
                (config.STATE_DIR / 'speakers.json'))


def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _vector(value):
    """A clean 1-D vector of finite floats, or None. Never echo the contents."""
    if _np is not None and isinstance(value, _np.ndarray):
        if value.ndim != 1:
            return None
        value = value.tolist()
    if not isinstance(value, (builtins.list, tuple)) or not value:
        return None
    try:
        out = [float(x) for x in value]
    except (TypeError, ValueError, OverflowError):
        return None
    return out if all(math.isfinite(x) for x in out) else None


def _dot(a, b):
    if _np is not None:
        x, y = _np.asarray(a, dtype=_np.float64), _np.asarray(b, dtype=_np.float64)
        denom = float(_np.linalg.norm(x) * _np.linalg.norm(y))
        return float(_np.dot(x, y)) / denom if denom > 0.0 else 0.0
    denom = math.sqrt(math.fsum(x * x for x in a)) * math.sqrt(math.fsum(y * y for y in b))
    return math.fsum(x * y for x, y in zip(a, b)) / denom if denom > 0.0 else 0.0


def cosine(a, b):
    """Cosine similarity in [-1, 1]; bad or different-sized vectors score 0."""
    a, b = _vector(a), _vector(b)
    if a is None or b is None or len(a) != len(b):
        return 0.0
    return max(-1.0, min(1.0, _dot(a, b)))


class SpeakerStore:
    """Persistent profiles plus the pure operations the ears and the panel need."""

    def __init__(self, path=None):
        self.path = Path(path) if path else speaker_file()
        self.diag = ''
        self.profiles = []
        self.load()

    # ---- disk
    def load(self):
        """Read the file; a broken one becomes an empty store with a diagnostic."""
        self.diag = ''
        try:
            raw = self.path.read_text(encoding='utf-8')
        except FileNotFoundError:
            self.profiles = []
            return self.profiles
        except OSError as exc:
            self.profiles = []
            self.diag = 'speaker file unreadable'
            return self.profiles
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError('not an object')
            version = data.get('version', SCHEMA_VERSION)
            if version != SCHEMA_VERSION:
                raise ValueError('unsupported schema')
            entries = data.get('profiles', [])
            if not isinstance(entries, builtins.list):
                raise ValueError('profiles is not a list')
        except (ValueError, TypeError):
            self.profiles = []
            self._quarantine()
            return self.profiles
        out, bad = [], 0
        seen = set()
        for item in entries:
            profile = self._clean(item)
            if profile is None or profile['id'] in seen:
                bad += 1
                continue
            seen.add(profile['id'])
            out.append(profile)
        self.profiles = out
        if bad:
            self.diag = f'{bad} bad profile(s) skipped'
        return self.profiles

    def _quarantine(self):
        self.diag = 'speaker file was broken, profile list is empty'
        try:
            self.path.replace(self.path.with_name(self.path.name + '.bad'))
        except OSError:
            pass

    def _clean(self, item):
        if not isinstance(item, dict):
            return None
        vec = _vector(item.get('embedding'))
        if vec is None:
            return None
        pid = str(item.get('id') or '').strip()[:64]
        if not pid:
            pid = 'spk_' + uuid.uuid4().hex[:8]
        return {
            'id': pid,
            'label': str(item.get('label') or 'Голос')[:64],
            'embedding': vec,
            'created_at': str(item.get('created_at') or _now())[:32],
            'updated_at': str(item.get('updated_at') or item.get('created_at') or _now())[:32],
            'source': str(item.get('source') or 'manual')
                      if item.get('source') in SOURCES else 'manual',
        }

    def save(self):
        """Atomic write, in the same style as config.save_settings / save_actions."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + '.tmp')
            payload = {'version': SCHEMA_VERSION, 'profiles': self.profiles}
            tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False),
                           encoding='utf-8')
            tmp.replace(self.path)
            self.diag = ''
            return True
        except OSError:
            self.diag = 'speaker file could not be saved'
            return False

    # ---- matching
    def _best(self, vec):
        best_id, score = None, 0.0
        for profile in self.profiles:
            s = cosine(vec, profile['embedding'])
            if s > score:
                best_id, score = profile['id'], s
        return best_id, score

    def _next_id(self):
        used = {p['id'] for p in self.profiles}
        n = 1
        while f'spk_{n:02d}' in used:
            n += 1
        return f'spk_{n:02d}'

    def verify(self, embedding, threshold=DEFAULT_THRESHOLD, enabled=True):
        """'known' / 'unknown' / 'disabled' — no vector ever comes back."""
        vec = _vector(embedding)
        if not enabled or vec is None:
            return {'status': 'disabled', 'id': None, 'score': 0.0}
        pid, score = self._best(vec)
        try:
            line = max(0.0, min(1.0, float(threshold)))
        except (TypeError, ValueError):
            line = DEFAULT_THRESHOLD
        if pid and score >= line:
            return {'status': 'known', 'id': pid, 'score': round(score, 4)}
        return {'status': 'unknown', 'id': None, 'score': round(score, 4)}

    def enroll(self, embedding, label=None, source='wake'):
        """Add a profile, or refresh an existing one at DEDUP_SCORE and above."""
        vec = _vector(embedding)
        if vec is None:
            return None
        pid, score = self._best(vec)
        if pid and score >= DEDUP_SCORE:
            profile = next(p for p in self.profiles if p['id'] == pid)
            profile['embedding'] = vec
            profile['updated_at'] = _now()
            if label:
                profile['label'] = str(label)[:64]
            self.save()
            return pid
        pid = self._next_id()
        stamp = _now()
        self.profiles.append({
            'id': pid,
            'label': str(label or f'Голос {len(self.profiles) + 1}')[:64],
            'embedding': vec,
            'created_at': stamp,
            'updated_at': stamp,
            'source': source if source in SOURCES else 'manual',
        })
        self.save()
        return pid

    # ---- management
    def list(self):
        """Public list: labels and ids, never embeddings."""
        return [{'id': p['id'], 'label': p['label'], 'source': p['source'],
                 'created_at': p['created_at'], 'updated_at': p['updated_at']}
                for p in self.profiles]

    def rename(self, pid, label):
        text = str(label or '').strip()[:64]
        if not text:
            return False
        for profile in self.profiles:
            if profile['id'] == pid:
                profile['label'] = text
                profile['updated_at'] = _now()
                return self.save()
        return False

    def delete(self, pid):
        before = len(self.profiles)
        self.profiles = [p for p in self.profiles if p['id'] != pid]
        if len(self.profiles) == before:
            return False
        return self.save()

    def label(self, pid):
        for profile in self.profiles:
            if profile['id'] == pid:
                return profile['label']
        return None

    def snapshot(self):
        """Safe for /api/status: metadata only, no vectors and no paths."""
        return {'version': SCHEMA_VERSION, 'count': len(self.profiles),
                'profiles': self.list(), 'diag': self.diag}


_shared = None


def store():
    """One shared store, re-read when the test path changes."""
    global _shared
    path = speaker_file()
    if _shared is None or _shared.path != path:
        _shared = SpeakerStore(path)
    return _shared


def load():
    return store().load()


def save():
    return store().save()


def enroll(embedding, label=None, source='wake'):
    return store().enroll(embedding, label, source)


def verify(embedding, threshold=DEFAULT_THRESHOLD, enabled=True):
    return store().verify(embedding, threshold, enabled)


def list():                              # noqa: A001 - the module API mirrors the store
    return store().list()


def rename(pid, label):
    return store().rename(pid, label)


def delete(pid):
    return store().delete(pid)


def snapshot(reload=False):
    """Public snapshot; ``reload=True`` sees edits made by the ears daemon.

    The GTK process and the daemon keep separate ``SpeakerStore`` instances.
    Without a re-read the panel would still list a profile after the daemon
    renamed or deleted it (or created one from a wake word).
    """
    shared = store()
    if reload:
        shared.load()
    return shared.snapshot()


def diag():
    return store().diag
