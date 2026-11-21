#!/usr/bin/env python3
"""Model integrity: record a hash, then spot a changed copy (no GTK, no daemon).
Run: python3 tests/test_models.py"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yumi import models  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix='yumi-models-'))
one = tmp / 'model.bin'
one.write_bytes(b'original model bytes')
folder = tmp / 'vosk'
folder.mkdir()
(folder / 'a.bin').write_bytes(b'a')
(folder / 'b.bin').write_bytes(b'b')
unknown = tmp / 'unknown.bin'
unknown.write_bytes(b'never recorded')
missing = tmp / 'not-here'

old_specs, old_hash, old_last = models.specs, models.HASH_FILE, models._last
models.specs = lambda: {'one': one, 'folder': folder, 'unknown': unknown, 'missing': missing}
models.HASH_FILE = tmp / 'model_hashes.json'
models._last = None

try:
    recorded = models.record(['one', 'folder', 'missing'])
    assert 'one' in recorded['saved'] and models.HASH_FILE.exists()
    assert len(models.hashes()) == 2            # the missing path was not saved

    data = models.verify()
    assert data['one']['status'] == 'ok', data['one']
    assert data['folder']['status'] == 'ok'
    assert data['folder']['size'] == 2
    assert data['unknown']['status'] == 'unknown'
    assert data['missing']['status'] == 'missing'
    assert all('token' not in str(v).lower() for v in data.values())

    one.write_bytes(b'changed model bytes')
    data = models.verify()
    assert data['one']['status'] == 'bad', data['one']
    assert data['folder']['status'] == 'ok'

    cached = models.verify_cached(force=True)
    assert cached['models']['one']['status'] == 'bad'
    assert models.cached()['checked'] == cached['checked']
finally:
    models.specs, models.HASH_FILE, models._last = old_specs, old_hash, old_last

print('test_models: ok')
