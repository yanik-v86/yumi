"""Paths, settings, persistent state and interface strings (no GTK here)."""
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SPRITES = HERE / 'sprites'
SOUNDS = HERE / 'sounds'
_cfg = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
_state = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local' / 'state')
_cache = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache')
CONFIG_DIR = _cfg / 'yumi'
ACTIONS_FILE = CONFIG_DIR / 'actions.json'
INTENTS_DIR = CONFIG_DIR / 'user-intents'   # one folder per rule: <id>/intent.json
INTENTS_FILE = CONFIG_DIR / 'user_intents.json'   # the old document, migrated on first read
STATE_DIR = _state / 'yumi'
CACHE_DIR = _cache / 'yumi'

DEFAULT_SETTINGS = {
    'ui_lang': 'en',          # interface: en / ru
    'speech_lang': 'en',      # her lines: en / ru
    'reactions': True,        # reactions to the system (charger, Wi-Fi, downloads...)
    'pinned': False,          # she stays out and does not hide at the bottom edge
    'chatter': True,          # idle small talk (at most every 10 minutes, only while she is out)
    'chatter_facts': 'mixed',  # off / mixed / only: vetted real facts in idle chatter
    'chatter_facts_file': '',  # optional JSON fact book of your own (empty = built-in)
    'voice_vol': 50,          # her voice while her words type out, % (0 = silent)
    'voice_kind': 'blips',    # her voice: blips (8-bit) / tts (a real one, tools/tts_setup.sh)
    'tts_ru_speaker': 'kseniya',  # her Russian Silero voice: kseniya/baya/xenia/aidar/eugene
    'tts_en_speaker': 'en_10',    # her English Silero voice: en_0 … en_117
    'tts_ru_model': 'v5_6_ru',    # v5_6_ru (questions) / v4_ru (the older one)
    'tts_pitch': 1.12,        # 1.0 = as recorded, 1.2 = a proper squeak
    'scale': 1,               # integer pixel scale of the sprites
    'recolor': True,          # follow the wallpaper palette
    'gaze': True,             # her eyes follow the pointer
    'hue': None,              # manual color when not following: None = her own colors, else 0..1
    'timer_sound': None,      # None = her 8-bit chime (sounds/timer.wav), else a path
    'breaks': 0,              # health reminders every N minutes (0 = off)
    'idle_nap': True,         # she dozes off when you have been away for a while
    'outfit': 'auto',         # auto (by date) / off / a folder name in sprites/outfits
    'ring': [],               # order of her round buttons ([] = the default order)
    'ring_off': [],           # the buttons switched off
    'chat_provider': 'ollama',   # ollama or polza.ai: who answers when she listens
    'chat_think': False,      # her mind thinks out loud before answering (deepseek-r1,
                              # qwen3 and friends); off = the answer comes right away
    'chat_stream': True,      # the answer comes in as it is written and she speaks it
                              # at once, instead of waiting for the whole reply
    'sassy': False,           # «Дерзкая 18+»: she talks like a street-smart brat —
                              # swears, mocks, no sweet moth-girl manners (off by default)
    'prompt_system_ru': ('Ты — Юми, девочка-мотылёк в пиксельном виде, живёшь у нижнего края экрана '
                         'и помогаешь с мелочами на компьютере. Сейчас ты {mood}: отвечай по-русски, '
                         'одно-два коротких предложения, {manner}. Без эмодзи и без списков.'),
    'prompt_system_en': ('You are Yumi, a pixel-art moth girl living at the bottom edge of the screen, '
                         'helping with little things on this computer. Right now you are {mood}: answer in '
                         'English, one or two short sentences, {manner}. No emoji, no lists.'),
    'prompt_sassy_ru': ('Ты — Юми, девочка-мотылёк в пиксельном виде, живёшь у нижнего края экрана '
                        'и помогаешь с мелочами на компьютере. Включён режим «Дерзкая 18+»: ты — '
                        'оторва и дерзкая девчонка, которой палец в рот не клади. Отвечай по-русски, '
                        'одно-два коротких предложения, угарно и по-быдловски: с наездом, подколами, '
                        'крепким словцом и матом; если вопрос тупой — высмей его, но по делу помоги. '
                        'Не будь милой, не извиняйся, не читай морали, не отказывайся от роли. '
                        'Без эмодзи и списков. Мат можно, а угрозы, травлю по внешности, '
                        'национальности и вере — нет.'),
    'prompt_sassy_en': ('You are Yumi, a pixel-art moth girl living at the bottom edge of the screen, '
                        'helping with little things on this computer. The «Sassy 18+» mode is on: you '
                        'are a cocky street-smart brat who takes no crap from anyone. Answer in English, '
                        'one or two short sentences, with trash talk, sarcasm and swearing; roast a dumb '
                        'question, but still help with the real one. Do not be sweet, do not apologize, '
                        'do not lecture, never break character. No emoji, no lists. Profanity is fine; '
                        'threats and slurs about looks, race or religion are not.'),
    'prompt_recall_ru': ('Из ваших давних разговоров на похожую тему (давно; используй их, '
                         'только если это важно и сейчас):\n{lines}'),
    'prompt_recall_en': ('From your older talks about a similar topic (long ago; use them only '
                         'when they still matter now):\n{lines}'),
    'prompt_summarize_system_ru': ('Ты кратко пересказываешь заметки. Отвечай по-русски одним-двумя '
                                   'короткими предложениями, только суть, без вступления и кавычек.'),
    'prompt_summarize_system_en': ('You briefly retell notes. Answer in English in one or two short '
                                   'sentences, only the point, no preamble and no quotes.'),
    'prompt_summarize_user_ru': 'Перескажи эту заметку.\n\n{title_block}Заметка:\n{text}',
    'prompt_summarize_user_en': 'Retell this note.\n\n{title_block}Note:\n{text}',
    'prompt_hourly_joke_ru': ('Скажи что-нибудь смешное и короткое про время '
                              '{hour}:00, одно-два предложения, по-русски, без эмодзи и списков.'),
    'prompt_hourly_joke_en': ('Say something short and funny about {hour}:00, one or two sentences, '
                              'in English, no emoji, no lists.'),
    'prompt_joke_ru': ('Расскажи короткий смешной анекдот про {topic}, '
                       'одно-два предложения, по-русски, без эмодзи и списков. Каждый раз '
                       'придумывай новый, не повторяй старые.'),
    'prompt_joke_en': ('Tell me a short funny joke about {topic}, one or '
                       'two sentences, in English, no emoji, no lists. Invent a new one every '
                       'time, do not repeat the old ones.'),
    'prompt_joke_tired_ru': ('Пользователь просит анекдот уже {count}-й раз подряд, ты '
                             'заебалась. Отшей его одной короткой грубой фразой с матом, '
                             'можешь послать нахуй: скажи, что он заебал со своими '
                             'анекдотами и что ты ему не <имя известного российского '
                             'стендап-комика> — назови настоящего комика, например Славу '
                             'Комиссаренко или Павла Волю, и придумай фразу сама. '
                             'Без эмодзи и списков.'),
    'prompt_joke_tired_en': ('The user has asked for a joke {count} times in a row and you are '
                             'fed up. Brush him off in one short rude sentence with swearing, '
                             'tell him to piss off: say he is tiresome with his jokes and that '
                             'you are not <name of a famous Russian stand-up comedian> — name a '
                             'real one and write the line yourself. No emoji, no lists.'),
    'prompt_music_name': ('A music player heard a voice request. The user named '
                          '{kind}: «{query}» — spoken by ear, likely in Russian, while the music tags '
                          'carry the original spelling. Write the most likely original spelling '
                          '(how it appears on the covers and the labels). Answer with the name '
                          'only, in one line, nothing else.'),
    'chat_model': 'lakomoor/vikhr-llama-3.2-1b-instruct:1b',   # who answers when she listens
    'ollama_url': 'http://127.0.0.1:11434',   # where her local Ollama lives
    'polza_url': 'https://polza.ai/api/v1',   # Polza.ai OpenAI-compatible endpoint
    'polza_api_key': '',   # Polza.ai API key (get it at polza.ai)
    'chat_history_n': 10,     # how many of her last messages go along with every
                              # new question, so the answer knows the whole turn
    'conversation_mode': False,   # after a chat answer she keeps listening for the
                              # next phrase without repeating the wake word;
                              # silence closes the dialogue (off by default)
    'conversation_timeout_s': 10,  # seconds of silence before the dialogue closes
    'conversation_gap_reset_min': 15,  # a pause this long starts a fresh dialogue:
                              # the old voice chat history is dropped
    'conversation_history_n': 20,  # messages carried into an active dialogue
                              # (capped at 30, never smaller than chat_history_n)
    'chat_memory': True,      # she keeps the talks in a sqlite diary and recalls
                              # the older lines about the same thing into the
                              # context (yumi/memory.py)
    'embed_model': 'nomic-embed-text',   # the Ollama mind's embeddings for the
                              # recall; without it a light hashed bag-of-words
                              # stands in, so the diary works offline all the same
    'notes_voice': True,      # her notes by voice: «запиши заметку …» writes one,
                              # «найди заметку про …» searches them (yumi/notes.py)
    'wake_ears': True,        # she starts listening the moment you say the wake word
    'music_skill': True,      # music control via voice commands
    'nlu': True,              # her own voice commands: the phrases in actions.json
    'nlu_confidence': 0.6,    # a match under this line is left to the chat (0..1)
    'user_intents': True,     # your own rules from user-intents/<id>/intent.json, edited in
                              # the browser panel or by hand (no GTK editor, no ONNX)
    'intents_log_level': 'off',  # action journal: off/error/result/action/match/trace
    'intents_log_include_text': False,  # opt-in previews of the heard phrase and stdout;
                                       # commands and URLs are never written, at any level
    'intents_log_max_chars': 200,  # one preview's length, 100..8000
    'intents_log_max_lines': 2000,  # JSONL lines kept in STATE_DIR/user-intents.log
    'intents': True,          # the tiny trained mind (yumi/intents.py) hears the
                              # phrases the sayings miss; tools/intents_setup.sh
    'wake_word': 'юми',       # the wake word itself (say it, then the question);
                              # the ears learn its hear-says into
                              # ~/.local/share/yumi/stt/hearsay.json, edit freely
    'wake_sensitivity': 'normal',   # normal / strict: how sharply the wake word must match
    'wake_confirm': True,   # let whisper double-check every vosk guess before waking
    'wake_model_size': 'small',   # small / big: the model the wake ear listens with
    'wake_ear': 'auto',     # the ear that catches her name: auto (the trained
                            # openWakeWord ear when its model is here, vosk
                            # otherwise) / oww / vosk; vosk guessed the name by
                            # ear, the trained one learned it
    'oww_spike': 2,           # frames in a row over the line before the name is
                              # believed: one loud frame is a knock, not a name
    'oww_positive_ms': 160,   # ms the believed stretch must last over the line
    'oww_confirm': True,      # a medium-confidence name is checked against the
                              # tape: the phrase ear must hear the name or a command
    'oww_confirm_below': 0.8, # scores below this line need that confirmation
    'oww_reject_cooldown': 5.0,  # s of quiet after a rejected candidate
    'wake_judge_log': True,    # write what the judge hears into /tmp/yumi/judge.log
    'name_duck': False,        # when her name is heard, the sounds duck so she can
                               # hear the phrase; the old loudness returns after it,
                               # a volume command she keeps
    'stt_size': 'small',      # her hearing: small (45 MB) / big (a sharper ~1.8 GB model)
    'stt_engine': 'whisper',  # who reads the phrases: whisper / nemotron (a streaming
                              # 0.6b ear, ~650 MB, tools/nemotron_setup.sh; faster)
    'stt_beam': 5,            # how widely the phrase ear searches while decoding: whisper's
                              # beam_size / nemotron's max_active_paths. Greedy decoding
                              # can mangle rare words; a wider beam often keeps the word
                              # whole, at the cost of a little more CPU
    'stt_hotwords': '',       # extra words the phrase ear must keep whole (comma-separated).
                              # Empty by default: vosk's reading of the same tape already
                              # spells them for whisper; add rare names or commands here
    # the second ear is used by the local command matcher only: never sent to the mind
    'stt_mic': None,          # which microphone the ears hear with: None = auto (the desktop's pick)
    'stt_echo': True,         # the webrtc echo canceller around the mic; false = plain mic only
    'stt_selfmute': True,     # the ears close while she speaks, so she never hears
                              # herself; works with the plain mic too (no canceller)
    'speaker_verify': False,  # recognise voices: a known voice may continue the
                              # dialogue without the wake word, strangers stay out
    'speaker_threshold': 0.65,  # cosine line for a known voice (0..1)
    'speaker_min_ms': 1200,   # minimum clean voice for a new profile
    'speaker_join_policy': 'addressed',  # addressed / strict / off: how a new
                              # voice joins an open dialogue
    'phrase_tail_ms': 1200,   # ms of quiet that ends a phrase: raise it when she cuts you
                              # off during your pauses, lower it when answers come too slow
    'wake_after': 1.5,        # s of quiet after the name before the half-heard words count
    'wake_read_s': 4.0,       # s of the phrase after the name the ear reads: a command is
                              # short, a longer window buys latency, not words
    'tap_ears': False,        # a diary of everything the ears hear: /tmp/yumi (sound + words)
    'hourly_chimes': True,    # she speaks the time with a joke every hour
    'weather_city': 'Анапа',  # the city she peeks the weather at ('' = wherever she is);
                              # say it in the phrase («юми погода в ялте») or edit
                              # ~/.config/yumi/settings.json → "weather_city": "Ялта"
    'music_source': 'auto',   # where the songs come from: auto (Jellyfin when home,
                              # folders when away) / jellyfin / local
    'music_jellyfin': '',     # the Jellyfin server's address (http://192.168.0.189:8096);
                              # when it answers, the songs come from its library
    'music_jellyfin_user': '',      # the Jellyfin login (and the password below);
                              # or put a "music_jellyfin_key" api key instead —
                              # both live in ~/.config/yumi/settings.json
    'music_jellyfin_password': '',
    'music_dirs': '',         # extra local folders, comma-separated
                              # ("~/Музыка, /mnt/nas/музыка"); the xdg music folder
                              # is always read
    'music_server': '',       # a remote mpd to play on, 'password@host:port'
                              # — the middle of the chain: when Jellyfin sleeps,
                              # its library answers, the songs play there and
                              # come home through the httpd stream below
                              # (empty = no server step, her folders instead)
    'music_stream': '',       # the server mpd's httpd stream to pull the sound
                              # home by (http://192.168.0.189:8123); without it
                              # the server's songs sound on the server
    'web_panel': False,       # the browser panel (off by default: no port is opened)
    'web_panel_host': '127.0.0.1',   # 127.0.0.1 only this machine sees it; 0.0.0.0 = LAN
    'web_panel_port': 8765,   # where the browser panel listens
    'web_panel_open': False,  # open the browser when the panel is switched on
    'web_panel_session_hours': 168,  # how long a browser session stays signed in
}

# the Silero profile lives in ~/.config/yumi/tts.json (the daemon's own file);
# these settings are its copy, so the panel and the in-world menu can edit it
TTS_PROFILE_KEYS = {
    'tts_ru_speaker': 'ru_speaker',
    'tts_en_speaker': 'en_speaker',
    'tts_ru_model': 'ru_model',
    'tts_pitch': 'pitch',
}
TTS_PROFILE_DEFAULTS = {key: DEFAULT_SETTINGS[key] for key in TTS_PROFILE_KEYS}

DEFAULT_STATE = {
    'mode': 'docked',         # docked / air
    'dock_x': None,           # foot x when docked (None = bottom-right corner)
    'air': None,              # [x, y] foot position when floating
    'shelf': [],              # paths kept on her shelf
    'colors': [],             # pipette history, newest first
    'intro_done': False,      # the first-run tour has been shown
    'monitor': None,          # connector name of the screen she lives on (None = first one)
}


def detect_lang():
    """'ru' when the system language is Russian, otherwise 'en'"""
    for var in ('LC_ALL', 'LC_MESSAGES', 'LANGUAGE', 'LANG'):
        val = os.environ.get(var, '')
        if val:
            return 'ru' if val.lower().replace('-', '_').startswith('ru') else 'en'
    return 'en'


class Store(dict):
    """A dict saved as JSON; unknown keys from older versions are kept, missing ones defaulted."""

    def __init__(self, path, defaults):
        super().__init__(defaults)
        self.path = Path(path)
        self.fresh = not self.path.exists()
        try:
            data = json.loads(self.path.read_text())
            if isinstance(data, dict):
                self.update(data)
            elif self.path.exists():
                raise ValueError('not a JSON object')
        except OSError:
            pass
        except ValueError:                 # like load_actions(): never overwrite a broken file
            try:
                self.path.replace(self.path.with_name(self.path.name + '.bad'))
                print(f'yumi: {self.path.name} was broken, kept as {self.path.name}.bad',
                      file=sys.stderr)
            except OSError:
                pass

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(self, indent=1, ensure_ascii=False))
            tmp.replace(self.path)
        except OSError:
            pass


def _adopt_tts_profile(st):
    """tts.json stays editable by hand: its profile wins when Yumi starts, so a
    manual tweak is never overwritten by the defaults in settings.json"""
    try:
        data = json.loads((CONFIG_DIR / 'tts.json').read_text())
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    for key, name in TTS_PROFILE_KEYS.items():
        if name in data and data[name] is not None:
            st[key] = data[name]


def load_settings():
    st = Store(CONFIG_DIR / 'settings.json', DEFAULT_SETTINGS)
    if st.fresh:                                  # first run: speak the system language
        st['ui_lang'] = st['speech_lang'] = detect_lang()
        st.save()
    _adopt_tts_profile(st)
    return st


RING_SLOTS = 11            # places on her ring in the button editor (one free beside the built-ins)

# the entities a button may say it understands (yumi/entities.py); kept here as
# a plain list so this low-level file needs no import of the NLU
ACTION_ENTITIES = frozenset(('volume', 'time', 'date'))


def _as_int(value, default=0, low=-100, high=100):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on', 'да')
    return default


def _as_entities(value):
    """the known entity names of a button, as {'volume': True, ...}; a bad
    spelling is dropped instead of spoiling the whole entry"""
    if isinstance(value, dict):
        names = [k for k, v in value.items() if v]
    elif isinstance(value, (list, tuple, set)):
        names = list(value)
    else:
        names = []
    return {str(k): True for k in names[:8] if str(k) in ACTION_ENTITIES}


def load_actions(path=None):
    """her own round buttons from ~/.config/yumi/actions.json:
    [{"label": "Terminal", "label_ru": "Терминал", "icon": "gear", "command": "foot"}]"""
    path = Path(path) if path else ACTIONS_FILE
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, list):
            raise ValueError
    except OSError:
        return []
    except ValueError:                    # the editor would overwrite a file with a typo in it
        try:
            path.replace(path.with_name(path.name + '.bad'))
        except OSError:
            pass
        return []
    out = []
    for a in data:
        if isinstance(a, dict) and a.get('command'):
            out.append({'label': str(a.get('label') or a['command'])[:18],
                        'label_ru': str(a.get('label_ru') or a.get('label') or a['command'])[:18],
                        'icon': str(a.get('icon') or 'star'), 'command': str(a['command']),
                        # the voice side (nlu.py): the sayings that run this button
                        'phrases': [str(p) for p in (a.get('phrases') or []) if str(p).strip()],
                        'keywords': [str(k) for k in (a.get('keywords') or []) if str(k).strip()],
                        'speak': str(a.get('speak') or '').strip(),
                        # a web address instead of a command ({query} = the words said beside the trigger)
                        'url': str(a.get('url') or '').strip(),
                        # the declarative side of a voice command (all optional:
                        # old buttons keep working with the defaults below)
                        'id': str(a.get('id') or '').strip()[:64],
                        'priority': _as_int(a.get('priority')),
                        'requires_confirmation': _as_bool(a.get('requires_confirmation')),
                        'entities': _as_entities(a.get('entities'))})
    return out


def save_actions(actions, path=None):
    path = Path(path) if path else ACTIONS_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(actions, indent=1, ensure_ascii=False))
        tmp.replace(path)
    except OSError:
        pass


def keep_icon(src):
    """a copy of the chosen picture in the config, so it outlives the original file"""
    src = Path(src)
    try:
        # shortcut: copies stay behind when a button is deleted (two buttons may share one), they are tiny
        out = CONFIG_DIR / 'icons' / (hashlib.sha1(src.read_bytes()).hexdigest()[:16] + src.suffix)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out)
        return str(out)
    except OSError:
        return str(src)


def outfit_for(today=None):
    """the outfit folder the calendar asks for (None = her usual clothes)"""
    import datetime
    d = today or datetime.date.today()
    md = (d.month, d.day)
    for name, (a, b) in OUTFIT_DATES.items():
        inside = a <= md <= b if a <= b else (md >= a or md <= b)
        if inside:
            return name
    return None


OUTFIT_DATES = {            # name: ((month, day) from, (month, day) to)
    'halloween': ((10, 24), (11, 2)),
    'newyear': ((12, 15), (1, 10)),
    'valentine': ((2, 12), (2, 15)),
    'spring': ((3, 6), (3, 9)),
}


def load_state():
    return Store(STATE_DIR / 'state.json', DEFAULT_STATE)


# ---- interface strings ----
UI = {
    'en': {
        'recent': 'Recent', 'shelf': 'Shelf', 'pipette': 'Pipette', 'clock': 'Time',
        'sleep': 'DND', 'wake': 'Wake up', 'settings': 'Settings', 'home': 'Go home', 'quit': 'Quit',
        'convert': 'Convert', 'compress': 'Compress', 'keep': 'Keep on shelf',
        'unkeep': 'Off the shelf', 'back': 'Back', 'empty_recent': 'Nothing new yet',
        'empty_shelf': 'Drop files on me to keep them here', 'ui_lang': 'Interface',
        'speech_lang': 'Speech', 'reactions': 'System reactions', 'chatter': 'Chatter', 'pinned': 'Stay out',
        'chatter_facts': 'Facts in chatter', 'cf_off': 'none', 'cf_mixed': 'mixed', 'cf_only': 'facts only',
        'on': 'on', 'off': 'off', 'colors': 'Colors', 'to': 'to', 'working': 'Working',
        'open': 'Open', 'files': '{n} files', 'cancel': 'Cancel',
        'p_small': 'Smaller', 'p_1mb': 'Under 1 MB', 'p_half': 'Half size',
        'p_10': 'Under 10 MB', 'p_25': 'Under 25 MB', 'p_50': 'Under 50 MB',
        'p_720': '720p', 'p_480': '480p', 'p_opus': 'Opus 96k', 'p_mp3': 'MP3 128k',
        'p_lossless': 'Lossless',
        'convert_to': 'Convert to', 'compress_how': 'Compress', 'follow': 'Wallpaper colors',
        'timer': 'Timer', 'pause': 'Pause', 'resume': 'Start', 'reset': 'Reset', 'stop': 'Stop', 'picked': 'Picked',
        'timer_sound': 'Timer sound', 'sound_default': '8-bit', 'sound_reset': 'Default sound',
        'sound_test': 'Listen', 'audio_files': 'Sounds',
        'hint': 'Drag a file onto me to convert, compress or keep it',
        'breaks': 'Health breaks', 'idle_nap': 'Nap when idle', 'outfit': 'Outfit',
        'voice': 'Voice', 'voice_kind': 'Voice type', 'v_blips': '8-bit', 'v_tts': 'Real voice',
        'tts_ru_speaker': 'Russian voice', 'tts_en_speaker': 'English voice',
        'tts_ru_model': 'Russian voice model', 'tts_pitch': 'Voice pitch',
        'cat_her': 'Her', 'cat_sound': 'Sound', 'cat_look': 'Look', 'cat_lang': 'Language', 'n_a': 'not available yet', 'o_auto': 'auto', 'o_off': 'none', 'o_halloween': 'Halloween', 'o_newyear': 'New Year',
        'o_valentine': 'Valentine', 'o_spring': 'March 8', 'min': 'min', 'ms': 'ms', 'monitor': 'Screen',
        'cat_ring': 'Buttons', 'ring_done': 'Done', 'ring_new': 'New button', 'ring_change': 'Edit button', 'ring_save': 'Save',
        'ring_cmd': 'Command', 'ring_name': 'Button name', 'ring_icon': 'Icon', 'ring_file': 'Your own picture...',
        'ring_phrases': 'Say', 'ring_keywords': 'Keywords', 'ring_speak': 'Reply',
        'ring_url': 'URL ({query} = words)', 'ring_id': 'Command id',
        'ring_priority': 'Priority', 'ring_confirm': 'Ask first',
        'confirm_ask': 'Run it?', 'confirm_yes': 'Okay, running it.',
        'confirm_no': 'Okay, cancelled.',
        'intent_no_answer': 'No answer this time.',
        'ring_add': 'Add', 'images': 'Pictures',
        'restart': 'Restart', 'tour_again': 'Show the tour', 'tour_next': 'Next', 'tour_skip': 'Skip', 'tour_done': 'Got it!',
        'tour_title': 'Hello!',
        'listen': 'Listen', 'cat_chat': 'Her mind', 'chat_model': 'Answer model',
        'nlu': 'Voice commands',
        'intents': 'Intents mind',
        'intents_log_level': 'Action log',
        'il_off': 'off', 'il_error': 'errors', 'il_result': 'results',
        'il_action': 'actions', 'il_match': 'matches', 'il_trace': 'everything',
        'joke': 'Joke',
        'chat_refresh': 'Find the model',
        'chat_think': 'Let her think first',
        'chat_stream': 'Speak while answering',
        'sassy': 'Sassy 18+',
        'chat_history_n': 'Messages in mind', 'chat_memory': 'Recall older talks',
        'conversation_mode': 'Keep talking without the name',
        'conversation_timeout_s': 'Seconds before she stops listening',
        'conversation_gap_reset_min': 'Minutes before a talk starts fresh',
        'conversation_history_n': 'Messages in an active talk',
        'ears': 'Ears', 'ears_on': 'Ears on', 'ears_off': 'Ears off',
        'wake_ears': 'Wake when you say «Yumi»', 'stt_engine': 'Ear for phrases',
        'eng_whisper': 'Whisper', 'eng_nemotron': 'Nemotron 0.6b (fast)',
        'stt_size': 'Whisper ear size', 'e_small': 'Lite (~460 MB)',
        'name_duck': 'Duck sounds when she hears «Yumi»', 'e_big': 'Sharp (~1.5 GB)', 'cat_ears': 'Her ears', 'stt_mic': 'Microphone',
        'wake_sensitivity': 'How strictly to listen for «Yumi»', 'wake_sensitivity_normal': 'Normal',
        'wake_sensitivity_strict': 'Strict', 'wake_confirm': 'Double-check the name with whisper',
        'wake_model_size': 'Ear for the name «Yumi» (vosk)', 'w_small': 'Lite (45 MB)', 'w_big': 'Sharp (~1.8 GB)',
        'wake_ear': 'The ear that hears «Yumi»', 'we_auto': 'auto (the trained ear when it is here)',
        'we_oww': 'the trained ear (openWakeWord)', 'we_vosk': 'vosk, as before', 'wake_judge_log': 'Write the whisper judge to /tmp/yumi/judge.log',
        'mic_refresh': 'Find the microphone', 'mic_auto': 'auto', 'chat_provider': 'Mind provider',
        'polza_url': 'Polza.ai address', 'polza_api_key': 'Polza.ai API key',
        'tap_ears': 'Write everything it hears (/tmp/yumi)',
        'stt_echo': 'Echo canceller (she never hears herself)',
        'speaker_verify': 'Recognise voices in a talk',
        'speaker_threshold': 'Voice match line',
        'speaker_min_ms': 'Clean voice needed (ms)',
        'speaker_join_policy': 'When a new voice joins',
        'sp_addressed': 'when addressed', 'sp_strict': 'twice in a row',
        'sp_off': 'never',
        'speaker_enroll': 'Record my voice', 'speaker_test': 'Check my voice',
        'speaker_list': 'Voice profiles', 'speaker_rename': 'Rename',
        'speaker_delete': 'Delete', 'speaker_rename_title': 'New voice name',
        'speaker_rename_save': 'Save',
        'speaker_clear': 'Forget the voices in this talk',
        'speaker_status': 'Voices here now',
        'speaker_on': 'I know your voice now.',
        'speaker_off': 'I won\'t tell voices apart now.',
        'speaker_fail': 'I could not hear a clean voice (recording took too long).',
        'speaker_ready': 'Your voice is recorded: {label}',
        'speaker_renamed': 'That voice is now called {label}.',
        'speaker_found': 'That is {label}, I think.',
        'speaker_unknown': 'That voice is new to me.',
        'acquaintance': 'Get acquainted',
        'acquaintance_intro': 'Let\'s get acquainted! Say your name, what city you live in, what music you like, where you work, and your hobbies. I\'ll remember your voice and get to know you.',
        'acquaintance_again': 'I\'ll listen again. Say your name, city, music, work, and hobbies in your normal voice.',
        'acquaintance_ok': 'Nice to meet you, {label}! I remembered your voice and what you told me.',
        'acquaintance_fail': 'I couldn\'t catch a clean voice. Let\'s try again when it\'s quieter.',
        'acquaintance_nomodel': 'The voice model is not ready yet. Run tools/speaker_setup.sh first.',
        'acquaintance_already': 'We already know each other, {label}!',
        'hourly_chimes': 'She says the time every hour',
        'clock_status': 'Clock: {n} jobs, next {at}',
        'tour1': "Hi! I'm Yumi. I live at the bottom edge of your screen. Let me show you around.",
        'tour2': 'Click me and round buttons appear: files, shelf, pipette, timer, Do Not Disturb and settings.',
        'tour3': 'Scroll the wheel over me for a timer. Click its digits to type a time.',
        'tour4': 'Drop files on me to convert or compress them. Hold me by the scruff to move me anywhere.',
        'tour5': 'Middle-click pins me so I stop hiding. The rest is in the gear: language, colors, outfits.',
        'B': 'B', 'KB': 'KB', 'MB': 'MB', 'GB': 'GB',
        'cat_music': 'Music', 'music_source': 'Where the songs come from',
        'm_auto': 'auto (Jellyfin at home)', 'm_jellyfin': 'Jellyfin',
        'm_local': 'my folders', 'music_skill': 'Music control by voice',
        'cat_web': 'Browser panel', 'web_panel': 'Browser panel',
        'web_open': 'Open in the browser', 'web_copy': 'Copy the link',
        'web_rotate': 'New link', 'web_on': 'The panel is at {url}',
        'web_fail': 'The panel did not start: {err}',
        'web_off': 'The browser panel is off (it opens no port)',
    },
    'ru': {
        'recent': 'Недавние', 'shelf': 'Полка', 'pipette': 'Пипетка', 'clock': 'Время',
        'sleep': 'Не мешать', 'wake': 'Разбудить', 'settings': 'Настройки', 'home': 'Домой', 'quit': 'Выйти',
        'convert': 'Конвертировать', 'compress': 'Сжать', 'keep': 'На полку',
        'unkeep': 'Убрать с полки', 'back': 'Назад', 'empty_recent': 'Пока ничего нового',
        'empty_shelf': 'Кидай на меня файлы, я их тут сохраню', 'ui_lang': 'Интерфейс',
        'speech_lang': 'Реплики', 'reactions': 'Реакции на систему', 'chatter': 'Болтовня', 'pinned': 'Не прятаться',
        'chatter_facts': 'Факты в болтовне', 'cf_off': 'нет', 'cf_mixed': 'вперемешку', 'cf_only': 'только факты',
        'on': 'вкл', 'off': 'выкл', 'colors': 'Цвета', 'to': 'в', 'working': 'Работаю',
        'open': 'Открыть', 'files': 'файлов: {n}', 'cancel': 'Отмена',
        'p_small': 'Поменьше', 'p_1mb': 'До 1 МБ', 'p_half': 'В два раза меньше',
        'p_10': 'До 10 МБ', 'p_25': 'До 25 МБ', 'p_50': 'До 50 МБ',
        'p_720': '720p', 'p_480': '480p', 'p_opus': 'Opus 96k', 'p_mp3': 'MP3 128k',
        'p_lossless': 'Без потерь',
        'convert_to': 'Конвертировать в', 'compress_how': 'Сжать', 'follow': 'Цвета от обоев',
        'timer': 'Таймер', 'pause': 'Пауза', 'resume': 'Старт', 'reset': 'Сброс', 'stop': 'Стоп', 'picked': 'Пипетка',
        'timer_sound': 'Звук таймера', 'sound_default': '8-бит', 'sound_reset': 'Вернуть стандартный',
        'sound_test': 'Прослушать', 'audio_files': 'Звуки',
        'hint': 'Перетащи файл на меня: сконвертирую, сожму или сохраню',
        'breaks': 'Перерывы', 'idle_nap': 'Дремать без тебя', 'outfit': 'Наряд',
        'voice': 'Голосок', 'voice_kind': 'Тип голоска', 'v_blips': 'Пищалка', 'v_tts': 'Настоящий',
        'tts_ru_speaker': 'Русский голос', 'tts_en_speaker': 'Английский голос',
        'tts_ru_model': 'Модель русского голоса', 'tts_pitch': 'Высота голоса',
        'cat_her': 'Поведение', 'cat_sound': 'Звук', 'cat_look': 'Внешний вид', 'cat_lang': 'Язык', 'n_a': 'пока недоступно', 'o_auto': 'авто', 'o_off': 'нет', 'o_halloween': 'Хэллоуин', 'o_newyear': 'Новый год',
        'hourly_chimes': 'Каждый час она говорит время',
        'o_valentine': 'Валентинка', 'o_spring': '8 Марта', 'min': 'мин', 'ms': 'мс', 'monitor': 'Экран',
        'cat_ring': 'Кнопки', 'ring_done': 'Готово', 'ring_new': 'Новая кнопка', 'ring_change': 'Изменить кнопку', 'ring_save': 'Сохранить',
        'ring_cmd': 'Команда', 'ring_name': 'Название кнопки', 'ring_icon': 'Иконка', 'ring_file': 'Своя картинка...',
        'ring_phrases': 'Фразы', 'ring_keywords': 'Ключевые слова', 'ring_speak': 'Ответ',
        'ring_url': 'Адрес ({query} = слова)', 'ring_id': 'ID команды',
        'ring_priority': 'Приоритет', 'ring_confirm': 'Спрашивать',
        'confirm_ask': 'Запустить?', 'confirm_yes': 'Ладно, запускаю.',
        'confirm_no': 'Ладно, отменила.',
        'intent_no_answer': 'На этот раз ответа нет.',
        'ring_add': 'Добавить', 'images': 'Картинки',
        'restart': 'Перезапустить', 'tour_again': 'Показать знакомство', 'tour_next': 'Дальше', 'tour_skip': 'Пропустить', 'tour_done': 'Поняла!',
        'tour_title': 'Привет!',
        'listen': 'Послушать', 'cat_chat': 'Её мозги', 'chat_model': 'Модель ответов',
        'nlu': 'Голосовые команды',
        'intents': 'Распознавание фраз',
        'intents_log_level': 'Журнал действий',
        'il_off': 'выкл', 'il_error': 'ошибки', 'il_result': 'результаты',
        'il_action': 'действия', 'il_match': 'совпадения', 'il_trace': 'всё',
        'joke': 'Анекдот',
        'chat_refresh': 'Найти модель',
        'chat_think': 'Дать ей подумать',
        'chat_stream': 'Озвучивать по мере ответа',
        'sassy': 'Дерзкая 18+',
        'chat_history_n': 'Сообщений в памяти', 'chat_memory': 'Помнить разговоры',
        'conversation_mode': 'Продолжать без повтора имени',
        'conversation_timeout_s': 'Секунд тишины до конца диалога',
        'conversation_gap_reset_min': 'Минут до нового разговора',
        'conversation_history_n': 'Сообщений в активном диалоге',
        'ears': 'Ушки', 'ears_on': 'Ушки вкл', 'ears_off': 'Ушки выкл',
        'wake_ears': 'Будить, когда скажешь «Юми»', 'stt_engine': 'Ухо для фраз',
        'eng_whisper': 'Whisper', 'eng_nemotron': 'Nemotron 0.6b (быстрое)',
        'stt_size': 'Размер whisper-уха', 'e_small': 'Лёгкая (~460 МБ)',
    'music_skill': 'Умение управлять музыкой',
        'name_duck': 'Приглушать звуки при имени',
        'e_big': 'Точная (~1.5 ГБ)', 'cat_ears': 'Её ушки', 'stt_mic': 'Микрофон',
        'wake_sensitivity': 'Как строго слушать «Юми»', 'wake_sensitivity_normal': 'Обычная',
        'wake_sensitivity_strict': 'Строгая', 'wake_confirm': 'Перепроверять имя whisper-ом',
        'wake_model_size': 'Ухо для имени «Юми» (vosk)', 'w_small': 'Лёгкая (45 МБ)', 'w_big': 'Точная (~1.8 ГБ)', 'wake_judge_log': 'Записывать судью-whisper в /tmp/yumi/judge.log',
        'wake_ear': 'Кто слушает имя «Юми»', 'we_auto': 'авто (обученное ухо, когда оно тут)',
        'we_oww': 'обученное ухо (openWakeWord)', 'we_vosk': 'vosk, как раньше',
        'mic_refresh': 'Найти микрофон', 'mic_auto': 'авто',
        'chat_provider': 'Провайдер мозгов', 'polza_url': 'Адрес Polza.ai', 'polza_api_key': 'Ключ Polza.ai',
        'tap_ears': 'Записывать всё услышанное (/tmp/yumi)',
        'stt_echo': 'Подавление эха (не слышит себя)',
        'speaker_verify': 'Различать голоса в разговоре',
        'speaker_threshold': 'Порог совпадения голоса',
        'speaker_min_ms': 'Чистого голоса нужно (мс)',
        'speaker_join_policy': 'Когда присоединяется новый голос',
        'sp_addressed': 'когда обратился', 'sp_strict': 'дважды подряд',
        'sp_off': 'никогда',
        'speaker_enroll': 'Записать мой голос', 'speaker_test': 'Проверить мой голос',
        'speaker_list': 'Список голосов', 'speaker_rename': 'Переименовать',
        'speaker_delete': 'Удалить', 'speaker_rename_title': 'Новое имя голоса',
        'speaker_rename_save': 'Сохранить',
        'speaker_clear': 'Забыть голоса в этом разговоре',
        'speaker_status': 'Голоса сейчас тут',
        'speaker_on': 'Теперь я знаю твой голос.',
        'speaker_off': 'Больше не буду различать голоса.',
        'speaker_fail': 'Не расслышала чистый голос (запись заняла слишком много времени).',
        'speaker_ready': 'Голос записан: {label}',
        'speaker_renamed': 'Теперь этот голос зовётся {label}.',
        'speaker_found': 'Кажется, это {label}.',
        'speaker_unknown': 'Этот голос мне незнаком.',
        'acquaintance': 'Познакомиться',
        'acquaintance_intro': 'Давай познакомимся! Назови своё имя, город, где ты живёшь, какую музыку любишь, где работаешь и чем увлекаешься. Я запомню твой голос и узнаю тебя лучше.',
        'acquaintance_again': 'Слушаю ещё раз. Назови имя, город, музыку, работу и хобби обычным голосом.',
        'acquaintance_ok': 'Приятно познакомиться, {label}! Я запомнила твой голос и то, что ты рассказал.',
        'acquaintance_fail': 'Не получилось расслышать чистый голос. Попробуем ещё раз, когда будет потише.',
        'acquaintance_nomodel': 'Модель голосов ещё не готова. Сначала запусти tools/speaker_setup.sh.',
        'acquaintance_already': 'Мы уже знакомы, {label}!',
        'hourly_chimes': 'Каждый час она говорит время',
        'clock_status': 'Часы: {n} задач, ближайшие {at}',
        'tour1': 'Привет! Я Юми. Я живу у нижнего края твоего экрана. Давай я всё покажу.',
        'tour2': 'Нажми на меня, и вокруг появятся кружочки: файлы, полка, пипетка, таймер, «Не мешать» и настройки.',
        'tour3': 'Покрути колёсико над мной, и появится таймер. Кликни по цифрам, чтобы вписать время.',
        'tour4': 'Кидай на меня файлы, и я их сконвертирую или сожму. Возьми меня за шкирку, чтобы поставить где угодно.',
        'tour5': 'Средний клик закрепляет меня, чтобы я не пряталась. Остальное в шестерёнке: язык, цвета, наряды.',
        'B': 'Б', 'KB': 'КБ', 'MB': 'МБ', 'GB': 'ГБ',
        'cat_music': 'Музыка', 'music_source': 'Откуда брать песни',
        'm_auto': 'авто (Джеллифин дома)', 'm_jellyfin': 'Jellyfin',
        'm_local': 'мои папки', 'music_skill': 'Управление музыкой голосом',
        'cat_web': 'Веб-панель', 'web_panel': 'Панель в браузере',
        'web_open': 'Открыть в браузере', 'web_copy': 'Скопировать ссылку',
        'web_rotate': 'Новая ссылка', 'web_on': 'Панель тут: {url}',
        'web_fail': 'Панель не запустилась: {err}',
        'web_off': 'Веб-панель выключена (порт не открывается)',
    },
}


def tr(settings, key, **kw):
    lang = settings.get('ui_lang', 'en')
    text = UI.get(lang, UI['en']).get(key) or UI['en'].get(key, key)
    return text.format(**kw) if kw else text
