"""TODO #17 Task C Phase 1 — conservative visual-evidence attribution.

youtube_visual_evidence has no ticker column. get_youtube_visual_evidence_for_ticker
attributes a video's on-screen chart numbers to a ticker only when that ticker is the
TOP-mentioned ticker for the video. These tests cover the read function and the
narrator-facing snippet builder.
"""
import pytest

from consensus_engine import db, config as cfg
from consensus_engine.alerts.all_command.aggregator import (
    _build_yt_visual_snippets,
    _visual_band_filter,
)


@pytest.fixture(autouse=True)
def setup_config():
    cfg.load_config()


@pytest.fixture
async def tmp_db(tmp_path):
    db_path = str(tmp_path / "test_yt_visual.db")
    cfg._config["database"] = {"path": db_path, "signal_ttl_hours": 2, "alert_history_days": 90}
    conn = await db.init_db()
    yield conn
    await db.close_db()


@pytest.mark.asyncio
async def test_visual_evidence_attributed_to_top_ticker_only(tmp_db):
    """One video, NVDA top-mentioned (5) vs LOWX side-mention (1). Visual rows
    attribute to NVDA, NOT to LOWX."""
    # NVDA is the dominant ticker for this video.
    await db.insert_youtube_signal(
        video_id="vidVA1", channel_name="ClickCapital", ticker="NVDA",
        direction="long", conviction="high", mention_count=5,
    )
    # LOWX is merely name-dropped in the same video.
    await db.insert_youtube_signal(
        video_id="vidVA1", channel_name="ClickCapital", ticker="LOWX",
        direction="long", conviction="low", mention_count=1,
    )
    # On-screen chart numbers captured from the video (no ticker column).
    await db.insert_youtube_visual_evidence(
        "vidVA1",
        [
            {"ts_sec": 12, "value": "$739.88", "kind": "price", "where": "chart axis"},
            {"ts_sec": 40, "value": "RSI 71", "kind": "indicator", "where": "indicator pane"},
        ],
    )

    nvda_rows = await db.get_youtube_visual_evidence_for_ticker("NVDA", days=7)
    values = sorted(r["value"] for r in nvda_rows)
    assert values == ["$739.88", "RSI 71"]
    assert all(r["channel_name"] == "ClickCapital" for r in nvda_rows)

    # The side-mentioned ticker must NOT inherit the chart numbers.
    lowx_rows = await db.get_youtube_visual_evidence_for_ticker("LOWX", days=7)
    assert lowx_rows == []


@pytest.mark.asyncio
async def test_visual_evidence_excludes_stale_window(tmp_db):
    """A ticker with no signal in the window gets no visual rows."""
    await db.insert_youtube_signal(
        video_id="vidVA2", channel_name="Chan", ticker="TSLA",
        direction="long", conviction="high", mention_count=3,
    )
    await db.insert_youtube_visual_evidence(
        "vidVA2", [{"ts_sec": 5, "value": "$250.10", "kind": "price", "where": "axis"}]
    )
    # Window of 0 days → cutoff is now; the just-inserted signal is < cutoff,
    # so nothing should match.
    rows = await db.get_youtube_visual_evidence_for_ticker("TSLA", days=0)
    assert rows == []


def test_build_yt_visual_snippets_renders_chart_shows():
    rows = [
        {"value": "$739.88", "channel_name": "ClickCapital", "where_seen": "chart axis"},
        {"value": "RSI 71", "channel_name": "ClickCapital", "where_seen": None},
        {"value": "", "channel_name": "ClickCapital"},  # skipped: empty value
    ]
    out = _build_yt_visual_snippets(rows)
    assert out == [
        "[ClickCapital] chart shows $739.88 (chart axis)",
        "[ClickCapital] chart shows RSI 71 (on chart)",
    ]


def test_build_yt_visual_snippets_handles_non_list():
    assert _build_yt_visual_snippets(None) == []
    assert _build_yt_visual_snippets("not a list") == []


# ── Phase 2: price-band filter ───────────────────────────────────────────────

def test_visual_band_filter_drops_far_prices_keeps_near():
    """At $98 with a 10% band, gridlines 0/20/50 drop; 95/102 (near) stay."""
    rows = [
        {"value": "0", "kind": "price"},
        {"value": "20", "kind": "price"},
        {"value": "50", "kind": "price"},
        {"value": "95", "kind": "price"},     # within 10% of 98
        {"value": "102", "kind": "price"},    # within 10% of 98
        {"value": "$1,090", "kind": "price"}, # far → drop (also tests $/comma strip)
    ]
    out = _visual_band_filter(rows, price=98.0, band_pct=0.10)
    assert sorted(r["value"] for r in out) == ["102", "95"]


def test_visual_band_filter_passes_non_price_kinds_untouched():
    """Greeks, $-exposure, tickers, labels are not price levels — band ignores them."""
    rows = [
        {"value": "$2.1B", "kind": "other"},     # notional, nowhere near 98
        {"value": "IV 62", "kind": "indicator"},
        {"value": "USCI", "kind": "ticker"},
        {"value": "10", "kind": "price"},        # gridline → drop
    ]
    out = _visual_band_filter(rows, price=98.0, band_pct=0.10)
    assert sorted(r["value"] for r in out) == ["$2.1B", "IV 62", "USCI"]


def test_visual_band_filter_keeps_all_when_no_live_price():
    rows = [{"value": "0", "kind": "price"}, {"value": "50", "kind": "price"}]
    assert _visual_band_filter(rows, price=0.0, band_pct=0.10) == rows


def test_visual_band_filter_keeps_unparseable_price_value():
    rows = [{"value": "near the 200dma", "kind": "price"}]
    assert _visual_band_filter(rows, price=98.0, band_pct=0.10) == rows


def test_visual_band_filter_non_list():
    assert _visual_band_filter(None, 98.0, 0.10) == []
