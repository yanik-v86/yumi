"""When a track is not found, say so plainly - not 'player broken'."""
import types
from yumi.brain import Brain


def _brain():
    b = types.SimpleNamespace(thinking=True, settings={}, calls=[])
    b.say = lambda key, **kw: b.calls.append((key, kw))
    return b


def test_not_found_says_music_not_found():
    b = _brain()
    Brain.said_music_found(b, {'ok': False, 'track': None, 'source': 'local', 'count': 0, 'kind': 'song', 'query': 'рамштайн'})
    assert b.calls == [('music_not_found', {'query': 'рамштайн'})]


def test_player_failure_says_music_no_way():
    b = _brain()
    Brain.said_music_found(b, {'ok': False, 'track': ('A', 'B'), 'source': 'local', 'count': 2, 'kind': 'artist', 'query': 'x'})
    assert b.calls == [('music_no_way', {})]


def test_empty_library_says_music_empty():
    b = _brain()
    Brain.said_music_found(b, {'ok': False, 'track': None, 'source': 'local', 'count': 0, 'kind': 'random', 'query': ''})
    assert b.calls == [('music_empty', {})]
