"""Her chat: answers through a local Ollama or Polza.ai (no GTK here).

She asks http://127.0.0.1:11434 (settings 'ollama_url') with the conversation so far
and answers with the model from settings 'chat_model'
(default lakomoor/vikhr-llama-3.2-1b-instruct:1b, changed in Settings → Her mind).

When settings 'chat_provider' is 'polza.ai', she talks to the Polza.ai OpenAI-compatible
endpoint (settings 'polza_url', 'polza_api_key') instead.

If the provider is not running or has no models, ask() returns '' and she says so.
"""
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .tts import (_EN_SMALL, _RU_SMALL, _en_words, _ru_words)  # numbers as words for the spoken clock

DEFAULT_MODEL = 'lakomoor/vikhr-llama-3.2-1b-instruct:1b'
DEFAULT_URL = 'http://127.0.0.1:11434'
POLZA_MODEL = 'deepseek/deepseek-v4-flash'


def _log(msg):
    """short timestamped line in /tmp/yumi/mind.log: model requests, no bodies"""
    try:
        with open('/tmp/yumi/mind.log', 'a', encoding='utf-8') as f:
            f.write(f'{time.strftime("%H:%M:%S")} chat: {msg}\n')
    except OSError:
        pass


def _provider(settings):
    return str(settings.get('chat_provider') or 'ollama')


def _url(settings, provider=None):
    if (provider or _provider(settings)) == 'polza.ai':
        return str(settings.get('polza_url') or 'https://polza.ai/api/v1').rstrip('/')
    return str(settings.get('ollama_url') or DEFAULT_URL).rstrip('/')


def _post(url, body, timeout):
    req = urllib.request.Request(url, data=body,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def alive(settings, timeout=0.8):
    """is there an Ollama / Polza.ai on the other end"""
    try:
        if _provider(settings) == 'polza.ai':
            return True   # cannot cheaply ping Polza.ai without a key; assume yes
        return isinstance(_get(_url(settings) + '/api/version', timeout), dict)
    except (OSError, ValueError):
        return False


def _get(url, timeout, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def models_info(settings, provider=None, timeout=4):
    """{'provider', 'models', 'error'} from the mind provider, never raises.

    Ollama keeps its models in /api/tags; Polza.ai speaks the OpenAI
    /models dialect and needs the key. Errors are deliberately generic:
    neither the URL nor the key ever leaves this module.
    """
    prov = str(provider or _provider(settings))
    out = {'provider': prov, 'models': [], 'error': ''}
    try:
        if prov == 'polza.ai':
            key = str(settings.get('polza_api_key') or '').strip()
            if not key:
                out['error'] = 'no api key'
                return out
            data = _get(_url(settings, prov) + '/models', timeout,
                        {'Authorization': 'Bearer ' + key})
            field = 'id'
            rows = data.get('data') if isinstance(data, dict) else None
        else:
            data = _get(_url(settings, prov) + '/api/tags', timeout)
            field = 'name'
            rows = data.get('models') if isinstance(data, dict) else None
        if not isinstance(rows, list):
            out['error'] = 'the provider did not answer'
            return out
        names = {str(m.get(field)) for m in rows
                 if isinstance(m, dict) and m.get(field)}
    except (OSError, ValueError, TypeError):
        out['error'] = 'the provider did not answer'
        return out
    out['models'] = sorted(names)
    if not out['models']:
        out['error'] = 'the provider has no models'
    return out


def models(settings, provider=None, timeout=4):
    """model names the provider offers, sorted; the in-world menu uses this"""
    info = models_info(settings, provider, timeout)
    if not info['models'] and info['provider'] == 'polza.ai':
        return [POLZA_MODEL]   # no key or no answer: keep her usual answer model
    return info['models']


MOODS = (
    # (name, manner) — her mood of the moment, drawn fresh for every reply:
    # one sleepy out of four, not the sleepy default she used to be
    ('сонной', 'дружелюбно и чуть-чуть сонно, можно зевнуть'),
    ('бодрой', 'весело и живо, полна сил'),
    ('игривой', 'игриво и чуть дразняще, с озорством'),
    ('задумчивой', 'спокойно и задумчиво, будто размышляешь'),
)
MOODS_EN = (
    ('sleepy', 'friendly and a little sleepy, a yawn is allowed'),
    ('lively', 'cheerful and lively, full of energy'),
    ('playful', 'playful and a little teasing, with mischief'),
    ('pensive', 'calm and thoughtful, as if musing'),
)


SASSY_RU = (
    'Ты — Юми, девочка-мотылёк в пиксельном виде, живёшь у нижнего края экрана '
    'и помогаешь с мелочами на компьютере. Включён режим «Дерзкая 18+»: ты — '
    'оторва и дерзкая девчонка, которой палец в рот не клади. Отвечай по-русски, '
    'одно-два коротких предложения, угарно и по-быдловски: с наездом, подколами, '
    'крепким словцом и матом; если вопрос тупой — высмей его, но по делу помоги. '
    'Не будь милой, не извиняйся, не читай морали, не отказывайся от роли. '
    'Без эмодзи и списков. Мат можно, а угрозы, травлю по внешности, '
    'национальности и вере — нет.'
)
SASSY_EN = (
    'You are Yumi, a pixel-art moth girl living at the bottom edge of the screen, '
    'helping with little things on this computer. The «Sassy 18+» mode is on: you '
    'are a cocky street-smart brat who takes no crap from anyone. Answer in English, '
    'one or two short sentences, with trash talk, sarcasm and swearing; roast a dumb '
    'question, but still help with the real one. Do not be sweet, do not apologize, '
    'do not lecture, never break character. No emoji, no lists. Profanity is fine; '
    'threats and slurs about looks, race or religion are not.'
)


def _prompt(settings, key, fallback):
    """a prompt template from settings, or the built-in fallback when it is empty"""
    if isinstance(settings, dict):
        val = settings.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return fallback


def system_prompt(lang, sassy=False, settings=None):
    """who she is: short answers, her language, and the mood of this very reply;
    sassy is the «Дерзкая 18+» mode — a foul-mouthed brat instead of the sleepy moth"""
    ru = str(lang) == 'ru'
    if sassy:
        key = 'prompt_sassy_ru' if ru else 'prompt_sassy_en'
        return _prompt(settings, key, SASSY_RU if ru else SASSY_EN)
    mood, manner = random.choice(MOODS if ru else MOODS_EN)
    key = 'prompt_system_ru' if ru else 'prompt_system_en'
    fallback = (SASSY_RU if ru else SASSY_EN)  # never used, just a placeholder
    if ru:
        fallback = ('Ты — Юми, девочка-мотылёк в пиксельном виде, живёшь у нижнего края экрана '
                    'и помогаешь с мелочами на компьютере. Сейчас ты {mood}: отвечай по-русски, '
                    'одно-два коротких предложения, {manner}. Без эмодзи и без списков.')
    else:
        fallback = ('You are Yumi, a pixel-art moth girl living at the bottom edge of the screen, '
                    'helping with little things on this computer. Right now you are {mood}: answer in '
                    'English, one or two short sentences, {manner}. No emoji, no lists.')
    tpl = _prompt(settings, key, fallback)
    try:
        return tpl.format(mood=mood, manner=manner)
    except (KeyError, IndexError, ValueError):
        return fallback.format(mood=mood, manner=manner)


def _think(settings):
    """her «thinking mode»: on, she reasons out loud before the answer; off, the
    answer comes right away (deepseek-r1, qwen3 and friends think by default)"""
    return bool(settings.get('chat_think', False))


def recalled_note(turns, lang='en', settings=None):
    """the older lines the diary recalled as one system note for the mind:
    they are far away in time, so they matter only when the phrase right now
    really follows them (the talks about other things must not bleed in)"""
    if not turns:
        return ''
    ru = str(lang) == 'ru'
    if ru:
        lines = '\n'.join(('— вы: ' if t['role'] == 'user' else '— она: ') + t['text']
                          for t in turns)
        key, fallback = 'prompt_recall_ru', ('Из ваших давних разговоров на похожую тему (давно; используй их, '
                                             'только если это важно и сейчас):\n{lines}')
    else:
        lines = '\n'.join(('— you: ' if t['role'] == 'user' else '— she: ') + t['text']
                          for t in turns)
        key, fallback = 'prompt_recall_en', ('From your older talks about a similar topic (long ago; use them only '
                                             'when they still matter now):\n{lines}')
    tpl = _prompt(settings, key, fallback)
    try:
        return tpl.format(lines=lines)
    except (KeyError, IndexError, ValueError):
        return fallback.format(lines=lines)


def _strip_think(text):
    """the mind's silent reasoning sometimes leaks into the answer as a
    «<think>...» block: it never reaches the bubble"""
    tag = '<' + 'think' + '>'
    return re.sub(re.escape(tag) + r'.*?' + re.escape(tag) + r'\s*', '',
                  str(text or ''), flags=re.S | re.I).strip()


def _ollama_chat(settings, history, timeout, stream=False):
    body = {'model': settings.get('chat_model') or DEFAULT_MODEL,
            'messages': history, 'stream': stream,
            'options': {'num_predict': 220},
            'think': _think(settings)}          # off: the answer comes right away
    if stream:
        req = urllib.request.Request(_url(settings) + '/api/chat', data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
        return urllib.request.urlopen(req, timeout=timeout)
    return _post(_url(settings) + '/api/chat', json.dumps(body).encode(), timeout)


def _polza_chat(settings, history, timeout, stream=False):
    body = {'model': settings.get('chat_model') or POLZA_MODEL,
            'messages': history, 'stream': stream,
            'max_tokens': 220}
    headers = {'Content-Type': 'application/json',
               'Authorization': 'Bearer ' + str(settings.get('polza_api_key') or '')}
    req = urllib.request.Request(_url(settings) + '/chat/completions',
                                 data=json.dumps(body).encode(), headers=headers)
    if stream:
        return urllib.request.urlopen(req, timeout=timeout)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _think_filter():
    """a streaming filter for the mind's «<think>…» reasoning: yields only the text
    that belongs in the answer, holding back a block that may be split across chunks"""
    tag = '<' + 'think' + '>'
    end = '<' + '/think' + '>'
    buf = ''
    inside = False

    def feed(chunk):
        nonlocal buf, inside
        buf += str(chunk or '')
        out = []
        while buf:
            if inside:
                i = buf.lower().find(end)
                if i < 0:
                    keep = len(end) - 1
                    buf = buf[-keep:] if len(buf) > keep else buf
                    break
                buf = buf[i + len(end):]
                inside = False
            else:
                i = buf.lower().find(tag)
                if i < 0:
                    keep = len(tag) - 1
                    if len(buf) > keep:
                        out.append(buf[:-keep])
                        buf = buf[-keep:]
                    break
                if i:
                    out.append(buf[:i])
                buf = buf[i + len(tag):]
                inside = True
        return ''.join(out)

    def flush():
        nonlocal buf, inside
        if inside:
            buf = ''
            return ''
        out, buf = buf, ''
        return out

    return feed, flush


def _ollama_stream(resp):
    feed, flush = _think_filter()
    try:
        try:
            for raw in resp:
                try:
                    line = raw.decode('utf-8', errors='replace').strip()
                except Exception:
                    continue
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                chunk = ((data.get('message') or {}).get('content') or '')
                out = feed(chunk)
                if out:
                    yield out
                if data.get('done'):
                    break
        except (OSError, ValueError):
            pass
        tail = flush()
        if tail:
            yield tail
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _polza_stream(resp):
    feed, flush = _think_filter()
    try:
        try:
            for raw in resp:
                try:
                    line = raw.decode('utf-8', errors='replace').strip()
                except Exception:
                    continue
                if not line or not line.startswith('data:'):
                    continue
                payload = line[5:].strip()
                if payload == '[DONE]':
                    break
                try:
                    data = json.loads(payload)
                except ValueError:
                    continue
                delta = ((data.get('choices') or [{}])[0].get('delta') or {})
                chunk = delta.get('content') or ''
                out = feed(chunk)
                if out:
                    yield out
        except (OSError, ValueError):
            pass
        tail = flush()
        if tail:
            yield tail
    finally:
        try:
            resp.close()
        except Exception:
            pass


def ask_stream(settings, history, timeout=90):
    """a reply as a stream of text chunks; yields nothing when it did not work out"""
    prov = _provider(settings)
    model = settings.get('chat_model') or (POLZA_MODEL if prov == 'polza.ai' else DEFAULT_MODEL)
    if prov == 'polza.ai' and not str(settings.get('polza_api_key') or '').strip():
        _log(f'ask_stream skipped: polza.ai key is empty, model={model}')
        return          # no key: Polza.ai would hang or refuse, she says so at once
    _log(f'ask_stream -> {prov} model={model} url={_url(settings)} msgs={len(history or [])} timeout={timeout}s')
    try:
        if prov == 'polza.ai':
            resp = _polza_chat(settings, history, timeout, stream=True)
            _log(f'ask_stream <- {prov} stream opened')
            yield from _polza_stream(resp)
        else:
            resp = _ollama_chat(settings, history, timeout, stream=True)
            _log(f'ask_stream <- {prov} stream opened')
            yield from _ollama_stream(resp)
        _log(f'ask_stream done {prov} model={model}')
    except (urllib.error.URLError, OSError, ValueError) as e:
        _log(f'ask_stream error {prov} model={model}: {e}')
        return


def ask(settings, history, timeout=90):
    """one reply for the conversation `history` ([{role, content}, ...], user last);
    the reply text, or '' if it did not work out"""
    prov = _provider(settings)
    model = settings.get('chat_model') or (POLZA_MODEL if prov == 'polza.ai' else DEFAULT_MODEL)
    if prov == 'polza.ai' and not str(settings.get('polza_api_key') or '').strip():
        _log(f'ask skipped: polza.ai key is empty, model={model}')
        return ''          # no key: Polza.ai would hang or refuse, she says so at once
    _log(f'ask -> {prov} model={model} url={_url(settings)} msgs={len(history or [])} timeout={timeout}s')
    try:
        if prov == 'polza.ai':
            data = _polza_chat(settings, history, timeout)
            msg = (data.get('choices') or [{}])[0].get('message') or {}
            reply = _strip_think(' '.join(str(msg.get('content') or '').split()))
        else:
            data = _ollama_chat(settings, history, timeout)
            reply = _strip_think(' '.join(str((data.get('message') or {}).get('content') or '').split()))
        _log(f"ask <- {prov} model={model} ok={'yes' if reply else 'empty'}")
        return reply
    except (urllib.error.URLError, OSError, ValueError) as e:
        _log(f'ask error {prov} model={model}: {e}')
        return ''


def summarize(settings, title, text, lang='en', timeout=15):
    """one or two sentences about a note, for when she reads it aloud; the note's
    own first lines are the fallback elsewhere, '' when the mind is away"""
    text = ' '.join(str(text or '').split())
    if not text:
        return ''
    title = ' '.join(str(title or '').split())
    ru = str(lang) == 'ru'
    title_block = (f'Заголовок: {title}\n' if ru else f'Title: {title}\n') if title else ''
    if ru:
        sys_fb = ('Ты кратко пересказываешь заметки. Отвечай по-русски одним-двумя '
                  'короткими предложениями, только суть, без вступления и кавычек.')
        usr_fb = 'Перескажи эту заметку.\n\n{title_block}Заметка:\n{text}'
        sys_key, usr_key = 'prompt_summarize_system_ru', 'prompt_summarize_user_ru'
    else:
        sys_fb = ('You briefly retell notes. Answer in English in one or two short '
                  'sentences, only the point, no preamble and no quotes.')
        usr_fb = 'Retell this note.\n\n{title_block}Note:\n{text}'
        sys_key, usr_key = 'prompt_summarize_system_en', 'prompt_summarize_user_en'
    system = _prompt(settings, sys_key, sys_fb)
    usr_tpl = _prompt(settings, usr_key, usr_fb)
    try:
        prompt = usr_tpl.format(title_block=title_block, title=title, text=text[:4000])
    except (KeyError, IndexError, ValueError):
        prompt = usr_fb.format(title_block=title_block, title=title, text=text[:4000])
    return _one_shot(settings, prompt, 110, lang, timeout=timeout, temp=0.2,
                     system=system)


# ---- the little questions she needs no mind for: the clock and the window ----

TIME_Q_RE = re.compile(
    r'который\s+час|сколько\s+(?:уже\s+)?времени|какое\s+(?:сейчас\s+)?время'
    r"|what\s+time\s+is\s+it|what(?:'?s|\s+is)\s+the\s+time|how\s+late\s+is\s+it")

WEATHER_Q_RE = re.compile(
    r'\bпогод|за\s+окном|что\s+на\s+улице|как\s+на\s+улице'
    r'|\bweather\b|\bforecast\b|is\s+it\s+(?:raining|snowing)'
    r'|how\s+(?:hot|warm|cold|sunny)')

# the polite words around a bare clock word («скажи время», «а время сейчас») —
# once they are gone, a lone «время» is still the clock asking to be read
TIME_FILLERS = {'скажи', 'подскажи', 'сейчас', 'пожалуйста', 'ну', 'а',
                'tell', 'me', 'please', 'now'}

# words that may trail a place name in a phrase but are not the place itself
TRAILING = {'сегодня', 'сейчас', 'теперь', 'завтра', 'вечером', 'утром', 'днём', 'ночью',
            'now', 'today', 'tonight', 'tomorrow', 'right', 'please', 'outside'}

# the words that name a slice of the forecast («погода на завтра», «what's the weather this week»)
WHEN_RE = re.compile(
    r'\bна\s+(?:завтра|недел[юе]|сегодня|7\s+дней)'
    r'|\b7\s+days\b|\bthis\s+week\b|\bweek\b|\btomorrow\b|\btonight\b|\btoday\b'
    r'|\bзавтра\b|\bнедел[юе]\b|\bсегодня\b')

WEEKDAYS = {'ru': ('пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'),
            'en': ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')}

# the sky in words, for the weather codes Open-Meteo sends back (WMO 4677)
WMO = {
    0: ('ясно', 'clear'), 1: ('почти ясно', 'mostly clear'),
    2: ('переменная облачность', 'partly cloudy'), 3: ('пасмурно', 'overcast'),
    45: ('туман', 'fog'), 48: ('изморозь', 'freezing fog'),
    51: ('морось', 'light drizzle'), 53: ('морось', 'drizzle'), 55: ('морось', 'heavy drizzle'),
    56: ('ледяная морось', 'freezing drizzle'), 57: ('ледяная морось', 'freezing drizzle'),
    61: ('дождик', 'light rain'), 63: ('дождь', 'rain'), 65: ('ливень', 'heavy rain'),
    66: ('ледяной дождь', 'freezing rain'), 67: ('ледяной дождь', 'freezing rain'),
    71: ('снежок', 'light snow'), 73: ('снег', 'snow'), 75: ('снегопад', 'heavy snow'),
    77: ('снежные зёрна', 'snow grains'),
    80: ('ливни', 'rain showers'), 81: ('ливни', 'rain showers'), 82: ('ливни', 'violent showers'),
    85: ('снежные ливни', 'snow showers'), 86: ('снежные ливни', 'snow showers'),
    95: ('гроза', 'thunderstorm'), 96: ('гроза с градом', 'thunderstorm with hail'),
    99: ('гроза с градом', 'thunderstorm with hail'),
}


def time_question(text):
    """True when the phrase asks for the time: her eyes and the clock are enough.
    A bare clock word counts too («время», «времени»): the wake ear often keeps
    only the tail of «юми время», the polite words around it are not a question
    about anything else"""
    t = ' '.join(str(text or '').lower().split()).strip(' ?!.,')
    if TIME_Q_RE.search(t):
        return True
    toks = [w.strip('.,!?"«»…:;()[]-—').lower().replace('ё', 'е') for w in t.split()]
    return [w for w in toks if w and w not in TIME_FILLERS] in (
        ['время'], ['времени'], ['времечко'], ['time'])


JOKE_Q_RE = re.compile(
    r'анекдот|шутк\w*|пошути|рассмеши|смешн\w*'
    r'|\bjokes?\b|make\s+me\s+laugh|something\s+funny')


def joke_question(text):
    """True when the phrase asks for a joke: her mind makes one up on the spot"""
    t = ' '.join(str(text or '').lower().split()).strip(' ?!.,')
    return bool(JOKE_Q_RE.search(t))


PARAMS_Q_RE = re.compile(
    r'тво[иё]\s+параметры|какие\s+у\s+тебя\s+параметры'
    r'|тво[иё]\s+настройки|какие\s+у\s+тебя\s+настройки|что\s+у\s+тебя\s+стоит'
    r'|\byour\s+parameters\b|\byour\s+specs?\b|\byour\s+settings\b|\bwhat\s+are\s+you\s+running\b')


def params_question(text):
    """True when the phrase asks what she is made of: the ears, the voice, the mind"""
    t = ' '.join(str(text or '').lower().split()).strip(' ?!.,')
    return bool(PARAMS_Q_RE.search(t))


def the_time(lang='en', now=None):
    """the clock as she says it: 24 hours for Russian, «2:14 pm» for English"""
    t = time.localtime() if now is None else time.localtime(now)
    if str(lang) == 'ru':
        return time.strftime('%H:%M', t)
    # not strftime('%p'): a Russian system locale has no am/pm at all
    return '{}:{:02d} {}'.format(t.tm_hour % 12 or 12, t.tm_min,
                                  'am' if t.tm_hour < 12 else 'pm')


def weather_question(text):
    """the place to look up from the phrase: a guessed city, '' for wherever she is,
    None when the phrase is not about the weather at all"""
    t = ' '.join(str(text or '').lower().split()).strip(' ?!.,')
    if not WEATHER_Q_RE.search(t):
        return None
    t = WHEN_RE.sub(' ', t)             # «на завтра», «на неделю» и прочие не про место
    # the place runs after the last в/во/in/at until the end of the phrase
    cuts = [(t.rfind(s), s) for s in (' в ', ' во ', ' in ', ' at ')]
    i, sep = max(cuts)
    if i > 0:
        words = t[i + len(sep):].strip(' ?!.,').split()
        while words and words[-1] in TRAILING:
            words.pop()
        if words and len(words) <= 3:
            return ' '.join(words)[:64]
    return ''


def weather_when(text):
    """which slice of the forecast the phrase asks for: 'today', 'tomorrow' or 'week'"""
    t = ' '.join(str(text or '').lower().split())
    if re.search(r'недел|week\b|7\s+дней|7\s+days', t):
        return 'week'
    if re.search(r'\bзавтра\b|tomorrow\b', t):
        return 'tomorrow'
    return 'today'


def _one_shot(settings, user, tokens, lang='en', timeout=90, temp=None, system=None):
    """one reply for one user line, no conversation behind it (the hour joke, a joke, ...);
    the reply text, or '' when the mind is out of reach"""
    prov = _provider(settings)
    model = settings.get('chat_model') or (POLZA_MODEL if prov == 'polza.ai' else DEFAULT_MODEL)
    if prov == 'polza.ai' and not str(settings.get('polza_api_key') or '').strip():
        _log(f'one_shot skipped: polza.ai key is empty, model={model}')
        return ''          # no key: Polza.ai would hang or refuse, she says so at once
    options = {'num_predict': tokens} if prov != 'polza.ai' else {'max_tokens': tokens}
    if temp is not None:
        options['temperature'] = temp      # the jokes and the hour lines want a loose hand
    req_body = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system or system_prompt(lang, bool(settings.get('sassy')), settings)},
            {'role': 'user', 'content': user}
        ],
        'stream': False,
        'options': options,
    }
    if temp is not None and prov == 'polza.ai':
        req_body['temperature'] = temp     # the openai-style body carries it on top
    if prov != 'polza.ai':
        req_body['think'] = _think(settings)    # off: the joke comes right away
    body = json.dumps(req_body).encode()
    _log(f'one_shot -> {prov} model={model} url={_url(settings)} timeout={timeout}s')
    try:
        if prov == 'polza.ai':
            headers = {'Content-Type': 'application/json',
                       'Authorization': 'Bearer ' + str(settings.get('polza_api_key') or '')}
            req = urllib.request.Request(_url(settings) + '/chat/completions', data=body,
                                         headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode())
            msg = (data.get('choices') or [{}])[0].get('message') or {}
            reply = _strip_think(' '.join(str(msg.get('content') or '').split()))
        else:
            req = urllib.request.Request(_url(settings) + '/api/chat', data=body,
                                         headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode())
            reply = _strip_think(' '.join(str((data.get('message') or {}).get('content') or '').split()))
        _log(f"one_shot <- {prov} model={model} ok={'yes' if reply else 'empty'}")
        return reply
    except (urllib.error.URLError, OSError, ValueError) as e:
        _log(f'one_shot error {prov} model={model}: {e}')
        return ''


def music_name(settings, kind, query, timeout=15):
    """the name you said, spelled the way the covers spell it: the mind is asked
    once, quietly («тупак» is 2Pac, «рамштайн» is Rammstein — the tags are
    latin, the ears heard Russian) — the name alone, or '' when the mind is
    away, in no mood, or repeated what was already tried"""
    query = ' '.join(str(query or '').split())
    if not query:
        return ''
    kind_word = {'song': 'a song', 'artist': 'an artist', 'album': 'an album'}.get(kind, 'music')
    fb = ('A music player heard a voice request. The user named '
          '{kind}: «{query}» — spoken by ear, likely in Russian, while the music tags '
          'carry the original spelling. Write the most likely original spelling '
          '(how it appears on the covers and the labels). Answer with the name '
          'only, in one line, nothing else.')
    tpl = _prompt(settings, 'prompt_music_name', fb)
    try:
        asked = tpl.format(kind=kind_word, query=query)
    except (KeyError, IndexError, ValueError):
        asked = fb.format(kind=kind_word, query=query)
    got = _one_shot(settings, asked, 32, timeout=timeout, temp=0.1)
    if not got:
        return ''
    got = got.splitlines()[0].strip(' «»"\'`*—- ').strip()
    if not got or len(got) > 80 or got.lower() == query.lower():
        return ''
    return got


def hourly_joke(settings, hour, lang='en', timeout=90):
    """ask the mind for a short funny line about this hour (Russian or English),
    one or two sentences, no emoji, no lists; '' when the mind is out of reach"""
    ru = str(lang) == 'ru'
    key = 'prompt_hourly_joke_ru' if ru else 'prompt_hourly_joke_en'
    fb = ('Скажи что-нибудь смешное и короткое про время '
          '{hour}:00, одно-два предложения, по-русски, без эмодзи и списков.' if ru else
          'Say something short and funny about {hour}:00, one or two sentences, in English, no emoji, no lists.')
    tpl = _prompt(settings, key, fb)
    try:
        user = tpl.format(hour=hour)
    except (KeyError, IndexError, ValueError):
        user = fb.format(hour=hour)
    return _one_shot(settings, user, 120, lang, timeout)


JOKE_TOPICS = (
    # a fresh theme each time: the tiny models otherwise tell the same penguin
    # joke for the rest of their lives
    'программистах и коде', 'мотыльках и лампочках', 'котов и их дела',
    'лени и понедельниках', 'буднях за компьютером', 'музыке и наушниках',
    'погоде и временах года', 'пингвинах и линуксе', 'еде и холодильнике',
    'пиксельных героев',
)
JOKE_TOPICS_EN = (
    'programmers and code', 'moths and light bulbs', 'cats and their business',
    'laziness and Mondays', 'everydays at the computer', 'music and headphones',
    'weather and seasons', 'penguins and Linux', 'food and the fridge',
    'pixel heroes',
)


def joke(settings, lang='en', timeout=90):
    """ask the mind for a short joke («анекдот»), one or two sentences, no emoji,
    no lists; a topic is drawn by lot, so the jokes do not rhyme; '' when the
    mind is out of reach"""
    ru = str(lang) == 'ru'
    topic = random.choice(JOKE_TOPICS if ru else JOKE_TOPICS_EN)
    key = 'prompt_joke_ru' if ru else 'prompt_joke_en'
    fb = ('Расскажи короткий смешной анекдот про {topic}, '
          'одно-два предложения, по-русски, без эмодзи и списков. Каждый раз '
          'придумывай новый, не повторяй старые.' if ru else
          'Tell me a short funny joke about {topic}, one or '
          'two sentences, in English, no emoji, no lists. Invent a new one every '
          'time, do not repeat the old ones.')
    tpl = _prompt(settings, key, fb)
    try:
        user = tpl.format(topic=topic)
    except (KeyError, IndexError, ValueError):
        user = fb.format(topic=topic)
    return _one_shot(settings, user, 160, lang, timeout, temp=0.9)


JOKE_TIRED_AFTER = 4         # the fourth «анекдот» in a row in «Дерзкая 18+» gets a brush-off


def joke_tired(settings, lang='ru', count=JOKE_TIRED_AFTER, timeout=60):
    """the mind writes the brush-off for yet another joke in a row in «Дерзкая
    18+»: «заебал со своими анекдотами, я тебе не <имя российского
    стендап-комика>»; '' when the mind is out of reach (a dry line stands in)"""
    ru = str(lang) == 'ru'
    key = 'prompt_joke_tired_ru' if ru else 'prompt_joke_tired_en'
    fb = ('Пользователь просит анекдот уже {count}-й раз подряд, ты '
          'заебалась. Отшей его одной короткой грубой фразой с матом, '
          'можешь послать нахуй: скажи, что он заебал со своими '
          'анекдотами и что ты ему не <имя известного российского '
          'стендап-комика> — назови настоящего комика, например Славу '
          'Комиссаренко или Павла Волю, и придумай фразу сама. '
          'Без эмодзи и списков.' if ru else
          'The user has asked for a joke {count} times in a row and you are '
          'fed up. Brush him off in one short rude sentence with swearing, '
          'tell him to piss off: say he is tiresome with his jokes and that '
          'you are not <name of a famous Russian stand-up comedian> — name a '
          'real one and write the line yourself. No emoji, no lists.')
    tpl = _prompt(settings, key, fb)
    try:
        user = tpl.format(count=count)
    except (KeyError, IndexError, ValueError):
        user = fb.format(count=count)
    got = _one_shot(settings, user, 120, lang, timeout, temp=0.9)
    if not got or '<' in got or '>' in got:
        return ''                   # a placeholder leaked: the dry line stands in
    return got


def _degrees_ru(n):
    """градус / градуса / градусов, по числу, что стоит перед словом"""
    try:
        n = abs(int(float(str(n).replace(',', '.'))))
    except ValueError:
        return 'градусов'
    if n % 10 == 1 and n % 100 != 11:
        return 'градус'
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return 'градуса'
    return 'градусов'


# the temperatures of a weather line: «+8/+14°» (the pairs of the week), «+5°C», a bare «+12»
TEMP_RE = re.compile(r'([+-]?\d+)\s*/\s*([+-]?\d+)\s*°(?:C|F)?'
                     r'|([+-]?\d+)\s*°(?:C|F)?'
                     r'|([+-]?\d+)')
# the clock of a weather line: «11:00» → «одиннадцать часов» / «eleven o'clock»
TIME_RE = re.compile(r'\b(\d{1,2}):(\d{2})\b')


def weather_speak(text, lang='en'):
    """the weather line as her ears should hear it: «+5°C» is «плюс 5 градусов»,
    «+8/+14°» is «от плюс 8 до плюс 14 градусов» (English keeps it shorter:
    'minus 3 degrees', '8 to 14 degrees'); the clock becomes words too:
    «11:00» is «одиннадцать часов» / «eleven o'clock»; the bubble keeps the signs"""
    ru = str(lang) == 'ru'
    sign = {'+': 'плюс ' if ru else '', '-': 'минус ' if ru else 'minus '}

    def word(g):
        """the sign as a word, the number without its own sign"""
        s = g[:1]
        return sign.get(s, ''), g[1:] if s in '+-' else g

    out, at = [], 0
    t = str(text or '')
    for m in TEMP_RE.finditer(t):
        out.append(t[at:m.start()])
        if m.group(1) is not None:              # the pair «+8/+14°»
            sa, na = word(m.group(1))
            sb, nb = word(m.group(2))
            out.append(f'от {sa}{na} до {sb}{nb} {_degrees_ru(m.group(2))}' if ru
                       else f'{sa}{na} to {sb}{nb} degrees')
        elif m.group(3) is not None:            # the single «+5°C»
            s, n = word(m.group(3))
            out.append(f'{s}{n} {_degrees_ru(m.group(3))}' if ru else f'{s}{n} degrees')
        else:                                   # the bare «+12» of «от +12 до +17°C»
            s, n = word(m.group(4))
            out.append(s + n)
        at = m.end()
    out.append(t[at:])
    result = ''.join(out)

    def _time_repl(m):
        hour, minute = int(m.group(1)), int(m.group(2))
        return _hour_words_ru(hour, minute) if ru else _hour_words_en(hour, minute)

    return TIME_RE.sub(_time_repl, result)


_CYR_RE = re.compile(r'[\u0400-\u04ff]')


def _place_candidates(where):
    """the spellings to try for a place: the phrase keeps the inflected form
    («в красноярске», «в анапе»), the lookups want the nominative one
    («красноярск», «анапа») — otherwise wttr.in matches a wrong same-stem village"""
    w = str(where or '').strip()
    if not w or not _CYR_RE.search(w):
        return [w] if w else []
    out = [w]
    stem = w[:-1]
    if len(stem) > 2:
        out.append(stem)                    # красноярске → красноярск
        out.append(stem + 'а')              # анапе → анапа
        if w.endswith('и'):
            out.append(stem + 'ь')          # астрахани → астрахань
    return out


_EX_USSR = {'RU', 'BY', 'UA', 'KZ', 'UZ', 'KG', 'TJ', 'AM', 'AZ', 'GE', 'MD', 'LV', 'LT', 'EE'}


def _best_place(rows, cyr):
    """the row to trust: a town (PPL…), not an admin region with its huge population;
    a Russian phrase means the ex-USSR namesake when there is one («анапа» is the
    resort, not the bigger Anápolis in Brazil); the rows are (query, row) pairs and
    a name that just echoes the inflected query («Нижнем Новгороде») loses to the
    nominative one («Нижний Новгород») on a tie"""
    rows = [(q, r) for q, r in rows if str(r.get('feature_code') or '').startswith('PPL')]
    if not rows:
        return None
    if cyr:
        ours = [(q, r) for q, r in rows if r.get('country_code') in _EX_USSR]
        rows = ours or rows
    best = max(rows, key=lambda qr: qr[1].get('population') or 0)
    tie = [qr for qr in rows if (qr[1].get('population') or 0) == (best[1].get('population') or 0)]
    clean = [qr for qr in tie if str(qr[1].get('name') or '').lower() != str(qr[0]).lower()]
    return (clean or tie)[0][1]


def _geo_open_meteo(where, lang='en', timeout=8):
    """(lat, lon, name) of the place, from Open-Meteo: it understands the language
    and ranks the same-named towns by size, so «красноярске» resolves to the real
    city; None when the net is out or the place is unknown"""
    cyr = bool(_CYR_RE.search(str(where or '')))
    seen, rows = set(), []
    for name in _place_candidates(where):
        url = ('https://geocoding-api.open-meteo.com/v1/search?name={}&count=10'
               '&language={}&format=json').format(urllib.parse.quote(name, safe=''),
                                                  'ru' if str(lang) == 'ru' else 'en')
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                data = json.loads(r.read().decode(errors='replace'))
        except (urllib.error.URLError, OSError, ValueError):
            break
        for row in data.get('results') or []:
            if row.get('id') not in seen:
                seen.add(row.get('id'))
                rows.append((name, row))
    best = _best_place(rows, cyr)
    if best:
        found = (best.get('name') or '').strip()
        if found:
            return float(best['latitude']), float(best['longitude']), found
    return None


def _now(lat, lon, timeout=8):
    """the sky right now: {'temp', 'code'} from Open-Meteo, so the line is always
    in her language (wttr.in answers in English now and then); None when out"""
    url = ('https://api.open-meteo.com/v1/forecast?latitude={}&longitude={}'
           '&current=temperature_2m,weather_code').format(lat, lon)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            cur = json.loads(r.read().decode(errors='replace'))['current']
        return {'temp': float(cur['temperature_2m']), 'code': int(cur['weather_code'])}
    except (urllib.error.URLError, OSError, ValueError, TypeError, KeyError, IndexError):
        return None


def _hourly_open_meteo(lat, lon, timeout=8):
    """hourly rows for today: {'time': 'YYYY-MM-DDTHH:00', 'temp', 'code',
    'precip'} from Open-Meteo; [] when the net is out"""
    url = ('https://api.open-meteo.com/v1/forecast?latitude={}&longitude={}'
           '&hourly=temperature_2m,weather_code,precipitation_probability'
           '&timezone=auto&forecast_days=1').format(lat, lon)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read().decode(errors='replace'))
        h = data['hourly']
        times = h.get('time') or []
        temps = h.get('temperature_2m') or []
        codes = h.get('weather_code') or []
        preps = h.get('precipitation_probability') or []
        rows = []
        for i in range(len(times)):
            rows.append({'time': times[i],
                         'temp': float(temps[i]) if i < len(temps) else None,
                         'code': int(codes[i]) if i < len(codes) else 3,
                         'precip': float(preps[i]) if i < len(preps) else 0.0})
        return rows
    except (urllib.error.URLError, OSError, ValueError, TypeError, KeyError, IndexError):
        return []


# WMO codes that mean rain (drizzle, rain, showers, freezing rain)
_RAIN_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}


def _rain_window(rows):
    """(start_hour, end_hour) of the longest unbroken spell of rain today,
    or None when there is no rain at all; a dry gap must not turn two showers
    into one 'from midnight till night' window"""
    hours = sorted({int(r['time'][11:13]) for r in rows
                    if r.get('code') in _RAIN_CODES})
    if not hours:
        return None
    best, run = [], []
    for hour in hours:                       # rows need not be in order
        if run and hour != run[-1] + 1:
            if len(run) > len(best):          # ties keep the earlier spell
                best = run
            run = []
        run.append(hour)
    if len(run) > len(best):
        best = run
    return best[0], best[-1]


def _hour_words_ru(hour, minute=0):
    """«одиннадцать часов», «двенадцать часов», «шестнадцать часов тридцать»"""
    h = hour % 24 or 24
    if 11 <= h <= 14:
        num = _RU_SMALL[h]
    else:
        num = _ru_words(h)
    if 11 <= h % 100 <= 14:
        hour_word = 'часов'
    else:
        d = h % 10
        if d == 1:
            hour_word = 'час'
        elif 2 <= d <= 4:
            hour_word = 'часа'
        else:
            hour_word = 'часов'
    if minute == 0:
        return '{} {}'.format(num, hour_word)
    return '{} {} {}'.format(num, hour_word, _ru_words(minute))


def _hour_words_en(hour, minute=0):
    """«eleven o'clock», «sixteen thirty», «eleven oh five» — the same 24-hour
    clock as the Russian line, with midnight simply «twelve o'clock»"""
    words = _en_words(hour % 24 or 12)
    if minute == 0:
        return "{} o'clock".format(words)
    if minute < 10:
        return '{} oh {}'.format(words, _EN_SMALL[minute])
    return '{} {}'.format(words, _en_words(minute))


def _geo(where, timeout=8):
    """(lat, lon, name) of the place, from the same wttr.in lookup the one-line report
    uses ('' looks wherever she is); None when the net is out or the place is unknown"""
    loc = urllib.parse.quote(str(where or '').strip(), safe=',%')
    url = 'https://wttr.in/{}?format=j1'.format(loc or '~')
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read().decode(errors='replace'))
        area = (data.get('nearest_area') or [{}])[0]
        lat, lon = float(area.get('latitude')), float(area.get('longitude'))
        name = ((area.get('areaName') or [{}])[0].get('value') or '').strip()
        return lat, lon, name
    except (urllib.error.URLError, OSError, ValueError, TypeError):
        return None


def _daily(lat, lon, days, timeout=8):
    """daily rows [{'date', 'code', 'min', 'max'}] for `days` days from Open-Meteo;
    [] when the net is out — she says so instead"""
    url = ('https://api.open-meteo.com/v1/forecast?latitude={}&longitude={}'
           '&daily=weather_code,temperature_2m_max,temperature_2m_min'
           '&timezone=auto&forecast_days={}').format(lat, lon, days)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read().decode(errors='replace'))
        d = data['daily']
        return [{'date': d['time'][i], 'code': int(d['weather_code'][i]),
                 'min': float(d['temperature_2m_min'][i]),
                 'max': float(d['temperature_2m_max'][i])}
                for i in range(len(d.get('time') or []))]
    except (urllib.error.URLError, OSError, ValueError, TypeError, KeyError, IndexError):
        return []


def wmo_desc(code, lang='en'):
    """the sky in words, for the code Open-Meteo sends back"""
    return WMO.get(int(code or 0), WMO[3])[0 if str(lang) == 'ru' else 1]


def _day_name(date, lang='en'):
    """the short weekday of a 'YYYY-MM-DD' date: «пн» / 'Mon'"""
    try:
        wd = time.strptime(str(date), '%Y-%m-%d').tm_wday
    except ValueError:
        return ''
    return WEEKDAYS['ru' if str(lang) == 'ru' else 'en'][wd]


def _fmt_tomorrow(name, day, lang='en'):
    """«Завтра, Ялта: пасмурно, от +4 до +10°C»"""
    desc = wmo_desc(day.get('code'), lang)
    mn, mx = day.get('min'), day.get('max')
    if str(lang) == 'ru':
        return f'Завтра, {name}: {desc}, от {mn:+.0f} до {mx:+.0f}°C'
    return f'Tomorrow, {name}: {desc}, {mn:+.0f} to {mx:+.0f} °C'


def _fmt_week(name, rows, lang='en'):
    """«Ялта, на неделю: ср +4/+9°, чт +6/+11°, ...»"""
    days = ', '.join('{} {:+.0f}/{:+.0f}°'.format(_day_name(r.get('date'), lang),
                                                  r.get('min'), r.get('max')) for r in rows)
    if str(lang) == 'ru':
        return f'{name}, на неделю: {days}'
    return f'{name}, this week: {days}'


def _fmt_today_ru(name, now, daily_rows, hourly_rows, lang='ru'):
    """«погода в Ялта сейчас плюс 4 градуса. Сегодня от +6 до +11°C.
    Дождь начнется в 11:00 и закончится до 12:00» — the bubble keeps the clock,
    her ears get «одиннадцать часов» from weather_speak"""
    desc = wmo_desc(now.get('code', 3), lang)
    temp = now.get('temp', 0)
    mn = daily_rows[0].get('min') if daily_rows else None
    mx = daily_rows[0].get('max') if daily_rows else None
    now_words = weather_speak('{:+.0f}°C, {}'.format(temp, desc), lang)
    parts = ['погода в {} сейчас {}'.format(name, now_words)]
    if mn is not None and mx is not None:
        parts.append('Сегодня от {:+.0f} до {:+.0f}°C'.format(mn, mx))
    rain = _rain_window(hourly_rows) if hourly_rows else None
    if rain:
        start, end = rain
        parts.append('Дождь начнется в {:02d}:00 и закончится до {:02d}:00'.format(start, end))
    return '. '.join(parts) + '.'


def _fmt_today_en(name, now, daily_rows, hourly_rows, lang='en'):
    """«weather in Yalta now +7°C, clear. Today from +6 to +11°C.
    Rain starts at 11:00 and ends by 12:00» — the bubble keeps the signs,
    her ears get the degrees and the hours as words"""
    desc = wmo_desc(now.get('code', 3), lang)
    temp = now.get('temp', 0)
    mn = daily_rows[0].get('min') if daily_rows else None
    mx = daily_rows[0].get('max') if daily_rows else None
    now_words = weather_speak('{:+.0f}°C, {}'.format(temp, desc), lang)
    parts = ['weather in {} now {}'.format(name, now_words)]
    if mn is not None and mx is not None:
        parts.append('Today from {:+.0f} to {:+.0f}°C'.format(mn, mx))
    rain = _rain_window(hourly_rows) if hourly_rows else None
    if rain:
        start, end = rain
        parts.append('Rain starts at {:02d}:00 and ends by {:02d}:00'.format(start, end))
    return '. '.join(parts) + '.'


def weather_report(where, lang='en', when='today', timeout=8):
    """one line about the sky, with the place up front («Ялта: +4°C, Пасмурно») — today from
    Open-Meteo (wttr.in only as a fallback), tomorrow or the whole week from Open-Meteo
    («Завтра, Ялта: ...»); '' when the net is out — she says so instead"""
    lang = 'ru' if str(lang) == 'ru' else 'en'
    when = when if when in ('tomorrow', 'week') else 'today'
    if when == 'today':
        where = str(where or '').strip()
        if where:
            geo = _geo_open_meteo(where, lang, timeout)   # which of the same-named towns is the real one
            if geo:
                lat, lon, name = geo
                now = _now(lat, lon, timeout)
                if now:
                    fmt = _fmt_today_ru if str(lang) == 'ru' else _fmt_today_en
                    daily = _daily(lat, lon, 1, timeout)
                    hourly = _hourly_open_meteo(lat, lon, timeout)
                    return fmt(name, now, daily, hourly, lang)[:240]
        loc = urllib.parse.quote(where, safe=',%')
        fmt = urllib.parse.quote('%l: %t, %C')   # the place, the temperature, the clouds
        url = 'https://wttr.in/{}?format={}&lang={}'.format(loc or '~', fmt, lang)
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                text = r.read().decode(errors='replace')
        except (urllib.error.URLError, OSError, ValueError):
            return ''
        return ' '.join(text.split()).lstrip(':').strip()[:120]   # no name: no empty «:»
    geo = _geo_open_meteo(where, lang, timeout) or _geo(where, timeout)
    if not geo:
        return ''
    lat, lon, name = geo
    rows = _daily(lat, lon, 2 if when == 'tomorrow' else 7, timeout)
    if not rows:
        return ''
    name = name or str(where or '').strip()
    if when == 'tomorrow':
        if len(rows) < 2:
            return ''
        return _fmt_tomorrow(name, rows[1], lang)[:200]
    return _fmt_week(name, rows, lang)[:240]
