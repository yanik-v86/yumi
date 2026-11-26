"""Yumi's internal clock: one tick per frame, jobs and handler registration.

A clean service: no GTK, no HTTP, no import of Brain and no business rules.
Consumers register a handler for their ``kind`` and schedule jobs; the clock
calls the handler when the job is due. Both times are passed to ``tick()``:
``now_wall`` (epoch) decides *when*, ``now_monotonic`` is only diagnostics.
"""
import copy
import time
import uuid

from . import clock_store

MISSED_WINDOW_S = 900          # a job later than 15 min is missed, never fired in the past
JOB_ID_RE = clock_store.JOB_ID_RE
MIN_REPEAT_S = 30


class JobExists(ValueError):
    """A job with this id is already scheduled."""


class InvalidJob(ValueError):
    """The schedule parameters do not describe a valid job."""


def _copy(value):
    try:
        return copy.deepcopy(value)
    except Exception:
        return value


class Clock:
    """A tiny scheduler driven by the application frame.

    `now_wall` is an optional callable returning epoch seconds; it is used for
    ``in_s`` and ``created_at`` so tests can work with a fake time. The real
    wall time for each tick is passed to ``tick()`` by Brain.
    """

    def __init__(self, *, store=None, missed_window_s=MISSED_WINDOW_S, now_wall=None):
        self.store = store
        self.missed_window_s = max(0.0, float(missed_window_s))
        self._time = now_wall or (lambda: time.time())
        self.jobs = {}                 # id -> job dict
        self.handlers = {}             # kind -> callable(job)
        self._error_cb = None
        self.last_error = None
        self.last_fired_at = 0.0
        if store is not None:
            try:
                self.restore(store.load())
            except (OSError, ValueError) as exc:
                self._fail({'id': '', 'kind': 'clock_store'}, exc)

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _name(value, what):
        if not isinstance(value, str) or not JOB_ID_RE.fullmatch(value):
            raise InvalidJob(f'bad {what}: expected 1..64 of [a-zA-Z0-9_-]')
        return value

    def register(self, kind, handler):
        """One handler per kind; registering again replaces the old one."""
        kind = self._name(kind, 'kind')
        if not callable(handler):
            raise InvalidJob('handler must be callable')
        self.handlers[kind] = handler

    def on_error(self, callback):
        """callback(job, exc) for exceptions raised by a consumer's handler."""
        if callback is not None and not callable(callback):
            raise InvalidJob('on_error must be callable')
        self._error_cb = callback

    def restore(self, jobs):
        """Replace the active jobs with validated ones (used at startup)."""
        self.jobs.clear()
        for raw in jobs or ():
            try:
                job = clock_store.normalize_job(raw)
            except (clock_store.BadJob, TypeError, ValueError):
                continue
            if job['id'] in self.jobs:
                continue
            self.jobs[job['id']] = job

    # ------------------------------------------------------------------ jobs
    def schedule(self, kind, *, in_s=None, due_at=None, every_s=0, owner='', payload=None,
                 persist=False, id=None):
        """Plan a job and return its id. Exactly one of `in_s` / `due_at` is required."""
        kind = self._name(kind, 'kind')
        if (in_s is None) == (due_at is None):
            raise InvalidJob('give exactly one of in_s and due_at')
        if in_s is not None:
            try:
                delay = float(in_s)
            except (TypeError, ValueError):
                raise InvalidJob('bad in_s') from None
            if delay < 0 or delay != delay or delay == float('inf'):
                raise InvalidJob('in_s must be a finite, non-negative number')
            now = self._time()
            due = now + delay
        else:
            try:
                due = float(due_at)
            except (TypeError, ValueError):
                raise InvalidJob('bad due_at') from None
            if due <= 0 or due != due or due == float('inf'):
                raise InvalidJob('due_at must be a finite epoch timestamp')
        try:
            period = float(every_s or 0)
        except (TypeError, ValueError):
            raise InvalidJob('bad every_s') from None
        if period < 0 or period != period or period == float('inf') or 0 < period < MIN_REPEAT_S:
            raise InvalidJob(f'every_s=0 or >= {MIN_REPEAT_S}')

        job_id = self._name(id, 'id') if id is not None else self._new_id(kind)
        if job_id in self.jobs:
            raise JobExists(job_id)
        self.jobs[job_id] = {
            'id': job_id,
            'kind': kind,
            'owner': str(owner or '')[:64],
            'due_at': due,
            'every_s': period,
            'defer_until': 0.0,
            'payload': _copy(payload),
            'enabled': True,
            'persist': bool(persist),
            'last_fired_at': 0.0,
            'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(self._time())),
        }
        self._persist({'persist': bool(persist)})
        return job_id

    def _new_id(self, kind):
        slug = ''.join(ch if ch.isalnum() or ch in '_-' else '_' for ch in kind)[:40]
        return f'{slug}_{uuid.uuid4().hex[:12]}'

    def cancel(self, job_id):
        job = self.jobs.pop(str(job_id), None)
        if job is None:
            return False
        self._persist(job)
        return True

    def defer(self, job_id, delay_s):
        """Push the next firing to now + delay_s; earlier than `due_at` is ignored."""
        job = self.jobs.get(str(job_id))
        if job is None:
            return False
        try:
            delay = float(delay_s)
        except (TypeError, ValueError):
            raise InvalidJob('bad delay_s') from None
        if delay < 0 or delay != delay or delay == float('inf'):
            raise InvalidJob('delay_s must be a finite, non-negative number')
        job['defer_until'] = self._time() + delay
        self._persist(job)
        return True

    def skip(self, job_id):
        """Skip the nearest firing. A repeat keeps its period; a one-shot is dropped."""
        job = self.jobs.get(str(job_id))
        if job is None:
            return False
        if job['every_s'] > 0:
            job['due_at'] += job['every_s']
            job['defer_until'] = 0.0
            self._persist(job)
            return True
        return self.cancel(job_id)

    def pause(self, job_id):
        job = self.jobs.get(str(job_id))
        if job is None:
            return False
        job['enabled'] = False
        self._persist(job)
        return True

    def resume(self, job_id):
        job = self.jobs.get(str(job_id))
        if job is None:
            return False
        job['enabled'] = True
        self._persist(job)
        return True

    # ------------------------------------------------------------------ tick
    @staticmethod
    def _effective(job):
        return max(job['due_at'], job['defer_until'])

    def due(self, now_wall):
        """Copies of the enabled jobs whose effective time has come."""
        rows = [j for j in self.jobs.values() if j['enabled'] and self._effective(j) <= now_wall]
        rows.sort(key=lambda j: (self._effective(j), j['id']))
        return [_copy(job) for job in rows]

    def tick(self, now_wall, now_monotonic):
        """Fire the due jobs, return diagnostic events and never raise to the frame."""
        events = []
        for job in self.due(now_wall):
            job_id, due = job['id'], self._effective(job)
            missed = now_wall - due > self.missed_window_s
            # mark fired and move the next due *before* calling the handler:
            # a slow handler or a second tick with the same time cannot repeat it
            current = self.jobs.get(job_id)
            if current is None:
                continue
            current['defer_until'] = 0.0
            if current['every_s'] > 0:
                nxt = current['due_at'] + current['every_s']
                while nxt <= now_wall:
                    nxt += current['every_s']
                current['due_at'] = nxt
            else:
                self.jobs.pop(job_id, None)

            event = {'id': job_id, 'kind': job['kind'], 'owner': job['owner'],
                     'status': 'missed' if missed else 'fired',
                     'due_at': due, 'at': now_wall, 'monotonic': now_monotonic}
            if missed:
                events.append(event)
                self._persist(current)
                continue

            events.append(event)
            current['last_fired_at'] = now_wall
            self.last_fired_at = max(self.last_fired_at, now_wall)
            self._persist(current)      # one-shot removal / a new due_at for repeats
            handler = self.handlers.get(job['kind'])
            if handler:
                try:
                    handler(_copy(current))
                except Exception as exc:
                    event['status'] = 'error'
                    event['error'] = self._fail(current, exc)
        return events

    def _fail(self, job, exc):
        text = f"{job.get('kind', '?')}/{job.get('id', '?')}: {exc}"[:300]
        self.last_error = text
        if self._error_cb:
            try:
                self._error_cb(_copy(job), exc)
            except Exception:
                pass                    # a broken diagnostic must not stop the clock
        return text

    def _persist(self, job=None):
        if not self.store or (job is not None and not job.get('persist')):
            return
        jobs = [_copy(job) for job in self.jobs.values() if job['persist']]
        try:
            self.store.save(jobs)
        except Exception as exc:
            self._fail({'id': '', 'kind': 'clock_store'}, exc)

    def snapshot(self):
        """Read-only status for the panel and the GTK menu; no payloads."""
        jobs = list(self.jobs.values())
        due = [self._effective(job) for job in jobs if job['enabled']]
        return {
            'enabled': True,
            'now_wall': self._time(),
            'jobs_active': len(jobs),
            'jobs_persisted': sum(1 for job in jobs if job['persist']),
            'next_due_at': round(min(due), 3) if due else 0.0,
            'last_fired_at': self.last_fired_at,
            'last_error': self.last_error,
        }
