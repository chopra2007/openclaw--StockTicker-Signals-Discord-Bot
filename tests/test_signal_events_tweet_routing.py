"""Tests for Q2b: signal_events tweet routing.

RED at Commit A — turns GREEN when Commit C lands.

Covers:
- insert_signal(SourceType.TWITTER, ...) also writes a signal_events row with
  matching ticker, source_type='twitter', source_detail=<analyst>
- get_signal_events_for_ticker('NVDA', 3600) returns >= 1 row after inserting a
  twitter signal
"""
import time
import sqlite3
from unittest.mock import AsyncMock, patch
import pytest

from consensus_engine import db, config as cfg
from consensus_engine.models import (
    Conviction, Direction, ParsedTweet, SourceType, TickerPostView, TickerSignal,
    Sentiment, TweetType,
)


@pytest.fixture(autouse=True)
def _load_cfg():
    cfg.load_config()


@pytest.fixture
async def test_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    cfg._config.setdefault("database", {})["path"] = db_path
    db._db = None
    conn = await db.init_db()
    yield conn
    await db.close_db()


# ---------------------------------------------------------------------------
# signal_events row created on TWITTER insert (RED until Commit C)
# ---------------------------------------------------------------------------

async def test_insert_signal_twitter_also_writes_signal_events_row(test_db):
    """insert_signal() for SourceType.TWITTER must also write a signal_events row.

    RED until Commit C routes twitter signals into signal_events.
    """
    signal = TickerSignal(
        ticker="NVDA",
        source_type=SourceType.TWITTER,
        source_detail="TeresaTrades",
        raw_text="NVDA breaking out, loading calls",
        sentiment=Sentiment.BULLISH,
    )
    await db.insert_signal(signal)

    cursor = await test_db.execute(
        "SELECT * FROM signal_events WHERE ticker = 'NVDA' AND source_type = 'twitter'"
    )
    rows = await cursor.fetchall()
    assert len(rows) >= 1, (
        "Expected at least one signal_events row with ticker='NVDA' and "
        "source_type='twitter' after insert_signal(SourceType.TWITTER, ...) — "
        "RED until Commit C adds the signal_events write"
    )


async def test_insert_signal_twitter_sets_correct_source_detail(test_db):
    """signal_events row written by insert_signal has source_detail = analyst handle.

    RED until Commit C routes twitter signals into signal_events.
    """
    signal = TickerSignal(
        ticker="AAPL",
        source_type=SourceType.TWITTER,
        source_detail="kpak82",
        raw_text="AAPL catalyst, adding more",
        sentiment=Sentiment.BULLISH,
    )
    await db.insert_signal(signal)

    cursor = await test_db.execute(
        "SELECT source_detail FROM signal_events "
        "WHERE ticker = 'AAPL' AND source_type = 'twitter'"
    )
    rows = await cursor.fetchall()
    assert rows, "No signal_events rows found — RED until Commit C"
    assert rows[0]["source_detail"] == "kpak82", (
        f"source_detail mismatch: expected 'kpak82', got {rows[0]['source_detail']!r}"
    )


async def test_non_twitter_insert_signal_does_not_write_signal_events(test_db):
    """insert_signal() for non-TWITTER source types must NOT write a signal_events row
    via the twitter-routing path (each source type has its own routing).

    This verifies insert_signal remains targeted: only TWITTER gets the new row.
    """
    signal = TickerSignal(
        ticker="MSFT",
        source_type=SourceType.REDDIT,
        source_detail="r/wallstreetbets",
        raw_text="MSFT gang",
        sentiment=Sentiment.NEUTRAL,
    )
    await db.insert_signal(signal)

    cursor = await test_db.execute(
        "SELECT COUNT(*) as cnt FROM signal_events "
        "WHERE ticker = 'MSFT' AND source_type = 'twitter'"
    )
    row = await cursor.fetchone()
    assert row["cnt"] == 0, (
        "REDDIT insert_signal should not create a source_type='twitter' signal_events row"
    )


# ---------------------------------------------------------------------------
# get_signal_events_for_ticker returns the new rows (RED until Commit C)
# ---------------------------------------------------------------------------

async def test_get_signal_events_for_ticker_returns_row_after_twitter_insert(test_db):
    """get_signal_events_for_ticker('NVDA', 3600) returns >= 1 row after a twitter
    insert_signal call.

    RED until Commit C: currently insert_signal does NOT write signal_events.
    """
    signal = TickerSignal(
        ticker="NVDA",
        source_type=SourceType.TWITTER,
        source_detail="FlowAlerts",
        raw_text="NVDA huge flow",
        sentiment=Sentiment.BULLISH,
    )
    await db.insert_signal(signal)

    events = await db.get_signal_events_for_ticker("NVDA", window_seconds=3600)
    assert len(events) >= 1, (
        "get_signal_events_for_ticker must return >= 1 row after twitter insert_signal — "
        "RED until Commit C adds the signal_events write to insert_signal"
    )


async def test_twitter_view_is_durable_and_linked_after_signal_cleanup(test_db):
    reason = "$NVDA broke resistance after earnings"
    raw_text = ("context " * 300) + reason
    start = raw_text.index(reason)
    signal = TickerSignal(
        ticker="NVDA", source_type=SourceType.TWITTER, source_detail="analyst",
        raw_text=raw_text, sentiment=Sentiment.BULLISH, detected_at=time.time() - 8000,
    )
    view = TickerPostView(
        ticker="NVDA", direction="long", reason_text=reason,
        reason_start=start, reason_end=start + len(reason), reason_kind="setup",
        decision_code="explicit_clause", parser_version="analyst-view-v1",
    )

    await db.insert_signal(
        signal, ticker_view=view, source_url="https://example.test/source",
        parsed_summary="NVDA earnings breakout",
    )
    await db.prune_expired()

    row = await (await test_db.execute(
        """SELECT apv.*, se.analyst_post_view_id
             FROM signal_events se
             JOIN analyst_post_views apv ON apv.id=se.analyst_post_view_id
            WHERE se.ticker='NVDA'"""
    )).fetchone()
    assert row["raw_text"] == raw_text
    assert row["parsed_summary"] == "NVDA earnings breakout"
    assert row["reason_text"] == reason
    assert row["reason_start"] == start
    assert row["reason_end"] == start + len(reason)
    assert len(row["raw_text_sha256"]) == 64
    assert row["analyst_post_view_id"] == row["id"]
    remaining = await (await test_db.execute("SELECT COUNT(*) AS n FROM ticker_signals")).fetchone()
    assert remaining["n"] == 0


async def test_invalid_reason_span_is_saved_fail_closed(test_db):
    raw_text = "$NVDA broke resistance"
    signal = TickerSignal(
        ticker="NVDA", source_type=SourceType.TWITTER, source_detail="analyst",
        raw_text=raw_text, sentiment=Sentiment.BULLISH,
    )
    invalid = TickerPostView(
        ticker="NVDA", direction="long", reason_text="paraphrased breakout",
        reason_start=0, reason_end=len(raw_text), reason_kind="setup",
        decision_code="explicit_clause", parser_version="analyst-view-v1",
    )

    await db.insert_signal(signal, ticker_view=invalid, source_url="https://example.test/source")

    row = await (await test_db.execute("SELECT * FROM analyst_post_views")).fetchone()
    assert row["display_direction"] == "unclear"
    assert row["reason_text"] is None
    assert row["reason_start"] is None
    assert row["reason_end"] is None
    assert row["decision_code"] == "invalid_span"


async def test_storage_repairs_unique_exact_reason_offsets(test_db):
    raw_text = "$NVDA raised guidance after earnings"
    reason = "raised guidance after earnings"
    signal = TickerSignal(
        ticker="NVDA", source_type=SourceType.TWITTER, source_detail="analyst",
        raw_text=raw_text, sentiment=Sentiment.BULLISH,
    )
    view = TickerPostView(
        ticker="NVDA", direction="long", reason_text=reason,
        reason_start=0, reason_end=4, reason_kind="event_claim",
        decision_code="explicit_clause", parser_version="analyst-view-v1",
    )

    await db.insert_signal(signal, ticker_view=view, source_url="https://example.test/unique")

    row = await (await test_db.execute("SELECT * FROM analyst_post_views")).fetchone()
    assert row["display_direction"] == "unclear"
    assert row["reason_text"] == reason
    assert row["reason_start"] == raw_text.index(reason)
    assert row["reason_end"] == raw_text.index(reason) + len(reason)
    assert row["decision_code"] == "reason_only"


async def test_storage_maps_unique_whitespace_normalized_reason_to_source(test_db):
    raw_text = "$NVDA raised guidance\nafter   earnings"
    model_reason = "$NVDA raised guidance after earnings"
    signal = TickerSignal(
        ticker="NVDA", source_type=SourceType.TWITTER, source_detail="analyst",
        raw_text=raw_text, sentiment=Sentiment.BULLISH,
    )
    view = TickerPostView(
        ticker="NVDA", direction="unclear", reason_text=model_reason,
        reason_start=0, reason_end=len(model_reason), reason_kind="event_claim",
        decision_code="reason_only", parser_version="analyst-view-v1",
    )

    await db.insert_signal(signal, ticker_view=view, source_url="https://example.test/spacing")

    row = await (await test_db.execute("SELECT * FROM analyst_post_views")).fetchone()
    assert row["display_direction"] == "unclear"
    assert row["reason_text"] == raw_text
    assert row["reason_start"] == 0
    assert row["reason_end"] == len(raw_text)
    assert row["decision_code"] == "reason_only"


async def test_storage_rejects_repeated_exact_reason(test_db):
    reason = "$NVDA breakout"
    raw_text = f"{reason} then {reason}"
    signal = TickerSignal(
        ticker="NVDA", source_type=SourceType.TWITTER, source_detail="analyst",
        raw_text=raw_text, sentiment=Sentiment.BULLISH,
    )
    view = TickerPostView(
        ticker="NVDA", direction="unclear", reason_text=reason,
        reason_start=0, reason_end=len(reason), reason_kind="setup",
        decision_code="reason_only", parser_version="analyst-view-v1",
    )

    await db.insert_signal(signal, ticker_view=view, source_url="https://example.test/repeated")

    row = await (await test_db.execute("SELECT * FROM analyst_post_views")).fetchone()
    assert row["display_direction"] == "unclear"
    assert row["reason_text"] is None
    assert row["decision_code"] == "invalid_span"


async def test_storage_rejects_exact_reason_plus_whitespace_equivalent_duplicate(test_db):
    reason = "$NVDA breakout"
    raw_text = f"{reason} then $NVDA   breakout"
    signal = TickerSignal(
        ticker="NVDA", source_type=SourceType.TWITTER, source_detail="analyst",
        raw_text=raw_text, sentiment=Sentiment.BULLISH,
    )
    view = TickerPostView(
        ticker="NVDA", direction="unclear", reason_text=reason,
        reason_start=0, reason_end=len(reason), reason_kind="setup",
        decision_code="reason_only", parser_version="analyst-view-v1",
    )

    await db.insert_signal(signal, ticker_view=view, source_url="https://example.test/mixed-repeat")

    row = await (await test_db.execute("SELECT * FROM analyst_post_views")).fetchone()
    assert row["display_direction"] == "unclear"
    assert row["reason_text"] is None
    assert row["decision_code"] == "invalid_span"


async def test_storage_discards_reason_when_source_option_has_no_side(test_db):
    reason = "$NVDA reports earnings tomorrow"
    raw_text = f"{reason}; 150 calls expire Friday"
    signal = TickerSignal(
        ticker="NVDA", source_type=SourceType.TWITTER, source_detail="analyst",
        raw_text=raw_text, sentiment=Sentiment.NEUTRAL,
    )
    view = TickerPostView(
        ticker="NVDA", direction="unclear", reason_text=reason,
        reason_start=0, reason_end=len(reason), reason_kind="event_claim",
        decision_code="reason_only", parser_version="analyst-view-v1",
    )

    await db.insert_signal(signal, ticker_view=view, source_url="https://example.test/unsided-source")

    row = await (await test_db.execute("SELECT * FROM analyst_post_views")).fetchone()
    assert row["display_direction"] == "unclear"
    assert row["reason_text"] is None
    assert row["decision_code"] == "unsided_option"


@pytest.mark.parametrize(
    ("view", "raw_text", "expected_direction", "expected_reason", "expected_code"),
    [
        (
            TickerPostView(
                ticker="NVDA", direction="unclear", reason_text="$NVDA earnings tomorrow",
                reason_start=0, reason_end=23, reason_kind="event_claim",
                decision_code="reason_only",
            ),
            "$NVDA earnings tomorrow", "unclear", "$NVDA earnings tomorrow", "reason_only",
        ),
        (
            TickerPostView(
                ticker="NVDA", direction="long", reason_text=None,
                reason_start=None, reason_end=None, reason_kind="none",
                decision_code="direction_only",
            ),
            "$NVDA bullish above 150", "long", None, "direction_only",
        ),
    ],
)
async def test_storage_keeps_direction_and_reason_independently(
    test_db, view, raw_text, expected_direction, expected_reason, expected_code
):
    signal = TickerSignal(
        ticker="NVDA", source_type=SourceType.TWITTER, source_detail=expected_code,
        raw_text=raw_text, sentiment=Sentiment.BULLISH,
    )

    await db.insert_signal(
        signal, ticker_view=view, source_url=f"https://example.test/{expected_code}"
    )

    row = await (await test_db.execute(
        "SELECT * FROM analyst_post_views WHERE analyst=?", (expected_code,)
    )).fetchone()
    assert row["display_direction"] == expected_direction
    assert row["reason_text"] == expected_reason
    assert row["decision_code"] == expected_code


async def test_schema_version_34_and_nullable_event_link_exist(test_db):
    version = await (await test_db.execute(
        "SELECT note FROM schema_version WHERE version=34"
    )).fetchone()
    columns = {
        row["name"] for row in await (await test_db.execute("PRAGMA table_info(signal_events)")).fetchall()
    }
    assert version is not None
    assert "analyst_post_view_id" in columns


async def test_migration_34_upgrades_legacy_signal_events_idempotently(tmp_path):
    legacy_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(legacy_path)
    conn.execute(
        """CREATE TABLE signal_events (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               source_type TEXT NOT NULL,
               source_detail TEXT,
               ticker TEXT NOT NULL,
               direction TEXT,
               quality_score REAL DEFAULT 0.5,
               recorded_at REAL NOT NULL
           )"""
    )
    conn.execute(
        """INSERT INTO signal_events
           (source_type, source_detail, ticker, direction, recorded_at)
           VALUES ('twitter', 'legacy', 'NVDA', 'long', 1.0)"""
    )
    conn.commit()
    conn.close()

    db.DB_PATH = str(legacy_path)
    db._db = None
    try:
        upgraded = await db.init_db()
        await db._run_column_migrations(upgraded)
        columns = {
            row["name"] for row in await (await upgraded.execute(
                "PRAGMA table_info(signal_events)"
            )).fetchall()
        }
        legacy = await (await upgraded.execute(
            "SELECT analyst_post_view_id FROM signal_events WHERE source_detail='legacy'"
        )).fetchone()
        version = await (await upgraded.execute(
            "SELECT version FROM schema_version WHERE version=34"
        )).fetchone()
        assert "analyst_post_view_id" in columns
        assert legacy["analyst_post_view_id"] is None
        assert version["version"] == 34
    finally:
        await db.close_db()
        db.DB_PATH = None
        db._db = None


async def test_process_tweet_routes_ticker_view_without_changing_global_direction():
    from consensus_engine import main as main_mod

    text = "$AMD bullish. $NVDA lost support."
    nvda_reason = "$NVDA lost support"
    view = TickerPostView(
        ticker="NVDA", direction="short", reason_text=nvda_reason,
        reason_start=text.index(nvda_reason),
        reason_end=text.index(nvda_reason) + len(nvda_reason),
        reason_kind="setup", decision_code="explicit_clause",
    )
    parsed = ParsedTweet(
        tweet_url="https://example.test/post", analyst="analyst", raw_text=text,
        tweet_type=TweetType.TICKER_CALLOUT, tickers=["NVDA"],
        direction=Direction.LONG, options=None, conviction=Conviction.MEDIUM,
        summary="mixed post", ticker_views=[view],
    )
    raw = {"url": parsed.tweet_url, "analyst": parsed.analyst, "text": text}

    with patch.object(main_mod, "parse_tweet", new=AsyncMock(return_value=parsed)), \
         patch.object(main_mod.db, "check_seen_tweet", new=AsyncMock(return_value=False)), \
         patch.object(main_mod.db, "mark_tweet_seen", new=AsyncMock()), \
         patch.object(main_mod.db, "insert_signal", new=AsyncMock()) as insert_signal, \
         patch.object(main_mod, "validate_ticker_market_cap", new=AsyncMock(return_value=True)), \
         patch.object(main_mod, "_passes_quality_gate", return_value=True), \
         patch.object(main_mod.db, "check_alert_cooldown", new=AsyncMock(return_value=False)), \
         patch.object(main_mod.cfg, "get", side_effect=lambda key, default=None: False if key in {
             "features.analyst_herding.enabled", "measurement.batch1.collect_enabled"
         } else default):
        await main_mod.process_tweet(raw)

    signal = insert_signal.await_args.args[0]
    assert signal.sentiment == Sentiment.BULLISH
    assert insert_signal.await_args.kwargs["ticker_view"] is view
    assert insert_signal.await_args.kwargs["source_url"] == parsed.tweet_url
    assert insert_signal.await_args.kwargs["parsed_summary"] == parsed.summary
