#!/usr/bin/env python3
"""TODO #88 check 3 — find files the bot can no longer write because a root
session took them over.

The bot runs as user `openclaw`. Anything root creates or rewrites in its tree
becomes root-owned, and the bot then fails silently: that is how the Schwab
login token died for 2.1 days (2026-08-17 -> 2026-08-19) and how 668 repo files
had to be handed back in one session.

  python3 scripts/check_ownership.py          # report, exit 1 if anything is wrong
  python3 scripts/check_ownership.py --fix    # hand them back (needs root)
  python3 scripts/check_ownership.py --quiet  # only print the bad lines

Nothing is followed through a symlink; /root/.openclaw is a symlink into
/home/openclaw/.openclaw and would otherwise be scanned twice.
"""

from __future__ import annotations

import argparse
import os
import pwd
import stat
import sys

BOT_USER = "openclaw"

# Everything under here belongs to the bot.
SCAN_ROOTS = ["/home/openclaw/.openclaw"]

# Files outside the bot's tree that the bot still has to write.
EXTRA_PATHS = ["/root/task_system/notifications.log"]

# Directories that are noise: caches, third-party installs, build junk.
SKIP_DIRS = {
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "site-packages",
}

# Single files that are rewritten as root by tooling outside the bot and hold no
# bot data. TODO #90: the OMC `persistent-mode` Stop hook rewrites the cooldown
# clock below at the end of every turn, so the guard fired every turn for a
# throwaway timestamp. Only ever ignore an exact path here — never a directory
# under .omc/state, which holds real bot data (calibration_model.pkl,
# news_cascade_brave_counter.json, searxng_health.json).
SKIP_PATHS = {
    "/home/openclaw/.openclaw/workspace/.omc/state/idle-notif-cooldown.json",
}

# The ones that have actually broken something. Reported first, in plain words.
KNOWN_VICTIMS = {
    "/home/openclaw/.openclaw/schwab_token.json": "the Schwab login token — the live options feed dies without it",
    "/home/openclaw/.openclaw/.env": "the API key file",
    "/home/openclaw/.openclaw/.env.service": "the API key file the engine service reads (it won't start without it)",
    "/home/openclaw/.openclaw/openclaw.json": "the gateway config",
    "/home/openclaw/.openclaw/state": "the gateway state folder",
    "/home/openclaw/.openclaw/workspace/.git": "the repo's git data — pushes fail",
    "/root/task_system/notifications.log": "the alert log the session-start digest reads",
}


# How many bad files to name one by one before switching to per-folder counts.
MAX_LISTED = 15


def folder_counts(items: list[tuple[str, str]]) -> list[tuple[str, int]]:
    """Group bad paths by their folder, biggest first."""
    counts: dict[str, int] = {}
    for path, _owner in items:
        counts[os.path.dirname(path)] = counts.get(os.path.dirname(path), 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def bot_ids() -> tuple[int, int]:
    entry = pwd.getpwnam(BOT_USER)
    return entry.pw_uid, entry.pw_gid


def writable_by_bot(st: os.stat_result, uid: int, gid: int) -> bool:
    """Can user `openclaw` write this, by owner/group/other bits?"""
    mode = st.st_mode
    if st.st_uid == uid:
        # The bot owns it, so it can always give itself write access again.
        # Deliberately read-only files (git pack files, for one) are not a problem.
        return True
    if st.st_gid == gid:
        return bool(mode & stat.S_IWGRP)
    return bool(mode & stat.S_IWOTH)


def walk(root: str):
    """Yield every path under root, skipping cache dirs and never following links."""
    if os.path.islink(root) or not os.path.exists(root):
        return
    yield root
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in dirnames + filenames:
            yield os.path.join(dirpath, name)


def scan() -> list[tuple[str, str]]:
    """Return (path, owner-name) for everything the bot cannot write."""
    uid, gid = bot_ids()
    bad: list[tuple[str, str]] = []
    seen: set[str] = set()

    paths = []
    for root in SCAN_ROOTS:
        paths.extend(walk(root))
    paths.extend(EXTRA_PATHS)

    for path in paths:
        if path in seen or path in SKIP_PATHS:
            continue
        seen.add(path)
        try:
            st = os.lstat(path)
        except OSError:
            continue
        if stat.S_ISLNK(st.st_mode):
            continue
        if writable_by_bot(st, uid, gid):
            continue
        try:
            owner = pwd.getpwuid(st.st_uid).pw_name
        except KeyError:
            owner = str(st.st_uid)
        bad.append((path, owner))
    return bad


def fix(paths: list[str]) -> list[tuple[str, str]]:
    """chown back to the bot. Returns (path, error) for the ones that failed."""
    uid, gid = bot_ids()
    failures = []
    for path in paths:
        try:
            os.lchown(path, uid, gid)
        except OSError as exc:
            failures.append((path, str(exc)))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="hand the files back to the bot (needs root)")
    parser.add_argument("--quiet", action="store_true", help="print only the problems")
    args = parser.parse_args()

    bad = scan()
    if not bad:
        if not args.quiet:
            print("Ownership sweep: clean — the bot can write everything it owns.")
        return 0

    known = [(p, o) for p, o in bad if p in KNOWN_VICTIMS]
    other = [(p, o) for p, o in bad if p not in KNOWN_VICTIMS]

    for path, owner in known:
        print(f"BROKEN: {path} is owned by {owner}, so the bot cannot write it — {KNOWN_VICTIMS[path]}")

    # A root session can leave hundreds of files behind. Listing every one drowns
    # the notification log, so list a handful and then count by folder.
    for path, owner in other[:MAX_LISTED]:
        print(f"BROKEN: {path} is owned by {owner}, so the bot cannot write it")
    if len(other) > MAX_LISTED:
        print(f"...and {len(other) - MAX_LISTED} more, by folder:")
        folders = folder_counts(other[MAX_LISTED:])
        for folder, count in folders[:10]:
            print(f"  {count} file(s) under {folder}")
        if len(folders) > 10:
            print(f"  ...and {len(folders) - 10} more folders")

    print(f"{len(bad)} file(s) the bot cannot write. Run: sudo python3 scripts/check_ownership.py --fix")

    if args.fix:
        failures = fix([p for p, _ in bad])
        fixed = len(bad) - len(failures)
        print(f"Handed {fixed} file(s) back to {BOT_USER}.")
        for path, err in failures:
            print(f"COULD NOT FIX: {path} — {err}")
        return 1 if failures else 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
