#!/usr/bin/env python3
"""Root pre-step of the nightly backup: private copy of the web DB for md-archive.

The archive role never reads the live database. It receives this copy, strips the feed
cards, encrypts it and deletes it.
"""
import os, pwd, sqlite3
from contextlib import closing

WEB = '/var/lib/member-dashboard/web/web.sqlite3'
ROOT = '/var/lib/member-dashboard/archives'
owner = pwd.getpwnam('md-archive')
tmp, final = ROOT + '/web-snapshot.partial', ROOT + '/web-snapshot.sqlite3'
for path in (tmp, final): os.unlink(path) if os.path.exists(path) else None
fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600); os.close(fd)
with closing(sqlite3.connect(f'file:{WEB}?mode=ro', uri=True, timeout=10)) as src, closing(sqlite3.connect(tmp)) as dst:
    src.backup(dst)
    dst.execute('PRAGMA journal_mode=DELETE')
os.chown(tmp, owner.pw_uid, owner.pw_gid); os.chmod(tmp, 0o600)
os.replace(tmp, final)
print('web snapshot ready for the nightly backup')
