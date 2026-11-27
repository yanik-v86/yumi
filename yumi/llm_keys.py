"""The providers' secrets, kept apart from settings.json (no GTK, no panel).

A provider record never carries its key: only this module reads and writes
``llm_keys.json`` (0600, atomic replace).  Neither the value nor an error about
it ever reaches a log, a repr or an API answer.
"""
import json
import os
import re

from . import config

KEYS_FILE = config.CONFIG_DIR / 'llm_keys.json'
_ID = re.compile(r'^[a-z0-9_-]{1,32}$')


def path():
    """where the private key file lives right now (tests may point it elsewhere)"""
    return os.fspath(KEYS_FILE)


def load():
    """{provider id: key}; an absent, broken or unreadable file is an empty map"""
    try:
        data = json.loads(open(path(), encoding='utf-8').read())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()
            if _ID.match(str(k)) and isinstance(v, str) and v}


def get(provider_id):
    """the key of one provider, or '' (never logs or raises about the value)"""
    return load().get(str(provider_id) or '', '')


def _save(data):
    try:
        target = os.fspath(path())
        os.makedirs(os.path.dirname(target) or '.', exist_ok=True)
        tmp = target + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
        os.chmod(target, 0o600)
        return True
    except OSError:
        # no key, path or exception detail: only the fact that writing failed
        print('yumi: could not save the provider keys', file=__import__('sys').stderr)
        return False


def set(provider_id, value):
    """store a key; an empty value removes the record.  True on success."""
    pid = str(provider_id or '')
    if not _ID.match(pid):
        raise ValueError('bad provider id')
    data = load()
    secret = str(value or '').strip()
    if secret:
        data[pid] = secret
    else:
        data.pop(pid, None)
    return _save(data)


def set_key(provider_id, value):
    """the old spelling of set(), kept for callers of the handoff contract"""
    return set(provider_id, value)


def delete(provider_id):
    """forget one key; True when the file was written successfully"""
    return set(provider_id, '')
