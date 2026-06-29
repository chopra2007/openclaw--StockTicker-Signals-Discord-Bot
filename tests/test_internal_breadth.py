"""F5 internal-breadth oscillator tests (TDD: written before the impl was wired in).

The oscillator is a DESCRIPTIVE market-context read built from the bot's OWN
directional stream (``signal_events.direction`` from INFORMED sources). It is NOT
a buy/sell signal, has NO gate, and changes NO alert. These tests cover, on a
deterministic synthetic ``signal_events`` fixture with known long/short/neutral
counts over dates:

  * net = distinct bullish - distinct bearish tickers over the rolling window,
    with the same ticker on two days inside the window counted ONCE (distinct);
  * neutral direction, raw ApeWisdom, and Form-4 rows are EXCLUDED;
  * epoch-1970 garbage rows are dropped;
  * EMA smoothing + expanding-window z-score match a hand computation;
  * point-in-time: the value on the full rows == the value on the prefix-to-date
    (no look-ahead);
  * lookup_internal_breadth reads the persisted table and cold-starts on
    flag-off / stale / missing, and always carries the long-bias note;
  * compute_and_persist writes one internal_breadth_daily row from signal_events.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

import pytest

from consensus_engine.analysis import internal_breadth as ib


# ---------------------------------------------------------------------------
# Synthetic signal_events fixture
# ---------------------------------------------------------------------------

def _epoch(date_str: str) -> float:
    """Noon-UTC unix epoch for a YYYY-MM-DD string (so the UTC date is unambiguous)."""
    y, m, d = (int(x) for x in date_str.split("-"))
    return datetime(y, m, d, 12, 0, 0, tzinfo=timezone.utc).timestamp()


def _row(ticker, direction, date_str, source_type="twitter", recorded_at=None):
    return {
        "ticker": ticker,
        "direction": direction,
        "source_type": source_type,
        "recorded_at": recorded_at if recorded_at is not None else _epoch(date_str),
    }


# Three trading dates. Distinct-across-window is exercised on D2 (AAPL appears on
# both D1 and D2 → counts once when window spans both).
D1, D2, D3 = "2024-03-01", "2024-03-02", "2024-03-03"

_BASE_ROWS = [
    # D1: bull {AAPL, MSFT}, bear {TSLA}
    _row("AAPL", "long", D1),
    _row("MSFT", "long", D1),
    _row("TSLA", "short", D1),
    # D2: bull {AAPL (again), NVDA}, bear {GOOG}
    _row("AAPL", "long", D2),
    _row("NVDA", "long", D2),
    _row("GOOG", "short", D2),
    # D3: bull {AMZN}; everything else here must be EXCLUDED
    _row("AMZN", "long", D3),
    _row("META", "neutral", D3),                       # neutral -> excluded
    _row("SPY", "long", D3, source_type="apewisdom"),  # ApeWisdom -> excluded
    _row("XOM", "short", D3, source_type="form4"),     # Form-4 -> excluded
    _row("AAA", "long", D3, recorded_at=100.0),        # epoch-1970 garbage -> dropped
]


def _by_date(series):
    return {r["date_utc"]: r for r in series}


# ---------------------------------------------------------------------------
# 1. net / distinct / exclusions (window=2)
# ---------------------------------------------------------------------------

def test_net_distinct_and_exclusions_window2():
    series = ib.compute_internal_breadth(_BASE_ROWS, window=2, ema_alpha=0.5)
    by = _by_date(series)

    # No 1970 bucket from the garbage row.
    assert all(not d.startswith("1970") for d in by)
    assert set(by) == {D1, D2, D3}

    # D1 window=[D1]
    assert by[D1]["n_bullish"] == 2   # AAPL, MSFT
    assert by[D1]["n_bearish"] == 1   # TSLA
    assert by[D1]["net_bull_bear"] == 1
    assert by[D1]["n_signals"] == 3

    # D2 window=[D1,D2]: AAPL distinct across days -> counted once
    assert by[D2]["n_bullish"] == 3   # {AAPL, MSFT, NVDA}
    assert by[D2]["n_bearish"] == 2   # {TSLA, GOOG}
    assert by[D2]["net_bull_bear"] == 1
    assert by[D2]["n_signals"] == 6

    # D3 window=[D2,D3]: neutral/apewisdom/form4/garbage all excluded
    assert by[D3]["n_bullish"] == 3   # {AAPL, NVDA, AMZN}
    assert by[D3]["n_bearish"] == 1   # {GOOG}
    assert by[D3]["net_bull_bear"] == 2
    assert by[D3]["n_signals"] == 4   # D2's 3 informed + AMZN only


def test_neutral_and_noise_only_yields_no_series():
    rows = [
        _row("META", "neutral", D1),
        _row("SPY", "long", D1, source_type="apewisdom"),
        _row("XOM", "short", D1, source_type="form4"),
        _row("AAA", "long", D1, recorded_at=100.0),
    ]
    assert ib.compute_internal_breadth(rows, window=2, ema_alpha=0.5) == []


# ---------------------------------------------------------------------------
# 2. EMA + expanding z-score match a hand computation (window=2, alpha=0.5)
# ---------------------------------------------------------------------------

def test_ema_and_zscore_hand_check():
    series = ib.compute_internal_breadth(_BASE_ROWS, window=2, ema_alpha=0.5)
    by = _by_date(series)

    # net series oldest->newest = [1, 1, 2]; ema(0.5) = [1, 1, 1.5]
    # z is the population z of the latest ema within the expanding ema window.
    assert by[D1]["osc_z"] == pytest.approx(0.0)   # single point
    assert by[D2]["osc_z"] == pytest.approx(0.0)   # [1,1] -> zero variance

    ema = [1.0, 1.0, 1.5]
    mean = sum(ema) / 3
    var = sum((x - mean) ** 2 for x in ema) / 3
    expected_z = (ema[-1] - mean) / math.sqrt(var)
    assert by[D3]["osc_z"] == pytest.approx(expected_z)
    assert expected_z == pytest.approx(math.sqrt(2), abs=1e-6)


# ---------------------------------------------------------------------------
# 3. point-in-time: value on full rows == value on prefix-to-date
# ---------------------------------------------------------------------------

def test_point_in_time_truncation():
    full = _by_date(ib.compute_internal_breadth(_BASE_ROWS, window=2, ema_alpha=0.5))
    # Prefix = only D1 + D2 rows (drop everything dated D3).
    prefix_rows = [r for r in _BASE_ROWS if r["recorded_at"] != 100.0
                   and r["recorded_at"] < _epoch(D3)]
    prefix = _by_date(ib.compute_internal_breadth(prefix_rows, window=2, ema_alpha=0.5))

    for d in (D1, D2):
        for field in ("net_bull_bear", "n_bullish", "n_bearish", "n_signals", "osc_z"):
            assert prefix[d][field] == pytest.approx(full[d][field]), (d, field)


# ---------------------------------------------------------------------------
# 4. lookup_internal_breadth: persisted read + cold starts + long-bias note
# ---------------------------------------------------------------------------

@pytest.fixture
async def tmp_db(tmp_path, monkeypatch):
    from consensus_engine import db
    prev = db.DB_PATH
    db.DB_PATH = str(tmp_path / "breadth.db")
    await db.init_db()
    try:
        yield db
    finally:
        await db.close_db()
        db.DB_PATH = prev


def _enable_flag(monkeypatch, enabled=True):
    prev = ib.cfg.get

    def _patched(key, default=None):
        if key == "features.internal_breadth.enabled":
            return enabled
        return prev(key, default)

    monkeypatch.setattr(ib.cfg, "get", _patched)


async def _insert_breadth_row(db, *, date_utc="2024-03-03", net=2, n_bull=3,
                              n_bear=1, osc_z=1.41, n_signals=4, computed_at=None):
    conn = await db.get_db()
    await conn.execute(
        """INSERT OR REPLACE INTO internal_breadth_daily
           (date_utc, net_bull_bear, n_bullish, n_bearish, osc_z, n_signals, computed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (date_utc, net, n_bull, n_bear, osc_z, n_signals,
         computed_at if computed_at is not None else time.time()),
    )
    await conn.commit()


async def test_lookup_reads_fresh_row(tmp_db, monkeypatch):
    _enable_flag(monkeypatch, True)
    await _insert_breadth_row(tmp_db)
    ctx = await ib.lookup_internal_breadth()
    assert ctx.cold_start is False
    assert ctx.as_of_date == "2024-03-03"
    assert ctx.net_bull_bear == 2
    assert ctx.n_bullish == 3
    assert ctx.n_bearish == 1
    assert ctx.osc_z == pytest.approx(1.41)
    assert ctx.long_bias_note  # always carries the structural long-bias caveat


async def test_lookup_cold_start_when_flag_off(tmp_db, monkeypatch):
    _enable_flag(monkeypatch, False)
    await _insert_breadth_row(tmp_db)
    ctx = await ib.lookup_internal_breadth()
    assert ctx.cold_start is True
    assert ctx.long_bias_note


async def test_lookup_cold_start_when_stale(tmp_db, monkeypatch):
    _enable_flag(monkeypatch, True)
    await _insert_breadth_row(tmp_db, computed_at=time.time() - 10 * 86400)
    ctx = await ib.lookup_internal_breadth()
    assert ctx.cold_start is True


async def test_lookup_cold_start_when_missing(tmp_db, monkeypatch):
    _enable_flag(monkeypatch, True)
    ctx = await ib.lookup_internal_breadth()
    assert ctx.cold_start is True


# ---------------------------------------------------------------------------
# 5. compute_and_persist writes one internal_breadth_daily row (forward-collect)
# ---------------------------------------------------------------------------

async def test_compute_and_persist_writes_row(tmp_db, monkeypatch):
    # forward-collect runs even with the flag OFF; seed today's informed signals.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = await tmp_db.get_db()
    now = time.time()
    for tk, dr, src in [("AAPL", "long", "twitter"), ("MSFT", "long", "twitter"),
                        ("TSLA", "short", "twitter"),
                        ("META", "neutral", "twitter"),          # excluded
                        ("SPY", "long", "apewisdom")]:           # excluded
        await conn.execute(
            """INSERT INTO signal_events (source_type, ticker, direction, recorded_at)
               VALUES (?, ?, ?, ?)""",
            (src, tk, dr, now),
        )
    await conn.commit()

    last = await ib.compute_and_persist()
    assert last is not None
    assert last["date_utc"] == today
    assert last["net_bull_bear"] == 1   # bull {AAPL,MSFT}=2 - bear {TSLA}=1
    assert last["n_bullish"] == 2
    assert last["n_bearish"] == 1
    assert last["n_signals"] == 3       # neutral + apewisdom excluded

    from consensus_engine.analysis import market_panel
    row = await market_panel.get_latest_row("internal_breadth_daily")
    assert row is not None
    assert row["date_utc"] == today
    assert row["net_bull_bear"] == 1
    assert row["n_bullish"] == 2
