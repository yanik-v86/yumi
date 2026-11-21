#!/usr/bin/env python3
"""A broken settings.json is kept as .bad, never silently overwritten.
Run: python3 tests/test_config_backup.py"""
import io
import sys
import tempfile
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yumi import config  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix='yumi-config-'))

broken = tmp / 'settings.json'
broken.write_text('{ this is not JSON')
err = io.StringIO()
with redirect_stderr(err):
    store = config.Store(broken, {'ui_lang': 'en', 'web_panel': False})
assert dict(store) == {'ui_lang': 'en', 'web_panel': False}
assert (tmp / 'settings.json.bad').read_text() == '{ this is not JSON'
assert 'broken' in err.getvalue() and 'settings.json.bad' in err.getvalue()

array = tmp / 'other.json'
array.write_text('[]')
with redirect_stderr(io.StringIO()):
    config.Store(array, {'a': 1})
assert (tmp / 'other.json.bad').read_text() == '[]'

good = tmp / 'good.json'
good.write_text('{"ui_lang": "ru", "unknown": 7}')
with redirect_stderr(io.StringIO()):
    good_store = config.Store(good, {'ui_lang': 'en', 'web_panel': False})
assert good_store['ui_lang'] == 'ru' and good_store['unknown'] == 7
assert not (tmp / 'good.json.bad').exists()

print('test_config_backup: ok')
