"""The follow-up window after her answer: pure logic, no GTK, no threads.

Conversation mode lets you keep talking after the wake word opened the door.
This module only tracks *when* the door is open and *how much* of the voice
chat history belongs with the next question.  All times are monotonic
(``brain.now``), so a laptop suspend cannot stretch a window by accident.
The GTK side drives these objects and publishes them through ``voice_state``
and ``/api/status``; nothing here imports the UI.
"""
from __future__ import annotations


class Conversation:
    """The 'she answered, now waiting for your next phrase' window.

    ``id`` is bumped on every open/close.  A worker that listened on behalf of
    an older window compares its saved id before touching the brain again, so
    a late answer cannot reopen a conversation you already stopped.
    """

    def __init__(self, timeout=10.0):
        self.timeout = max(1.0, float(timeout or 10.0))
        self.active = False
        self.id = 0
        self.source = None          # 'voice' | 'panel' | 'ask'
        self.since = 0.0            # when the conversation opened
        self.until = 0.0            # deadline of the current follow-up window
        self.last_at = 0.0          # last successful exchange
        self.last_wait = 0.0        # when the current follow-up listen began
        self.exchanges = 0
        self.reason = ''            # why it was closed, for the panel
        self.waiting_answer = False  # a phrase was delivered; do not listen again yet
        # who is speaking inside this window.  These are profile ids, never
        # embeddings, and they live only until close()/timeout.
        self.participants = set()
        self.last_speaker = None
        self.last_route = ''
        self.join_events = 0

    def begin(self, now, source=None, timeout=None):
        """open a conversation (bump id), or refresh an already open one"""
        if timeout is not None:
            self.timeout = max(1.0, float(timeout or self.timeout))
        if self.active:
            return self.extend(now, source)
        self.id += 1
        self.active = True
        self.source = source
        self.since = float(now)
        self.last_at = float(now)
        self.until = float(now) + self.timeout
        self.last_wait = 0.0
        self.exchanges = 1
        self.reason = ''
        self.waiting_answer = False
        self.participants.clear()
        self.last_speaker = None
        self.last_route = ''
        self.join_events = 0
        return True

    def add_participant(self, pid):
        """a voice joins the current dialogue; True only the first time."""
        if not pid or pid in self.participants:
            return False
        self.participants.add(str(pid))
        self.last_speaker = str(pid)
        self.join_events += 1
        return True

    def remove_participant(self, pid):
        if pid not in self.participants:
            return False
        self.participants.remove(pid)
        if self.last_speaker == pid:
            self.last_speaker = None
        return True

    def participant_seen(self, pid):
        """remember who just spoke; True when that voice is in the dialogue."""
        self.last_speaker = str(pid) if pid else None
        return bool(pid) and str(pid) in self.participants

    def clear_participants(self):
        self.participants.clear()
        self.last_speaker = None

    def extend(self, now, source=None):
        """a new phrase arrived in the window: keep the conversation going"""
        if not self.active:
            return False
        self.last_at = float(now)
        self.until = float(now) + self.timeout
        self.exchanges += 1
        self.waiting_answer = False     # the previous phrase has been answered
        if source:
            self.source = source
        return True

    def wait_start(self, now, timeout=None):
        """the ears actually opened for a follow-up: start the silence timer"""
        if timeout is not None:
            self.timeout = max(1.0, float(timeout or self.timeout))
        if not self.active:
            return False
        self.until = float(now) + self.timeout
        self.last_wait = float(now)
        return True

    def hold(self, now, timeout=None):
        """keep the window open while she is thinking or speaking.

        The silence timer starts only when the ears actually open for a
        follow-up: a long answer must not expire the dialogue before it even
        had a chance to listen for the next phrase.
        """
        if timeout is not None:
            self.timeout = max(1.0, float(timeout or self.timeout))
        if not self.active:
            return False
        self.until = float(now) + self.timeout
        return True

    def due(self, now):
        """the follow-up window ran out (only meaningful once listening began)"""
        return bool(self.active and self.last_wait and now >= self.until)

    def remaining(self, now):
        return max(0.0, self.until - float(now)) if self.active else 0.0

    def stale(self, cid):
        """a callback from an older window must be ignored"""
        return cid != self.id

    def close(self, reason=''):
        """close now; also invalidates any pending follow-up callback"""
        if not self.active:
            return False
        self.active = False
        self.id += 1
        self.until = 0.0
        self.last_wait = 0.0
        self.waiting_answer = False
        self.reason = str(reason or '')[:80]
        self.clear_participants()
        self.last_route = ''
        self.join_events = 0
        return True

    def expire(self, now, reason='timeout'):
        if self.due(now):
            return self.close(reason)
        return False

    def snapshot(self, now=None):
        """a copy safe to publish on /api/status"""
        # Without a clock, report the full window rather than a bogus monotonic
        # timestamp; the live panel always passes ``brain.now``.
        if now is None:
            now = self.last_wait if self.last_wait else (self.until - self.timeout)
        return {
            'active': bool(self.active),
            'source': self.source,
            'since': round(self.since, 2),
            'until': round(self.until, 2),
            'remaining': round(self.remaining(now), 2),
            'last_at': round(self.last_at, 2),
            'exchanges': self.exchanges,
            'timeout': round(self.timeout, 2),
            'waiting_answer': bool(self.waiting_answer),
            'reason': self.reason,
            'id': self.id,
            'participants': sorted(self.participants),
            'last_speaker': self.last_speaker,
            'last_route': self.last_route,
            'join_events': self.join_events,
        }


# Keep a hard ceiling so an enthusiastic dialogue cannot inflate the prompt
# for ever, whatever the settings say.
HISTORY_CAP = 30


def context_window(now, last_at, active, base_n, active_n, gap_reset_s=900.0):
    """How many voice-chat messages to carry into the next question.

    Returns ``(limit, reset)``.  A long silence means a *new* dialogue: reset
    tells the caller to drop the old turns before adding the fresh question.
    An active conversation may borrow a bigger window; a cold one keeps the
    ordinary size.  Both numbers are capped by ``HISTORY_CAP``.
    """
    base_n = max(2, min(int(base_n or 10), HISTORY_CAP))
    active_n = max(base_n, min(int(active_n or base_n), HISTORY_CAP))
    gap = float(now) - float(last_at) if last_at else 0.0
    if gap > max(60.0, float(gap_reset_s or 900.0)):
        return base_n, True
    if active:
        return active_n, False
    return base_n, False
