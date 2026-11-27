"""Jellyfin's SearchTerm is a substring, so a phrase must be searched word by word."""
from yumi import library


TRACKS = {
    'rammstein': [{'Id': '1', 'Name': 'Rammstein', 'Artists': ['Rammstein'], 'Album': 'Rammstein'}],
    'sonne': [{'Id': '2', 'Name': 'Sonne', 'Artists': ['Rammstein'], 'Album': 'Mutter'}],
    'крылья': [{'Id': '3', 'Name': 'Крылья', 'Artists': ['Наутилус Помпилиус'], 'Album': 'Разлука'}],
}


class FakeJellyfin(library.Jellyfin):
    def __init__(self):
        super().__init__({'music_jellyfin': 'http://jf', 'music_jellyfin_key': 'test'})
        self.terms = []

    def _get(self, path, **params):
        term = str(params.get('SearchTerm') or '').lower()
        self.terms.append(term)
        return {'Items': [dict(t) for t in TRACKS.get(term, [])]}


def test_multiword_search_finds_the_song_by_artist_and_title():
    jf = FakeJellyfin()
    got = jf.search('Rammstein Sonne')
    assert len(got) == 1 and got[0]['title'] == 'Sonne', got
    assert jf.terms == ['rammstein', 'sonne']   # not one phrase that finds nothing


def test_one_word_still_takes_one_request():
    jf = FakeJellyfin()
    got = jf.search('Sonne')
    assert len(got) == 1 and got[0]['title'] == 'Sonne'
    assert jf.terms == ['sonne']


def test_a_stranger_word_finds_nothing():
    jf = FakeJellyfin()
    assert jf.search('完全没有') == []


def test_wrong_words_do_not_make_a_match_out_of_unrelated_tracks():
    jf = FakeJellyfin()
    assert jf.search('Rammstein Крылья') == []
