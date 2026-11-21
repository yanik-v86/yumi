"""A bare artist name like «включи рамштайн» should play the artist, not a random title match."""
from yumi import music, library
import yumi.chat as chat


def test_song_query_upgrades_to_artist_when_artist_matches(monkeypatch):
    def fake_resolve(settings, kind, query=''):
        if kind == 'song' and query.lower() == 'rammstein':
            tracks = [
                {'title': 'Du Hast', 'artist': 'Rammstein', 'album': 'Sehnsucht', 'path': '/m/1.mp3', 'source': 'local'},
                {'title': 'Sonne', 'artist': 'Rammstein', 'album': 'Mutter', 'path': '/m/2.mp3', 'source': 'local'},
            ]
            return {'source': 'local', 'kind': kind, 'query': query, 'tracks': tracks, 'lib': library.Local(settings)}
        if kind == 'artist' and query.lower() == 'rammstein':
            tracks = [
                {'title': 'Du Hast', 'artist': 'Rammstein', 'album': 'Sehnsucht', 'path': '/m/1.mp3', 'source': 'local'},
                {'title': 'Sonne', 'artist': 'Rammstein', 'album': 'Mutter', 'path': '/m/2.mp3', 'source': 'local'},
                {'title': 'Mein Herz brennt', 'artist': 'Rammstein', 'album': 'Mutter', 'path': '/m/3.mp3', 'source': 'local'},
            ]
            return {'source': 'local', 'kind': kind, 'query': query, 'tracks': tracks, 'lib': library.Local(settings)}
        return {'source': 'local', 'kind': kind, 'query': query, 'tracks': [], 'lib': library.Local(settings)}

    played = {}
    def fake_play(tracks):
        played['tracks'] = tracks
        return True
    monkeypatch.setattr(library, 'resolve', fake_resolve)
    monkeypatch.setattr(music, 'play_tracks', fake_play)
    monkeypatch.setattr(chat, 'music_name', lambda *a, **k: '')

    r = music.play_query('song', 'Rammstein', {})
    assert r['ok'] is True
    assert r['kind'] == 'artist'
    assert r['count'] == 3
    assert played['tracks'][0]['artist'] == 'Rammstein'


def test_song_query_keeps_song_when_title_matches(monkeypatch):
    def fake_resolve(settings, kind, query=''):
        if kind == 'song':
            return {'source': 'local', 'kind': kind, 'query': query,
                    'tracks': [{'title': 'Rammstein', 'artist': 'Other', 'album': 'X', 'path': '/m/1.mp3', 'source': 'local'}],
                    'lib': library.Local(settings)}
        return {'source': 'local', 'kind': kind, 'query': query, 'tracks': [], 'lib': library.Local(settings)}

    played = {}
    def fake_play(tracks):
        played['tracks'] = tracks
        return True
    monkeypatch.setattr(library, 'resolve', fake_resolve)
    monkeypatch.setattr(music, 'play_tracks', fake_play)
    monkeypatch.setattr(chat, 'music_name', lambda *a, **k: '')

    r = music.play_query('song', 'Rammstein', {})
    assert r['kind'] == 'song'
    assert r['track'][1] == 'Rammstein'
