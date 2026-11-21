#!/usr/bin/env python3
"""One microphone state, shared by the app and the panel.
Run: python3 tests/test_voice_state.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yumi.voice_state import STATES, VoiceState  # noqa: E402

vs = VoiceState()
assert vs.snapshot()['state'] == 'off' and vs.generation == 0

assert vs.wake_on()
first = vs.snapshot()
assert first['state'] == 'watching' and first['owner'] == 'wake'
assert first['wake_enabled'] is True and first['generation'] == 1
assert not vs.wake_on()                    # a pure no-op is not a transition
assert vs.generation == 1

assert vs.listening('wake', 'listening for the wake word')
assert vs.candidate()
assert vs.held()
held = vs.snapshot()
assert held['state'] == 'held_for_answer' and held['generation'] == 4
assert len(held['transitions']) == 4
assert held['transitions'][-1]['owner'] == 'wake'

assert vs.wake_paused('paused from the panel')
assert vs.snapshot()['state'] == 'paused'
assert vs.snapshot()['owner'] == 'panel_test'
assert vs.snapshot()['wake_enabled'] is True   # pause does not forget the wake setting
assert vs.wake_resumed()
assert vs.snapshot()['wake_enabled'] is True
assert vs.wake_off()
assert vs.snapshot()['wake_enabled'] is False

try:
    vs.set('dancing')
    raise AssertionError('an unknown state was accepted')
except ValueError:
    pass

for state in STATES:
    assert isinstance(state, str) and state
print('test_voice_state: ok')
