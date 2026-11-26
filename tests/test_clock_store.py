#!/usr/bin/env python3
"""Clock persistence: atomic save/load, persist flag, broken files, revision.
Run: python3 tests/test_clock_store.py"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yumi.clock import Clock  # noqa: E402
from yumi.clock_store import ClockStore  # noqa: E402


def job(jid, **kw):
    row = {
        'id': jid, 'kind': 'task', 'owner': 'health', 'due_at': 1010.0,
        'every_s': 60.0, 'defer_until': 0.0, 'payload': {'cup': 1},
        'enabled': True, 'persist': True, 'last_fired_at': 0.0,
        'created_at': '2026-11-25T12:00:00Z',
    }
    row.update(kw)
    return row


def test_roundtrip_and_revision():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'clock-jobs.json'
        store = ClockStore(path)
        assert store.load() == [] and store.revision == 0
        assert not path.exists()              # a missing file is not created on load

        assert store.save([job('water'), job('eyes', persist=False)]) == 1
        assert path.exists() and not path.with_suffix('.tmp').exists()
        raw = json.loads(path.read_text())
        assert raw['version'] == 1 and raw['revision'] == 1
        assert [j['id'] for j in raw['jobs']] == ['water']   # no persist flag in the file

        store.revision = 0                    # emulate a fresh process
        restored = store.load()
        assert store.revision == 1
        assert len(restored) == 1 and restored[0]['id'] == 'water'
        assert restored[0]['persist'] is True and restored[0]['payload'] == {'cup': 1}

        restored[0]['due_at'] = 2000.0
        assert store.save(restored) == 2 and store.revision == 2
        assert json.loads(path.read_text())['revision'] == 2
        assert ClockStore(path).load()[0]['due_at'] == 2000.0


def test_broken_file_does_not_break_start():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'clock-jobs.json'
        path.write_text('{not json')
        before = path.read_text()
        store = ClockStore(path)
        assert store.load() == [] and store.revision == 0
        assert path.read_text() == before      # a broken file is never overwritten

        clock = Clock(store=store, now_wall=lambda: 1000.0)
        assert clock.snapshot()['jobs_active'] == 0
        clock.schedule('task', in_s=5, persist=True)
        assert json.loads(path.read_text())['revision'] == 1

        path.write_text(json.dumps({'version': 9, 'revision': 3, 'jobs': []}))
        assert ClockStore(path).load() == []   # unknown format is ignored too
        path.write_text(json.dumps({'version': 1, 'revision': 1, 'jobs': [
            job('ok'), job('bad id'), {'id': 'x'}, job('ok'),
        ]}))
        loaded = ClockStore(path).load()
        assert [j['id'] for j in loaded] == ['ok']


def test_clock_persists_mutations():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'clock-jobs.json'
        clock = Clock(store=ClockStore(path), now_wall=lambda: 1000.0)
        clock.register('task', lambda j: None)

        keep = clock.schedule('task', in_s=10, every_s=60, persist=True, payload={'a': 1})
        forget = clock.schedule('task', in_s=20)   # not in the file
        assert [j['id'] for j in ClockStore(path).load()] == [keep]

        clock.defer(keep, 30)
        assert ClockStore(path).load()[0]['defer_until'] == 1030.0
        clock.skip(keep)
        assert ClockStore(path).load()[0]['due_at'] == 1070.0
        clock.pause(keep)
        assert ClockStore(path).load()[0]['enabled'] is False
        clock.resume(keep)
        assert ClockStore(path).load()[0]['enabled'] is True

        clock.cancel(forget)
        assert [j['id'] for j in ClockStore(path).load()] == [keep]
        clock.cancel(keep)
        assert ClockStore(path).load() == []

        clock.schedule('task', in_s=10, persist=True, id='fire')
        clock.tick(1010.0, 1.0)
        assert ClockStore(path).load() == []    # one-shot fired: removed from the file

        repeat = clock.schedule('task', in_s=10, every_s=60, persist=True, id='repeat')
        clock.tick(1010.0, 2.0)
        assert ClockStore(path).load()[0]['due_at'] == clock.jobs[repeat]['due_at']


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
    print('test_clock_store: ok')
