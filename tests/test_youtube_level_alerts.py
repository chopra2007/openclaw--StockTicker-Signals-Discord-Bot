"""#29: YouTube level-proximity alerts (main._check_youtube_level_alerts).

The loop fetches every distinct youtube_levels ticker's live price concurrently
(via run_in_executor over _fetch_yfinance_price), zips ticker->price, skips any
result that is an Exception OR falsy, and fires a '🎯' alert + dedupe record when
the live price sits within proximity_pct of a stored level.

Covered here (no prior test existed):
  (a) in-band fires, out-of-band does NOT — exactly one alert (NVDA), text carries
      '🎯' + 'NVDA' + '$100';
  (b) the fired alert records a dedupe row via db.record_level_alert (NVDA);
  (c) the error-skip branch (main.py ~918-921 isinstance(Exception)): when the
      TSLA price fetch RAISES, gather(return_exceptions=True) hands the loop an
      Exception, the loop swallows it, and NVDA still alerts normally.
"""
import os
import tempfile

import pytest

from consensus_engine import config as cfg, db, main


@pytest.fixture
async def tmp_db():
    prev = db.DB_PATH
    db._db = None
    db.DB_PATH = tempfile.mktemp(suffix=".db")
    await db.init_db()
    yield
    await db.close_db()
    try:
        os.unlink(db.DB_PATH)
    except OSError:
        pass
    db.DB_PATH = prev
    db._db = None


async def _seed_levels():
    """NVDA support @100 + TSLA resistance @250 (both fresh, within the 14d window)."""
    await db.insert_youtube_level("vid_nvda", "NVDA", "support", 100.0,
                                  confidence=0.9, channel_name="TA Guy")
    await db.insert_youtube_level("vid_tsla", "TSLA", "resistance", 250.0,
                                  confidence=0.9, channel_name="Chart Wiz")


async def test_in_band_fires_out_of_band_skips_and_dedupes(tmp_db, monkeypatch):
    await _seed_levels()

    # NVDA $100.20 is within 0.5% of the $100 support -> fire; TSLA $300 is far from
    # the $250 resistance -> skip.
    prices = {"NVDA": 100.2, "TSLA": 300.0}
    monkeypatch.setattr(main, "_fetch_yfinance_price", lambda t: prices[t])

    posted: list[str] = []
    async def _capture(text):
        posted.append(text)
    monkeypatch.setattr(main, "_post_to_alerts_channel", _capture)

    await main._check_youtube_level_alerts()

    # (a) exactly one alert, and it is the NVDA support hit
    assert len(posted) == 1
    msg = posted[0]
    assert "🎯" in msg and "NVDA" in msg and "$100" in msg
    assert "TSLA" not in msg

    # (b) dedupe row recorded for NVDA (record_level_alert wrote youtube_level_alerts)
    assert await db.was_level_recently_alerted("NVDA", 100.0)
    assert not await db.was_level_recently_alerted("TSLA", 250.0)


async def test_error_skip_branch_swallows_exception(tmp_db, monkeypatch):
    """The TSLA price fetch RAISES. gather(return_exceptions=True) turns that into an
    Exception in the prices list; the isinstance(Exception) guard skips it without
    crashing, and the in-band NVDA level still alerts normally."""
    await _seed_levels()

    def _flaky(t):
        if t == "TSLA":
            raise RuntimeError("yfinance blew up for TSLA")
        return 100.2  # NVDA in-band

    monkeypatch.setattr(main, "_fetch_yfinance_price", _flaky)

    posted: list[str] = []
    async def _capture(text):
        posted.append(text)
    monkeypatch.setattr(main, "_post_to_alerts_channel", _capture)

    # must not raise — the TSLA exception is swallowed inside the loop
    await main._check_youtube_level_alerts()

    assert len(posted) == 1
    assert "NVDA" in posted[0] and "🎯" in posted[0]
    assert await db.was_level_recently_alerted("NVDA", 100.0)
