"""What a half-heard phrase after her name is: a command, a word for her, or noise.

OpenWakeWord is the ear that decides the name, and it sometimes misses «юми»
while the small vosk ear hears both the name and the wish after it.  Such a
fallback phrase must not be limited to notes: a command («включи музыку») has
to run, and a phrase that is clearly meant for her («как дела?») may go to her
mind.  A half-heard background phrase must not wake the mind for nothing.

route() gives that one answer to both sides: yumi/stt_daemon.py lets the
fallback wake through only when the tail is not noise, and yumi/brain.py keeps
a fallback phrase out of the mind when it is noise.  The hints are the user's
own phrases and keywords from actions.json — the ears daemon has no other way
to know them.  No GTK, no extra dependencies: the ears venv imports this file
too.
"""
from __future__ import annotations

# the punctuation the ears may put around a word (they rarely add any, but whisper does)
_CLIP = '.,!?"«»…:;()[]-—’\''

# the verbs of a wish may stand anywhere in the phrase; the skill's own nouns
# count near the start only, so «сегодня хорошая погода» is somebody's talk
RU_VERB_STEMS = (
    'включ', 'выключ', 'вруб', 'выруб', 'открой', 'открыв', 'закрой', 'закрыв',
    'постав', 'запуст', 'переключ', 'найд', 'поищ', 'запиш', 'покаж',
    'скаж', 'расскаж', 'объясн', 'напомн', 'перевед', 'посчит', 'нарису',
    'сделай', 'сдел', 'убери', 'убер', 'сохран', 'удал', 'сним', 'провер',
    'позвон', 'напиш', 'ответ', 'подскаж', 'останов', 'продолж',
    'перемота', 'следующ', 'предыдущ', 'дальш', 'далш', 'назад',
    'громч', 'тиш', 'замолч', 'молчи', 'спой', 'играй', 'играт', 'пауз',
)
RU_NOUN_STEMS = (
    'погод', 'врем', 'анекдот', 'шутк', 'пошут', 'параметр', 'настройк',
    'музык', 'таймер', 'будильник', 'замет',
)
RU_COMMAND_WORDS = frozenset(('стоп', 'стой'))      # «стопка» stays a box

# English imperatives keep their base form exactly: «starts» in somebody's talk is
# not «start», while the same word said to her is
EN_VERB_WORDS = frozenset((
    'play', 'pause', 'stop', 'next', 'previous', 'open', 'close', 'launch',
    'start', 'turn', 'set', 'find', 'search', 'write', 'show', 'tell',
    'explain', 'remind', 'translate', 'count', 'draw', 'delete', 'remove', 'save',
))
EN_NOUN_WORDS = frozenset((
    'note', 'notes', 'weather', 'time', 'joke', 'settings', 'parameter',
    'music', 'timer', 'alarm', 'volume', 'louder', 'quieter', 'mute',
))

# a question is a word for her even without a command («как дела», «что нового»);
# the short Russian words stay whole («чтобы» is not «что»), the longer ones take
# their forms as a stem
QUESTION_WORDS = frozenset((
    'кто', 'что', 'где', 'когда', 'почему', 'зачем', 'сколько', 'куда', 'откуда',
    'чей', 'чья', 'чье', 'чьи', 'который', 'можно', 'можешь', 'сможешь', 'правда',
    'верно', 'разве', 'неужели',
    'who', 'where', 'when', 'why', 'which', 'whose', 'can', 'could', 'would',
    'should', 'will', 'shall', 'do', 'does', 'did', 'is', 'are', 'am',
))
QUESTION_STEMS = ('как', 'what', 'how')       # «какой», «какая», «what's», «how's»

# the second person: the phrase is about her or said to her, not somebody else's talk
SECOND_PERSON = frozenset((
    'ты', 'тебя', 'тебе', 'тобой', 'тобою', 'твой', 'твоя', 'твое', 'твои',
    'твоего', 'твоей', 'твоих', 'твоим', 'твоими', 'твою',
    'вы', 'вас', 'вам', 'вами', 'ваш', 'ваша', 'ваше', 'ваши', 'вашего', 'вашей',
    'ваших', 'вашим', 'вашими', 'вашу',
    'you', 'your', 'yours', 'yourself',
))

# a mood said to her is a word for her even with no question in it («мне скучно»)
MOOD_WORDS = frozenset((
    'скучно', 'грустно', 'плохо', 'хорошо', 'весело', 'страшно', 'тревожно',
    'одиноко', 'устал', 'устала', 'радостно', 'обидно',
))

# a first-person wish after the name is said to her («я хочу пиццу»)
WISH_WORDS = frozenset((
    'хочу', 'хочется', 'хотел', 'хотела', 'хотелось', 'помоги', 'помогите',
    'посоветуй', 'посоветуйте', 'нужно', 'надо',
    'want', 'need', 'wish',
))

# greetings and the polite words that only make sense when the phrase is for her
ADDRESS_WORDS = frozenset((
    'привет', 'приветик', 'здравствуй', 'здравствуйте', 'доброе', 'добрый',
    'доброго', 'спокойной', 'пока', 'прощай', 'прощайте', 'спасибо', 'благодарю',
    'пожалуйста', 'извини', 'извините', 'прости', 'простите',
    'hello', 'hi', 'hey', 'thanks', 'thank', 'please', 'sorry', 'bye', 'goodbye',
    'good',
))


def words(text):
    """the phrase as the router reads it: lower case, the ears' punctuation gone,
    ё folded into е — the same canon nlu.py keeps"""
    out = []
    for token in str(text or '').split():
        word = token.strip(_CLIP).lower().replace('ё', 'е')
        if word:
            out.append(word)
    return out


def hints_from(actions, extra=None):
    """phrases and keywords from actions.json, plus the enabled custom intents:
    the ears daemon runs in another process and the mind has both lists anyway —
    one shape for both sides of the fallback (see SensesMixin.wake_hints)"""
    out = []
    for action in list(actions or ()):
        if not isinstance(action, dict):
            continue
        for key in ('phrases', 'keywords'):
            out.extend(str(x) for x in (action.get(key) or ()) if str(x).strip())
    for phrase in list(extra or ()):
        text = str(phrase).strip()
        if text:
            out.append(text)
    return out[:64]


def _alike(a, b):
    """one bent letter apart at most: the ears' slip in a keyword («терминай»),
    never a whole different word"""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1 or min(len(a), len(b)) < 5:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    if len(a) > len(b):
        a, b = b, a
    return b[:-1] == a or b[1:] == a


def _hinted(toks, hints):
    """the user's own phrases/keywords from actions.json stand somewhere in the
    phrase: their buttons have no built-in vocabulary the ears could know"""
    for hint in hints or ():
        want = words(hint)
        if not want or len(want) > len(toks):
            continue
        for i in range(len(toks) - len(want) + 1):
            if all(_alike(want[j], toks[i + j]) for j in range(len(want))):
                return True
    return False


def _command(toks):
    """the phrase carries an imperative or, near its start, a skill's own noun"""
    for token in toks:
        head = token.split('-')[0]
        if head in RU_COMMAND_WORDS or head in EN_VERB_WORDS:
            return True
        if any(head.startswith(stem) for stem in RU_VERB_STEMS):
            return True
    for token in toks[:2]:
        head = token.split('-')[0]
        if head in EN_NOUN_WORDS:
            return True
        if any(head.startswith(stem) for stem in RU_NOUN_STEMS):
            return True
    return False


def _addressed(toks):
    """the phrase is a question, a greeting or speaks to her in the second person.
    A question word counts near the start of the phrase only: «он сказал, что
    придёт» is somebody's talk, while «что нового?» is for her."""
    for token in toks:
        head = token.split('-')[0]
        if head in SECOND_PERSON or head in ADDRESS_WORDS:
            return True
    if 'мне' in toks and any(token in MOOD_WORDS for token in toks):
        return True
    if any(token in ('я', 'i') for token in toks) \
            and any(token in MOOD_WORDS or token in WISH_WORDS for token in toks):
        return True
    for token in toks[:2]:
        head = token.split('-')[0]
        if head in QUESTION_WORDS:
            return True
        if any(head.startswith(stem) for stem in QUESTION_STEMS):
            return True
    return False


_WAKES = frozenset(('юми', 'yumi'))

# ---- acquaintance / voice enrollment -------------------------------------
# «Юми, давай знакомиться» has no imperative stem from RU_VERB_STEMS and no
# question word, so route() used to call it background talk.  The small ear
# heard the name and the whole phrase (recogn.txt has both lines), but the
# wake's fallback threw it away — the phrase was recognized, never processed.
# brain.acquaintance_command() delegates here, so the ears, the speaker gate
# and the mind all use one vocabulary.
ACQUAINTANCE_PHRASES = (
    'давай познакомимся', 'давай знакомиться', 'давайте познакомимся',
    'познакомимся', 'хочу познакомиться', 'можно познакомиться',
    'знакомство', 'запомни мой голос', 'запиши мой голос',
    'запомни меня', 'запомни голос', 'запиши голос',
    'давай запишем мой голос', 'запомни как я говорю',
    'lets get acquainted', "let's get acquainted", 'get acquainted',
    'remember my voice', 'record my voice', 'learn my voice',
    'enroll my voice', 'recognize my voice', 'recognise my voice',
    'know my voice',
)
_ACQ_WISH = frozenset((
    'давай', 'давайте', 'хочу', 'можно', "let's", 'lets', 'want',
))
_ACQ_VOICE = frozenset((
    'голос', 'voice', 'запомни', 'запиши', 'запомнить', 'записать',
    'remember', 'record', 'learn', 'enroll', 'recognize', 'recognise',
    'меня', 'нас', 'me', 'us',
))
_ACQ_RECORD = _ACQ_VOICE - {'меня', 'нас', 'me', 'us'}


def acquaintance_command(text):
    """True when the phrase asks Yumi to remember the speaker's voice.

    The canonical matcher: the ears' fallback router, the multi-speaker gate
    and the brain's heard_text() all ask this same question.  «Покажи
    знакомство» stays the tour button, not an enrollment request.
    """
    low = ' '.join(str(text or '').lower().split())
    if not low:
        return False
    toks = set(words(low))
    if 'знакомств' in low and (toks & {'покажи', 'показать', 'открой', 'открыть',
                                        'show', 'open'}):
        if not (toks & _ACQ_RECORD):
            return False
    for phrase in ACQUAINTANCE_PHRASES:
        if phrase in low:
            return True
    if 'познаком' in low or 'acquaint' in low:
        if toks & _ACQ_VOICE:
            return True
        return bool(toks & _ACQ_WISH)
    if (toks & {'голос', 'voice'}) and (toks & _ACQ_RECORD):
        return True
    return False


def _named_other(raw, toks, labels):
    """A phrase that opens by calling somebody else is not a word for her.

    ``labels`` are the names of the voices already in the dialogue; a bare
    «Борис, где ключи?» counts too, because a name followed by a comma is an
    address to a person, not a question thrown at the room.
    """
    for label in labels or ():
        head = words(label)
        if head and toks[:len(head)] == head:
            return True
    if ',' in raw or '，' in raw:
        first = raw.strip().split(',', 1)[0].strip()
        if first and ' ' not in first and first[0].isupper() and len(first) <= 24:
            return True
    return False


def addressee(text, labels=()):
    """'yumi' — said to her, 'other' — said to another person, 'unclear' — no sign.

    Unlike route(), a bare question mark is not enough: «Борис, где ключи?»
    must not become her wish just because whisper kept the '?'.  This is the
    check the multi-speaker gate uses; route() stays backward compatible.
    """
    raw = str(text or '')
    toks = words(raw)
    if not toks:
        return 'unclear'
    if _named_other(raw, toks, labels):
        return 'other'
    if acquaintance_command(raw):
        return 'yumi'
    if any(token in _WAKES for token in toks):
        return 'yumi'
    for token in toks:
        head = token.split('-')[0]
        if head in SECOND_PERSON or head in ADDRESS_WORDS:
            return 'yumi'
    if 'мне' in toks and any(token in MOOD_WORDS for token in toks):
        return 'yumi'
    if any(token in ('я', 'i') for token in toks) \
            and any(token in MOOD_WORDS or token in WISH_WORDS for token in toks):
        return 'yumi'
    for token in toks[:2]:
        head = token.split('-')[0]
        if head in QUESTION_WORDS or any(head.startswith(stem) for stem in QUESTION_STEMS):
            return 'yumi'
    if _command(toks):
        return 'yumi'
    return 'unclear'


def route_strict(text, labels=(), hints=()):
    """route() with the addressee gate: another person's words stay ignored."""
    if addressee(text, labels) == 'other':
        return 'ignore'
    result = route(text, hints)
    if result == 'chat' and addressee(text, labels) == 'unclear':
        return 'ignore'
    return result


def route(text, hints=()):
    """'command' — run it, 'chat' — it is meant for her, 'ignore' — background talk."""
    raw = str(text or '')
    toks = words(raw)
    if not toks:
        return 'ignore'
    if acquaintance_command(raw):
        return 'command'
    if _hinted(toks, hints):
        return 'command'
    if _command(toks):
        return 'command'
    if '?' in raw or _addressed(toks):
        return 'chat'
    return 'ignore'
