"""Tests for scripts/backfill_wolf.py — the one-shot Wolf Gmail backfill.

Gmail is fully mocked (a fake service returning canned message lists + metadata);
the parser/decoder are mocked too so these tests exercise ONLY the backfill
orchestration: pagination, ascending (internalDate, msg_id) sort, the unseen-skip
resume path, received_at recording, idempotence, the failure-injection atomicity
guarantee (Codex BLOCKER-3), the empty-state precondition (Codex MAJOR-4),
--rebuild, and dry-run-writes-nothing.
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consensus_engine import db
from consensus_engine.scanners import gmail_watcher
from consensus_engine.analysis import wolf_email_parser
import scripts.backfill_wolf as backfill_wolf


# ---------------------------------------------------------------- fake Gmail
class _Exec:
    def __init__(self, result):
        self._r = result

    def execute(self):
        return self._r


class _FakeMessages:
    """Paginates `records` (list of (internalDate_ms:int, msg_id:str)) across pages
    of `page_size`, and serves get() from a built id->message map."""

    def __init__(self, records, page_size, sender):
        self._records = records
        self._page_size = page_size
        self._sender = sender
        # id -> full message
        self._by_id = {}
        for ims, mid in records:
            self._by_id[mid] = {
                "id": mid,
                "internalDate": str(ims),
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": f"Wolf {mid}"},
                        {"name": "From", "value": sender},
                    ],
                    "mimeType": "text/html",
                    "body": {},
                },
            }
        # build pages of ids
        ids = [mid for _, mid in records]
        self._pages = [ids[i:i + page_size] for i in range(0, len(ids), page_size)] or [[]]

    def list(self, userId, q, maxResults=500, pageToken=None):
        idx = int(pageToken) if pageToken else 0
        page_ids = self._pages[idx] if idx < len(self._pages) else []
        result = {"messages": [{"id": i} for i in page_ids]}
        if idx + 1 < len(self._pages):
            result["nextPageToken"] = str(idx + 1)
        return _Exec(result)

    def get(self, userId, id, format):
        return _Exec(self._by_id[id])


class _FakeUsers:
    def __init__(self, msgs):
        self._msgs = msgs

    def messages(self):
        return self._msgs


class _FakeService:
    def __init__(self, records, page_size, sender):
        self._users = _FakeUsers(_FakeMessages(records, page_size, sender))

    def users(self):
        return self._users


SENDER = "support@wolf-on-wallstreet.com"


@pytest.fixture
async def bf_env(monkeypatch):
    """Fresh temp DB + mocked Gmail/decoder/parser. Yields a setup() helper."""
    db._db = None
    db.DB_PATH = tempfile.mktemp(suffix=".db")
    await db.init_db()

    # decoder/quote-strip: identity-ish, payload-shape independent
    monkeypatch.setattr(gmail_watcher, "_decode_body", lambda payload: ("body", "<html>"))
    monkeypatch.setattr(gmail_watcher, "_strip_quoted", lambda s: s)

    # parser: every email = one NVDA bull thesis; stage rises with internalDate so
    # all emails touch the SAME thesis and evidence accumulates in order.
    async def fake_parse(text, html, subject, sender, ts):
        # stage by arrival order: earliest forming -> ... -> acting
        return {
            "regime": None,
            "theses": [{
                "scope_type": "stock", "scope_key": "NVDA", "direction": "bull",
                "stage": "imminent", "levels": [], "snippet": f"call from {subject}",
            }],
            "big_catalysts": [],
            "chart_reads": [],
            "subject": subject,
            "ts": ts,
        }

    monkeypatch.setattr(wolf_email_parser, "parse_email", fake_parse)

    def setup(records, page_size=500):
        monkeypatch.setattr(gmail_watcher, "_build_service",
                            lambda: _FakeService(records, page_size, SENDER))

    yield setup

    await db.close_db()
    db._db = None
    db.DB_PATH = None


async def _run(argv):
    """Invoke the script's main() with the given argv (sans program name)."""
    import sys as _sys
    old = _sys.argv
    _sys.argv = ["backfill_wolf.py"] + argv
    try:
        return await backfill_wolf.main()
    finally:
        _sys.argv = old


# ---------------------------------------------------------------- tests
async def test_dry_run_writes_nothing(bf_env):
    bf_env([(3000_000, "m_c"), (1000_000, "m_a"), (2000_000, "m_b")])
    rc = await _run(["--dry-run"])
    assert rc == 0
    assert len(await db.get_active_theses()) == 0          # no theses
    conn = await db.get_db()
    cur = await conn.execute("SELECT COUNT(*) AS c FROM wolf_emails_processed")
    assert (await cur.fetchone())["c"] == 0                # no ledger rows


async def test_pagination_and_ascending_order(bf_env):
    # out-of-order + spread across 2 pages; expect ascending (internalDate,msg_id)
    bf_env([(3000_000, "m_c"), (1000_000, "m_a"), (2000_000, "m_b")], page_size=2)
    rc = await _run([])
    assert rc == 0
    theses = await db.get_active_theses()
    assert len(theses) == 1
    evlog = json.loads(theses[0]["evidence_log_json"])
    ts_order = [e["ts"] for e in evlog]
    assert ts_order == [1000.0, 2000.0, 3000.0], ts_order   # internalDate ms -> s, ascending


async def test_received_at_recorded(bf_env):
    bf_env([(1700_000, "m1")])
    await _run([])
    conn = await db.get_db()
    cur = await conn.execute("SELECT received_at, processed_at FROM wolf_emails_processed WHERE message_id='m1'")
    row = await cur.fetchone()
    assert row["received_at"] == 1700.0                     # internalDate/1000
    assert row["processed_at"] != row["received_at"]        # processed_at = wall clock


async def test_idempotent_rerun(bf_env):
    bf_env([(1000_000, "m1"), (2000_000, "m2")])
    await _run([])
    theses = await db.get_active_theses()
    ev_before = json.loads(theses[0]["evidence_log_json"])
    # second full run: everything already seen -> 0 new evidence
    await _run([])
    theses = await db.get_active_theses()
    ev_after = json.loads(theses[0]["evidence_log_json"])
    assert ev_after == ev_before


async def test_failure_injection_atomicity(bf_env, monkeypatch):
    """Crash AFTER ingest, BEFORE the ledger write, then rerun: 0 duplicate
    evidence entries (Codex BLOCKER-3 — the must-fix this whole design hinges on)."""
    bf_env([(1000_000, "m1"), (2000_000, "m2"), (3000_000, "m3")])

    real_record = db.record_wolf_email
    calls = {"n": 0}

    async def flaky_record(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:   # m2: ingest already ran; die before its ledger write
            raise RuntimeError("simulated crash between ingest and ledger")
        return await real_record(*a, **k)

    monkeypatch.setattr(db, "record_wolf_email", flaky_record)
    with pytest.raises(RuntimeError):
        await _run([])

    # m1 fully done; m2 ingested but NOT in ledger; m3 untouched
    conn = await db.get_db()
    cur = await conn.execute("SELECT message_id FROM wolf_emails_processed ORDER BY message_id")
    seen = [r["message_id"] for r in await cur.fetchall()]
    assert seen == ["m1"]
    theses = await db.get_active_theses()
    evlog = json.loads(theses[0]["evidence_log_json"])
    srcs_after_crash = [e.get("src") for e in evlog]
    assert srcs_after_crash == ["m1", "m2"]               # m2's evidence DID get appended

    # rerun cleanly: m2 re-ingested must be a NO-OP (src already present), not a dup
    monkeypatch.setattr(db, "record_wolf_email", real_record)
    await _run([])
    theses = await db.get_active_theses()
    evlog = json.loads(theses[0]["evidence_log_json"])
    srcs = [e.get("src") for e in evlog]
    assert srcs == ["m1", "m2", "m3"], srcs                # exactly one entry per email, no dup m2
    cur = await conn.execute("SELECT COUNT(*) AS c FROM wolf_emails_processed")
    assert (await cur.fetchone())["c"] == 3                # all three ledgered now


async def test_empty_state_precondition_aborts(bf_env, monkeypatch):
    """A thesis updated AFTER the oldest email to replay => abort (return 2) unless
    --rebuild (Codex MAJOR-4: don't scramble live-advanced theses)."""
    # seed a 'live' thesis with last_updated newer than the oldest email
    await db.insert_thesis("stock", "NVDA", "bull", "acting", "[]", None, 0,
                           json.dumps([{"ts": 9_000_000.0, "to": "acting"}]), 9_000_000.0)
    bf_env([(1000_000, "old_a"), (2000_000, "old_b")])      # received ~1000-2000s << 9_000_000
    rc = await _run([])
    assert rc == 2                                          # aborted
    # no backfill ledger rows written
    conn = await db.get_db()
    cur = await conn.execute("SELECT COUNT(*) AS c FROM wolf_emails_processed")
    assert (await cur.fetchone())["c"] == 0


async def test_rebuild_clears_and_replays(bf_env):
    """--rebuild backs up + clears the live thesis, then replays from scratch."""
    await db.insert_thesis("stock", "TSLA", "bear", "acting", "[]", None, 0,
                           json.dumps([{"ts": 9_000_000.0, "to": "acting"}]), 9_000_000.0)
    bf_env([(1000_000, "m1"), (2000_000, "m2")])
    rc = await _run(["--rebuild"])
    assert rc == 0
    theses = await db.get_active_theses()
    # old TSLA gone; only the replayed NVDA thesis remains
    keys = sorted(t["scope_key"] for t in theses)
    assert keys == ["NVDA"], keys


async def test_max_emails_cap(bf_env):
    bf_env([(1000_000, "m1"), (2000_000, "m2"), (3000_000, "m3")])
    await _run(["--max-emails", "2"])
    conn = await db.get_db()
    cur = await conn.execute("SELECT COUNT(*) AS c FROM wolf_emails_processed")
    assert (await cur.fetchone())["c"] == 2


# ---------------------------------------------------------------- #5 sender split
def test_wolf_sender_reads_split_lists(monkeypatch):
    """phase-4 #5: the Gmail query is never empty after the allowlist split.

    _wolf_sender must prefer allowed_emails, then allowed_domains, then the legacy
    list — never an empty string (which would make the Gmail `from:` query match all).
    """
    def mk(mapping):
        monkeypatch.setattr(backfill_wolf.cfg, "get", lambda k, d=None: mapping.get(k, d))

    mk({"gmail_watcher.allowed_emails": ["support@wolf-on-wallstreet.com"]})
    assert backfill_wolf._wolf_sender() == "support@wolf-on-wallstreet.com"
    assert backfill_wolf._gmail_query(None).startswith("from:")

    mk({"gmail_watcher.allowed_domains": ["wolf-on-wallstreet.com"]})
    assert backfill_wolf._wolf_sender() == "wolf-on-wallstreet.com"

    # legacy combined list still honoured
    mk({"gmail_watcher.sender_allowlist": ["legacy@wolf-on-wallstreet.com"]})
    assert backfill_wolf._wolf_sender() == "legacy@wolf-on-wallstreet.com"

    # nothing configured -> safe non-empty default (never an empty from: query)
    mk({})
    assert backfill_wolf._wolf_sender() == "support@wolf-on-wallstreet.com"
