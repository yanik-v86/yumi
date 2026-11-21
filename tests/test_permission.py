#!/usr/bin/env python3
"""Permission rules: refusals win, secrets are never remembered forever.
Run: python3 tests/test_permission.py"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yumi import permission  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix='yumi-permission-'))
original = permission.PERMISSION_FILE
permission.PERMISSION_FILE = tmp / 'permissions.json'

try:
    assert permission.words('Да, НЕт') == ['да', 'нет']
    assert permission.spoken_answer('да нет') == 'deny'
    assert permission.spoken_answer('давай') == 'once'
    assert permission.spoken_answer('всегда') is None   # only a click grants ALWAYS
    assert permission.negative_wins(['once', 'always', 'deny']) == 'deny'
    assert permission.negative_wins(['once', 'always']) == 'always'

    assert permission.is_secret('~/.ssh/id_rsa')
    assert permission.is_secret('file:///home/me/.ssh/../.ssh/config')
    assert permission.is_secret('https://user:password@example.org/')
    assert not permission.is_secret(str(tmp / 'notes.txt'))

    # a symlink must not sneak a protected folder past the check
    hidden = tmp / '.ssh'
    hidden.mkdir()
    (hidden / 'config').write_text('host example')
    outside = tmp / 'open'
    outside.mkdir()
    (outside / 'link').symlink_to(hidden, target_is_directory=True)
    assert permission.is_secret(str(outside / 'link' / 'config'))

    safe = tmp / 'safe' / 'script.sh'
    safe.parent.mkdir()
    safe.write_text('#!/bin/sh\n')
    assert not permission.is_secret(str(safe))
    assert permission.remember(str(safe.parent), 'allow')
    assert permission.allowed(str(safe))
    assert permission.allowed(str(safe.parent / 'child' / 'other.sh'))
    assert not permission.allowed(str(hidden / 'config'))
    assert not permission.remember(str(hidden / 'id_rsa'), 'allow')

    # an exact denial beats the broader allow and survives a reload of the file
    assert permission.remember(str(safe), 'deny')
    assert not permission.allowed(str(safe))
    rules = permission.snapshot()
    assert str(safe) in rules['deny'] and str(safe.parent) not in rules['allow']

    assert permission.clear()
    assert not permission.allowed(str(safe))
finally:
    permission.PERMISSION_FILE = original

print('test_permission: ok')
