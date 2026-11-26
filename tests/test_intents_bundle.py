#!/usr/bin/env python3
"""ZIP bundles and signed remote repositories for your own intents.
Run: python3 tests/test_intents_bundle.py"""
import base64
import hashlib
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yumi import config, intents_bundle, intents_remote, user_intents  # noqa: E402
from yumi.brain import Brain  # noqa: E402
from yumi.phrases import Speech  # noqa: E402
from yumi.sprites import Meta  # noqa: E402

_tmp = tempfile.TemporaryDirectory()
_original_dir = user_intents.INTENTS_DIR
_original_file = user_intents.INTENTS_FILE
user_intents.INTENTS_DIR = Path(_tmp.name) / 'user-intents'
user_intents.INTENTS_FILE = Path(_tmp.name) / 'user_intents.json'
ROOT = user_intents.INTENTS_DIR

try:
    LAMP = {
        'id': 'lights_on', 'name': 'Свет', 'phrases': ['включи свет'],
        'action': {'type': 'command', 'value': 'python3 lights.py'},
        'capture': True, 'speak': 'Свет: {stdout}',
    }
    NEWS = {
        'id': 'news', 'name': 'Новости', 'keywords': ['новости'],
        'action': {'type': 'say', 'value': 'Сейчас расскажу'},
    }
    user_intents.save({'version': 1, 'revision': 0, 'intents': [LAMP]}, ROOT)
    (ROOT / 'lights_on' / 'lights.py').write_text('print("on")\n')
    (ROOT / 'lights_on' / 'lights.py').chmod(0o755)
    (ROOT / 'lights_on' / 'note.txt').write_text('a note\n')

    # ---- export: manifest, hashes, modes, all the files a rule needs
    raw = intents_bundle.export_bundle(ROOT)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        assert names == ['manifest.json', 'intents/index.json',
                         'intents/lights_on/intent.json', 'intents/lights_on/lights.py',
                         'intents/lights_on/note.txt'], names
        manifest = json.loads(archive.read('manifest.json'))
        info = archive.getinfo('intents/lights_on/lights.py')
        assert (info.external_attr >> 16) & 0o777 == 0o755
    assert manifest['format'] == intents_bundle.BUNDLE_FORMAT
    assert len(manifest['files']) == len(names) - 1
    for entry in manifest['files']:
        assert hashlib.sha256(entry['sha256'].encode()).hexdigest() != entry['sha256']
        assert len(entry['sha256']) == 64
    view = intents_bundle.inspect_bundle(raw)
    assert view['file_count'] == 4
    assert view['intents'][0]['id'] == 'lights_on'
    assert view['signature']['status'] == 'unsigned'
    public = intents_bundle.public_view(view)
    assert 'python3 lights.py' not in json.dumps(public)

    # ---- a changed auxiliary file is rejected before anything is installed
    def repack(mutate):
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as src, \
                zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as dst:
            for name in src.namelist():
                dst.writestr(name, mutate(name, src.read(name)))
        return out.getvalue()

    for bad in (
        repack(lambda n, p: b'print("evil")\n' if n.endswith('lights.py') else p),
        repack(lambda n, p: p if n != 'manifest.json'
               else p.replace(b'"format": "yumi-intents-bundle"',
                              b'"format": "tampered"', 1)),
    ):
        try:
            intents_bundle.inspect_bundle(bad)
            raise AssertionError('a bad bundle was accepted')
        except intents_bundle.BadBundle:
            pass

    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as src, \
            zipfile.ZipFile(out, 'w') as dst:
        for name in src.namelist():
            dst.writestr(name.replace('lights.py', '../../escape.py')
                         if name.endswith('lights.py') else name, src.read(name))
    try:
        intents_bundle.inspect_bundle(out.getvalue())
        raise AssertionError('a path escape was accepted')
    except intents_bundle.BadBundle:
        pass

    # ---- replace and merge: files come back, local rules survive a merge
    restore = Path(_tmp.name) / 'restored'
    result = intents_bundle.import_bundle(raw, restore, mode='replace')
    assert result['revision'] == 2
    assert [i['id'] for i in result['intents']] == ['lights_on']
    assert (restore / 'lights_on' / 'lights.py').read_text() == 'print("on")\n'
    assert (restore / 'lights_on' / 'lights.py').stat().st_mode & 0o111

    user_intents.save({'version': 1, 'revision': 0,
                       'intents': [dict(NEWS, action={'type': 'say', 'value': 'hello'})]},
                      restore)
    merged = intents_bundle.import_bundle(raw, restore, mode='merge')
    assert {i['id'] for i in merged['intents']} == {'news', 'lights_on'}
    assert (restore / 'news' / 'intent.json').exists()
    assert (restore / 'lights_on' / 'note.txt').exists()

    # ---- Ed25519: valid, tampered and missing keys
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        Ed25519PrivateKey = None
    if Ed25519PrivateKey is not None:
        private = Ed25519PrivateKey.generate()
        pub = base64.b64encode(
            private.public_key().public_bytes_raw()).decode('ascii')
        keys = [f'official:{pub}']
        signed = intents_bundle.export_bundle(
            ROOT, signer=lambda payload: intents_bundle.sign(payload, private, 'official'))
        signed_view = intents_bundle.inspect_bundle(signed, trusted_keys=keys)
        assert signed_view['signature']['status'] == 'valid'
        assert intents_bundle.inspect_bundle(
            signed, trusted_keys=keys, require_signature=True)['signature']['status'] == 'valid'
        assert intents_bundle.parse_trusted_keys(keys)['official']
        assert intents_bundle.signature_status(b'x', {'algorithm': 'ed25519',
            'key_id': 'official', 'signature': base64.b64encode(b'0' * 64).decode()},
            keys)['status'] == 'invalid'
        try:
            intents_bundle.inspect_bundle(signed, trusted_keys=['official:' + base64.b64encode(
                Ed25519PrivateKey.generate().public_key().public_bytes_raw()).decode()])
            raise AssertionError('a bad signature was accepted')
        except intents_bundle.BadBundle:
            pass
        try:
            intents_bundle.inspect_bundle(raw, require_signature=True)
            raise AssertionError('an unsigned bundle passed a signed-only check')
        except intents_bundle.BadBundle:
            pass

    # ---- remote catalog: signature, checksum, merge install
    catalog = {
        'format': 'yumi-intents-repo', 'version': 1, 'updated_at': '2026-11-26T00:00:00Z',
        'bundles': [{'id': 'pack', 'name': 'Pack', 'version': '1.0',
                     'url': 'pack.zip', 'sha256': hashlib.sha256(raw).hexdigest()}],
    }
    index_raw = json.dumps(catalog).encode()
    settings = {'user_intents_repo_url': 'https://example.org/intents/',
                'user_intents_require_signature': False}
    checked = intents_remote.read_index(index_raw, None, [], False)
    assert checked['bundles'][0]['id'] == 'pack'
    try:
        intents_remote.read_index(index_raw, None, [], True)
        raise AssertionError('an unsigned catalog passed a signed-only check')
    except intents_remote.BadRepository:
        pass

    remote_root = Path(_tmp.name) / 'remote'
    calls = {'n': 0}

    def fake_fetch(url, limit, timeout):
        calls['n'] += 1
        if url.endswith('pack.zip'):
            return raw
        if url.endswith('index.sig'):
            raise __import__('urllib.error', fromlist=['HTTPError']).HTTPError(url, 404, 'no', {}, None)
        return index_raw

    original_fetch = intents_remote._fetch
    intents_remote._fetch = fake_fetch
    try:
        fetched = intents_remote.fetch_bundle(settings, 'pack')
        assert fetched['entry']['id'] == 'pack'
        installed = intents_bundle.import_bundle(
            fetched['raw'], remote_root, mode='merge',
            require_signature=False)
        assert installed['intents'][0]['id'] == 'lights_on'
        assert (remote_root / 'lights_on' / 'lights.py').exists()
    finally:
        intents_remote._fetch = original_fetch
    assert calls['n'] >= 2
finally:
    user_intents.INTENTS_DIR = _original_dir
    user_intents.INTENTS_FILE = _original_file
    _tmp.cleanup()

# ---- the desktop side: the signature switch and a shortcut to the page in the panel
settings = dict(config.DEFAULT_SETTINGS)
b = Brain(Meta(config.SPRITES, None), settings, {'intro_done': True},
          Speech(settings), lambda *_a: (10, 10))
b.open_menu('set_web')
assert ('set', 'user_intents_require_signature',
        config.tr(settings, 'user_intents_require_signature')) in b.menu['rows']
assert not any(a == 'web_intents' for _r, a, _g in b.menu['rows'])
b.settings['web_panel'] = True
b.open_menu('set_web')
assert ('web_intents', None, config.tr(settings, 'web_intents')) in b.menu['rows']
b.requests.clear()
b.do('web_intents', None)
assert ('web_intents',) in b.requests
b.do('set', 'user_intents_require_signature')
assert b.settings['user_intents_require_signature'] is False
assert ('save_settings',) in b.requests
assert b.cycle_text('user_intents_require_signature', True) == config.tr(settings, 'on')

print('intents bundle: ok')
