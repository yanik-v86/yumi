"""One-shot compatibility layer for the old mind settings.

This is the only file where legacy setting names are allowed to appear.  It is
called from :func:`yumi.config.load_settings` and is deliberately boring: it
reads old keys, builds ordinary registry records, moves the secret into the
private key file, and only then drops the old keys.  Nothing here knows about
GTK or the browser panel, and a second call changes nothing.
"""
import copy
import sys

from . import llm, llm_keys

# legacy setting names, kept in one place on purpose
LEGACY_LOCAL_URL = 'ollama_url'
LEGACY_CLOUD_URL = 'polza_url'
LEGACY_CLOUD_KEY = 'polza_api_key'
LEGACY_PROVIDER_LOCAL = 'ollama'
LEGACY_PROVIDER_CLOUD = 'polza.ai'

CLOUD_ID = 'cloud'
CLOUD_MODEL = 'deepseek/deepseek-v4-flash'
CLOUD_URL = 'https://polza.ai/api/v1'
CLOUD_NAME = 'Cloud model'


def _default_local():
    """a fresh copy of the built-in local record (never share DEFAULT_SETTINGS)"""
    return dict(llm.DEFAULT_PROVIDERS[0], models=[])


def migrate(settings):
    """upgrade a settings dict in place; True when something was changed"""
    if not isinstance(settings, dict):
        return False
    watched = ('llm_providers', 'embed_url', 'chat_provider',
               LEGACY_CLOUD_KEY, LEGACY_CLOUD_URL, LEGACY_LOCAL_URL)
    before = {name: copy.deepcopy(settings.get(name)) for name in watched}

    raw = settings.get('llm_providers')
    try:
        records = llm.normalize_list(raw)
    except (TypeError, ValueError):
        records = []
    if not records:
        records = [_default_local()]
    local = next((r for r in records if r['id'] == 'local'), None)
    if local is None:
        local = _default_local()
        records.append(local)

    old_local_url = str(settings.get(LEGACY_LOCAL_URL) or '').strip().rstrip('/')
    if old_local_url and local['url'] != old_local_url:
        local['url'] = old_local_url
    if not str(settings.get('embed_url') or '').strip():
        settings['embed_url'] = old_local_url or llm.DEFAULT_EMBED_URL

    old_url = str(settings.get(LEGACY_CLOUD_URL) or '').strip().rstrip('/')
    old_key = str(settings.get(LEGACY_CLOUD_KEY) or '').strip()
    old_provider = str(settings.get('chat_provider') or '').strip()
    cloud = next((r for r in records if r['id'] == CLOUD_ID), None)
    needs_cloud = bool(old_url or old_key or old_provider == LEGACY_PROVIDER_CLOUD)
    if needs_cloud and cloud is None:
        current = str(settings.get('chat_model') or '').strip()
        default_model = (current if old_provider == LEGACY_PROVIDER_CLOUD and current
                         and current != local['default_model'] else CLOUD_MODEL)
        cloud = {'id': CLOUD_ID, 'name': CLOUD_NAME, 'kind': 'openai',
                 'url': old_url or CLOUD_URL, 'default_model': default_model,
                 'enabled': True, 'models': []}
        records.append(cloud)
    if cloud and old_url and cloud['url'] != old_url:
        cloud['url'] = old_url

    if old_provider == LEGACY_PROVIDER_LOCAL:
        settings['chat_provider'] = 'local'
    elif old_provider == LEGACY_PROVIDER_CLOUD:
        settings['chat_provider'] = CLOUD_ID

    if records != raw:
        settings['llm_providers'] = records

    # the secret is written first; the legacy keys are removed only on success
    key_written = True
    if old_key:
        try:
            key_written = bool(llm_keys.set(CLOUD_ID, old_key))
        except (OSError, ValueError):
            key_written = False
        if not key_written:
            print('yumi: could not move the mind provider key to its private file',
                  file=sys.stderr)

    if key_written:
        for name in (LEGACY_CLOUD_KEY, LEGACY_CLOUD_URL, LEGACY_LOCAL_URL):
            if name in settings:
                del settings[name]

    return any(settings.get(name) != before[name] for name in watched)
