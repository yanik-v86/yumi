#!/usr/bin/env python3
"""The phrase ear keeps rare words whole: a spelling hint from the stop ear.

At 22:53 on 22 November whisper wrote «расскажи о негдот» where vosk, reading
the very same tape, wrote «расскажи анекдот». The hint goes to the decoder
only — the mind still gets one reading, never a note about two ears.
Run: python3 tests/test_stt_hotwords.py"""
import os
import sys
import tempfile
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

from yumi import stt_daemon as stt  # noqa: E402


class FakeModel:
    def __init__(self, no_hotwords=False):
        self.calls = []
        self.no_hotwords = no_hotwords

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        if self.no_hotwords and 'hotwords' in kwargs:
            raise TypeError('this whisper knows no hotwords')
        return [type('Seg', (), {'text': 'расскажи анекдот'})()], {}


def test_transcribe_model_forwards_the_hint():
    model = FakeModel()
    text = stt.transcribe_model(model, b'\0\0' * 1600, 'ru',
                                hotwords='расскажи анекдот', beam=5)
    assert text == 'расскажи анекдот'
    call = model.calls[0]
    assert call['hotwords'] == 'расскажи анекдот'
    assert call['beam_size'] == 5
    assert call['language'] == 'ru'
    assert call['vad_filter'] is True
    assert call['condition_on_previous_text'] is False


def test_an_old_whisper_still_reads_without_a_hint():
    model = FakeModel(no_hotwords=True)
    text = stt.transcribe_model(model, b'\0\0' * 1600, 'ru', hotwords='анекдот')
    assert text == 'расскажи анекдот'
    assert 'hotwords' not in model.calls[-1]


def test_read_tape_passes_the_hint_to_whisper():
    ears = stt.Ears()
    seen = []

    def fake_transcribe(pcm, lang, size='small', beam=5, hotwords=None):
        seen.append((lang, beam, hotwords))
        return 'расскажи анекдот'

    ears.transcribe = fake_transcribe
    text, engine, variants = ears.read_tape(b'\0\0' * 32000, 'ru', engine='whisper',
                                             beam=5, hotwords='расскажи анекдот')
    assert (text, engine) == ('расскажи анекдот', 'whisper')
    assert variants == [('whisper', 'расскажи анекдот')]
    assert seen == [('ru', 5, 'расскажи анекдот')]


def test_hint_text_is_short_and_clean():
    assert stt.hotwords_text('я говорю расскажи анекдот', 'терминал') == \
        'я говорю расскажи анекдот, терминал'
    assert stt.hotwords_text('  ', None, '') == ''
    assert len(stt.hotwords_text('а ' * 500)) <= 300


def test_only_a_final_after_the_name_is_a_hint():
    # the stale final from before the wake spoke about another phrase
    assert stt.fresh_hotwords([(100.9, 'юный расскажи анекдот')], 101.0, 102.0) == ''
    # a final after the name read this very phrase
    assert stt.fresh_hotwords([(100.0, 'старое'), (101.5, 'расскажи анекдот')],
                              101.0, 102.0) == 'расскажи анекдот'


def test_setting_is_read_without_a_daemon_restart():
    old = os.environ.get('HOME')
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / '.config' / 'yumi'
        cfg.mkdir(parents=True)
        (cfg / 'settings.json').write_text('{"stt_hotwords": "анекдот, терминал"}')
        os.environ['HOME'] = tmp
        try:
            assert stt._wake_tuning()['stt_hotwords'] == 'анекдот, терминал'
        finally:
            if old is None:
                os.environ.pop('HOME', None)
            else:
                os.environ['HOME'] = old


if __name__ == '__main__':
    for test in (test_transcribe_model_forwards_the_hint,
                 test_an_old_whisper_still_reads_without_a_hint,
                 test_read_tape_passes_the_hint_to_whisper,
                 test_hint_text_is_short_and_clean,
                 test_only_a_final_after_the_name_is_a_hint,
                 test_setting_is_read_without_a_daemon_restart):
        test()
    print('stt hotword checks: ok')
