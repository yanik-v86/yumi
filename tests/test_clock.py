#!/usr/bin/env python3
"""Yumi's internal clock: tick, idempotency, repeats, defer/skip, missed jobs.
Run: python3 tests/test_clock.py"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yumi.clock import Clock, InvalidJob, JobExists, MISSED_WINDOW_S  # noqa: E402
from yumi.clock_store import ClockStore  # noqa: E402


def test_schedule_cancel_and_collision():
    c = Clock(now_wall=lambda: 1000.0)
    jid = c.schedule('water', in_s=10, owner='health', payload={'cup': 1})
    assert c.jobs[jid]['due_at'] == 1010.0
    assert c.jobs[jid]['every_s'] == 0 and c.jobs[jid]['owner'] == 'health'
    assert c.jobs[jid]['payload'] == {'cup': 1}
    assert c.due(1009.0) == [] and [j['id'] for j in c.due(1010.0)] == [jid]
    try:
        c.schedule('water', due_at=1010.0, id=jid)
    except JobExists:
        pass
    else:
        raise AssertionError('a duplicate id must be rejected')
    for bad in (lambda: c.schedule('x', in_s=1, due_at=2),
                lambda: c.schedule('x'),
                lambda: c.schedule('x', in_s=-1),
                lambda: c.schedule('x', in_s=1, every_s=5),
                lambda: c.schedule('bad id', in_s=1),
                lambda: c.schedule('x', in_s=1, id='bad id')):
        try:
            bad()
        except InvalidJob:
            pass
        else:
            raise AssertionError('bad schedule parameters must be rejected')
    assert c.cancel(jid) is True and c.cancel(jid) is False
    assert jid not in c.jobs


def test_one_shot_fires_once():
    c = Clock(now_wall=lambda: 1000.0)
    seen = []
    c.register('task', lambda job: seen.append(job['id']))
    jid = c.schedule('task', in_s=2)
    assert c.tick(1001.0, 1.0) == []
    assert seen == []
    events = c.tick(1002.0, 2.0)
    assert [e['status'] for e in events] == ['fired']
    assert events[0]['id'] == jid and events[0]['due_at'] == 1002.0
    assert seen == [jid]
    c.tick(1002.0, 3.0)                 # same wall time: no second call
    c.tick(1003.0, 4.0)                 # one-shot jobs are gone after firing
    assert seen == [jid] and jid not in c.jobs
    snap = c.snapshot()
    assert snap['enabled'] is True and snap['jobs_active'] == 0
    assert snap['last_fired_at'] == 1002.0 and snap['last_error'] is None


def test_repeat_defer_skip_and_pause():
    c = Clock(now_wall=lambda: 1000.0)
    seen = []
    c.register('tick', lambda job: seen.append(job['id']))
    jid = c.schedule('tick', in_s=10, every_s=60)

    assert len(c.tick(1010.0, 1.0)) == 1
    assert len(c.tick(1010.0, 2.0)) == 0  # idempotent at the same wall time
    assert len(c.tick(1069.0, 3.0)) == 0
    assert len(c.tick(1070.0, 4.0)) == 1  # next due is from the previous due, not the tick
    assert c.jobs[jid]['due_at'] == 1130.0
    assert seen == [jid, jid]

    assert c.defer(jid, 30) is True
    assert c.jobs[jid]['due_at'] == 1130.0 and c.jobs[jid]['defer_until'] == 1030.0
    assert c.due(1129.0) == []
    assert len(c.due(1130.0)) == 1        # defer_until is already behind due_at
    assert c.defer('nope', 1) is False

    c.schedule('tick', in_s=100, every_s=60, id='other')
    c.skip('other')
    assert c.jobs['other']['due_at'] == 1160.0
    assert c.skip('one') is False
    one = c.schedule('tick', in_s=100, id='one')
    assert c.skip(one) is True and one not in c.jobs  # no repeat left to keep

    assert c.pause(jid) is True
    assert jid not in [j['id'] for j in c.due(2000.0)]
    assert c.resume(jid) is True and jid in [j['id'] for j in c.due(2000.0)]
    assert c.pause('nope') is False and c.resume('nope') is False


def test_defer_priority():
    c = Clock(now_wall=lambda: 1000.0)
    c.register('task', lambda job: None)
    jid = c.schedule('task', in_s=5)
    c.defer(jid, 40)
    assert c.due(1005.0) == [] and c.due(1039.0) == []
    assert [j['id'] for j in c.due(1040.0)] == [jid]
    events = c.tick(1040.0, 1.0)
    assert events[0]['status'] == 'fired' and events[0]['due_at'] == 1040.0


def test_missed_window():
    c = Clock(now_wall=lambda: 1000.0)
    seen = []
    c.register('task', lambda job: seen.append(job['id']))
    jid = c.schedule('task', in_s=10)
    late = 1000.0 + 10 + MISSED_WINDOW_S + 1
    events = c.tick(late, 1.0)
    assert [e['status'] for e in events] == ['missed']
    assert seen == [] and jid not in c.jobs

    again = Clock(now_wall=lambda: 1000.0, missed_window_s=60)
    again.register('task', lambda job: seen.append('repeat'))
    rjd = again.schedule('task', in_s=10, every_s=60)
    events = again.tick(1200.0, 1.0)     # 190 s late: missed, not fired in the past
    assert [e['status'] for e in events] == ['missed']
    assert seen == [] and again.jobs[rjd]['due_at'] > 1200.0


def test_handler_error_is_isolated():
    c = Clock(now_wall=lambda: 1000.0)
    errors = []
    c.on_error(lambda job, exc: errors.append((job['id'], str(exc))))
    c.register('boom', lambda job: 1 / 0)
    c.register('fine', lambda job: None)
    c.schedule('boom', in_s=1)
    c.schedule('fine', in_s=1)
    events = c.tick(1001.0, 1.0)
    assert sorted(e['status'] for e in events) == ['error', 'fired']
    assert len(errors) == 1 and errors[0][1] == 'division by zero'
    assert 'boom' in c.last_error
    c.tick(1002.0, 2.0)                  # the error did not leave a stuck job
    assert c.snapshot()['jobs_active'] == 0


def test_restore_and_snapshot_are_safe():
    c = Clock(now_wall=lambda: 1000.0)
    c.restore([
        {'id': 'kept', 'kind': 'task', 'owner': 'o', 'due_at': 1010.0, 'every_s': 60.0,
         'defer_until': 0.0, 'payload': {'x': 1}, 'enabled': True, 'persist': True,
         'last_fired_at': 0.0, 'created_at': '2026-11-25T12:00:00Z'},
        {'id': 'bad id', 'kind': 'task', 'due_at': 1010.0},
    ])
    snap = c.snapshot()
    assert snap['jobs_active'] == 1 and snap['jobs_persisted'] == 1
    assert snap['next_due_at'] == 1010.0 and snap['now_wall'] == 1000.0
    assert 'payload' not in snap
    c.jobs['kept']['payload']['x'] = 99
    assert snap['jobs_active'] == 1       # the snapshot did not alias the jobs


def test_brain_update_ticks_the_clock():
    """The clock is driven by Brain.update(), with no GTK and no extra timer."""
    import gi                                      # noqa: F401
    gi.require_version('GdkPixbuf', '2.0')
    from yumi import config
    from yumi.brain import Brain
    from yumi.phrases import Speech
    from yumi.sprites import Meta

    s = dict(config.DEFAULT_SETTINGS)
    b = Brain(Meta(config.SPRITES, None), s, {'intro_done': True}, Speech(s),
              lambda *_a: (10, 10))
    b.clock = Clock(now_wall=lambda: 1000.0)       # no file writes in the test
    seen = []
    b.clock.register('task', lambda job: seen.append(job['id']))
    jid = b.clock.schedule('task', in_s=2)

    fake = [1000.0]
    original = time.time
    time.time = lambda: fake[0]
    try:
        b.update(1.0)
        assert seen == []
        fake[0] = 1002.0
        b.update(2.0)
    finally:
        time.time = original
    assert seen == [jid] and jid not in b.clock.jobs

    b.open_menu('main')
    row = next(r for r in b.menu['rows'] if r[0] == 'clock_status')
    assert row[2].startswith('Clock:')
    b.do('clock_status', None)
    assert b.bubble and b.bubble['text'].startswith('Clock:')


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
    print('test_clock: ok')
