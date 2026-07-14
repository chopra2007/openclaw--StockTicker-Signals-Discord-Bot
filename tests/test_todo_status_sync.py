"""TODO #72 — status-line reconciler (scripts/todo_status_sync.py).

Each test builds a tiny synthetic TODO.md + detail file and checks one drift
rule or one --fix behavior. DETAIL_DIR is monkeypatched to tmp_path.
"""
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "todo_status_sync", REPO / "scripts" / "todo_status_sync.py")
tds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tds)


def make_detail(tmp_path, name, status, lead=None, notes=()):
    parts = [f"# {name}", "", f"**Status:** {status}", "**Created:** 2026-07-01", ""]
    if lead:
        parts += [lead, ""]
    parts += ["Body prose.", ""]
    for d in notes:
        parts += [f"### Session notes — {d}", "- **Worked on:** x", ""]
    (tmp_path / name).write_text("\n".join(parts))


def todo_entry(num, title, file, lead=None, switches=None):
    parts = [f"## {num}. {title}", "", f"**File:** `{file}`", ""]
    if switches:
        parts += [f"**Switches:** {switches}", ""]
    if lead:
        parts += [lead, ""]
    parts += ["One-sentence goal summary.", ""]
    return "\n".join(parts)


@pytest.fixture
def detail_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tds, "DETAIL_DIR", tmp_path)
    return tmp_path


# ---------- parsing ----------

def test_parse_header_kinds():
    assert tds.parse_header("Fix thing") == ("active", None)
    assert tds.parse_header("Fix thing — DONE 2026-07-09 (verified)") == ("complete", "2026-07-09")
    assert tds.parse_header("Soak — SOAKING until 2026-07-15") == ("soaking", "2026-07-15")
    # a soak with no date is still real work
    assert tds.parse_header("Soak — SOAKING until whenever") == ("active", None)
    assert tds.parse_header("Blocked — PARKED: needs money") == ("parked", None)
    assert tds.parse_header("Menu — ONGOING") == ("ongoing", None)
    assert tds.parse_header(
        "Built — AWAITING APPROVAL: 8 switches need a yes/no") == ("approval", None)


def test_classify_detail_status_conservative():
    assert tds.classify_detail_status("OPEN") == "active"
    assert tds.classify_detail_status("✅ FIXED 2026-06-06 — commit x") == "complete"
    assert tds.classify_detail_status("SHIPPED — v1.1.0 LIVE") == "complete"
    assert tds.classify_detail_status("LIVING RECORD — v1.3.0") == "ongoing"
    assert tds.classify_detail_status("REOPENED 2026-06-06 — was DONE") == "active"
    assert tds.classify_detail_status("AWAITING APPROVAL — 8 switches") == "approval"
    # unknown vocabulary must NOT guess
    assert tds.classify_detail_status("MOSTLY RESOLVED (2026-06-06)") is None
    assert tds.classify_detail_status("E2 shadow mode is ON") is None


# ---------- drift rules ----------

def test_header_done_but_detail_open_flags(detail_dir):
    make_detail(detail_dir, "a.md", "OPEN")
    text = todo_entry(1, "Thing — DONE 2026-07-09", "a.md")
    msgs = [m for _, m in tds.find_drift(text)]
    assert any("header says COMPLETE" in m and "ACTIVE" in m for m in msgs)


def test_soaking_header_accepts_doneish_detail(detail_dir):
    make_detail(detail_dir, "a.md", "DONE 2026-07-08 (built, live behind flags)")
    text = todo_entry(1, "Thing — SOAKING until 2026-07-15", "a.md")
    assert not any("header says" in m for _, m in tds.find_drift(text))


def test_out_of_sync_lead_flags_and_fix_repairs(detail_dir):
    fresh = "**CURRENT STATUS (2026-07-11):** all done, thresholds tuned."
    make_detail(detail_dir, "a.md", "DONE 2026-07-11", lead=fresh)
    text = todo_entry(1, "Thing — DONE 2026-07-11", "a.md",
                      lead="**CURRENT STATUS (2026-07-08):** still owed: tune thresholds.")
    assert any("out of sync" in m for _, m in tds.find_drift(text))

    fixed, changed = tds.apply_fix(text)
    assert changed == [1]
    assert fresh in fixed
    assert "2026-07-08" not in fixed
    assert not any("out of sync" in m for _, m in tds.find_drift(fixed))
    # idempotent
    fixed2, changed2 = tds.apply_fix(fixed)
    assert changed2 == [] and fixed2 == fixed


def test_fix_inserts_lead_when_index_has_none(detail_dir):
    lead = "**CURRENT STATUS (2026-07-12):** built, soaking."
    make_detail(detail_dir, "a.md", "OPEN", lead=lead)
    text = todo_entry(1, "Thing", "a.md", switches="features.x.enabled=on")
    fixed, changed = tds.apply_fix(text)
    assert changed == [1]
    # inserted right under the Switches line, before the summary sentence
    assert fixed.index("**Switches:**") < fixed.index(lead) < fixed.index("One-sentence goal")


def test_index_only_lead_flags_migration(detail_dir):
    make_detail(detail_dir, "a.md", "OPEN")
    text = todo_entry(1, "Thing", "a.md",
                      lead="**CURRENT STATUS (2026-07-10):** index-only prose.")
    assert any("detail file has none" in m for _, m in tds.find_drift(text))


def test_lead_predating_done_date_flags(detail_dir):
    make_detail(detail_dir, "a.md", "DONE 2026-07-09",
                lead="**CURRENT STATUS (2026-07-08):** two things keep this open.")
    text = todo_entry(1, "Thing — DONE 2026-07-09", "a.md")
    assert any("describes the state BEFORE" in m for _, m in tds.find_drift(text))


def test_loose_end_phrase_in_done_item_flags(detail_dir):
    make_detail(detail_dir, "a.md",
                "DONE 2026-07-04 — all switches ON. Live watch owed: eyeball it next trading day.")
    text = todo_entry(1, "Thing — DONE 2026-07-04", "a.md")
    assert any("forward-looking work" in m for _, m in tds.find_drift(text))


def test_stale_lead_vs_newer_session_notes_flags(detail_dir):
    make_detail(detail_dir, "a.md", "OPEN",
                lead="**CURRENT STATUS (2026-07-10):** waiting on the race.",
                notes=["2026-07-11", "2026-07-12"])
    text = todo_entry(1, "Thing", "a.md")
    msgs = [m for _, m in tds.find_drift(text)]
    assert any("newer session notes (2026-07-12)" in m for m in msgs)


def test_loose_end_regex_word_boundaries(detail_dir):
    # 'showed' must not match 'owed'; 'Nothing owed' is a closure, not a loose end
    make_detail(detail_dir, "a.md",
                "DONE 2026-07-05 — the card showed a process condition. Nothing owed.")
    text = todo_entry(1, "Thing — DONE 2026-07-05", "a.md")
    assert not any("forward-looking" in m for _, m in tds.find_drift(text))


def test_done_item_without_index_lead_not_flagged_or_inserted(detail_dir):
    make_detail(detail_dir, "a.md", "DONE 2026-07-05",
                lead="**CURRENT STATUS (2026-07-05) — DONE.** Shipped and verified.")
    text = todo_entry(1, "Thing — DONE 2026-07-05", "a.md")
    assert not any("out of sync" in m for _, m in tds.find_drift(text))
    fixed, changed = tds.apply_fix(text)
    assert changed == [] and fixed == text


def test_clean_item_stays_silent(detail_dir):
    lead = "**CURRENT STATUS (2026-07-12):** all phases live."
    make_detail(detail_dir, "a.md", "OPEN", lead=lead, notes=["2026-07-12"])
    text = todo_entry(1, "Thing", "a.md", lead=lead)
    assert tds.find_drift(text) == []
