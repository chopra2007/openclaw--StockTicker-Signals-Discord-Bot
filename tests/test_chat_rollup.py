"""Tests for #39 chat-memory rollups: redaction, parsing, extractive rollup, idempotency,
and the identity-gated cleanup (never delete a raw archive without an exact-hash complete
rollup of those bytes)."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consensus_engine import db
from consensus_engine.memory import chat_rollup as cr


# ---- redaction ----
def test_redact_masks_secrets_and_emails():
    s = ("token apify_api_FAKEFAKEFAKE1234 and sk-abcdef0123456789ABCDEF "
         "email teche2014@gmail.com bearer ey.J.tok api_key=supersecretvalue123")
    out = cr.redact(s)
    for leak in ["apify_api_FAKEFAKEFAKE1234", "sk-abcdef0123456789", "teche2014@gmail.com", "supersecretvalue123"]:
        assert leak not in out
    assert "[REDACTED]" in out


def test_redact_keeps_normal_text():
    assert cr.redact("NVDA is up and the earnings_calendar.py bug was fixed") == \
        "NVDA is up and the earnings_calendar.py bug was fixed"


# ---- parsing ----
def _write_archive(path, records):
    with open(path, "w") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def test_parse_strips_context_preamble_and_reads_compaction(tmp_path):
    p = tmp_path / "channel-123.deleted.1000.jsonl"
    _write_archive(p, [
        {"type": "session"},
        {"type": "message", "timestamp": "2026-05-20T21:00:00.000Z",
         "message": {"role": "user", "content": [{"type": "text",
            "text": "[Context: it is now. blah blah]\n\nUser message:\n```\nwhy false NVDA signals?\n```"}]}},
        {"type": "message", "timestamp": "2026-05-20T21:00:05.000Z",
         "message": {"role": "assistant", "content": [{"type": "text",
            "text": "Root cause: fetch_recent_earnings_for_ticker in earnings_calendar.py"}]}},
        {"type": "compaction", "timestamp": "2026-05-20T21:30:00.000Z",
         "summary": "## Decisions\n- investigate NVDA false signals"},
    ])
    parsed = cr.parse_archive(str(p))
    assert len(parsed["turns"]) == 2
    assert parsed["turns"][0]["text"] == "why false NVDA signals?"   # preamble stripped
    assert "earnings_calendar.py" in parsed["turns"][1]["text"]
    assert parsed["compaction_summaries"] == ["## Decisions\n- investigate NVDA false signals"]


def test_extractive_rollup_buckets_and_includes_summaries(tmp_path):
    p = tmp_path / "channel-123.deleted.1000.jsonl"
    _write_archive(p, [
        {"type": "message", "timestamp": "2026-05-20T21:00:00.000Z",
         "message": {"role": "user", "content": [{"type": "text", "text": "q1"}]}},
        {"type": "message", "timestamp": "2026-05-20T21:00:05.000Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "a1"}]}},
        {"type": "compaction", "timestamp": "2026-05-20T21:30:00.000Z", "summary": "S1"},
    ])
    roll = cr.build_extractive_rollup(cr.parse_archive(str(p)))
    assert "2026-05-20" in roll and "Q: q1" in roll and "A: a1" in roll
    assert "S1" in roll


# ---- summarize + idempotency (temp DB) ----
@pytest.fixture
async def memdb():
    db._db = None
    db.DB_PATH = tempfile.mktemp(suffix=".db")
    await db.init_db()
    yield
    await db.close_db()
    db._db = None
    db.DB_PATH = None


async def test_summarize_writes_row_and_is_idempotent(memdb, tmp_path):
    p = tmp_path / "channel-555.deleted.2000.jsonl"
    _write_archive(p, [
        {"type": "message", "timestamp": "2026-05-20T21:00:00.000Z",
         "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]}},
        {"type": "message", "timestamp": "2026-05-20T21:00:05.000Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "hi there"}]}},
    ])
    r1 = await cr.summarize_archive(str(p), use_llm=False)
    assert r1["status"] == "complete" and r1["channel_id"] == "555"
    assert await db.chat_rollup_exists(r1["sha"])
    rolls = await db.get_chat_rollups_for_channel("555")
    assert len(rolls) == 1
    # re-run -> upsert on the same sha, still ONE row (idempotent)
    await cr.summarize_archive(str(p), use_llm=False)
    assert len(await db.get_chat_rollups_for_channel("555")) == 1


# ---- identity-gated cleanup ----
async def test_cleanup_only_deletes_with_exact_complete_rollup(memdb, tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "SESSIONS_DIR", str(tmp_path))
    # an OLD archive (mtime 60 days ago) with NO rollup -> must be kept
    old = tmp_path / "channel-1.deleted.1.jsonl"
    _write_archive(old, [{"type": "message", "timestamp": "2026-04-01T00:00:00.000Z",
                          "message": {"role": "user", "content": [{"type": "text", "text": "x"}]}}])
    old_t = time.time() - 60 * 86400
    os.utime(old, (old_t, old_t))
    deleted = await cr.cleanup_old_archives(retention_days=30)
    assert deleted == 0 and old.exists()        # no rollup -> kept

    # now summarize it (creates a complete rollup of these exact bytes) -> cleanup deletes it
    await cr.summarize_archive(str(old), use_llm=False)
    os.utime(old, (old_t, old_t))               # keep it "old" after the write
    deleted2 = await cr.cleanup_old_archives(retention_days=30)
    assert deleted2 >= 1 and not old.exists()    # covered + old -> deleted

    # a FRESH archive (recent mtime) with a rollup must NOT be deleted (retention guard)
    fresh = tmp_path / "channel-2.deleted.2.jsonl"
    _write_archive(fresh, [{"type": "message", "timestamp": "2026-06-14T00:00:00.000Z",
                            "message": {"role": "user", "content": [{"type": "text", "text": "y"}]}}])
    await cr.summarize_archive(str(fresh), use_llm=False)
    assert await cr.cleanup_old_archives(retention_days=30) == 0 and fresh.exists()
