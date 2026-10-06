"""Protected local administrator bootstrap/recovery, without browser authority."""
import argparse
import getpass
from pathlib import Path
import sys
import time
from .auth import AuthError, AuthService, normalize_username
from .local_authority import GRANT_PATH, verify_local_operator
from .store import WebStore


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local dashboard administrator management')
    parser.add_argument('command',choices=['create-admin','recover-admin'])
    parser.add_argument('--username',required=True)
    args = parser.parse_args(argv)
    try:
        # Only the protected host file chooses the database, never a flag or env.
        import json
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            raise AuthError()
        # Verify before reading a path used for any write or migration.
        # This first read is inert; the authority reopens/verifies the same file.
        grant = json.loads(GRANT_PATH.read_text(encoding='utf-8'))
        web_path = Path(grant['web_path'])
        operator = verify_local_operator(web_path)
        username = normalize_username(args.username)
        store = WebStore(web_path)
        # CLI never initializes a supplied/arbitrary database or creates directories.
        if not web_path.is_file():
            raise AuthError()
        service = AuthService(store)
        with store.transaction() as con:
            target = con.execute('SELECT id,role FROM members WHERE username=?',(username,)).fetchone()
            if args.command == 'recover-admin' and (not target or target[1] != 'admin'):
                raise AuthError()
            if args.command == 'create-admin' and con.execute("SELECT 1 FROM members WHERE role='admin'").fetchone():
                raise AuthError()
        first = getpass.getpass('New password: ')
        second = getpass.getpass('Repeat new password: ')
        if first != second:
            raise AuthError()
        if args.command == 'create-admin':
            service.create_admin(username,first,time.time())
        else:
            service.recover_admin(target[0],first,operator,time.time())
        print('Administrator credentials updated.')
        return 0
    except (AuthError,OSError,ValueError,KeyError):
        print('Local management unavailable.',file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
