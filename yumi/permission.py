"""Permission decisions: safe paths and spoken answers (no GTK here).

A refusal beats a consent, a path may not escape a secret folder through ``..``
or a symlink, and a spoken answer can never grant a permanent "always" — that
takes a deliberate click.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from . import config

PERMISSION_FILE = config.CONFIG_DIR / 'permissions.json'

# places that hold keys, passwords and browser sign-ins
SECRET_PARTS = frozenset((
    '.ssh', '.gnupg', '.gpg', '.aws', '.kube', '.docker',
    '.local/share/keyrings', '.keyring', '.secret', '.password-store',
    '.config/gh', '.config/gcloud', '.config/azure', '.config/kube',
    '.mozilla', '.mozilla-firefox', '.config/google-chrome',
    '.config/chromium', '.config/brave', '.config/brave-browser',
    '.config/vivaldi', '.config/opera', '.config/Code/User/globalStorage',
    '.config/yumi/webpanel.json',
))
SECRET_WORDS = frozenset((
    'id_rsa', 'id_ed25519', 'private.key', 'credentials', 'token',
    'password', 'passwd', 'secret.key',
))

YES = frozenset(('да', 'давай', 'конечно', 'ладно', 'ага', 'ок', 'ok', 'okay',
                 'yes', 'yeah', 'yep', 'sure', 'once', 'раз', 'один', 'allow'))
NO = frozenset(('нет', 'не', 'не надо', 'отмена', 'отмени', 'стоп', 'запрет',
                'no', 'nope', 'never', 'cancel', 'deny', 'reject'))
ALWAYS = frozenset(('всегда', 'навсегда', 'always'))

_TRANSLITER = str.maketrans({'ё': 'е'})
_WORD = re.compile(r'[\w]+', re.UNICODE)


def words(text):
    """the lower-case words of what was said (ё folded to е)"""
    return [w.translate(_TRANSLITER) for w in _WORD.findall(str(text or '').lower())]


def _clean_path(target):
    raw = str(target or '').strip()
    if raw.startswith('file://'):
        raw = raw[7:]
    if not raw:
        return ''
    try:
        return str(Path(raw).expanduser().resolve())
    except (OSError, RuntimeError, ValueError):
        return str(Path(raw).expanduser())


def is_secret(target):
    """True for keys, password stores and browser profiles; ``..`` and symlinks
    are resolved first so a crafted path cannot sneak into a protected folder"""
    raw = str(target or '').strip().lower()
    if not raw:
        return False
    if '://' in raw and not raw.startswith('file://'):
        host = raw.split('://', 1)[1].split('/', 1)[0]
        if '@' in host:                      # credentials in the URL itself
            return True
    if any(w in raw for w in SECRET_WORDS):
        return True
    path = _clean_path(target)
    if not path:
        return False
    low = path.lower().replace('\\', '/')
    return any(part in low for part in SECRET_PARTS)


def spoken_answer(text):
    """``once`` / ``deny`` from words heard aloud, never ``always``.

    A mumble, an unrelated phrase, or "always" alone gives None: the question
    stays open instead of silently granting more than the speaker asked for."""
    said = set(words(text))
    if said & NO:                            # a refusal wins even in "yes, no, maybe"
        return 'deny'
    if said & YES:
        return 'once'
    return None


def negative_wins(tokens):
    """the strictest decision in a collection of parsed answers"""
    decisions = {t for t in tokens if t in ('once', 'always', 'deny')}
    return 'deny' if 'deny' in decisions else ('always' if 'always' in decisions
                                               else 'once' if decisions else None)


# ---- saved "always" rules -------------------------------------------------

def load():
    """{'allow': [patterns], 'deny': [patterns]} from the small permissions file"""
    try:
        data = json.loads(PERMISSION_FILE.read_text())
    except (OSError, ValueError):
        return {'allow': [], 'deny': []}
    out = {}
    for key in ('allow', 'deny'):
        value = data.get(key) if isinstance(data, dict) else None
        out[key] = [str(v) for v in value if str(v).strip()][:200] if isinstance(value, list) else []
    return out


def save(rules):
    """atomic write; unknown top-level keys are kept for older versions"""
    data = load()
    for key in ('allow', 'deny'):
        if key in rules:
            data[key] = [str(v) for v in (rules[key] or []) if str(v).strip()][:200]
    try:
        PERMISSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PERMISSION_FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n')
        tmp.replace(PERMISSION_FILE)
        return True
    except OSError:
        return False


def matches(pattern, target):
    """a saved pattern applies to an exact target or to a path below it"""
    a, b = str(pattern or '').strip(), str(target or '').strip()
    if not a:
        return False
    if a == b:
        return True
    ap, bp = _clean_path(a), _clean_path(b)
    if not ap or not bp:
        return False
    return bp == ap or bp.startswith(ap.rstrip('/') + '/')


def allowed(target, kind='button'):
    """a saved rule that permits this target (never for a secret path)"""
    if is_secret(target):
        return False
    for pattern in load()['allow']:
        if matches(pattern, target):
            return True
    return False


def remember(target, decision='allow'):
    """save a permanent decision; refuses to remember unsafe targets"""
    if is_secret(target) or decision not in ('allow', 'deny'):
        return False
    rules = load()
    key = 'allow' if decision == 'allow' else 'deny'
    others = 'deny' if key == 'allow' else 'allow'
    rules[others] = [p for p in rules[others] if not matches(p, target)]
    if not any(matches(p, target) for p in rules[key]):
        rules[key].append(str(target)[:500])
    return save(rules)


def clear():
    return save({'allow': [], 'deny': []})


def snapshot():
    """a compact view for the panel's security page (no secrets in patterns)"""
    rules = load()
    return {'allow': rules['allow'][:50], 'deny': rules['deny'][:50],
            'path': str(PERMISSION_FILE)}
