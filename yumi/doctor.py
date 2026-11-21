"""Yumi's doctor: one structured health report for ears, voice and models (no GTK).

One pass loads the engines, says a control phrase, hears it back, judges the wake
word and prints verdicts and timings.  Yumi's per-part tests already live on the
voice page; this module ties them into one pass that both the terminal
(``yumi --doctor``) and the browser panel (the Diagnostics page) can show.  It is
pure: the audio checks are plain calls into ``ears``/``tts``, so tests can replace
them with mocks.  Nothing here logs secrets, tokens or the contents of private
files.
"""
from __future__ import annotations

import sys
import time

from . import config, ears, engines, models, tts

SECTIONS = ('engines', 'mics', 'models', 'wake', 'tts', 'stt')
DEFAULT_TEXT = 'Юми, проверка связи'


def _timed(fn):
    started = time.time()
    try:
        return fn(), time.time() - started, ''
    except Exception as exc:                      # a broken part must not kill the report
        return None, time.time() - started, f'{type(exc).__name__}: {exc}'[:200]


def _check_engines(settings):
    data = engines.status(settings)
    ok = bool(data['activation']['oww']['available'] or data['activation']['vosk']['available'])
    return {'ok': ok, 'data': data}, ok, []


def _check_mics(_settings):
    mics = ears.mics() or []
    ok = bool(mics)
    note = ('' if ok else 'no microphone found, or the ears are not set up yet')
    return {'ok': ok, 'mics': mics[:8], 'count': len(mics), 'note': note}, ok, []


def _check_models(_settings):
    data = models.verify()
    bad = [name for name, item in data.items() if item['status'] == 'bad']
    missing = [name for name, item in data.items() if item['status'] == 'missing']
    ok = not bad
    warnings = [f'missing: {", ".join(missing)}'] if missing else []
    return {'ok': ok, 'models': data, 'bad': bad}, ok, warnings


def _check_wake(settings):
    result, elapsed, error = _timed(lambda: ears.wake(
        lang=str(settings.get('speech_lang') or 'ru'),
        word=str(settings.get('wake_word') or 'юми'),
        secs=7,
        size=str(settings.get('stt_size') or 'small'),
        mic=settings.get('stt_mic') or None,
        sensitivity=str(settings.get('wake_sensitivity') or 'normal'),
        confirm=bool(settings.get('wake_confirm', True)),
        model_size=settings.get('wake_model_size') or None,
        judge_log=bool(settings.get('wake_judge_log', False)),
        engine=settings.get('stt_engine') or None,
        oww_ear=settings.get('wake_ear') or None,
    ))
    if error:
        return {'ok': False, 'error': error, 'elapsed': round(elapsed, 2)}, False, []
    if result is None:
        return {'ok': False, 'error': 'the ears cannot work (no Python or no daemon)',
                'elapsed': round(elapsed, 2)}, False, []
    woke = bool(result.get('woke'))
    verdict = dict(result.get('verdict') or {})
    verdict.update({'matched': woke, 'text': str(result.get('text') or '')[:200],
                    'alt': str(result.get('alt') or '')[:200],
                    'fallback': bool(result.get('fallback'))})
    verdict.setdefault('reason', 'heard her name' if woke else 'no wake word in this window')
    warnings = ['the trained ear did not fire; the fallback route was used'] if result.get('fallback') else []
    return {'ok': True, 'woke': woke, 'verdict': verdict, 'elapsed': round(elapsed, 2)}, True, warnings


def _check_tts(settings, text):
    result, elapsed, error = _timed(
        lambda: tts.speak(text, float(settings.get('voice_vol') or 50) / 100.0))
    if error or result is None:
        msg = error or tts.last_error or 'the voice daemon returned no WAV'
        return {'ok': False, 'error': msg[:200], 'elapsed': round(elapsed, 2)}, False, []
    return {'ok': True, 'path': str(result), 'elapsed': round(elapsed, 2)}, True, []


def _check_stt(settings, text):
    result, elapsed, error = _timed(lambda: ears.listen(
        lang=str(settings.get('speech_lang') or 'ru'),
        secs=7,
        size=str(settings.get('stt_size') or 'small'),
        mic=settings.get('stt_mic') or None,
        engine=settings.get('stt_engine') or None,
    ))
    if error or result is None:
        return {'ok': False, 'error': (error or 'the ears cannot work (no Python or no daemon)')[:200],
                'elapsed': round(elapsed, 2)}, False, []
    heard = str(result.get('text') or '')
    alt = str(result.get('vosk') or '')
    # a loose control check: the phrase need not be perfect, but some words must land
    expected = [w for w in str(text).lower().split() if len(w) > 2]
    hits = sum(1 for w in expected if w in heard.lower() or w in alt.lower())
    ok = bool(expected) and hits >= max(1, len(expected) // 2)
    readings = {'text': heard[:200], 'vosk': alt[:200], 'hits': hits, 'expected': len(expected)}
    note = '' if ok else 'the control phrase was not heard clearly (check the mic and the volume)'
    return {'ok': ok, 'heard': heard[:200], 'readings': readings, 'note': note,
            'elapsed': round(elapsed, 2)}, ok, ([note] if note else [])


def run(settings, sections=None, roundtrip_text=None):
    """Run the selected checks (all of them by default) and return one report.

    ``sections`` is a list of names from ``SECTIONS``.  ``roundtrip_text`` is the
    control phrase for the TTS → STT check.  The report is JSON-safe and carries
    only names, timings and public engine data — never a token or a secret.
    """
    settings = settings or config.load_settings()
    want = list(SECTIONS) if not sections else [s for s in sections if s in SECTIONS]
    text = str(roundtrip_text or DEFAULT_TEXT)[:200]
    started = time.time()
    checks, failed, warnings = {}, [], []
    builders = {
        'engines': lambda: _check_engines(settings),
        'mics': lambda: _check_mics(settings),
        'models': lambda: _check_models(settings),
        'wake': lambda: _check_wake(settings),
        'tts': lambda: _check_tts(settings, text),
        'stt': lambda: _check_stt(settings, text),
    }
    for name in want:
        try:
            data, ok, notes = builders[name]()
        except Exception as exc:                  # one broken part must not kill the report
            data = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'[:200]}
            ok, notes = False, []
        checks[name] = data
        if not ok:
            failed.append(name)
        warnings.extend(notes)
    elapsed = round(time.time() - started, 2)
    return {
        'started': started,
        'elapsed': elapsed,
        'sections': want,
        'checks': checks,
        'summary': {'ok': not failed, 'failed': failed, 'warnings': warnings[:10]},
    }


# ---- the terminal front end (yumi --doctor) --------------------------------

def _print_report(report):
    mark = lambda ok: 'OK  ' if ok else 'FAIL'
    print(f"Yumi doctor — {report['elapsed']}s")
    for name, data in report['checks'].items():
        ok = bool(data.get('ok'))
        line = f"  [{mark(ok)}] {name}"
        if data.get('elapsed') is not None:
            line += f" ({data['elapsed']}s)"
        if data.get('error') or data.get('note'):
            line += f" — {data.get('error') or data.get('note')}"
        print(line)
        if name == 'mics' and data.get('mics'):
            for mic in data['mics']:
                print(f"         · {mic.get('label') or mic.get('name')}")
        if name == 'wake' and data.get('verdict'):
            print(f"         verdict: {data['verdict']['reason']}")
        if name == 'models':
            for key, item in data.get('models', {}).items():
                print(f"         · {key}: {item['status']}")
    summary = report['summary']
    if summary['ok']:
        print('All checks passed.')
    else:
        print('Failed: ' + ', '.join(summary['failed']))
    for note in summary['warnings']:
        print('  ! ' + note)


def cli(argv=None):
    """entry point for ``yumi --doctor``; prints a report, returns a process code"""
    argv = list(sys.argv[1:] if argv is None else argv)
    sections = [a for a in argv if a in SECTIONS]
    report = run(None, sections=sections or None)
    _print_report(report)
    return 0 if report['summary']['ok'] else 1


if __name__ == '__main__':                          # python3 -m yumi.doctor
    raise SystemExit(cli())
