#!/usr/bin/env python3
"""Copy the bot's current Schwab access token to the dashboard (root, every minute).

Schwab rotates the refresh token on every refresh, so the dashboard must never refresh
on its own (it would log the bot out). It only borrows the access token the bot keeps
fresh. Nothing is printed except whether a copy happened.
"""
import fcntl, json, os, pwd
from pathlib import Path

BOT = Path('/root/.openclaw/schwab_token.json')
STATE = Path('/var/lib/member-dashboard/schwab')
owner = pwd.getpwnam('md-compute')

def private(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    os.fchown(fd, owner.pw_uid, owner.pw_gid); os.fchmod(fd, 0o600)
    return fd

source = json.loads(BOT.read_text())
target = STATE / 'token.json'
lock = private(STATE / 'refresh.lock')
try:
    fcntl.flock(lock, fcntl.LOCK_EX)
    current = json.loads(target.read_text()) if target.exists() else {}
    if current.get('token', {}).get('access_token') != source['token']['access_token']:
        pending = STATE / 'token.sync-pending'
        fd = private(pending)
        with os.fdopen(fd, 'w') as out:
            json.dump(source, out); out.flush(); os.fsync(out.fileno())
        os.replace(pending, target)
        print('copied newer access token')
finally:
    fcntl.flock(lock, fcntl.LOCK_UN); os.close(lock)
