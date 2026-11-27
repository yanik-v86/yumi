#!/usr/bin/env python3
"""The doctor collects one report from cheap checks (audio calls are mocked).
Run: python3 tests/test_doctor.py"""
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yumi import config, doctor, ears, engines, models, tts  # noqa: E402

settings = dict(config.DEFAULT_SETTINGS)
settings.update({'speech_lang': 'ru', 'wake_word': 'юми', 'voice_vol': 0})

saved = {
    'engines': engines.status,
    'mics': ears.mics,
    'wake': ears.wake,
    'listen': ears.listen,
    'speak': tts.speak,
    'last_error': tts.last_error,
    'models': models.verify,
    'load': config.load_settings,
}

try:
    engines.status = lambda s: {
        'activation': {'oww': {'available': True}, 'vosk': {'available': False}},
        'judge': {'whisper': {'available': True}, 'nemotron': {'available': False},
                  'gigaam': {'available': False}},
        'tts': {'available': True},
    }
    ears.mics = lambda: [{'name': 'plughw:1,0', 'label': 'Headset'}]
    ears.wake = lambda **kw: {
        'woke': True, 'text': 'привет', 'alt': '', 'fallback': False,
        'verdict': {'matched': True, 'reason': 'trained ear'},
    }
    ears.listen = lambda **kw: {'text': 'Юми проверка связи', 'vosk': ''}
    tts.speak = lambda text, volume=0.5: '/tmp/yumi-doctor-test.wav'
    tts.last_error = ''
    models.verify = lambda: {'oww': {'status': 'ok'}}

    report = doctor.run(settings)
    assert report['sections'] == list(doctor.SECTIONS)
    assert report['summary']['ok'], report['summary']
    assert report['checks']['mics']['count'] == 1
    assert report['checks']['wake']['verdict']['reason'] == 'trained ear'
    assert report['checks']['stt']['readings']['hits'] >= 1
    assert report['checks']['tts']['path'].endswith('.wav')
    assert 'token' not in str(report).lower() and 'secret' not in str(report).lower()

    ears.wake = lambda **kw: None
    broken = doctor.run(settings, sections=['wake'])
    assert broken['summary']['failed'] == ['wake']
    assert broken['sections'] == ['wake']

    config.load_settings = lambda: settings
    out = io.StringIO()
    with redirect_stdout(out):
        code = doctor.cli(['engines'])
    assert code == 0 and 'test' not in out.getvalue()   # CLI prints only the report
    assert 'engines' in out.getvalue()
finally:
    engines.status = saved['engines']
    ears.mics = saved['mics']
    ears.wake = saved['wake']
    ears.listen = saved['listen']
    tts.speak = saved['speak']
    tts.last_error = saved['last_error']
    models.verify = saved['models']
    config.load_settings = saved['load']

print('test_doctor: ok')
