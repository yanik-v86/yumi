#!/usr/bin/env bash
# No GTK: schedule in_s=2, tick twice, defer, cancel; one source of tick only.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from yumi.clock import Clock

now = [1000.0]
clock = Clock(now_wall=lambda: now[0])
seen = []
clock.register('task', lambda job: seen.append(job['id']))
jid = clock.schedule('task', in_s=2)
assert clock.tick(1001.0, 1.0) == [] and seen == []
assert [e['status'] for e in clock.tick(1002.0, 2.0)] == ['fired']
assert seen == [jid]
clock.tick(1002.0, 3.0)
assert seen == [jid], 'one-shot job fired twice'

later = clock.schedule('task', in_s=30)
clock.defer(later, 5)
assert clock.jobs[later]['defer_until'] == 1005.0
assert clock.cancel(later) is True and later not in clock.jobs
print('smoke_clock: ok')
PY

# The clock itself must never create a GLib timer; Brain.update owns the only tick.
! grep -q 'GLib' yumi/clock.py yumi/clock_store.py
grep -q 'clock.tick(time.time(), now)' yumi/brain.py
