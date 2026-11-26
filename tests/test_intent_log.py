#!/usr/bin/env python3
"""The private action journal: levels, filters, redaction, previews, rotation.
Run: python3 tests/test_intent_log.py"""
import json
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yumi import config, intent_log  # noqa: E402

_tmp = tempfile.TemporaryDirectory()
_original = config.STATE_DIR
config.STATE_DIR = Path(_tmp.name)


def settings(**overrides):
    out = dict(config.DEFAULT_SETTINGS)
    out.update(overrides)
    return out


# off is the default: nothing is created at all
assert intent_log.emit(settings(), 'start', intent_id='lights_on') is None
assert not intent_log.log_path().exists()

# an unknown level is treated as off
assert intent_log.emit(settings(intents_log_level='loud'), 'error') is None
assert not intent_log.log_path().exists()

# error: only errors pass, a start on the same run does not
s = settings(intents_log_level='error')
assert intent_log.emit(s, 'start', run_id='low', intent_id='lights_on') is None
rec = intent_log.emit(s, 'error', run_id='low', intent_id='lights_on',
                      error='timeout', status='fail', duration_ms=41)
assert rec and rec['stage'] == 'error' and rec['severity'] == 'error'
assert [r['run_id'] for r in intent_log.read()] == ['low']

# command/URL text is reduced to a hash; details are flat and denylisted
intent_log.clear()
s = settings(intents_log_level='trace')
intent_log.emit(s, 'start', run_id='deadbeef', source='panel',
                intent_id='lights_on', action_value='lights on --token=xyz',
                url='https://example.org/?key=xyz', heard_text='включи свет',
                stdout_preview='answer with secrets', stdout_len=100,
                details={'value': 'drop me', 'text': 'drop me', 'token': 'drop me',
                         'score': 0.8, 'decision': 'allowed',
                         'nested': {'value': 'drop me'}})
rec = intent_log.read()[0]
assert rec['run_id'] == 'deadbeef' and rec['source'] == 'panel'
assert rec['action_sha'].startswith('sha256:') and rec['action_len'] > 0
assert rec['heard_text'] is None and rec['stdout_preview'] is None
assert rec['stdout_len'] == 100
assert rec['details'] == {'score': 0.8, 'decision': 'allowed'}
dump = json.dumps(rec, ensure_ascii=False)
assert 'lights on' not in dump and 'example.org' not in dump
assert 'drop me' not in dump and 'включи свет' not in dump

# opt-in previews are separate fields and clipped to max_chars
s = settings(intents_log_level='trace', intents_log_include_text=True,
             intents_log_max_chars=100)
heard = 'ф' * 130
stdout = 'о' * 130
intent_log.emit(s, 'heard', run_id='abc12345',
                heard_text=heard, stdout_preview=stdout)
rec = intent_log.read()[0]
assert rec['heard_text'].endswith('…') and len(rec['heard_text']) == 100
assert rec['stdout_preview'].endswith('…') and len(rec['stdout_preview']) == 100
assert rec['heard_text'] != rec['stdout_preview']

# freshest first, with both filters applied
intent_log.clear()
for i, stage in enumerate(('heard', 'match', 'decision', 'result', 'match')):
    intent_log.emit(settings(intents_log_level='trace'), stage,
                    run_id=f'r{i}', intent_id='lights_on' if i % 2 == 0 else 'other')
assert [r['run_id'] for r in intent_log.read()] == ['r4', 'r3', 'r2', 'r1', 'r0']
assert len(intent_log.read(limit=2)) == 2
assert len(intent_log.read(intent='lights_on')) == 3
assert [r['run_id'] for r in intent_log.read(stage='match')] == ['r4', 'r1']

# rotation keeps the newest lines and leaves no temp file
intent_log.clear()
s = settings(intents_log_level='error', intents_log_max_lines=100)
for i in range(105):
    intent_log.emit(s, 'error', run_id=f'line{i}')
records = intent_log.read()
assert len(records) == 100
assert records[0]['run_id'] == 'line104' and records[-1]['run_id'] == 'line5'
assert not intent_log.log_path().with_name(intent_log.log_path().name + '.tmp').exists()
assert intent_log.line_count() == 100
info = intent_log.info(s)
assert info['level'] == 'error' and info['lines'] == 100 and info['errors'] == 100
assert intent_log.info()['level'] == 'off'

# the file is private
assert stat.S_IMODE(intent_log.log_path().stat().st_mode) == 0o600

intent_log.clear()
assert intent_log.read() == [] and intent_log.line_count() == 0
config.STATE_DIR = _original
_tmp.cleanup()

print('tests/test_intent_log.py: ok')
