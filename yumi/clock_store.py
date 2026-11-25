"""Persistence for Yumi's internal clock: one small JSON file, atomic writes.

Pure module: no GTK, no HTTP, no Brain. The clock passes jobs in; this module
only validates them, keeps the revision and writes STATE_DIR/clock-jobs.json.
"""
import copy
import json
import math
import os
import re

from .config import STATE_DIR

FORMAT_VERSION = 1
JOB_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')
DEFAULT_PATH = STATE_DIR / 'clock-jobs.json'


class BadJob(ValueError):
    """A restored job does not match the format and is skipped."""


def valid_job(job):
    """Whether a job dict is safe to restore or save (no mutation of `job`)."""
    if not isinstance(job, dict):
        return False
    if not isinstance(job.get('id'), str) or not JOB_ID_RE.fullmatch(job['id']):
        return False
    if not isinstance(job.get('kind'), str) or not JOB_ID_RE.fullmatch(job['kind']):
        return False
    for key in ('due_at', 'every_s', 'defer_until', 'last_fired_at'):
        val = job.get(key)
        if not isinstance(val, (int, float)) or isinstance(val, bool) or not math.isfinite(val):
            return False
    if job['due_at'] <= 0 or job['every_s'] < 0 or job['defer_until'] < 0 or job['last_fired_at'] < 0:
        return False
    if 0 < job['every_s'] < 30:                 # a repeat faster than 30 s is a typo
        return False
    if not isinstance(job.get('enabled'), bool) or not isinstance(job.get('persist'), bool):
        return False
    if not isinstance(job.get('created_at'), str):
        return False
    return True


def normalize_job(job, *, default_kind='task'):
    """A validated job with every field present; a deep copy of its payload."""
    if not valid_job(job):
        raise BadJob('invalid clock job')
    try:
        payload = copy.deepcopy(job.get('payload'))
    except Exception:
        payload = None
    return {
        'id': job['id'],
        'kind': job.get('kind') or default_kind,
        'owner': str(job.get('owner') or '')[:64],
        'due_at': float(job['due_at']),
        'every_s': float(job['every_s']),
        'defer_until': float(job['defer_until']),
        'payload': payload,
        'enabled': bool(job['enabled']),
        'persist': bool(job['persist']),
        'last_fired_at': float(job['last_fired_at']),
        'created_at': str(job['created_at']),
    }


class ClockStore:
    """Loads and saves the persistent jobs of a Clock.

    `load()` returns an empty list for a missing or broken file and never
    rewrites it; `save()` increments `revision` only after a successful write.
    """

    def __init__(self, path=None):
        self.path = path if path is not None else DEFAULT_PATH
        self.revision = 0

    def _read(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError, UnicodeError):
            return None
        if not isinstance(data, dict) or data.get('version') != FORMAT_VERSION:
            return None
        jobs = data.get('jobs')
        if not isinstance(jobs, list):
            return None
        rev = data.get('revision', 0)
        if not isinstance(rev, int) or isinstance(rev, bool) or rev < 0:
            rev = 0
        return {'revision': rev, 'jobs': jobs}

    def load(self):
        """Restore the jobs from disk; a broken file is left untouched."""
        self.revision = 0
        data = self._read()
        if data is None:
            return []
        out = []
        seen = set()
        for raw in data['jobs']:
            if not valid_job(raw) or raw['id'] in seen:
                continue
            seen.add(raw['id'])
            job = normalize_job(raw)
            job['persist'] = True           # only persistent jobs are stored
            out.append(job)
        self.revision = data['revision']
        return out

    def save(self, jobs):
        """Atomically write the persistent jobs; return the current revision."""
        rows = []
        seen = set()
        for raw in jobs or ():
            if not valid_job(raw) or not raw['persist'] or raw['id'] in seen:
                continue
            seen.add(raw['id'])
            row = normalize_job(raw)
            try:                            # a non-JSON payload cannot be stored
                json.dumps(row, ensure_ascii=False)
            except (TypeError, ValueError):
                continue
            rows.append(row)
        rows.sort(key=lambda row: row['id'])

        if not self.revision:
            data = self._read()             # keep a revision written by another Clock
            if data is not None:
                self.revision = data['revision']
        revision = self.revision + 1
        text = json.dumps({'version': FORMAT_VERSION, 'revision': revision, 'jobs': rows},
                          indent=1, ensure_ascii=False)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(text, encoding='utf-8')
            os.replace(tmp, self.path)
        except OSError:
            return self.revision             # failed write: the revision did not change
        self.revision = revision
        return revision
