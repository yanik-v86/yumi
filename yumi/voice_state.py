"""One source of truth for who owns Yumi's microphone (no GTK here).

Instead of scattering ``wake_on``, ``b.listening`` and pause flags around, every
change goes through one small tracker with explicit Watching / Listening / Held
states.  The GTK side publishes the same dict to the browser panel on every
status tick, so both front-ends show one state.
"""
from __future__ import annotations

import time

STATES = ('watching', 'candidate', 'listening', 'held_for_answer',
          'awaiting_followup', 'paused', 'muted', 'missing', 'busy', 'off')
OWNERS = ('wake', 'click_listen', 'panel_test', 'conversation', 'tts', None)


class VoiceState:
    """A tiny state machine.  Pure Python: no GTK, no threads, no I/O."""

    def __init__(self):
        self.state = 'off'
        self.owner = None
        self.generation = 0
        self.since = time.time()
        self.reason = ''
        self.wake_enabled = False
        self.transitions = []

    def set(self, state, owner=None, reason='', wake_enabled=None):
        """record a transition; a repeated identical state is still counted if
        the owner or generation changes, but a pure no-op is ignored"""
        if state not in STATES:
            raise ValueError(f'unknown voice state: {state}')
        same = (state == self.state and owner == self.owner and reason == self.reason)
        if same:
            return False
        self.generation += 1
        self.state = state
        self.owner = owner
        self.reason = str(reason or '')[:200]
        if wake_enabled is not None:
            self.wake_enabled = bool(wake_enabled)
        self.since = time.time()
        self.transitions.append({'state': state, 'owner': owner,
                                 'generation': self.generation,
                                 'at': self.since, 'reason': self.reason})
        self.transitions = self.transitions[-20:]
        return True

    def snapshot(self):
        return {'state': self.state, 'owner': self.owner,
                'generation': self.generation, 'since': self.since,
                'reason': self.reason, 'wake_enabled': self.wake_enabled,
                'transitions': list(self.transitions)}

    # ---- the transitions Yumi's code needs ---------------------------------
    def wake_on(self):
        return self.set('watching', 'wake', 'wake loop started', wake_enabled=True)

    def wake_off(self):
        return self.set('off', None, 'wake loop stopped', wake_enabled=False)

    def wake_paused(self, reason='mic held by the panel'):
        return self.set('paused', 'panel_test', reason, wake_enabled=self.wake_enabled)

    def wake_resumed(self):
        return self.set('watching', 'wake', 'wake loop resumed', wake_enabled=True)

    def listening(self, owner='wake', reason=''):
        return self.set('listening', owner, reason)

    def candidate(self, reason='wake word heard'):
        return self.set('candidate', 'wake', reason)

    def held(self, reason='waiting for the answer'):
        return self.set('held_for_answer', 'wake', reason)

    def followup(self, reason='waiting for the next phrase without a wake word'):
        return self.set('awaiting_followup', 'conversation', reason)

    def missing(self, reason='no microphone'):
        return self.set('missing', None, reason)

    def muted(self, reason='her own voice is playing'):
        return self.set('muted', 'tts', reason)

    def busy(self, reason='working'):
        return self.set('busy', None, reason)
