#!/usr/bin/env python3
"""TODO #88 check 2 — "when does this code actually run, and is the market open then?"

#87's SPY expected-move charts worked at every hour except the one that mattered:
the morning brief goes out at 5:51 AM PDT and the options market does not open
until 6:30 AM, so the charts were empty on every real brief.

Given changed files (default: whatever is uncommitted right now), this prints every
scheduled task that ends up running that code, its run time in PDT, and which part
of the trading day that lands in.

  python3 scripts/when_does_it_run.py
  python3 scripts/when_does_it_run.py consensus_engine/briefing/alfred.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
import sys

REPO = "/home/openclaw/.openclaw/workspace"
CRON_FILES = ["/etc/cron.d"]
CRON_USERS = ["root", "openclaw"]

# US market hours in the user's timezone. Options and equities open together.
MARKET_OPEN = dt.time(6, 30)
MARKET_CLOSE = dt.time(13, 0)
PREMARKET_OPEN = dt.time(1, 0)
AFTERHOURS_CLOSE = dt.time(17, 0)

# Config keys that name a clock time, and the plain-English note for each.
CONFIG_TIME_RE = re.compile(r"^\s*([a-z0-9_]*(?:time|window)[a-z0-9_]*)\s*:\s*(.+?)\s*(?:#.*)?$")
CLOCK_RE = re.compile(r"\b([0-2]?\d:[0-5]\d)\b")


def sh(args) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return ""


def market_session(when: dt.time) -> str:
    """Plain-English name for what the market is doing at this PDT time."""
    if when < PREMARKET_OPEN:
        return "market CLOSED (overnight)"
    if when < MARKET_OPEN:
        mins = (MARKET_OPEN.hour * 60 + MARKET_OPEN.minute) - (when.hour * 60 + when.minute)
        return ("BEFORE THE OPEN — %dh%02dm before options and shares start trading at 6:30 AM PDT"
                % (mins // 60, mins % 60))
    if when < MARKET_CLOSE:
        return "regular trading hours (6:30 AM - 1:00 PM PDT)"
    if when < AFTERHOURS_CLOSE:
        return "after-hours (market closed at 1:00 PM PDT)"
    return "market CLOSED (evening)"


def changed_files(explicit: list[str]) -> list[str]:
    if explicit:
        return explicit
    # Uncommitted work first, new files included; nothing uncommitted -> the last commit.
    out = sh(["git", "-C", REPO, "status", "--porcelain"])
    files = [l[3:].strip().strip('"') for l in out.splitlines() if l.strip()]
    if not files:
        print("(nothing uncommitted — checking the last commit instead)\n")
        out = sh(["git", "-C", REPO, "show", "--name-only", "--pretty=", "HEAD"])
        files = [l.strip() for l in out.splitlines() if l.strip()]
    return files


def systemd_schedules() -> list[tuple[str, str, str]]:
    """(timer name, next run in PDT, command it runs)."""
    out = sh(["systemctl", "list-timers", "--all", "--no-pager", "--no-legend"])
    rows = []
    for line in out.splitlines():
        m = re.search(r"(\S+\.timer)\s+(\S+\.service)\s*$", line)
        if not m:
            continue
        timer, service = m.group(1), m.group(2)
        show = sh(["systemctl", "show", timer, "-p", "TimersCalendar", "--no-pager"])
        nxt = re.search(r"next_elapse=([^;}]+)", show)
        when = nxt.group(1).strip() if nxt else "unknown"
        execs = sh(["systemctl", "show", service, "-p", "ExecStart", "--no-pager"])
        cmds = " ".join(re.findall(r"argv\[\]=([^;]+);", execs))
        rows.append((timer, when, cmds.strip()))
    return rows


def cron_schedules() -> list[tuple[str, str, str]]:
    """(where it is written, schedule fields, command). Cron runs in system time = PDT."""
    rows = []
    texts = []
    for user in CRON_USERS:
        texts.append(("crontab of %s" % user, sh(["crontab", "-l", "-u", user])))
    for folder in CRON_FILES:
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            path = os.path.join(folder, name)
            try:
                texts.append((path, open(path).read()))
            except OSError:
                continue
    for where, text in texts:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split(None, 5)
            if len(fields) < 6 or not re.match(r"^[\d*/,\-]+$", fields[0]):
                continue
            rows.append((where, " ".join(fields[:5]), fields[5]))
    return rows


def cron_time(spec: str) -> str | None:
    """'51 5 * * *' -> '05:51'. None when it is not a single fixed time."""
    minute, hour = spec.split()[0], spec.split()[1]
    if not minute.isdigit() or not hour.isdigit():
        return None
    return "%02d:%02d" % (int(hour), int(minute))


def config_windows() -> list[tuple[str, str, str]]:
    """(config key, the times it names, the section it sits under) from consensus.yaml."""
    path = os.path.join(REPO, "config", "consensus.yaml")
    rows = []
    section = ""
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return rows
    for line in lines:
        if re.match(r"^[a-z0-9_]+:", line):
            section = line.split(":")[0]
        m = CONFIG_TIME_RE.match(line)
        if not m:
            continue
        times = CLOCK_RE.findall(m.group(2))
        if times:
            rows.append((m.group(1), ", ".join(times), section))
    return rows


def mentions(path: str, needle: str) -> bool:
    """Does this file's text mention `needle`? Used for one hop of indirection:
    a timer runs a shell script, and the shell script runs the python file."""
    try:
        with open(path, errors="ignore") as f:
            return needle in f.read()
    except OSError:
        return False


def paths_in(command: str) -> list[str]:
    return [tok for tok in command.split() if tok.startswith("/") and os.path.isfile(tok)]


def reaches(command: str, target_base: str, target_rel: str) -> bool:
    """Does this command end up executing the changed file?"""
    if target_base in command or target_rel in command:
        return True
    for script in paths_in(command):
        if mentions(script, target_base):
            return True
    return False


def importers(target: str) -> list[str]:
    """Repo files that mention this module by name — the code that calls it.

    This is the hop that matters: #87 changed expected_move.py, which no timer
    names, but the morning brief imports it and the brief runs at 5:51 AM.
    """
    name = os.path.basename(target)
    if not name.endswith(".py"):
        return []
    module = name[:-3]
    # Only real import lines count. Matching any mention drags in every file that
    # merely names the module in a comment, and buries the answer in noise.
    out = sh(["git", "-C", REPO, "grep", "-l", "-E", "-e",
              r"^\s*(from|import)\s+\S*\b%s\b" % module, "--",
              "consensus_engine", "scripts"])
    return [f.strip() for f in out.splitlines()
            if f.strip() and f.strip() != target and f.strip().endswith(".py")]


def report(target: str, via: str = "") -> bool:
    """Print every schedule that reaches `target`. Returns True if any was found."""
    base = os.path.basename(target)
    rel = target
    found = False
    prefix = ("  (through %s) " % via) if via else "  "

    for timer, when, command in systemd_schedules():
        if not reaches(command, base, rel):
            continue
        found = True
        clock = re.search(r"\b(\d{2}):(\d{2}):\d{2}\b", when)
        session = market_session(dt.time(int(clock.group(1)), int(clock.group(2)))) if clock else "unknown time"
        print(prefix + "runs from the timer %s — next %s" % (timer, when))
        print("      -> %s" % session)

    for where, spec, command in cron_schedules():
        if not reaches(command, base, rel):
            continue
        found = True
        clock = cron_time(spec)
        session = market_session(dt.time(*map(int, clock.split(":")))) if clock else "repeats (%s)" % spec
        print(prefix + "runs from a scheduled task in %s — '%s' (PDT)" % (where, spec))
        print("      -> %s" % session)

    # The engine itself never stops; the times that matter are the posting windows
    # it reads out of consensus.yaml.
    for key, times, section in config_windows():
        if not (section and section in target.replace("/", " ").replace("_", " ")) and section not in target:
            continue
        found = True
        for clock in times.split(", "):
            hour, minute = clock.split(":")
            print(prefix + "the always-on engine posts this at %s PDT (config %s.%s)" % (clock, section, key))
            print("      -> %s" % market_session(dt.time(int(hour), int(minute))))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="files to check (default: your uncommitted changes)")
    args = parser.parse_args()

    files = changed_files(args.files)
    if not files:
        print("Nothing changed, so there is nothing to check.")
        return 0

    for path in files:
        print("%s:" % path)
        found = report(path)
        for caller in importers(path):
            found |= report(caller, via=caller)
        if not found:
            print("  no scheduled task runs this — it only runs when something calls it")
        print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
