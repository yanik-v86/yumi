#!/usr/bin/env python3
"""The spare wake ear: a name swallowed by noise suppression must still wake.

Run: python3 tests/test_stt_sweep.py

rnnoise keeps the room pleasant but under loud music it can erase a quiet
«Юми»; the raw microphone still has it.  These tests cover the two pure
pieces of that fallback: finding the plain source beside a denoised one and
deciding whether a phrase read from it is really an addressed wish.
"""
import importlib.util
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

spec = importlib.util.spec_from_file_location('stt_daemon', _root / 'yumi' / 'stt_daemon.py')
stt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stt)

from yumi import config  # noqa: E402
from yumi.webpanel import catalog  # noqa: E402

spellings = stt.variants('юми') | stt.hearsay_load('юми')

# ---- the plain source is found beside the denoised one ----
SOURCES = '\n'.join((
    '39\teffect_output.rnnoise\tPipeWire\tfloat32le 2ch 48000Hz\tRUNNING',
    '65\talsa_output.pci-0000_00_1f.3.playback.0.0.monitor\tPipeWire\ts32le\tSUSPENDED',
    '66\talsa_input.pci-0000_00_1f.3.capture.0.0\tPipeWire\ts32le\tRUNNING',
    f'77\t{stt.ECHO_SOURCE}\tPipeWire\ts16le\tRUNNING',
    '88\tbluez_output.04_21_44_C2_EE_25.1.monitor\tPipeWire\ts16le\tRUNNING',
))
_old = stt._pactl_short
try:
    stt._pactl_short = lambda what: SOURCES if what == 'sources' else ''
    assert stt.raw_source('effect_output.rnnoise') == \
        'alsa_input.pci-0000_00_1f.3.capture.0.0'
    assert stt.raw_source('') is None                 # auto: no denoised end
    assert stt.raw_source('alsa_input.pci-0000_00_1f.3.capture.0.0') is None
    assert stt.raw_source('yumi_ec') is None          # the canceller is plain already
    stt._pactl_short = lambda what: ''
    assert stt.raw_source('effect_output.rnnoise') is None   # no second source: no spare ear
finally:
    stt._pactl_short = _old

# ---- an addressed phrase read by the spare ear wakes; a mention does not ----
assert stt.stt_wake_tail('Юмин, включи музыку', spellings) == 'включи музыку'
assert stt.stt_wake_tail('Юми, включи музыку, посмотри запись', spellings) == \
    'включи музыку посмотри запись'
assert stt.stt_wake_tail('юми как дела?', spellings) == 'как дела'
# the name deep inside a sentence is somebody talking *about* her
assert stt.stt_wake_tail('Короче, говорим про юми, она не реагировала', spellings) is None
# no wish in the tail: background talk stays a dream
assert stt.stt_wake_tail('Юми, просто болтовня ни о чем', spellings) is None
assert stt.stt_wake_tail('Музыка играет, юми не слышно', spellings) is None

# ---- a stop shout read from the raw mic must stop her, not wake her ----
for stop in ('Юми стоп', 'юми, стоп', 'Ёми стоп!', 'Юми остановись'):
    assert stt.stop_shout(stop, spellings), stop
# a lyric with «стоп» in it is not a shout: it needs the name at the head
assert not stt.stop_shout('Блин, стоп!', spellings)
assert not stt.stop_shout('Напишите, что вы хотите, стоп', spellings)

# ---- the dial is visible in both the app and the browser panel ----
assert config.DEFAULT_SETTINGS['wake_stt_sweep'] is True
assert catalog.KEY_SECTION['wake_stt_sweep'] == 'ears'
assert catalog.CHOICES['wake_stt_sweep'] == [True, False]
assert 'wake_stt_sweep' in catalog.TITLES
assert 'wake_stt_sweep' in catalog.HINTS

# ---- the wake loop actually uses the spare ear ----
wake_src = str(Path(stt.__file__).read_text()).split('def wake(self, lang', 1)[1]
wake_src = wake_src.split('def stop(self', 1)[0]
assert 'spare_ear(' in wake_src
assert 'stt_wake_tail(' in wake_src
assert 'raw_source(' in wake_src
assert 'reason=\'stt_sweep\'' in wake_src
# the reading runs beside the loop: a synchronous read here starves Vosk and
# the stop word is lost — that was the regression this test guards against
worker = wake_src.split('def sweep_worker(', 1)[1].split(
    'if sweep_mic:\n            # the spare thread', 1)[0]
assert 'threading.Thread' in wake_src
assert wake_src.index('def sweep_worker(') < wake_src.index('sweep_thread.start()'), \
    'the worker must be defined before the thread starts'
assert 'sweep_q.put(' in worker
# the worker must not reach for self.whisper(): self.lock belongs to the wake
assert 'self.whisper(lang' not in worker
assert 'transcribe_model(' in worker
assert wake_src.index('spare_model = self.whisper(') < wake_src.index('with self.lock:')
spare = wake_src.split('def spare_ear(', 1)[1].split('while time.monotonic()', 1)[0]
assert 'read_tape(' not in spare
assert 'stop_shout(' in spare
assert "stop_result(text, 'LISTENING' if woken else 'SLEEP')" in spare

print('stt sweep: ok')
