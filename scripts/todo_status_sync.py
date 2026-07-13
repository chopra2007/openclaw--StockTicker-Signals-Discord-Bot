#!/usr/bin/env python3
"""TODO status-line reconciler — keeps TODO.md's lead status lines honest.

Why this exists (2026-07-12, TODO #72): the same status fact was hand-typed in
four places (TODO.md header marker, TODO.md first body line, detail-file
**Status:** line, detail-file CURRENT STATUS line) and nothing checked they
agreed. Close-time "refresh" edits, written from session memory instead of from
the detail file, produced index lines that were stale (#57/#59/#61) or wrong on
arrival (#20). Same lesson as scripts/todo_switch_state.py: copies drift —
derive, don't hand-copy.

The rule this enforces: the detail file is the ONLY place status prose is
written. TODO.md's lead `**CURRENT STATUS ...**` paragraph is a machine-made
mirror of the detail file's, never hand-edited.

Usage:
  python3 scripts/todo_status_sync.py --check   # drift lines only (for notifications.log)
  python3 scripts/todo_status_sync.py --fix     # mirror detail lead paragraphs into TODO.md
  python3 scripts/todo_status_sync.py           # human report (all items, all findings)

--check flags:
  * header marker vs detail **Status:** kind mismatch (e.g. header DONE, detail OPEN)
  * index lead paragraph out of sync with the detail file's (run --fix)
  * index has a CURRENT STATUS paragraph but the detail file has none
    (status prose living only in the index — migrate it to the detail file)
  * a DONE item whose lead status line predates its DONE date (the #57 shape)
  * a DONE item whose **Status:** line or lead paragraph still contains
    forward-looking work phrases ("Next:", "owed", "stays OPEN", ...) (the #54 shape)
  * a lead status line older than the newest "### Session notes" block below it
    (the #20 shape: status written from memory while fresher notes sit in the
    same file)
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
TODO_PATH = REPO / "TODO.md"
DETAIL_DIR = REPO / "todo"

HEADER_RE = re.compile(r"^##\s+(\d+)\.\s+(.*?)\s*$")
FILE_RE = re.compile(r"^\*\*File:\*\*\s*`([^`]+)`")
SWITCHES_RE = re.compile(r"^\*\*Switches:\*\*")
LEAD_RE = re.compile(r"^\*\*CURRENT STATUS", re.IGNORECASE)
LEAD_DATE_RE = re.compile(r"CURRENT STATUS\s*\((\d{4}-\d{2}-\d{2})", re.IGNORECASE)
DETAIL_STATUS_RE = re.compile(r"^\*\*Status:\*\*\s*(.+?)\s*$")
SESSION_NOTE_RE = re.compile(r"^###\s+Session notes\s+[—-]+\s+(\d{4}-\d{2}-\d{2})")

# Same marker grammar as scripts/todo_switch_state.py.
MARKER_RE = re.compile(
    r"[—-]+\s*(?P<kind>DONE|SOAKING|PARKED|ONGOING)\b"
    r"(?:\s+(?:until\s+)?(?P<mdate>\d{4}-\d{2}-\d{2}))?",
    re.IGNORECASE,
)

# Conservative first-word classifier for free-form detail **Status:** lines.
# Unknown vocabulary -> None (no check) rather than a guessed kind.
STATUS_WORDS = {
    "done": "complete", "resolved": "complete", "shipped": "complete",
    "fixed": "complete", "live": "complete", "complete": "complete",
    "open": "active", "active": "active", "reopened": "active",
    "parked": "parked",
    "ongoing": "ongoing", "living": "ongoing",
    "soaking": "soaking",
}

# Which detail-status kinds are fine under each header kind. A soaking item is
# built and live, so a done-ish detail line is its normal state, not drift.
COMPATIBLE = {
    "complete": {"complete"},
    "active": {"active"},
    "parked": {"parked"},
    "ongoing": {"ongoing"},
    "soaking": {"soaking", "complete"},
}

# Forward-looking phrases that contradict a DONE marker when they appear in the
# status line or lead paragraph (NOT the history prose, which may quote them).
LOOSE_END_RE = re.compile(
    r"\bnext:|not marking done|stays open|still open|(?<!nothing )\bowed\b"
    r"|eyeball it|execute it next",
    re.IGNORECASE,
)


def classify_detail_status(status_line: str) -> str | None:
    words = re.findall(r"[a-z]+", status_line.lower())
    return STATUS_WORDS.get(words[0]) if words else None


def parse_header(title: str) -> tuple[str, str | None]:
    """-> (kind, marker_date). kind: complete|soaking|parked|ongoing|active."""
    matches = list(MARKER_RE.finditer(title))
    if not matches:
        return "active", None
    m = matches[-1]
    kind = m.group("kind").upper()
    mdate = m.group("mdate")
    if kind == "DONE":
        return "complete", mdate
    if kind == "SOAKING":
        # A soak with no date is not a soak (see todo_switch_state.parse_status).
        return ("soaking", mdate) if mdate else ("active", None)
    return kind.lower(), mdate


def paragraph_at(lines: list[str], start: int) -> tuple[int, int]:
    """-> (start, end) line span of the paragraph beginning at `start`
    (end exclusive; paragraph runs to the first blank line)."""
    end = start
    while end < len(lines) and lines[end].strip():
        end += 1
    return start, end


def parse_todo(text: str) -> list[dict]:
    lines = text.splitlines()
    items: list[dict] = []
    for i, line in enumerate(lines):
        m = HEADER_RE.match(line)
        if m:
            items.append({"num": int(m.group(1)), "header_line": i,
                          "title": m.group(2), "file": None,
                          "switches_line": None, "lead_span": None, "end": len(lines)})
    for idx, it in enumerate(items):
        it["end"] = items[idx + 1]["header_line"] if idx + 1 < len(items) else len(lines)
        it["kind"], it["marker_date"] = parse_header(it["title"])
        for i in range(it["header_line"] + 1, it["end"]):
            if it["file"] is None:
                fm = FILE_RE.match(lines[i])
                if fm:
                    it["file"] = fm.group(1)
            if SWITCHES_RE.match(lines[i]) and it["switches_line"] is None:
                it["switches_line"] = i
            if LEAD_RE.match(lines[i]) and it["lead_span"] is None:
                it["lead_span"] = paragraph_at(lines, i)
    return items


def parse_detail(path: Path) -> dict:
    out = {"status": None, "lead": None, "lead_date": None, "latest_note": None}
    if not path.exists():
        return out
    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        if out["status"] is None:
            sm = DETAIL_STATUS_RE.match(line)
            if sm:
                out["status"] = sm.group(1)
        if out["lead"] is None and LEAD_RE.match(line):
            s, e = paragraph_at(lines, i)
            out["lead"] = "\n".join(lines[s:e])
        nm = SESSION_NOTE_RE.match(line)
        if nm:
            d = date.fromisoformat(nm.group(1))
            if out["latest_note"] is None or d > out["latest_note"]:
                out["latest_note"] = d
    if out["lead"]:
        dm = LEAD_DATE_RE.search(out["lead"])
        if dm:
            out["lead_date"] = date.fromisoformat(dm.group(1))
    return out


def find_drift(text: str) -> list[tuple[int, str]]:
    """-> [(item_num, drift message)] — everything --check would report."""
    lines = text.splitlines()
    drift: list[tuple[int, str]] = []
    for it in parse_todo(text):
        if not it["file"]:
            continue
        det = parse_detail(DETAIL_DIR / it["file"])
        index_lead = ("\n".join(lines[it["lead_span"][0]:it["lead_span"][1]])
                      if it["lead_span"] else None)

        if det["status"]:
            dkind = classify_detail_status(det["status"])
            if dkind and dkind not in COMPATIBLE[it["kind"]]:
                drift.append((it["num"],
                              f"header says {it['kind'].upper()} but the detail file's "
                              f"**Status:** line reads {dkind.upper()}-ish "
                              f"('{det['status'][:60]}...'). Align them."))

        # A DONE item needs no lead paragraph in the index — only flag a stale
        # existing one, never demand an insertion (keeps the index lean).
        if det["lead"] and index_lead != det["lead"] and (
                index_lead or it["kind"] != "complete"):
            drift.append((it["num"],
                          "index lead paragraph is out of sync with the detail file's "
                          "CURRENT STATUS. Run scripts/todo_status_sync.py --fix."))
        if index_lead and not det["lead"]:
            drift.append((it["num"],
                          "index has a CURRENT STATUS paragraph but the detail file has "
                          "none — status prose must live in the detail file; migrate it."))

        lead_date = det["lead_date"]
        if lead_date is None and index_lead:
            dm = LEAD_DATE_RE.search(index_lead)
            if dm:
                lead_date = date.fromisoformat(dm.group(1))

        if (it["kind"] == "complete" and it["marker_date"] and lead_date
                and lead_date < date.fromisoformat(it["marker_date"])):
            drift.append((it["num"],
                          f"marked DONE {it['marker_date']} but the lead status line is "
                          f"dated {lead_date} — it describes the state BEFORE the item "
                          f"was finished. Rewrite it in the detail file, then --fix."))

        if it["kind"] == "complete":
            for label, blob in (("**Status:** line", det["status"]),
                                ("lead CURRENT STATUS paragraph", det["lead"] or index_lead)):
                hit = LOOSE_END_RE.search(blob or "")
                if hit:
                    drift.append((it["num"],
                                  f"marked DONE but its {label} still contains "
                                  f"forward-looking work ('{hit.group(0)}'). Either the "
                                  f"work happened (record the dated outcome) or the item "
                                  f"isn't done."))

        if det["lead_date"] and det["latest_note"] and det["lead_date"] < det["latest_note"]:
            drift.append((it["num"],
                          f"detail file's CURRENT STATUS is dated {det['lead_date']} but "
                          f"newer session notes ({det['latest_note']}) sit below it — the "
                          f"status line was not refreshed after the latest work."))
    return drift


def apply_fix(text: str) -> tuple[str, list[int]]:
    """Mirror each detail file's lead CURRENT STATUS paragraph into TODO.md.
    Touches ONLY the lead paragraph (replace, or insert after **Switches:** /
    **File:**). -> (new_text, [changed item nums])."""
    lines = text.splitlines()
    changed: list[int] = []
    # Bottom-up so line spans stay valid while splicing.
    for it in reversed(parse_todo(text)):
        if not it["file"]:
            continue
        det = parse_detail(DETAIL_DIR / it["file"])
        if not det["lead"]:
            continue
        new_para = det["lead"].splitlines()
        if it["lead_span"]:
            s, e = it["lead_span"]
            if lines[s:e] == new_para:
                continue
            lines[s:e] = new_para
        elif it["kind"] == "complete":
            continue  # DONE items get no new index lead — see find_drift
        else:
            anchor = it["switches_line"]
            if anchor is None:
                anchor = next((i for i in range(it["header_line"] + 1, it["end"])
                               if FILE_RE.match(lines[i])), None)
            if anchor is None:
                continue
            lines[anchor + 1:anchor + 1] = [""] + new_para
        changed.append(it["num"])
    return "\n".join(lines) + ("\n" if text.endswith("\n") else ""), sorted(changed)


def main() -> int:
    args = sys.argv[1:]
    if not TODO_PATH.exists():
        print(f"TODO.md not found at {TODO_PATH}", file=sys.stderr)
        return 1
    text = TODO_PATH.read_text()

    if "--fix" in args:
        new_text, changed = apply_fix(text)
        if changed:
            TODO_PATH.write_text(new_text)
            print(f"synced lead status paragraphs for: {', '.join('#' + str(n) for n in changed)}")
        else:
            print("already in sync — nothing to change")
        return 0

    drift = find_drift(text)
    if "--check" in args:
        now = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d %H:%M %Z")
        for num, msg in drift:
            print(f"[{now}] ⚠️ TODO #{num} — {msg}")
        return 0

    if not drift:
        print("all status lines consistent ✅")
    for num, msg in drift:
        print(f"#{num}: {msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
