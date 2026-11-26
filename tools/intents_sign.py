"""Sign intent bundles and repository indexes for the official repository.

The private key stays with the publisher; Yumi only ever sees the public key
configured in `user_intents_trusted_keys`.  The signature covers the canonical
JSON bytes, exactly as yumi.intents_bundle.signature_status() verifies them.

Generate a key once (PEM, keep it private)::

    openssl genpkey -algorithm ED25519 -out intents_ed25519.pem
    openssl pkey -in intents_ed25519.pem -pubout -outform DER | tail -c 32 | base64

Then sign a bundle produced by the panel, or a repository index::

    python3 tools/intents_sign.py bundle intents.zip --key intents_ed25519.pem \
        --key-id official-2026 --out signed.zip
    python3 tools/intents_sign.py index index.json --key intents_ed25519.pem \
        --key-id official-2026 --out index.sig

Requires the optional `cryptography` package.
"""
import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from yumi import intents_bundle  # noqa: E402


def load_key(path):
    try:
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        raise SystemExit('install the optional cryptography package to sign bundles')
    data = Path(path).read_bytes()
    try:
        return serialization.load_pem_private_key(data, password=None)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f'cannot read the private key: {exc}') from exc


def sign_index(path, key, key_id, out):
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    record = intents_bundle.sign(intents_bundle.canonical_bytes(payload), key, key_id)
    Path(out).write_text(json.dumps(record, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'signed {path} -> {out}')


def sign_bundle(path, key, key_id, out):
    src = zipfile.ZipFile(path)
    with src:
        names = src.namelist()
        if intents_bundle.MANIFEST_NAME not in names:
            raise SystemExit('this ZIP has no manifest.json')
        manifest = json.loads(src.read(intents_bundle.MANIFEST_NAME).decode('utf-8'))
        record = intents_bundle.sign(intents_bundle.canonical_bytes(manifest), key, key_id)
        sig = (json.dumps(record, ensure_ascii=False) + '\n').encode('utf-8')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as dst:
            for name in names:
                if name == intents_bundle.SIGNATURE_NAME:
                    continue
                dst.writestr(name, src.read(name))
            dst.writestr(intents_bundle.SIGNATURE_NAME, sig)
    Path(out).write_bytes(buffer.getvalue())
    print(f'signed {path} -> {out}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('bundle', 'index'))
    parser.add_argument('path')
    parser.add_argument('--key', required=True, help='PEM private Ed25519 key')
    parser.add_argument('--key-id', default='', help='id published with the public key')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    key = load_key(args.key)
    if args.kind == 'index':
        sign_index(args.path, key, args.key_id, args.out)
    else:
        sign_bundle(args.path, key, args.key_id, args.out)


if __name__ == '__main__':
    main()
