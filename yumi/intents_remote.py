"""Fetch official intent bundles from a repository over HTTPS.

The repository is a directory with two small files and any number of bundles:

    index.json          {"format": "yumi-intents-repo", "version": 1,
                         "bundles": [{"id": "news", "name": "News",
                                      "version": "1.0", "url": "news.zip",
                                      "sha256": "...", "description": "..."}]}
    index.sig           detached Ed25519 signature of canonical index.json
    <bundle>.zip        an ordinary bundle from yumi.intents_bundle

Both the index and every bundle are checked before anything is installed: the
URL must be https (or localhost for development), redirects must stay on the
same host, the index signature must verify against the configured public key,
the bundle SHA-256 must match the index, and the bundle's own signature (when
present) must verify too.  The default URL is empty until the official
repository is published; no request is made without an explicit URL.
"""
from __future__ import annotations

import hashlib
import json
import re
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urljoin, urlsplit

from . import intents_bundle

OFFICIAL_REPO_URL = ''      # set when the official repository is published
INDEX_NAME = 'index.json'
SIGNATURE_NAME = 'index.sig'
REPO_FORMAT = 'yumi-intents-repo'
REPO_VERSION = 1
MAX_INDEX = 256 * 1024
MAX_BUNDLE = intents_bundle.MAX_ARCHIVE
_REPO_ID = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')


class BadRepository(ValueError):
    """the remote index or bundle cannot be trusted"""


def _check_url(url):
    try:
        parts = urlsplit(str(url or '').strip())
    except ValueError:
        raise BadRepository('bad repository URL') from None
    if parts.scheme not in ('https', 'http'):
        raise BadRepository('the repository must use https')
    if parts.scheme == 'http' and parts.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise BadRepository('plain http is allowed only for localhost')
    if not parts.hostname or parts.username or parts.password:
        raise BadRepository('bad repository URL')
    return parts


def _fetch(url, limit, timeout):
    parts = _check_url(url)
    req = urlrequest.Request(url, headers={'User-Agent': 'Yumi-Intents/1'})
    try:
        with urlrequest.urlopen(req, timeout=timeout) as response:
            final = urlsplit(response.geturl())
            if (final.hostname != parts.hostname or final.scheme != parts.scheme
                    or final.username or final.password):
                raise BadRepository('the repository redirected to another address')
            try:
                declared = int(response.headers.get('Content-Length') or 0)
            except (TypeError, ValueError):
                declared = 0
            if declared > limit:
                raise BadRepository('the remote file is too large')
            raw = response.read(limit + 1)
    except urlerror.HTTPError:
        raise
    except urlerror.URLError as exc:
        raise BadRepository(f'cannot reach the repository: {exc.reason}') from None
    except (OSError, TimeoutError):
        raise BadRepository('cannot reach the repository') from None
    if len(raw) > limit:
        raise BadRepository('the remote file is too large')
    return raw


def _base_url(settings, url=None):
    value = str(url or (settings.get('user_intents_repo_url') if settings else '') or '').strip()
    if not value:
        raise BadRepository('the repository URL is empty')
    if value.endswith('/' + INDEX_NAME):
        value = value[:-len(INDEX_NAME)]
    if not value.endswith('/'):
        value += '/'
    _check_url(value)
    return value


def trusted_keys(settings):
    return intents_bundle.parse_trusted_keys(
        (settings or {}).get('user_intents_trusted_keys'))


def require_signature(settings):
    value = (settings or {}).get('user_intents_require_signature', True)
    return value is not False


def read_index(raw, sig_raw, keys, required):
    """validate the remote catalog; a present but bad signature is fatal"""
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise BadRepository('index.json is not valid JSON') from None
    signature = None
    if sig_raw:
        try:
            signature = json.loads(sig_raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            raise BadRepository('index.sig is not valid JSON') from None
    verified = intents_bundle.signature_status(
        intents_bundle.canonical_bytes(payload), signature, keys)
    if signature and verified['status'] not in ('valid', 'no-verifier'):
        raise BadRepository(f'the repository signature is {verified["status"]}')
    if required and verified['status'] != 'valid':
        raise BadRepository('a valid official repository signature is required')
    if not isinstance(payload, dict) or payload.get('format') != REPO_FORMAT:
        raise BadRepository('this is not a Yumi intent repository')
    try:
        version = int(payload.get('version'))
    except (TypeError, ValueError):
        version = 0
    if version != REPO_VERSION:
        raise BadRepository(f'unsupported repository version: {version}')
    raw_bundles = payload.get('bundles', [])
    if not isinstance(raw_bundles, list) or len(raw_bundles) > 100:
        raise BadRepository('the bundle list is broken')
    bundles = []
    seen = set()
    for item in raw_bundles:
        if not isinstance(item, dict):
            continue
        ident = str(item.get('id') or '').strip()
        if not _REPO_ID.fullmatch(ident) or ident in seen:
            continue
        digest = str(item.get('sha256') or '').strip().lower()
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            continue
        name = str(item.get('name') or ident)[:200]
        bundle_url = str(item.get('url') or '').strip()[:1000]
        if not bundle_url:
            continue
        seen.add(ident)
        bundles.append({
            'id': ident, 'name': name, 'url': bundle_url, 'sha256': digest,
            'version': str(item.get('version') or '')[:40],
            'description': str(item.get('description') or '')[:500],
        })
    return {
        'format': REPO_FORMAT, 'version': REPO_VERSION, 'url': '',
        'updated_at': str(payload.get('updated_at') or '')[:40],
        'signature': verified, 'bundles': bundles,
    }


def fetch_index(settings, url=None, timeout=10):
    """GET and verify the repository catalog; no writes, no code execution"""
    base = _base_url(settings, url)
    raw = _fetch(urljoin(base, INDEX_NAME), MAX_INDEX, timeout)
    try:
        sig_raw = _fetch(urljoin(base, SIGNATURE_NAME), 4096, timeout)
    except urlerror.HTTPError as exc:
        if exc.code != 404:
            raise BadRepository('cannot read the repository signature') from None
        sig_raw = None
    result = read_index(raw, sig_raw, trusted_keys(settings), require_signature(settings))
    result['url'] = base
    result['signature_required'] = require_signature(settings)
    result['signature_available'] = intents_bundle.signature_available()
    return result


def fetch_bundle(settings, bundle_id, timeout=30):
    """GET one catalog entry and verify its SHA-256 and its own signature"""
    base = _base_url(settings)
    catalog = fetch_index(settings, timeout=timeout)
    entry = next((item for item in catalog['bundles']
                  if item['id'] == str(bundle_id)), None)
    if entry is None:
        raise BadRepository('there is no such bundle in the repository')
    url = urljoin(base, entry['url'])
    _check_url(url)
    raw = _fetch(url, MAX_BUNDLE, timeout)
    if hashlib.sha256(raw).hexdigest() != entry['sha256']:
        raise BadRepository('the bundle does not match the repository checksum')
    view = intents_bundle.inspect_bundle(
        raw, trusted_keys=trusted_keys(settings),
        require_signature=require_signature(settings))
    return {'raw': raw, 'entry': entry, 'base': base, 'view': view}
