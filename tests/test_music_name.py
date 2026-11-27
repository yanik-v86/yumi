"""Spoken song names must become cover spellings even when the mind stalls."""
from yumi import chat


def test_music_name_asks_with_examples_and_retries(monkeypatch):
    calls = []

    def fake_one_shot(settings, user, tokens, timeout=90, temp=None):
        calls.append((user, tokens, timeout))
        if len(calls) < 2:
            return ''
        return 'Rammstein – Sonne\n(in German: sun)'

    monkeypatch.setattr(chat, '_one_shot', fake_one_shot)
    got = chat.music_name({}, 'song', 'рамштайн сан')
    assert got == 'Rammstein Sonne'          # the dash is not part of the search name
    assert len(calls) == 2                   # one silent door, one answer
    prompt, tokens, timeout = calls[0]
    assert 'рамштайн сан' in prompt
    assert 'Rammstein Sonne' in prompt       # a real title, not a transliteration
    assert tokens >= 256                     # reasoning models need room to answer
    assert timeout <= 8                      # a short try, so the retry fits the budget


def test_music_name_keeps_a_custom_prompt(monkeypatch):
    seen = []

    def fake_one_shot(settings, user, tokens, timeout=90, temp=None):
        seen.append(user)
        return 'Answer: 2Pac'

    monkeypatch.setattr(chat, '_one_shot', fake_one_shot)
    settings = {'prompt_music_name': 'Name: {kind} — {query}'}
    assert chat.music_name(settings, 'artist', 'тупак') == '2Pac'
    assert seen[0].startswith('Name: an artist — тупак')
    assert 'Rammstein Sonne' in seen[0]      # the examples survive a custom prompt


def test_music_name_asks_a_local_model_when_the_chosen_one_is_silent(monkeypatch):
    monkeypatch.setattr(chat, '_one_shot', lambda *a, **k: '')
    rec = {'id': 'local', 'name': 'Local', 'kind': 'ollama', 'url': 'http://x',
           'default_model': 'small:latest', 'enabled': True, 'models': []}
    monkeypatch.setattr(chat.llm, 'providers', lambda settings: [rec])
    seen = []

    def fake_ask(settings, messages, **kwargs):
        seen.append(kwargs)
        return 'Rammstein Sonne'

    monkeypatch.setattr(chat.llm, 'ask', fake_ask)
    settings = {'chat_provider': 'cloud', 'chat_model': 'far-away-model'}
    assert chat.music_name(settings, 'song', 'рамштайн сан') == 'Rammstein Sonne'
    assert len(seen) == 1
    assert seen[0]['provider'] == 'local'
    assert seen[0]['model'] == 'small:latest'   # not the cloud model name
    assert seen[0]['max_tokens'] >= 256


def test_music_name_stays_quiet_when_every_mind_is_away(monkeypatch):
    monkeypatch.setattr(chat, '_one_shot', lambda *a, **k: '')
    monkeypatch.setattr(chat.llm, 'ask', lambda *a, **k: '')
    assert chat.music_name({}, 'song', 'рамштайн сан') == ''


def test_music_name_stays_quiet_without_query(monkeypatch):
    monkeypatch.setattr(chat, '_one_shot', lambda *a, **k: 'something')
    assert chat.music_name({}, 'song', '') == ''
