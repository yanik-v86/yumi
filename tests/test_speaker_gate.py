#!/usr/bin/env python3
"""The multi-speaker gate: who may talk to her inside an open dialogue."""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))
from yumi import brain as brain_mod  # noqa: E402
from yumi import speaker as profiles  # noqa: E402
from yumi.conversation import Conversation  # noqa: E402


class Speech:
    def say(self, *a, **kw):
        return None


def make_brain(monkeypatch, tmp_path, settings=None):
    monkeypatch.setenv('YUMI_SPEAKER_FILE', str(tmp_path / 'speakers.json'))
    br = brain_mod.Brain.__new__(brain_mod.Brain)
    br.settings = dict(brain_mod.Stub) if hasattr(brain_mod, 'Stub') else {
        'speaker_verify': True, 'speaker_min_ms': 1200, 'speaker_threshold': 0.65,
        'speaker_join_policy': 'addressed', 'conversation_mode': True,
        'conversation_timeout_s': 10, 'wake_ears': True, 'sleeping': False,
        'wake_word': 'юми', 'speech_lang': 'ru', 'ui_lang': 'ru',
        'music_skill': False, 'notes_voice': False, 'nlu': False,
        'stt_crosscheck': False, 'chat_history_n': 10, 'conversation_history_n': 20,
        'conversation_gap_reset_min': 15, 'chat_memory': False,
        'chat_provider': 'ollama', 'chat_model': 'test', 'chat_stream': False,
        'chat_think': False, 'chat_provider_url': '', 'ollama_url': '',
        'polza_url': '', 'polza_api_key': '', 'voice_vol': 0,
    }
    if settings:
        br.settings.update(settings)
    br.conversation = Conversation(timeout=10)
    br.conversation.begin(0.0, 'voice')
    br.speech = Speech()
    br.say = lambda *a, **kw: True       # a phrase event needs a real Brain's state
    br._pending_speaker = None
    br.custom = []
    br.requests = []
    br.chat_history = []
    br.now = 1.0
    br.listening = True
    br.thinking = False
    br.sleeping = False
    br.note_pending = False
    br.pending_permission = None
    br.talk_until = 0.0
    br.bubble = None
    br.bubble_n = 0
    br.last_chat_exchange_at = 0.0
    br.stops = []
    br.hints = []
    br.stop_all = lambda: br.stops.append(True)
    br.say_text = lambda *a, **kw: True
    br.voice_intent = lambda *a, **kw: False
    monkeypatch.setattr(brain_mod, 'music_control_text', lambda *a, **kw: None)
    return br


def asked(br):
    return [p for p in br.requests if p[0] == 'chat_ask']


def known(pid):
    return {'status': 'known', 'id': pid, 'score': 0.8, 'quality': True, 'ms': 2000}


def newcomer(pid):
    return {'status': 'unknown', 'id': None, 'score': 0.1, 'quality': True,
            'ms': 2000, 'joined_id': pid}


def test_stop_and_disabled(monkeypatch, tmp_path):
    br = make_brain(monkeypatch, tmp_path)
    br.heard_text('стоп', wake=True, followup=True,
                  speaker={'status': 'unknown', 'id': None, 'quality': False})
    assert br.stops and not asked(br)             # any voice can stop her

    br = make_brain(monkeypatch, tmp_path, {'speaker_verify': False})
    br.heard_text('как дела?', wake=True, followup=True,
                  speaker={'status': 'unknown', 'id': None, 'quality': False})
    assert len(asked(br)) == 1                    # old daemon / feature off: as before


def test_other_talk_is_ignored(monkeypatch, tmp_path):
    br = make_brain(monkeypatch, tmp_path)
    br.conversation.add_participant('spk_01')
    br.heard_text('Борис, где ключи?', wake=True, followup=True, speaker=known('spk_01'))
    assert not asked(br) and br.conversation.last_route == 'other'
    br.heard_text('он сказал, что придёт', wake=True, followup=True,
                  speaker=known('spk_01'))
    assert not asked(br)
    br.heard_text('как дела?', wake=True, followup=True,
                  speaker={'status': 'known', 'id': 'spk_09', 'quality': True})
    assert not asked(br)                          # a known voice outside this dialogue


def test_newcomer_joins_and_two_voices_take_turns(monkeypatch, tmp_path):
    monkeypatch.setenv('YUMI_SPEAKER_FILE', str(tmp_path / 'speakers.json'))
    pid = profiles.enroll([1.0, 0.0], 'Аня', source='wake')
    other = profiles.enroll([0.0, 1.0], 'Борис', source='join')
    br = make_brain(monkeypatch, tmp_path)
    br.conversation.add_participant(pid)

    br.heard_text('привет', wake=True, followup=True, speaker=newcomer(other), join=True)
    assert len(asked(br)) == 1
    assert other in br.conversation.participants
    assert br.chat_history[0]['speaker'] == other
    assert br.chat_history[0]['speaker_label'] == 'Борис'
    signed = asked(br)[0][1][-1]['content']
    assert signed.startswith('Борис: '), signed

    br.heard_text('как дела?', wake=True, followup=True, speaker=known(pid))
    br.heard_text('что нового?', wake=True, followup=True, speaker=known(other))
    assert len(asked(br)) == 3                    # no wake word for either voice
    assert br.conversation.last_speaker == other
    assert br.chat_history[-1]['speaker'] == other


def test_short_or_unaddressed_newcomer_stays_out(monkeypatch, tmp_path):
    br = make_brain(monkeypatch, tmp_path)
    br.conversation.add_participant('spk_01')
    short = newcomer('spk_02')
    short['quality'] = False
    br.heard_text('привет', wake=True, followup=True, speaker=short, join=True)
    assert not asked(br) and 'spk_02' not in br.conversation.participants
    br.heard_text('Анна, где ключи?', wake=True, followup=True,
                  speaker=newcomer('spk_02'), join=True)
    assert not asked(br) and 'spk_02' not in br.conversation.participants
    br.heard_text('он тут', wake=True, followup=True,
                  speaker=newcomer('spk_02'), join=True)
    assert not asked(br)
    br.heard_text('привет', wake=True, followup=True,
                  speaker=newcomer('spk_02'), join=False)
    assert not asked(br)


def test_join_policy_off(monkeypatch, tmp_path):
    br = make_brain(monkeypatch, tmp_path, {'speaker_join_policy': 'off'})
    br.conversation.add_participant('spk_01')
    br.heard_text('привет', wake=True, followup=True,
                  speaker=newcomer('spk_02'), join=True)
    # the daemon respects the policy itself; if a stale one still sent a joined
    # id, a disabled join must not add a participant behind the setting's back
    assert 'spk_02' not in br.conversation.participants and not asked(br)
