"""Portable ZIP bundles for your own intents.

A bundle is the whole live store plus every file that lives beside a rule:

    manifest.json              format, hashes and modes of all payload files
    manifest.sig               optional detached Ed25519 signature of manifest.json
    intents/index.json         version, revision, the order of the rules
    intents/<id>/intent.json   one rule, exactly as in the live folder
    intents/<id>/<your files>  scripts and other files the rule needs

The manifest is canonical JSON; the signature covers those bytes, so every
payload file is covered by its SHA-256 in the manifest.  A local export is
unsigned (you have no official private key); an import verifies a signature
when one is present.  Symlinks, absolute paths and ``..`` never enter a bundle,
and nothing here runs a command or imports GTK.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path

from . import user_intents

BUNDLE_FORMAT = 'yumi-intents-bundle'
BUNDLE_VERSION = 1
MANIFEST_NAME = 'manifest.json'
SIGNATURE_NAME = 'manifest.sig'
INTENTS_PREFIX = 'intents/'
SIGN_ALGORITHM = 'ed25519'

MAX_ARCHIVE = 8 * 1024 * 1024
MAX_FILE = 1024 * 1024
MAX_FILES = 200
SKIP_NAMES = {'__pycache__', '.git', 'Thumbs.db', '.DS_Store'}
_HEX64 = re.compile(r'^[0-9a-f]{64}$')
_SAFE_FILE = re.compile(r'^[a-zA-Z0-9_-]{1,64}/[a-zA-Z0-9][a-zA-Z0-9._-]{0,119}$')

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
except ImportError:                      # an optional dependency, not a hard one
    InvalidSignature = None
    Ed25519PublicKey = None


class BadBundle(ValueError):
    """the archive is not a safe, well-formed intent bundle"""


def canonical_bytes(payload):
    """the exact bytes a detached signature is made over"""
    return json.dumps(payload, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False).encode('utf-8')


def signature_available():
    """can this installation verify Ed25519 signatures at all?"""
    return Ed25519PublicKey is not None


def parse_trusted_keys(value):
    """``key_id:base64_ed25519_pubkey`` lines into ``{key_id: raw_key}``

    A line without a colon is a key with an empty id; it is used only when it
    is the sole configured key.  Bad lines are skipped: a broken key must not
    make the whole panel unusable.
    """
    if isinstance(value, dict):
        raw_lines = [f'{k}:{v}' for k, v in value.items()]
    elif isinstance(value, str):
        raw_lines = [value]
    elif isinstance(value, (list, tuple)):
        raw_lines = [str(item) for item in value]
    else:
        raw_lines = []
    # The settings form sends a textarea either as one string or as a list of
    # lines (catalog.coerce splits on commas), so accept all three shapes.
    lines = []
    for raw in raw_lines:
        lines.extend(str(raw).replace(',', '\n').splitlines())
    out = {}
    for line in lines:
        text = str(line).strip()
        if not text or text.startswith('#'):
            continue
        key_id, sep, encoded = text.partition(':')
        if not sep:
            key_id, encoded = '', key_id
        try:
            raw = base64.b64decode(encoded.strip(), validate=True)
        except (ValueError, TypeError):
            continue
        if len(raw) != 32:
            continue
        out[key_id.strip()[:64]] = raw
    return out


def sign(canonical, private_key, key_id=''):
    """make a detached signature record (used by the signing tool, never here)"""
    if private_key is None:
        raise ValueError('a private Ed25519 key is needed to sign')
    try:
        raw = private_key.sign(canonical)
    except AttributeError:
        raise ValueError('the private key cannot sign with Ed25519') from None
    return {'algorithm': SIGN_ALGORITHM, 'key_id': str(key_id or '')[:64],
            'signature': base64.b64encode(raw).decode('ascii')}


def signature_status(payload, info, trusted_keys=()):
    """verify a detached signature over ``payload``; never raises on bad input"""
    if not info:
        return {'status': 'unsigned', 'key_id': ''}
    if not isinstance(info, dict):
        return {'status': 'bad-format', 'key_id': ''}
    key_id = str(info.get('key_id') or '')[:64]
    result = {'status': 'bad-format', 'key_id': key_id}
    if str(info.get('algorithm') or '') != SIGN_ALGORITHM:
        return {**result, 'status': 'unsupported-algorithm'}
    try:
        raw_sig = base64.b64decode(str(info.get('signature') or ''), validate=True)
    except (ValueError, TypeError):
        return result
    keys = parse_trusted_keys(trusted_keys)
    if key_id and key_id in keys:
        candidates = [keys[key_id]]
    elif not key_id and len(keys) == 1:
        candidates = list(keys.values())
    else:
        return {**result, 'status': 'unknown-key'}
    if Ed25519PublicKey is None:
        return {**result, 'status': 'no-verifier'}
    for raw_key in candidates:
        try:
            Ed25519PublicKey.from_public_bytes(raw_key).verify(raw_sig, payload)
            return {**result, 'status': 'valid'}
        except (ValueError, InvalidSignature, TypeError):
            continue
    return {**result, 'status': 'invalid'}


def _payload(path, mode):
    digest = hashlib.sha256(path[1]).hexdigest()
    return {'path': path[0], 'sha256': digest, 'size': len(path[1]),
            'mode': int(mode) & 0o777}


def _safe_rel(path):
    """only index.json or <id>/<plain filename>, never a directory escape"""
    if not isinstance(path, str) or '\\' in path or path.startswith('/'):
        return False
    if '..' in path.split('/'):
        return False
    return path == user_intents.INDEX_FILE or bool(_SAFE_FILE.fullmatch(path))


def _aux_files(folder):
    """your own files beside intent.json; symlinks and junk are left out"""
    out = []
    for item in sorted(folder.iterdir()):
        name = item.name
        if (name == user_intents.INTENT_FILE or name in SKIP_NAMES
                or name.startswith('.') or item.is_symlink() or not item.is_file()):
            continue
        if len(name) > 120 or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]*', name):
            continue
        try:
            payload = item.read_bytes()
            mode = item.stat().st_mode & 0o777
        except OSError:
            continue
        if len(payload) > MAX_FILE:
            raise BadBundle(f'{name} is too large for a bundle (max {MAX_FILE})')
        out.append((name, payload, mode))
    return out


def export_bundle(path=None, signer=None):
    """build a ZIP from the live store; ``signer`` gets canonical manifest bytes"""
    root = user_intents.root_dir(path)
    data = user_intents.load(root)
    files = {}

    def put(rel, payload, mode=0o644):
        files[rel] = (payload, mode)

    index = {'version': user_intents.FORMAT_VERSION, 'revision': data['revision'],
             'order': [item['id'] for item in data['intents']]}
    put(user_intents.INDEX_FILE,
        (json.dumps(index, indent=1, ensure_ascii=False) + '\n').encode('utf-8'))
    total = 1
    for item in data['intents']:
        ident = item['id']
        put(f'{ident}/{user_intents.INTENT_FILE}',
            (json.dumps(item, indent=1, ensure_ascii=False) + '\n').encode('utf-8'))
        total += 1
        for name, payload, mode in _aux_files(root / ident):
            put(f'{ident}/{name}', payload, mode)
            total += 1
    if total > MAX_FILES or sum(len(v[0]) for v in files.values()) > MAX_ARCHIVE:
        raise BadBundle('too many or too large files for one bundle')

    manifest = {
        'format': BUNDLE_FORMAT, 'version': BUNDLE_VERSION,
        'created_at': user_intents._stamp(), 'revision': data['revision'],
        'intents': [item['id'] for item in data['intents']],
        'files': [_payload((rel, files[rel][0]), files[rel][1]) for rel in sorted(files)],
    }
    raw_manifest = (json.dumps(manifest, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        def add(name, payload, mode=0o644):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100000 | int(mode) & 0o777) << 16
            archive.writestr(info, payload)

        add(MANIFEST_NAME, raw_manifest)
        if signer is not None:
            record = signer(canonical_bytes(manifest))
            add(SIGNATURE_NAME,
                (json.dumps(record, ensure_ascii=False) + '\n').encode('utf-8'))
        for rel in sorted(files):
            payload, mode = files[rel]
            add(INTENTS_PREFIX + rel, payload, mode)
    return out.getvalue()


def inspect_bundle(raw, trusted_keys=(), require_signature=False):
    """check a ZIP before writing anything: paths, hashes, signature, intents"""
    if not isinstance(raw, (bytes, bytearray)):
        raise BadBundle('a ZIP file is needed')
    raw = bytes(raw)
    if len(raw) > MAX_ARCHIVE:
        raise BadBundle(f'the bundle is too large (max {MAX_ARCHIVE} bytes)')
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, OSError, ValueError):
        raise BadBundle('this is not a ZIP archive') from None
    with archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise BadBundle('the bundle has duplicate files')
        if len(names) > MAX_FILES + 2:
            raise BadBundle('too many files in the bundle')
        name_set = set(names)
        if MANIFEST_NAME not in name_set:
            raise BadBundle('manifest.json is missing')
        for name in names:
            if name in (MANIFEST_NAME, SIGNATURE_NAME):
                continue
            if name.endswith('/') or not name.startswith(INTENTS_PREFIX):
                raise BadBundle(f'unexpected path in the bundle: {name[:120]}')
            if not _safe_rel(name[len(INTENTS_PREFIX):]):
                raise BadBundle(f'unsafe path in the bundle: {name[:120]}')
        try:
            manifest = json.loads(archive.read(MANIFEST_NAME).decode('utf-8'))
        except (KeyError, ValueError, UnicodeDecodeError):
            raise BadBundle('manifest.json is not valid JSON') from None
        if not isinstance(manifest, dict) or manifest.get('format') != BUNDLE_FORMAT:
            raise BadBundle('not a Yumi intent bundle')
        try:
            version = int(manifest.get('version'))
        except (TypeError, ValueError):
            version = 0
        if version != BUNDLE_VERSION:
            raise BadBundle(f'unsupported bundle version: {version}')
        entries = manifest.get('files')
        if not isinstance(entries, list) or len(entries) > MAX_FILES:
            raise BadBundle('the file list is broken')

        signature = None
        if SIGNATURE_NAME in name_set:
            try:
                signature = json.loads(archive.read(SIGNATURE_NAME).decode('utf-8'))
            except (KeyError, ValueError, UnicodeDecodeError):
                raise BadBundle('manifest.sig is not valid JSON') from None
        verified = signature_status(canonical_bytes(manifest), signature, trusted_keys)
        if signature and verified['status'] not in ('valid', 'no-verifier'):
            raise BadBundle(f'the bundle signature is {verified["status"]}')
        if require_signature and verified['status'] != 'valid':
            raise BadBundle('a valid official signature is required')
        warnings = []
        if verified['status'] == 'no-verifier':
            warnings.append('Ed25519 verification is unavailable (install cryptography)')

        payloads = {}
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise BadBundle('a file entry is broken')
            rel = entry.get('path')
            if not _safe_rel(rel) or rel in seen:
                raise BadBundle('a file entry has an unsafe or duplicate path')
            seen.add(rel)
            digest, size = entry.get('sha256'), entry.get('size')
            if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
                raise BadBundle(f'bad checksum for {rel}')
            try:
                size = int(size)
            except (TypeError, ValueError):
                raise BadBundle(f'bad size for {rel}') from None
            if size < 0 or size > MAX_FILE:
                raise BadBundle(f'bad size for {rel}')
            name = INTENTS_PREFIX + rel
            if name not in name_set:
                raise BadBundle(f'{rel} is missing from the ZIP')
            try:
                payload = archive.read(name)
            except (KeyError, OSError):
                raise BadBundle(f'cannot read {rel}') from None
            if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
                raise BadBundle(f'{rel} does not match the manifest')
            try:
                mode = int(entry.get('mode', 0o644)) & 0o777
            except (TypeError, ValueError):
                mode = 0o644
            payloads[rel] = (payload, mode)
        extra = name_set - {MANIFEST_NAME, SIGNATURE_NAME} - {
            INTENTS_PREFIX + rel for rel in seen}
        if extra:
            raise BadBundle(f'files are not in the manifest: {sorted(extra)[0][:120]}')

    index_rel = user_intents.INDEX_FILE
    if index_rel not in payloads:
        raise BadBundle('intents/index.json is missing')
    try:
        index = json.loads(payloads[index_rel][0].decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise BadBundle('intents/index.json is not valid JSON') from None
    if not isinstance(index, dict):
        raise BadBundle('intents/index.json is broken')
    try:
        revision = int(index.get('revision', 0))
    except (TypeError, ValueError):
        revision = 0
    order = index.get('order', [])
    if not isinstance(order, list):
        order = []
    ids = [str(item.get('path', '')).split('/')[0]
           for item in entries
           if str(item.get('path', '')).endswith('/' + user_intents.INTENT_FILE)]
    for ident in ids:
        if ident not in order:
            order.append(ident)
    raw_intents = []
    used = set()
    for ident in order:
        ident = str(ident)
        rel = f'{ident}/{user_intents.INTENT_FILE}'
        if rel not in payloads or not user_intents.ID_RE.fullmatch(ident) or ident in used:
            continue
        used.add(ident)
        try:
            raw = json.loads(payloads[rel][0].decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            raise BadBundle(f'{rel} is not valid JSON') from None
        if not isinstance(raw, dict):
            raise BadBundle(f'{rel} is broken')
        raw_intents.append({**raw, 'id': ident})  # the folder is the id
    document = user_intents.validate({
        'version': user_intents.FORMAT_VERSION,
        'revision': max(0, revision), 'intents': raw_intents,
    })
    return {
        'format': BUNDLE_FORMAT, 'version': BUNDLE_VERSION,
        'revision': document['revision'], 'document': document, 'entries': payloads,
        'signature': verified, 'warnings': warnings,
        'intents': [user_intents.public(item) for item in document['intents']],
        'files': sorted(payloads), 'file_count': len(payloads),
    }


def _copy_live_files(root, staging):
    """merge mode: keep the current folder's files in the staged tree"""
    if not root.exists():
        return
    for item in root.rglob('*'):
        if item.is_symlink() or not item.is_file():
            continue
        rel = item.relative_to(root).as_posix()
        if not _safe_rel(rel):
            continue
        target = staging / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(item, target)
            target.chmod(item.stat().st_mode & 0o777)
        except OSError:
            continue


def _replace_root(root, staging):
    """swap the trees, keeping the old one until the new one is in place"""
    parent = root.parent
    parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if root.exists():
        backup = parent / f'.{root.name}.old-{uuid.uuid4().hex[:8]}'
        root.rename(backup)
    try:
        staging.rename(root)
    except OSError:
        if backup is not None:
            backup.rename(root)
        raise
    if backup is not None:
        shutil.rmtree(backup, ignore_errors=True)


def import_bundle(raw, path=None, mode='replace', trusted_keys=(),
                  require_signature=False):
    """verify and install a ZIP; ``mode='merge'`` keeps unrelated local rules"""
    if mode not in ('replace', 'merge'):
        raise BadBundle('mode must be replace or merge')
    view = inspect_bundle(raw, trusted_keys=trusted_keys,
                          require_signature=require_signature)
    root = user_intents.root_dir(path)
    current = user_intents.load(root) if mode == 'merge' else user_intents.empty()
    document = view['document']
    if mode == 'merge':
        by_id = {item['id']: item for item in document['intents']}
        merged = {item['id']: item for item in current['intents']}
        merged.update(by_id)
        order = [item['id'] for item in current['intents'] if item['id'] in merged]
        order += [ident for ident in by_id if ident not in order]
        document = {
            'version': user_intents.FORMAT_VERSION,
            'revision': max(current['revision'], document['revision']),
            'intents': [merged[ident] for ident in order],
        }

    parent = root.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / f'.{root.name}.new-{uuid.uuid4().hex[:8]}'
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        if mode == 'merge':
            _copy_live_files(root, staging)
        for rel, (payload, mode_bits) in view['entries'].items():
            target = staging / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            target.chmod(mode_bits)
        saved = user_intents.save(document, staging)
        _replace_root(root, staging)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return {
        'version': saved['version'], 'revision': saved['revision'],
        'intents': saved['intents'], 'mode': mode,
        'files': view['file_count'], 'signature': view['signature'],
        'warnings': view['warnings'], 'mtime': user_intents.mtime(root),
    }


def public_view(view):
    """what may cross into the browser: no command text, no file contents"""
    return {
        'format': view['format'], 'version': view['version'],
        'revision': view['revision'], 'intents': view['intents'],
        'files': view['files'], 'file_count': view['file_count'],
        'signature': view['signature'], 'warnings': view['warnings'],
    }
