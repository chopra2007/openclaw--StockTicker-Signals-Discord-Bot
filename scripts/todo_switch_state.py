#!/usr/bin/env python3
"""TODO switch-state reconciler — keeps the TODO list honest about live switches.

Why this exists (2026-06-28, TODO #32/#42 follow-up): a TODO item that says
"switch these on" is a HAND-TYPED copy of a fact that already lives in
config/consensus.yaml (what the engine actually runs). Copies drift. On
2026-06-27 every signal switch was already live, but #32 still read "to flip",
costing a whole session to re-derive. This reader removes the copy: it resolves
each item's switches straight from config.get() — the same call the engine uses
— so the list can never silently disagree with reality.

Annotation: add ONE line to a switch-bearing TODO item's body (under `**File:**`):

  **Switches:** features.cross_asset.enabled=on; features.consensus_logodds.enabled=noop

  key=expected, ';'-separated. expected is one of:
    on        -> SHOULD be ON in a healthy live state; OFF => still pending (real work left)
    noop/off  -> intentionally OFF (proven no-op / by design); ON => unexpected drift

Usage:
  python3 scripts/todo_switch_state.py            # full per-item report (human)
  python3 scripts/todo_switch_state.py --check    # only drift lines (for notifications.log)

--check flags TWO things, never normal pending work:
  * an OPEN item whose switches are ALL in their expected state (looks done but
    isn't closed — the #32/#42 failure), and
  * any unexpected-ON or MISSING (typo'd) key.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
TODO_PATH = REPO / "TODO.md"
sys.path.insert(0, str(REPO))
from consensus_engine import config  # noqa: E402

HEADER_RE = re.compile(r"^##\s+(\d+)\.\s+(.*?)\s*$")
SWITCHES_RE = re.compile(r"^\*\*Switches:\*\*\s*(.+?)\s*$")


def parse_items(text: str) -> list[dict]:
    items: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        m = HEADER_RE.match(line)
        if m:
            title = m.group(2)
            cur = {
                "num": int(m.group(1)),
                "title": re.sub(r"\s*[—-]+\s*DONE.*$", "", title).strip(),
                "done": "DONE" in title.upper(),
                "switches": None,
            }
            items.append(cur)
            continue
        if cur is not None:
            sm = SWITCHES_RE.match(line)
            if sm:
                cur["switches"] = sm.group(1)
    return [it for it in items if it["switches"]]


def parse_switches(spec: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for part in spec.split(";"):
        part = part.strip()
        if not part:
            continue
        key, _, exp = part.partition("=")
        out.append((key.strip(), (exp.strip().lower() or "on")))
    return out


def evaluate(items: list[dict]) -> list[dict]:
    rows = []
    for it in items:
        states, pending, unexpected, missing = [], [], [], []
        has_on = False
        for key, exp in parse_switches(it["switches"]):
            actual = config.get(key, None)
            if actual is None:
                missing.append(key)
                states.append((key, exp, "MISSING-KEY"))
                continue
            on = bool(actual)
            if exp == "on":
                has_on = True
                if on:
                    states.append((key, exp, "live ✅"))
                else:
                    pending.append(key)
                    states.append((key, exp, "PENDING ⏳"))
            else:  # noop / off
                if on:
                    unexpected.append(key)
                    states.append((key, exp, "UNEXPECTED-ON ⚠️"))
                else:
                    states.append((key, exp, "off ➖"))
        stale = (
            not it["done"]
            and has_on
            and not pending
            and not unexpected
            and not missing
        )
        rows.append({**it, "states": states, "pending": pending,
                     "unexpected": unexpected, "missing": missing, "stale": stale})
    return rows


def main() -> int:
    check = "--check" in sys.argv[1:]
    if not TODO_PATH.exists():
        print(f"TODO.md not found at {TODO_PATH}", file=sys.stderr)
        return 1
    rows = evaluate(parse_items(TODO_PATH.read_text()))

    if check:
        now = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d %H:%M %Z")
        for r in rows:
            if r["stale"]:
                print(f"[{now}] ⚠️ TODO #{r['num']} '{r['title']}' — all governed switches "
                      f"are in their expected live state but the item is still OPEN. "
                      f"Verify and mark DONE, or update its CURRENT STATUS line.")
            if r["unexpected"]:
                print(f"[{now}] ⚠️ TODO #{r['num']} — config keys ON but marked intentionally-off: "
                      f"{', '.join(r['unexpected'])}.")
            if r["missing"]:
                print(f"[{now}] ⚠️ TODO #{r['num']} — **Switches:** names unknown config keys "
                      f"(typo?): {', '.join(r['missing'])}.")
        return 0

    if not rows:
        print("No TODO items carry a **Switches:** line yet.")
        return 0
    for r in rows:
        flag = "DONE" if r["done"] else ("STALE? (all live but OPEN)" if r["stale"] else "OPEN")
        print(f"#{r['num']} {r['title']}  [{flag}]")
        for key, exp, state in r["states"]:
            print(f"    {state:<18} {key}  (want={exp})")
        if r["pending"]:
            print(f"    → {len(r['pending'])} still pending: {', '.join(r['pending'])}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
