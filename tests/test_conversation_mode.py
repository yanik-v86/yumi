#!/usr/bin/env python3
"""Conversation mode: window, cancellation and context policy, without GTK.
Run: python3 tests/test_conversation_mode.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yumi.conversation import Conversation, HISTORY_CAP, context_window  # noqa: E402

# ---- open, extend, timeout -------------------------------------------------
conv = Conversation(timeout=10)
assert not conv.active and conv.id == 0
assert conv.begin(100.0, 'voice')
assert conv.active and conv.id == 1 and conv.exchanges == 1
assert conv.snapshot(100.0)['remaining'] == 10.0
assert conv.wait_start(101.0)
assert not conv.due(110.9)
assert conv.due(111.0)                    # 101 + 10
assert conv.expire(111.0, 'silence') and not conv.active
assert conv.id == 2 and conv.reason == 'silence'
assert not conv.expire(111.0)             # already closed

# a new phrase in the window extends it and does not rotate the id
conv = Conversation(timeout=10)
conv.begin(100.0, 'voice')
first_id = conv.id
conv.wait_start(101.0)
assert conv.extend(105.0, 'voice') and conv.id == first_id
assert conv.exchanges == 2 and conv.last_at == 105.0
assert conv.until == 115.0

# a long answer must not expire the dialogue before the ears open
conv = Conversation(timeout=5)
conv.begin(100.0, 'voice')
conv.wait_start(100.0)
conv.extend(105.0)                 # a follow-up phrase arrived
conv.hold(120.0)                   # her answer is still being spoken
assert not conv.due(124.9)
assert conv.due(125.0)             # 120 + 5 from the last talk tick
assert conv.wait_start(125.0)
assert not conv.due(129.9)

# ---- stale callbacks cannot reopen a closed window ------------------------
conv = Conversation(timeout=10)
conv.begin(100.0)
cid = conv.id
conv.close('stop')
assert conv.stale(cid)
assert not conv.wait_start(200.0) and not conv.extend(200.0)
conv.begin(300.0, 'panel')
new_id = conv.id
assert not conv.stale(new_id) and new_id != cid

# a timeout changes the id too, so an in-flight listen is discarded
conv = Conversation(timeout=5)
conv.begin(100.0)
conv.wait_start(100.0)
cid = conv.id
conv.expire(106.0)
assert conv.stale(cid)

# ---- context policy: cold gap, active window, ordinary chat --------------
base, active, gap = 10, 20, 15 * 60
limit, reset = context_window(1000, 1000, True, base, active, gap)
assert (limit, reset) == (active, False)       # recent + active: bigger window

limit, reset = context_window(1000, 1000, False, base, active, gap)
assert (limit, reset) == (base, False)         # ordinary, cold but not stale

limit, reset = context_window(1000, 1000 - gap - 1, True, base, active, gap)
assert reset is True and limit == base         # big gap: caller drops old turns

# no last exchange yet: safe normal start, no reset
assert context_window(1000, 0, False, base, active, gap) == (base, False)

# hard cap: settings cannot inflate the prompt beyond HISTORY_CAP
limit, _ = context_window(1, 1, True, 4, 999, gap)
assert limit == HISTORY_CAP

# absurd settings still produce a usable window
limit, _ = context_window(1, 1, True, 0, 0, 0)
assert 2 <= limit <= HISTORY_CAP

print('test_conversation_mode: ok')
