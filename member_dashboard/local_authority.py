"""Host-only root-owned grants, independent of HTTP settings and caller strings."""
import json
import os
from pathlib import Path
import stat
import sys

from .auth import AuthError

GRANT_PATH = Path('/etc/member-dashboard/recovery.json')


def verify_local_operator(web_path):
    # Windows has no supported privileged recovery adapter. Fail closed.
    if os.name != 'posix' or not sys.stdin.isatty() or not sys.stderr.isatty():
        raise AuthError()
    import pwd
    try:
        for parent in [GRANT_PATH.parent.parent, GRANT_PATH.parent]:
            info = parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise AuthError()
        fd = os.open(GRANT_PATH, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > 4096:
                raise AuthError()
            with os.fdopen(fd, 'r', encoding='utf-8', closefd=False) as source:
                grant = json.load(source)
        finally:
            os.close(fd)
        uid = os.geteuid()
        if (set(grant) != {'allowed_uids','service_uid','web_path'}
                or not isinstance(grant['allowed_uids'], list)
                or any(type(item) is not int for item in grant['allowed_uids'])
                or type(grant['service_uid']) is not int
                or uid == grant['service_uid'] or uid not in grant['allowed_uids']
                or Path(grant['web_path']).resolve() != Path(web_path).resolve()):
            raise AuthError()
        return f'uid:{uid}:{pwd.getpwuid(uid).pw_name}'
    except (OSError, ValueError, KeyError, TypeError):
        raise AuthError() from None
