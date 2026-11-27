#!/usr/bin/env python3
"""Old settings become ordinary provider records: python3 tests/test_llm_migrate.py"""
import sys
import tempfile
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

from yumi import llm, llm_keys, llm_migrate  # noqa: E402

_original_keys_file = llm_keys.KEYS_FILE
tmp = tempfile.TemporaryDirectory()
llm_keys.KEYS_FILE = Path(tmp.name) / 'llm_keys.json'

LEGACY_LOCAL_URL = llm_migrate.LEGACY_LOCAL_URL
LEGACY_CLOUD_URL = llm_migrate.LEGACY_CLOUD_URL
LEGACY_CLOUD_KEY = llm_migrate.LEGACY_CLOUD_KEY

old = {
    'chat_provider': llm_migrate.LEGACY_PROVIDER_CLOUD,
    'chat_model': llm_migrate.CLOUD_MODEL,
    LEGACY_LOCAL_URL: 'http://127.0.0.1:5555',
    LEGACY_CLOUD_URL: 'https://example.test/v1',
    LEGACY_CLOUD_KEY: 'secret',
}
assert llm_migrate.migrate(old)
assert old['chat_provider'] == llm_migrate.CLOUD_ID
assert old['embed_url'] == 'http://127.0.0.1:5555'
assert not {LEGACY_LOCAL_URL, LEGACY_CLOUD_URL, LEGACY_CLOUD_KEY} & old.keys(), old
cloud = next(r for r in old['llm_providers'] if r['id'] == 'cloud')
local = next(r for r in old['llm_providers'] if r['id'] == 'local')
assert cloud['kind'] == 'openai' and cloud['url'] == 'https://example.test/v1'
assert cloud['default_model'] == 'deepseek/deepseek-v4-flash'
assert local['url'] == 'http://127.0.0.1:5555'
assert llm_keys.get('cloud') == 'secret' and 'key' not in cloud
assert not llm_migrate.migrate(old), 'a second migration must be idempotent'

fresh = {'chat_provider': llm_migrate.LEGACY_PROVIDER_LOCAL, 'chat_model': 'any-model'}
assert llm_migrate.migrate(fresh)
assert fresh['chat_provider'] == 'local'
assert fresh['embed_url'] == llm.DEFAULT_EMBED_URL
assert len(fresh['llm_providers']) == 1
assert not llm_migrate.migrate(fresh)

# a failed key write leaves the legacy key in place: nothing is silently lost
saved_set = llm_keys.set
try:
    llm_keys.set = lambda *_a: False
    failed = {'chat_provider': llm_migrate.LEGACY_PROVIDER_CLOUD,
              LEGACY_CLOUD_KEY: 'another-secret'}
    assert llm_migrate.migrate(failed)
    assert failed[LEGACY_CLOUD_KEY] == 'another-secret'
finally:
    llm_keys.set = saved_set

llm_keys.KEYS_FILE = _original_keys_file
tmp.cleanup()
print('ok')
