#!/usr/bin/env python3
"""Run on Windows to complete Gmail OAuth2 flow and produce token.json.

Usage:
    python windows_runtime/setup/bootstrap_gmail.py

Prerequisites:
    pip install google-auth-oauthlib

Steps:
    1. Place credentials.json (downloaded from Google Cloud Console) in the
       same directory as this script (windows_runtime/setup/).
    2. Run this script — your browser will open for Google sign-in.
    3. Sign in as teche2014@gmail.com and grant the requested scopes.
    4. token.json is written to the same directory.
    5. SCP token.json to the VPS (see GMAIL_SETUP.md for the full command).
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).parent
CREDS_FILE = HERE / "credentials.json"
TOKEN_FILE = HERE / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]


def main() -> None:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("ERROR: google-auth-oauthlib not installed.")
        print("Run: pip install google-auth-oauthlib")
        sys.exit(1)

    if not CREDS_FILE.exists():
        print(f"ERROR: credentials.json not found at {CREDS_FILE}")
        print()
        print("Download it from Google Cloud Console:")
        print("  APIs & Services → Credentials → OAuth 2.0 Client ID → Download JSON")
        print(f"  Then rename it to credentials.json and place it in: {HERE}")
        sys.exit(1)

    print(f"Using credentials: {CREDS_FILE}")
    print("Opening browser for Google OAuth2 sign-in...")
    print("Sign in as teche2014@gmail.com when prompted.")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(creds.to_json())
    print(f"token.json written to: {TOKEN_FILE}")
    print()
    print("Next step — SCP to VPS:")
    print(f"  scp \"{TOKEN_FILE}\" root@<your-vps>:/root/.openclaw/gmail/token.json")
    print()
    print("Then verify on VPS:")
    print(
        "  python3 -c \"import json,pathlib; "
        "d=json.loads(pathlib.Path('/root/.openclaw/gmail/token.json').read_text()); "
        "print(d.get('client_id','ok'))\""
    )


if __name__ == "__main__":
    main()
