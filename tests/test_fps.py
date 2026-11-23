"""The frame-rate budget: a quiet desktop must not repaint at refresh rate."""
from types import SimpleNamespace

from yumi.brain import Brain


def brain_stub(**kw):
    b = SimpleNamespace(
        mode='docked',
        x=SimpleNamespace(v=0.0), y=SimpleNamespace(v=0.0),
        yoff=SimpleNamespace(v=0.0), pile_t=SimpleNamespace(v=0.0),
        radial_t=SimpleNamespace(v=0.0),
        pile=False, pull_v={}, beat=0.0, music=False,
        visible=lambda: False,
        moth=SimpleNamespace(visible=lambda: False, state='gone'),
    )
    b.__dict__.update(kw)
    return b


def test_idle_fps():
    assert Brain.fps(brain_stub()) == 12


def test_moving_fps():
    b = brain_stub()
    b.y.v = 1.0
    assert Brain.fps(b) == 60
    b.y.v = 0.0
    b.mode = 'held'
    assert Brain.fps(b) == 60


def test_moth_fps():
    b = brain_stub(moth=SimpleNamespace(visible=lambda: True, state='wander'))
    assert Brain.fps(b) == 16


def test_music_fps():
    b = brain_stub(visible=lambda: True)
    b.beat = 0.4
    assert Brain.fps(b) == 24
    b.beat = 0.0
    b.music = True
    assert Brain.fps(b) == 24


def test_hidden_music_fps():
    b = brain_stub(music=True)
    assert Brain.fps(b) == 16
