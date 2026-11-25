"""A small, hand-checked fact book for idle chatter (no GTK, no model calls).

The built-in rows are short and carry a source: the model is deliberately not
asked to invent facts.  The panel can point Yumi at an extra JSON file of the
user's own vetted facts; it is validated and falls back to the built-in book on
any problem.  Expected format::

    {"facts": [{"id": "my-1", "ru": "...", "en": "...",
                "source": "My notes", "url": "https://…"}]}
"""
import json
import random
import re
import threading
from collections import deque, namedtuple
from pathlib import Path
from urllib.parse import urlparse

Fact = namedtuple('Fact', ('id', 'ru', 'en', 'source', 'url'))

MAX_TEXT = 240
MAX_FILE = 1_000_000
MAX_FACTS = 1000
KEEP_RECENT = 8

# Every row is a real, checkable claim with a stable source.  The two languages
# say the same thing: no fact is rewritten by a language model at runtime.
BUILTIN = (
    Fact('bug-1947',
         'Первый настоящий «баг» нашли в 1947 году: мотылёк застрял в реле «Марка II» и его вклеили в журнал.',
         'The first actual computer bug was a moth found in a Harvard Mark II relay in 1947, taped into the logbook.',
         'Computer History Museum', 'https://www.computerhistory.org/tdih/september/9/'),
    Fact('moth-species',
         'Видов мотыльков описано намного больше, чем видов дневных бабочек.',
         'There are far more described moth species than butterfly species.',
         'Britannica', 'https://www.britannica.com/animal/moth'),
    Fact('moth-hearing',
         'У многих мотыльков есть уши: они слышат ультразвук летучих мышей и резко меняют полёт.',
         'Many moths can hear the ultrasound of hunting bats and change their flight in response.',
         'Britannica', 'https://www.britannica.com/animal/moth'),
    Fact('octopus-hearts',
         'У осьминога три сердца: два гонят кровь через жабры, третье — по телу.',
         'An octopus has three hearts: two pump blood through the gills, one around the body.',
         'Smithsonian Ocean', 'https://ocean.si.edu/ocean-life/invertebrates/octopuses'),
    Fact('octopus-blood',
         'Кровь осьминога голубая: переносчик кислорода в ней содержит медь.',
         'Octopus blood is blue: its oxygen carrier is copper-based.',
         'Smithsonian Ocean', 'https://ocean.si.edu/ocean-life/invertebrates/octopuses'),
    Fact('bee-dance',
         'Пчёлы рассказывают о еде танцем: направление и длина «виляющего танца» указывают на цветы.',
         'Honeybees describe food with a waggle dance: its angle and length point to the flowers.',
         'Britannica', 'https://www.britannica.com/animal/honeybee'),
    Fact('bee-uv',
         'Пчёлы видят ультрафиолет: для них лепестки с узорами заметнее, чем для нас.',
         'Bees see ultraviolet light, so patterned petals stand out to them in a way we cannot see.',
         'Britannica', 'https://www.britannica.com/animal/honeybee'),
    Fact('honey-tombs',
         'Мёд почти не портится: в гробницах Древнего Египта находили съедобный мёд.',
         'Honey keeps for a very long time: edible honey has been found in ancient Egyptian tombs.',
         'Smithsonian Magazine', 'https://www.smithsonianmag.com/history/8-things-you-didnt-know-about-honey-118406124/'),
    Fact('banana-berry',
         'С ботанической точки зрения банан — ягода, а клубника — нет.',
         'Botanically, a banana is a berry and a strawberry is not.',
         'Britannica', 'https://www.britannica.com/science/berry'),
    Fact('bones-206',
         'У взрослого человека 206 костей; у младенца их больше — со временем часть срастается.',
         'An adult human skeleton has 206 bones; a baby has more, and some fuse as it grows.',
         'Britannica', 'https://www.britannica.com/science/human-skeleton'),
    Fact('crows-faces',
         'Вороны узнают человеческие лица и помнят их.',
         'Crows recognize and remember individual human faces.',
         'Wikipedia', 'https://en.wikipedia.org/wiki/Crow'),
    Fact('bristlecone',
         'Самые старые известные живые деревья — сосны-долгожители: некоторым больше 4800 лет.',
         'The oldest known living trees are bristlecone pines; some are over 4,800 years old.',
         'Wikipedia', 'https://en.wikipedia.org/wiki/Bristlecone_pine'),
    Fact('great-pyramid',
         'Великая пирамида оставалась самым высоким сооружением, сделанным человеком, примерно 3800 лет.',
         'The Great Pyramid was the tallest human-made structure for roughly 3,800 years.',
         'Britannica', 'https://www.britannica.com/topic/Great-Pyramid-of-Giza'),
    Fact('venus-day',
         'Венера крутится «задом наперёд», и её сутки длятся дольше года.',
         'Venus spins backwards, and its day lasts longer than its year.',
         'NASA', 'https://science.nasa.gov/venus/facts/'),
    Fact('mars-sol',
         'Сутки на Марсе — соль: примерно 24 часа 37 минут.',
         'A Martian day, or sol, lasts about 24 hours 37 minutes.',
         'NASA', 'https://science.nasa.gov/mars/facts/'),
    Fact('jupiter-spot',
         'Большое красное пятно Юпитера — буря, которую наблюдают уже не меньше 350 лет.',
         "Jupiter's Great Red Spot is a storm that has been watched for at least 350 years.",
         'NASA', 'https://science.nasa.gov/jupiter/facts/'),
    Fact('moonquakes',
         'На Луне бывают лунопрясения: её кора сжимается и трясётся.',
         'The Moon has moonquakes: its crust contracts and shudders.',
         'NASA', 'https://science.nasa.gov/moon/'),
    Fact('sound-vacuum',
         'В вакууме звук не распространяется: нечему колебаться.',
         'Sound cannot travel through a vacuum: there is nothing to carry it.',
         'NASA', 'https://www.nasa.gov/audio/'),
    Fact('ocean-71',
         'Океаны покрывают около 71% поверхности Земли.',
         'Oceans cover about 71% of Earth’s surface.',
         'NOAA', 'https://oceanservice.noaa.gov/facts/oceanwater.html'),
    Fact('lightning-44',
         'По всему миру молнии вспыхивают в среднем примерно 44 раза в секунду.',
         'Lightning flashes somewhere on Earth about 44 times a second on average.',
         'Wikipedia', 'https://en.wikipedia.org/wiki/Lightning'),
    Fact('air-78',
         'Воздух примерно на 78% состоит из азота и на 21% — из кислорода.',
         'Air is about 78% nitrogen and 21% oxygen.',
         'NASA', 'https://science.nasa.gov/earth/facts/'),
    Fact('triple-point',
         'Вода может кипеть и замерзать одновременно — в тройной точке.',
         'Water can boil and freeze at the same time at its triple point.',
         'Britannica', 'https://www.britannica.com/science/triple-point'),
    Fact('snail-sleep',
         'Улитка может впадать в летнюю спячку на несколько лет.',
         'A snail can estivate for several years.',
         'Britannica', 'https://www.britannica.com/animal/snail'),
    Fact('reef',
         'Большой Барьерный риф — крупнейшая в мире система коралловых рифов.',
         'The Great Barrier Reef is the largest coral reef system in the world.',
         'NASA Earth Observatory', 'https://earthobservatory.nasa.gov/features/GreatBarrierReef'),
)


def clean_text(value, limit=MAX_TEXT):
    """collapse whitespace, or return '' for a missing/oversized value"""
    text = ' '.join(str(value or '').split())
    return text if text and len(text) <= limit else ''


def _safe_url(value):
    url = ' '.join(str(value or '').split())
    if not url:
        return ''
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('a fact url must be an http(s) address')
    return url


def parse_facts(raw):
    """a list of Fact rows from a JSON file or a dict; raises ValueError"""
    if isinstance(raw, dict):
        rows = raw.get('facts')
    else:
        rows = raw
    if not isinstance(rows, list):
        raise ValueError('the fact book must hold a "facts" list')
    facts = []
    for i, row in enumerate(rows[:MAX_FACTS]):
        if not isinstance(row, dict):
            raise ValueError(f'fact {i + 1} is not an object')
        ru = clean_text(row.get('ru'))
        en = clean_text(row.get('en'))
        if not ru or not en:
            raise ValueError(f'fact {i + 1} needs both ru and en text (max {MAX_TEXT} chars)')
        fid = clean_text(row.get('id') or f'custom-{i + 1}', 80) or f'custom-{i + 1}'
        fact = Fact(fid, ru, en, clean_text(row.get('source'), 120) or 'Your fact book',
                    _safe_url(row.get('url')))
        facts.append(fact)
    if not facts:
        raise ValueError('the fact book has no usable facts')
    return tuple(facts)


def load_file(path):
    """read and validate an optional custom fact book; path may start with ~"""
    file = Path(str(path or '')).expanduser()
    raw = file.read_text(encoding='utf-8', errors='strict')[:MAX_FILE + 1]
    if len(raw) > MAX_FILE:
        raise ValueError('the fact book is too large')
    return parse_facts(json.loads(raw))


def _stamp(path):
    if not path:
        return None
    try:
        st = Path(path).expanduser().stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


class FactBook:
    """Built-in facts plus a validated optional file, with a short no-repeat memory."""

    def __init__(self, path=''):
        self.path = ' '.join(str(path or '').split())
        self.lock = threading.RLock()
        self.recent = {}
        self.last = None
        self.custom = ()
        self.error = ''
        self.stamp = None
        self.reload()

    def reload(self):
        with self.lock:
            self.stamp = _stamp(self.path)
            self.custom = ()
            self.error = ''
            if not self.path:
                return
            try:
                self.custom = load_file(self.path)
            except (OSError, ValueError, UnicodeError) as exc:
                self.error = f'{type(exc).__name__}: {exc}'
                self.error = re.sub(r'\s+', ' ', self.error)[:300]

    def _fresh(self):
        if _stamp(self.path) != self.stamp:
            self.reload()

    @property
    def facts(self):
        return BUILTIN + self.custom

    def find(self, fact_id):
        """one fact by id, or None; id comes from the panel only"""
        self._fresh()
        wanted = str(fact_id or '')
        with self.lock:
            for fact in self.facts:
                if fact.id == wanted:
                    self.last = fact
                    return fact
            return None

    def pick(self, lang='en', rng=None):
        """a fact that was not among the last few, preferring a new one"""
        self._fresh()
        with self.lock:
            pool = self.facts
            seen = self.recent.setdefault(lang, deque(maxlen=min(KEEP_RECENT, len(pool))))
            choices = [f for f in pool if f.id not in seen] or list(pool)
            fact = (rng or random).choice(choices)
            seen.append(fact.id)
            self.last = fact
            return fact

    def items(self, lang='en'):
        """panel-safe rows in the current speech language"""
        self._fresh()
        with self.lock:
            return [{'id': f.id, 'text': f.ru if lang == 'ru' else f.en,
                     'source': f.source, 'url': f.url} for f in self.facts]

    def info(self):
        self._fresh()
        with self.lock:
            return {'path': self.path, 'builtin': len(BUILTIN), 'custom': len(self.custom),
                    'total': len(self.facts), 'error': self.error,
                    'ok': not self.error}


_BOOKS = {}
_BOOK_LOCK = threading.Lock()


def get_book(settings):
    """one book per configured path; a changed file is noticed on the next call"""
    path = ' '.join(str((settings or {}).get('chatter_facts_file') or '').split())
    with _BOOK_LOCK:
        if path not in _BOOKS:
            _BOOKS[path] = FactBook(path)
        return _BOOKS[path]


def clear_cache():
    """for tests and for a settings change that must take effect at once"""
    with _BOOK_LOCK:
        _BOOKS.clear()
