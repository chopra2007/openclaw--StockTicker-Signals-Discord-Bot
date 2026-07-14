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

--check flags THREE things, never normal pending work:
  * an ACTIVE item whose switches are ALL in their expected state (looks done but
    isn't closed — the #32/#42 failure),
  * a SOAKING item whose soak window has ended (time's up: close it or re-open it), and
  * any unexpected-ON or MISSING (typo'd) key.

Only ACTIVE items are nagged for the "all live but open" case. Soaking / Parked /
Ongoing items are SUPPOSED to sit with their switches live, so nagging them would
train the reader to ignore the alarm.
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
TODO_PATH = REPO / "TODO.md"
sys.path.insert(0, str(REPO))
from consensus_engine import config  # noqa: E402

HEADER_RE = re.compile(r"^##\s+(\d+)\.\s+(.*?)\s*$")
SWITCHES_RE = re.compile(r"^\*\*Switches:\*\*\s*(.+?)\s*$")

# Status marker at the end of a header (a trailing parenthetical is allowed after it).
# See todo/CONVENTION.md "Status markers".
STATUS_RE = re.compile(
    r"[—-]+\s*(?P<kind>DONE|SOAKING|PARKED|ONGOING|AWAITING APPROVAL)\b"
    r"(?:\s+until\s+(?P<soak>\d{4}-\d{2}-\d{2}))?",
    re.IGNORECASE,
)


def parse_status(title: str, today: date) -> tuple[str, str, date | None]:
    """-> (clean_title, status, soak_until).

    status is one of: active | soaking | soaking_due | parked | ongoing |
    approval | complete
    """
    matches = list(STATUS_RE.finditer(title))
    if not matches:
        return title.strip(), "active", None
    m = matches[-1]  # the LAST marker wins — prose may mention an earlier one
    clean = title[: m.start()].strip().rstrip("—-").strip()
    kind = m.group("kind").upper()
    if kind == "DONE":
        return clean, "complete", None
    if kind == "PARKED":
        return clean, "parked", None
    if kind == "ONGOING":
        return clean, "ongoing", None
    if kind == "AWAITING APPROVAL":
        return clean, "approval", None
    # SOAKING — a soak with no date is not a soak; it is still real work. Keep the
    # malformed marker in the title so the mistake is visible in the rendered list.
    raw = m.group("soak")
    if not raw:
        return title.strip(), "active", None
    soak_until = date.fromisoformat(raw)
    return clean, ("soaking_due" if today > soak_until else "soaking"), soak_until


def parse_items(text: str, today: date) -> list[dict]:
    items: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        m = HEADER_RE.match(line)
        if m:
            clean, status, soak_until = parse_status(m.group(2), today)
            cur = {
                "num": int(m.group(1)),
                "title": clean,
                "status": status,
                "soak_until": soak_until,
                "switches": None,
            }
            items.append(cur)
            continue
        if cur is not None:
            sm = SWITCHES_RE.match(line)
            if sm:
                cur["switches"] = sm.group(1)
    return items


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
    """Resolve switch state for switch-bearing items. Items with no **Switches:**
    line pass through with empty state (they still carry a status, so the soak-window
    check below reaches them)."""
    rows = []
    for it in items:
        if not it["switches"]:
            rows.append({**it, "states": [], "pending": [], "unexpected": [],
                         "missing": [], "stale": False})
            continue
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
        # Only ACTIVE items can be "stale". Soaking/Parked/Ongoing/Awaiting-approval/
        # Complete items are meant to sit as they are — nagging them would be noise.
        stale = (
            it["status"] == "active"
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
    tz_today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
    rows = evaluate(parse_items(TODO_PATH.read_text(), tz_today))

    if check:
        now = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d %H:%M %Z")
        for r in rows:
            if r["stale"]:
                print(f"[{now}] ⚠️ TODO #{r['num']} '{r['title']}' — all governed switches "
                      f"are in their expected live state but the item is still ACTIVE. "
                      f"Verify and mark DONE, or update its CURRENT STATUS line.")
            if r["status"] == "soaking_due":
                print(f"[{now}] ⚠️ TODO #{r['num']} '{r['title']}' — soak window ended "
                      f"{r['soak_until']}. Read the shadow data, then mark DONE or return it "
                      f"to ACTIVE with a reason.")
            if r["unexpected"]:
                print(f"[{now}] ⚠️ TODO #{r['num']} — config keys ON but marked intentionally-off: "
                      f"{', '.join(r['unexpected'])}.")
            if r["missing"]:
                print(f"[{now}] ⚠️ TODO #{r['num']} — **Switches:** names unknown config keys "
                      f"(typo?): {', '.join(r['missing'])}.")
        return 0

    switch_rows = [r for r in rows if r["switches"]]
    if not switch_rows:
        print("No TODO items carry a **Switches:** line yet.")
        return 0
    for r in switch_rows:
        flag = "STALE? (all live but ACTIVE)" if r["stale"] else r["status"].upper()
        print(f"#{r['num']} {r['title']}  [{flag}]")
        for key, exp, state in r["states"]:
            print(f"    {state:<18} {key}  (want={exp})")
        if r["pending"]:
            print(f"    → {len(r['pending'])} still pending: {', '.join(r['pending'])}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
