"""Tests for the YouTube RSS scanner."""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from consensus_engine import db, config as cfg
from consensus_engine.scanners.youtube import (
    fetch_channel_videos_rss,
    process_video,
)


@pytest.fixture(autouse=True)
def setup_config():
    cfg.load_config()


@pytest.fixture
async def test_db(tmp_path):
    db_path = str(tmp_path / "yt_scanner.db")
    cfg._config["database"] = {"path": db_path, "signal_ttl_hours": 2, "alert_history_days": 90}
    conn = await db.init_db()
    yield conn
    await db.close_db()


VALID_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015">
  <entry>
    <yt:videoId>abc123</yt:videoId>
    <title>First Video</title>
    <published>2026-04-06T10:00:00+00:00</published>
  </entry>
  <entry>
    <yt:videoId>def456</yt:videoId>
    <title>Second Video</title>
    <published>2026-04-05T10:00:00+00:00</published>
  </entry>
</feed>"""

MALFORMED_RSS = "<<this is not xml>>"


@pytest.mark.asyncio
async def test_rss_parse_success():
    import aiohttp
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value=VALID_RSS)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)

    videos = await fetch_channel_videos_rss(mock_session, "UCtest", limit=5)
    assert len(videos) == 2
    assert videos[0]["video_id"] == "abc123"
    assert videos[0]["title"] == "First Video"
    assert videos[1]["video_id"] == "def456"


@pytest.mark.asyncio
async def test_rss_parse_limit():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value=VALID_RSS)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)

    videos = await fetch_channel_videos_rss(mock_session, "UCtest", limit=1)
    assert len(videos) == 1
    assert videos[0]["video_id"] == "abc123"


@pytest.mark.asyncio
async def test_rss_malformed_returns_empty():
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value=MALFORMED_RSS)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)

    videos = await fetch_channel_videos_rss(mock_session, "UCtest", limit=5)
    assert videos == []


@pytest.mark.asyncio
async def test_rss_http_error_returns_empty():
    mock_resp = AsyncMock()
    mock_resp.status = 503
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)

    videos = await fetch_channel_videos_rss(mock_session, "UCtest", limit=5)
    assert videos == []


@pytest.mark.asyncio
async def test_process_video_dedup(test_db, tmp_path):
    """Second call for same video_id after save should be a no-op."""
    semaphore = asyncio.Semaphore(1)
    video = {"video_id": "vidX", "channel_id": "UCX", "title": "T", "published_at": "2026-04-06T00:00:00Z"}

    with patch("consensus_engine.utils.transcript_fetch.fetch_transcript_cascade",
               new=AsyncMock(return_value=("Some transcript text", "en", True))):
        await process_video(video, semaphore, ["en"], str(tmp_path))
        # second call — fetch_transcript should NOT be called again (video now processed)
        with patch("consensus_engine.utils.transcript_fetch.fetch_transcript_cascade",
                   new=AsyncMock(side_effect=AssertionError("should not be called"))) as mock_ft2:
            await process_video(video, semaphore, ["en"], str(tmp_path))


@pytest.mark.asyncio
async def test_process_video_missing_captions(test_db, tmp_path, monkeypatch):
    """Caption-unavailable error sets status to 'missing', does not raise."""
    monkeypatch.setitem(cfg._config["youtube"], "use_two_stage", False)
    semaphore = asyncio.Semaphore(1)
    video = {"video_id": "vidY", "channel_id": "UCY", "title": "No Caps", "published_at": "2026-04-06T00:00:00Z"}

    with patch("consensus_engine.utils.transcript_fetch.fetch_transcript_cascade",
               new=AsyncMock(side_effect=Exception("no caption tracks for vidY"))):
        await process_video(video, semaphore, ["en"], str(tmp_path))

    conn = await db.get_db()
    cursor = await conn.execute("SELECT transcript_status FROM youtube_videos WHERE video_id='vidY'")
    row = await cursor.fetchone()
    assert row["transcript_status"] == "missing"


@pytest.mark.asyncio
async def test_process_video_persists_options(test_db, tmp_path, monkeypatch):
    """process_video() stores VideoOptionIdea rows in youtube_options (Path C)."""
    monkeypatch.setitem(cfg._config["youtube"], "use_two_stage", False)
    from consensus_engine.models import (
        ParsedVideo, MacroThesis, Direction, Conviction, VideoOptionIdea,
    )

    opt = VideoOptionIdea(
        ticker="TSLA", option_type="call", strike=250.0, expiry="2026-05-16",
        strategy="single", source="flow_observation", conviction="high",
        context="big call sweep", source_snippet="bought 250c", chunk_id=1,
    )
    mock_parsed = ParsedVideo(
        video_id="vidOPT1", channel_name="TraderChan", raw_transcript="",
        tickers=[],
        price_levels=[],
        macro_thesis=MacroThesis(direction=Direction.NEUTRAL, themes=[], timeframe="short", summary=""),
        overall_conviction=Conviction.MEDIUM,
        run_id=42, options=[opt], setups=[],
    )

    async def fake_fetch(*a, **kw):
        return "transcript " * 300, "en", False

    monkeypatch.setattr(
        "consensus_engine.utils.transcript_fetch.fetch_transcript_cascade",
        fake_fetch,
    )
    monkeypatch.setattr(
        "consensus_engine.analysis.video_parser.parse_video_transcript",
        AsyncMock(return_value=mock_parsed),
    )

    sem = asyncio.Semaphore(1)
    video_meta = {"video_id": "vidOPT1", "channel_id": "ch2",
                  "title": "Options Trade", "published_at": "2026-04-22T10:00:00Z"}
    await process_video(video_meta, sem, ["en"], str(tmp_path))

    opts = await db.get_youtube_options_for_ticker("TSLA", days=1)
    assert len(opts) == 1
    assert opts[0]["option_type"] == "call"
    assert opts[0]["strike"] == 250.0
    assert opts[0]["run_id"] == 42


@pytest.mark.asyncio
async def test_process_video_uses_two_stage_when_flag_on(test_db, tmp_path, monkeypatch):
    """When use_two_stage=True, process_video runs the v2 pipeline and persists candidates."""
    from consensus_engine.models import (
        EvidenceBundle, EvidenceSpan, CandidateSignal, CandidateLevel,
        Direction, Conviction, MacroThesis, RunTelemetry,
    )
    from consensus_engine.analysis.video_classifier import ClassificationResult

    # Flip the flag on just for this test
    monkeypatch.setitem(cfg._config["youtube"], "use_two_stage", True)
    monkeypatch.setitem(cfg._config["youtube"], "legacy_fallback", False)

    bundle = EvidenceBundle(
        video_id="vidTS1ABCDE",
        duration_sec=120,
        publish_ts="2026-04-17T12:00:00Z",
        segments=[{"ts_start_sec": 0, "title": "Intro"}],
        spans=[
            EvidenceSpan(ts_sec=42, quote="MSFT breakout above 400",
                         tickers=["MSFT"], numbers=[400.0], dates_mentioned=[]),
        ],
    )
    telemetry = RunTelemetry(
        input_tokens=100, output_tokens=50, latency_ms=250,
        json_parse_ok=True, span_count=1,
    )
    fake_result = ClassificationResult(
        signals=[CandidateSignal(
            ticker="MSFT", direction=Direction.LONG, conviction=Conviction.HIGH,
            mention_count=3, context="MSFT breakout", evidence_span_ids=[],
            classifier_confidence=0.85, video_timestamp_sec=42,
        )],
        levels=[CandidateLevel(
            ticker="MSFT", level_type="support", price=400.0,
            context="breakout above 400", classifier_confidence=0.9,
            video_timestamp_sec=42,
        )],
        setups=[],
        catalyst_candidates=[],
        macro_thesis=MacroThesis(
            direction=Direction.LONG, themes=["tech"], timeframe="short",
            summary="bullish", narrative="bullish on MSFT",
        ),
    )

    monkeypatch.setattr(
        "consensus_engine.local_video_ingest.extract_evidence_via_chain",
        AsyncMock(return_value=(bundle, telemetry)),
    )
    monkeypatch.setattr(
        "consensus_engine.analysis.video_classifier.classify_evidence",
        MagicMock(return_value=fake_result),
    )
    monkeypatch.setattr(
        "consensus_engine.analysis.catalyst_resolver.resolve_and_verify_catalysts",
        AsyncMock(return_value=[]),
    )
    # Block all alerts so the test is offline
    monkeypatch.setitem(cfg._config["youtube"], "standalone_alerts", False)

    sem = asyncio.Semaphore(1)
    video_meta = {"video_id": "vidTS1ABCDE", "channel_id": "ch-two-stage",
                  "title": "Two-Stage Test", "published_at": "2026-04-17T12:00:00Z"}
    await process_video(video_meta, sem, ["en"], str(tmp_path))

    sigs = await db.get_youtube_signals_for_ticker("MSFT", days=1)
    assert len(sigs) == 1
    assert sigs[0]["video_id"] == "vidTS1ABCDE"

    lvls = await db.get_youtube_levels_for_ticker("MSFT", days=1)
    assert len(lvls) == 1
    assert lvls[0]["level_type"] == "support"


@pytest.mark.asyncio
async def test_process_video_persists_setups(test_db, tmp_path, monkeypatch):
    """process_video() stores VideoTradeSetup rows and absorbs constituent levels."""
    monkeypatch.setitem(cfg._config["youtube"], "use_two_stage", False)
    from consensus_engine.models import (
        ParsedVideo, MacroThesis, Direction, Conviction,
        VideoTradeSetup, PriceLevel,
    )

    level = PriceLevel(
        ticker="NVDA", level_type="support", price=800.0,
        condition="if holds 800", consequence="rally to 850", confidence=0.9,
    )
    setup = VideoTradeSetup(
        ticker="NVDA", entry_low=800.0, entry_high=810.0, stop=790.0,
        targets=[850.0, 900.0], timeframe="swing", setup_type="breakout",
        context="NVDA breakout above 810", source_snippet="buy 800-810 stop 790",
        chunk_id=2, risk_reward=3.0,
    )
    mock_parsed = ParsedVideo(
        video_id="vidSET1", channel_name="SetupChan", raw_transcript="",
        tickers=[],
        price_levels=[level],
        macro_thesis=MacroThesis(direction=Direction.LONG, themes=[], timeframe="swing", summary=""),
        overall_conviction=Conviction.HIGH,
        run_id=55, options=[], setups=[setup],
    )

    async def fake_fetch(*a, **kw):
        return "transcript " * 300, "en", False

    monkeypatch.setattr(
        "consensus_engine.utils.transcript_fetch.fetch_transcript_cascade",
        fake_fetch,
    )
    monkeypatch.setattr(
        "consensus_engine.analysis.video_parser.parse_video_transcript",
        AsyncMock(return_value=mock_parsed),
    )

    sem = asyncio.Semaphore(1)
    video_meta = {"video_id": "vidSET1", "channel_id": "ch3",
                  "title": "Setup Video", "published_at": "2026-04-22T10:00:00Z"}
    await process_video(video_meta, sem, ["en"], str(tmp_path))

    setups = await db.get_youtube_setups_for_ticker("NVDA", days=1)
    assert len(setups) == 1
    assert setups[0]["setup_type"] == "breakout"
    assert setups[0]["run_id"] == 55

    # Level should be absorbed into the setup
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT setup_id FROM youtube_levels WHERE video_id='vidSET1' AND ticker='NVDA'"
    )
    row = await cur.fetchone()
    assert row is not None
    assert row["setup_id"] == setups[0]["id"]


# ---------------------------------------------------------------------------
# Layer 3: video-level allowlist suppression (off_allowlist)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_off_allowlist_suppressed(monkeypatch):
    """An NVDA candidate signal is suppressed when video evidence has only AMC/GME."""
    from consensus_engine.scanners import youtube as scanner
    from consensus_engine.models import (
        EvidenceBundle, EvidenceSpan, CandidateSignal, Direction, Conviction, RunTelemetry,
    )
    from consensus_engine.analysis.video_classifier import ClassificationResult

    bundle = EvidenceBundle(
        video_id="vidX1234567", duration_sec=600, publish_ts="2026-04-23T00:00:00Z",
        segments=[],
        spans=[
            EvidenceSpan(ts_sec=100, quote="Burry buys more AMC",
                         tickers=["AMC"], numbers=[], dates_mentioned=[]),
            EvidenceSpan(ts_sec=200, quote="GameStop short squeeze setup",
                         tickers=["GME"], numbers=[], dates_mentioned=[]),
        ],
    )

    async def _stub_extract(video_id, channel, published_at):
        return bundle, RunTelemetry()

    monkeypatch.setattr(
        "consensus_engine.local_video_ingest.extract_evidence_via_chain",
        _stub_extract,
    )

    def _stub_classify(b):
        return ClassificationResult(signals=[
            CandidateSignal(ticker="NVDA", direction=Direction.LONG,
                            conviction=Conviction.HIGH, mention_count=1,
                            classifier_confidence=0.8, evidence_span_ids=[],
                            context="AI sector"),
            CandidateSignal(ticker="AMC", direction=Direction.LONG,
                            conviction=Conviction.HIGH, mention_count=4,
                            classifier_confidence=0.9, evidence_span_ids=[],
                            context="Burry buying AMC"),
        ])

    monkeypatch.setattr(
        "consensus_engine.analysis.video_classifier.classify_evidence",
        _stub_classify,
    )

    async def _stub_resolve(candidates, publish_ts):
        return []

    monkeypatch.setattr(
        "consensus_engine.analysis.catalyst_resolver.resolve_and_verify_catalysts",
        _stub_resolve,
    )

    async def _stub_get_video(vid):
        return {"video_id": vid, "title": "AMC GAMESTOP — Burry buys more"}

    monkeypatch.setattr("consensus_engine.db.get_youtube_video", _stub_get_video)

    # Capture insert calls to verify suppression flags
    inserted_signals = []

    async def _fake_insert_signal(**kwargs):
        inserted_signals.append(kwargs)
        return 1

    monkeypatch.setattr("consensus_engine.db.insert_youtube_signal", _fake_insert_signal)
    monkeypatch.setattr("consensus_engine.db.insert_youtube_level", AsyncMock(return_value=1))
    monkeypatch.setattr("consensus_engine.db.insert_youtube_setup", AsyncMock(return_value=1))
    monkeypatch.setattr("consensus_engine.db.insert_youtube_catalyst", AsyncMock(return_value=1))
    monkeypatch.setattr("consensus_engine.db.insert_youtube_macro", AsyncMock(return_value=None))
    monkeypatch.setattr("consensus_engine.db.create_analysis_run", AsyncMock(return_value=99))
    monkeypatch.setattr("consensus_engine.db.update_analysis_run_metrics", AsyncMock(return_value=None))
    monkeypatch.setattr("consensus_engine.db.mark_youtube_video_status", AsyncMock(return_value=None))
    monkeypatch.setattr("consensus_engine.db.get_channel_trust", AsyncMock(return_value=0.0))
    monkeypatch.setattr(scanner, "_send_two_stage_alerts", AsyncMock(return_value=None))

    ok = await scanner._process_video_two_stage(
        "vidX1234567", "ch1", "TestChan", "2026-04-23T00:00:00Z",
    )

    assert ok is True
    nvda_rows = [r for r in inserted_signals if r.get("ticker") == "NVDA"]
    amc_rows  = [r for r in inserted_signals if r.get("ticker") == "AMC"]
    assert nvda_rows, "NVDA signal should have been persisted (suppressed)"
    assert all(r.get("suppressed") == 1 for r in nvda_rows)
    assert all(r.get("suppression_reason") == "off_allowlist" for r in nvda_rows)
    assert amc_rows, "AMC signal should have been persisted"
    assert all(r.get("suppressed") == 0 for r in amc_rows)
