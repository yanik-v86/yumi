#!/usr/bin/env python3
"""«тише»/«громче» без имени и «юми, продолжи» после остановки.
Run: python3 tests/test_quick_commands.py"""
import importlib.util
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, _root / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


stt = load('stt_daemon_quick', 'yumi/stt_daemon.py')
from yumi import music  # noqa: E402

spellings = stt.variants('юми') | stt.hearsay_load('юми')

# the two quick words heard by the little ear while she waits for her name
assert stt.quick_volume('тише') == 'volume_down'
assert stt.quick_volume('громче') == 'volume_up'
assert stt.quick_volume('тише!') == 'volume_down'
assert stt.quick_volume('юми тише', spellings) == 'volume_down'
assert stt.quick_volume('потише, пожалуйста') == 'volume_down'
assert stt.quick_volume('громче ещё') == 'volume_up'
assert stt.quick_volume('убавь громкость') == 'volume_down'
assert stt.quick_volume('прибавь громкость') == 'volume_up'
assert stt.quick_volume('уменьши звук') == 'volume_down'
assert stt.quick_volume('тисе') == 'volume_down'      # a letter lost over the music
assert stt.quick_volume('громч') == 'volume_up'
assert stt.quick_volume('гром') is None               # too short for a slip to count
assert stt.quick_volume('') is None
assert stt.quick_volume('включи музыку') is None
assert stt.quick_volume('тишина') is None
assert stt.quick_volume('громче так нельзя') is None  # other words: background talk
assert stt.quick_volume('расскажи, почему тут тише') is None
assert stt.quick_volume('тише и громче') is None      # neither wish is clear

# one phrase turns the knob once: a re-heard final cannot pump it ten at a time
stt._quick_cache['t'] = 0.0
assert stt._quick_ready()
assert not stt._quick_ready()
stt._quick_cache['t'] = 0.0

# the quick word reaches the app the way «стоп» does: daemon → /wake → ears → loop
daemon_src = (_root / 'yumi' / 'stt_daemon.py').read_text(encoding='utf-8')
assert 'def quick_volume(' in daemon_src
assert 'quick_result(cmd, words)' in daemon_src
assert "'cmd': str(res.get('cmd') or '')" in daemon_src
ears_src = (_root / 'yumi' / 'ears.py').read_text(encoding='utf-8')
assert "'cmd': str(data.get('cmd') or '')" in ears_src
senses_src = (_root / 'yumi' / 'ui' / 'senses.py').read_text(encoding='utf-8')
assert "if res.get('cmd'):" in senses_src
assert 'br.music_control(c)' in senses_src

# «продолжи»: the track «стоп» cut off comes back, not a fresh library
brain_src = (_root / 'yumi' / 'brain.py').read_text(encoding='utf-8')
assert "MUSIC_RESUME = frozenset((" in brain_src
assert "return 'resume'" in brain_src
assert "self.requests.append(('music_resume',))" in brain_src
app_src = (_root / 'yumi' / 'ui' / 'app.py').read_text(encoding='utf-8')
assert "elif kind == 'music_resume':" in app_src

# the memory survives the stop and chooses the road home
saved = {k: getattr(music, k) for k in
         ('_player_status', 'get_mpd_status', 'play_tracks', 'play_music',
          '_playerctl', 'stop_music', '_mpc', 'is_mpd_playing')}
memory = dict(music._resume)
calls = []
try:
    music._player_status = lambda: ''
    music.get_mpd_status = lambda: None
    music.play_tracks = lambda tracks: calls.append(('tracks', tracks)) or True
    music.play_music = lambda **kw: calls.append(('dir', kw)) or True
    music._playerctl = lambda *a: None
    music.stop_music = lambda **kw: True
    played_mpd = []
    music._mpc = lambda *a, **kw: played_mpd.append(a) or type(
        'R', (), {'returncode': 0, 'stdout': ''})()
    music.is_mpd_playing = lambda: True

    music._resume.update(mode='mpd_file', value={'file': '/music/song.mp3', 'env': None})
    assert music.resume_music() is True
    assert played_mpd[-1] == ('play',)        # her queue survived the stop: that very song

    music._resume.update(mode='tracks', value=[{'url': 'http://song'}])
    assert music.resume_available()
    assert music.resume_music() is True
    assert calls[-1][0] == 'tracks' and calls[-1][1][0]['url'] == 'http://song'

    music._resume.update(mode='file', value='/tmp/song.mp3')
    assert music.resume_music() is True
    assert calls[-1][1] == [{'path': '/tmp/song.mp3'}]

    music._resume.update(mode='dir', value='/music')
    assert music.resume_music() is True
    assert calls[-1] == ('dir', {'directory': '/music'})

    music._resume.update(mode=None, value=None)
    assert not music.resume_available()
    music._player_status = lambda: 'Playing'
    assert music.music_control('stop') is True   # remember the stranger's track
    assert music._resume['mode'] == 'player'
    music._player_status = lambda: ''

    played = []
    music._playerctl = lambda *a: played.append(a) or type('R', (), {'returncode': 0})()
    assert music.resume_music() is True
    assert played and played[-1][0] == 'play'
finally:
    for k, v in saved.items():
        setattr(music, k, v)
    music._resume.clear()
    music._resume.update(memory)

# and the web panel has the same resume: status flag, button and control
bridge_src = (_root / 'yumi' / 'ui' / 'bridge.py').read_text(encoding='utf-8')
assert "'resumable': bool(music.resume_available())" in bridge_src
panel_src = (_root / 'yumi' / 'ui' / 'webpanel.py').read_text(encoding='utf-8')
assert "'resumable': self._web_resumable" in panel_src
js = (_root / 'yumi' / 'webui' / 'static' / 'js' / 'pages' / 'dashboard.js').read_text(encoding='utf-8')
assert "musicCmd('resume')" in js
assert 'resumeBtn.disabled = !runtime.music?.resumable;' in js
js_music = (_root / 'yumi' / 'webui' / 'static' / 'js' / 'pages' / 'music.js').read_text(encoding='utf-8')
assert "'resume', 'play'" in js_music
assert 'resumeButton.disabled = !music.resumable;' in js_music

print('test_quick_commands: ok')
