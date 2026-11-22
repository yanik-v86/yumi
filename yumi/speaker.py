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

SCHEMA_VERSION = 3
SUPPORTED_SCHEMA = frozenset((1, 2, 3))
DEFAULT_THRESHOLD = 0.65
DEFAULT_MIN_MS = 1200
DEDUP_SCORE = 0.75          # a second enroll of the same voice joins the profile
SOFT_MATCH_SCORE = 0.55     # a wake near-miss is the same voice, not «Голос 2»
MAX_EMBEDDINGS = 12         # a profile keeps this many samples of the voice
SOURCES = frozenset(('wake', 'join', 'manual'))
PROFILE_INFO_KEYS = ('name', 'city', 'music', 'work', 'hobbies', 'about')

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


def is_generic_label(label):
    """True for an auto-generated label such as «Голос 1» or `spk_03`.

    Such a label is a placeholder, not something Yumi should repeat as a name.
    """
    low = ' '.join(str(label or '').lower().split())
    if not low:
        return True
    if low in ('голос', 'voice'):
        return True
    parts = low.split()
    if len(parts) == 2 and parts[0] in ('голос', 'voice') and parts[1].isdigit():
        return True
    if low.startswith('spk_') and low[4:].isdigit():
        return True
    return False


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


def _vecs(profile):
    """All clean sample vectors of a profile (new files keep many, old ones one)."""
    out = []
    candidates = [profile.get('embedding')]
    more = profile.get('embeddings')
    if isinstance(more, (builtins.list, tuple)):
        candidates.extend(more)
    for item in candidates:
        v = _vector(item)
        if v is not None and v not in out:
            out.append(v)
    return out


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
            if version not in SUPPORTED_SCHEMA:
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

    def _clean_info(self, item):
        info = {}
        raw = item.get('info')
        src = raw if isinstance(raw, dict) else item
        for k in PROFILE_INFO_KEYS:
            v = src.get(k)
            if v is None:
                continue
            text = str(v).strip()[:256]
            if text:
                info[k] = text
        return info

    def _clean(self, item):
        if not isinstance(item, dict):
            return None
        vecs = _vecs(item)
        if not vecs:
            return None
        pid = str(item.get('id') or '').strip()[:64]
        if not pid:
            pid = 'spk_' + uuid.uuid4().hex[:8]
        profile = {
            'id': pid,
            'label': str(item.get('label') or 'Голос')[:64],
            'embedding': vecs[0],
            'embeddings': vecs[:MAX_EMBEDDINGS],
            'created_at': str(item.get('created_at') or _now())[:32],
            'updated_at': str(item.get('updated_at') or item.get('created_at') or _now())[:32],
            'source': str(item.get('source') or 'manual')
                      if item.get('source') in SOURCES else 'manual',
        }
        info = self._clean_info(item)
        if info:
            profile['info'] = info
        return profile

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
        """Best profile by its closest stored sample (a voice varies by phrase)."""
        best_id, score = None, 0.0
        for profile in self.profiles:
            s = max((cosine(vec, v) for v in _vecs(profile)), default=0.0)
            if s > score:
                best_id, score = profile['id'], s
        return best_id, score

    def _next_id(self):
        used = {p['id'] for p in self.profiles}
        n = 1
        while f'spk_{n:02d}' in used:
            n += 1
        return f'spk_{n:02d}'

    def closest(self, embedding):
        """(pid, raw score) of the nearest profile, without applying a threshold.

        The wake path uses this for a near-miss: a phrase that scores 0.60 is
        still the same person, and adding it as a sample is far better than
        spawning another generic «Голос 2» profile.
        """
        vec = _vector(embedding)
        return self._best(vec) if vec is not None else (None, 0.0)

    def add_sample(self, pid, embedding, label=None, info=None):
        """Attach one more reading of an already-known voice to its profile."""
        profile = next((p for p in self.profiles if p['id'] == pid), None)
        vec = _vector(embedding)
        if profile is None or vec is None:
            return None
        vecs = _vecs(profile)
        if vec not in vecs:
            vecs.append(vec)
            profile['embeddings'] = vecs[-MAX_EMBEDDINGS:]
            profile['embedding'] = profile['embeddings'][0]
        profile['updated_at'] = _now()
        if label:
            profile['label'] = str(label)[:64]
        if isinstance(info, dict):
            clean = self._clean_info(info)
            if clean:
                cur = profile.get('info') if isinstance(profile.get('info'), dict) else {}
                cur.update(clean)
                profile['info'] = cur
        self.save()
        return pid

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

    def enroll(self, embedding, label=None, source='wake', info=None):
        """Add a profile, or add another sample of the same voice at DEDUP_SCORE.

        One utterance scores 0.35–0.95 against another of the very same person
        with 3D-Speaker; a single vector per profile made repeated enrollments
        spawn duplicates and made live verification miss.  Keep several samples
        and match against the closest one.
        """
        vec = _vector(embedding)
        if vec is None:
            return None
        clean_info = self._clean_info(info) if isinstance(info, dict) else {}
        pid, score = self._best(vec)
        if pid and score >= DEDUP_SCORE:
            profile = next(p for p in self.profiles if p['id'] == pid)
            vecs = _vecs(profile)
            if vec not in vecs:
                vecs.append(vec)
                profile['embeddings'] = vecs[-MAX_EMBEDDINGS:]
                profile['embedding'] = profile['embeddings'][0]
            profile['updated_at'] = _now()
            if label:
                profile['label'] = str(label)[:64]
            if clean_info:
                cur = profile.get('info') if isinstance(profile.get('info'), dict) else {}
                cur.update(clean_info)
                profile['info'] = cur
            self.save()
            return pid
        pid = self._next_id()
        stamp = _now()
        profile = {
            'id': pid,
            'label': str(label or f'Голос {len(self.profiles) + 1}')[:64],
            'embedding': vec,
            'embeddings': [vec],
            'created_at': stamp,
            'updated_at': stamp,
            'source': source if source in SOURCES else 'manual',
        }
        if clean_info:
            profile['info'] = clean_info
        self.profiles.append(profile)
        self.save()
        return pid

    # ---- management
    def list(self):
        """Public list: labels and ids, never embeddings."""
        out = []
        for p in self.profiles:
            row = {'id': p['id'], 'label': p['label'], 'source': p['source'],
                   'created_at': p['created_at'], 'updated_at': p['updated_at']}
            info = p.get('info')
            if isinstance(info, dict) and info:
                row['info'] = dict(info)
            out.append(row)
        return out

    def profile(self, pid):
        for p in self.profiles:
            if p['id'] == pid:
                out = {'id': p['id'], 'label': p['label'], 'source': p['source'],
                       'created_at': p['created_at'], 'updated_at': p['updated_at']}
                info = p.get('info')
                if isinstance(info, dict) and info:
                    out['info'] = dict(info)
                return out
        return None

    def update_info(self, pid, info, label=None):
        if not isinstance(info, dict):
            return False
        clean_info = self._clean_info(info)
        if not clean_info and not label:
            return False
        for profile in self.profiles:
            if profile['id'] == pid:
                if clean_info:
                    cur = profile.get('info') if isinstance(profile.get('info'), dict) else {}
                    cur.update(clean_info)
                    profile['info'] = cur
                if label:
                    profile['label'] = str(label)[:64]
                profile['updated_at'] = _now()
                return self.save()
        return False

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

    def merge(self, ids, label=None):
        """Fold several profiles into one, keeping all of their voice samples.

        Used when wake auto-enrollment and a guided interview made several
        profiles of the same person; each one holds a different reading of the
        voice and throwing any of them away loses a match.
        """
        ids = {str(x) for x in (ids or [])}
        rows = [p for p in self.profiles if p['id'] in ids]
        if len(rows) < 2:
            return None
        keep = rows[0]
        vecs = []
        info = {}
        for p in rows:
            for v in _vecs(p):
                if v not in vecs:
                    vecs.append(v)
            info.update(p.get('info') or {})
        keep['embeddings'] = vecs[:MAX_EMBEDDINGS]
        keep['embedding'] = keep['embeddings'][0]
        if label:
            keep['label'] = str(label)[:64]
        if info:
            keep['info'] = info
        keep['updated_at'] = _now()
        keep_id = keep['id']
        self.profiles = [p for p in self.profiles if p['id'] == keep_id or p['id'] not in ids]
        self.save()
        return keep_id

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


def enroll(embedding, label=None, source='wake', info=None):
    """The ears daemon's /speaker/enroll passes profile info here."""
    return store().enroll(embedding, label, source, info=info)


def verify(embedding, threshold=DEFAULT_THRESHOLD, enabled=True):
    return store().verify(embedding, threshold, enabled)


def closest(embedding):
    """(pid, raw score) without a threshold — for the wake near-miss path."""
    return store().closest(embedding)


def add_sample(pid, embedding, label=None, info=None):
    """Add one more reading of an existing voice (no new profile)."""
    return store().add_sample(pid, embedding, label, info)


def list():                              # noqa: A001 - the module API mirrors the store
    return store().list()


def profile(pid):
    """Public metadata for one profile (no embedding), or None."""
    return store().profile(pid)


def update_info(pid, info, label=None):
    """Merge extracted acquaintance fields, optionally renaming the profile."""
    return store().update_info(pid, info, label)


def rename(pid, label):
    return store().rename(pid, label)


def delete(pid):
    return store().delete(pid)


def merge(ids, label=None):
    """Fold several profiles into one (see SpeakerStore.merge)."""
    return store().merge(ids, label)


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
