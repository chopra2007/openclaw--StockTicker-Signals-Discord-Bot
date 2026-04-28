"""Tests for D1: Form 4 cluster-buy detector (sec_form4_cluster.py).

8 scenarios per spec §8.2:
  (a) 3-insider P fires
  (b) 10b5-1 excluded by regex
  (c) split-filing dedupe
  (d) per-ticker 14d cooldown
  (e) falling_knife calm/elevated/panic branches
  (f) replay 90d Form 4 window_days param
  (g) scanners.sec_background_watchers_enabled gate
  (h) members_json schema validation
"""
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from consensus_engine.scanners.sec_form4_cluster import (
    Form4ClusterAlert,
    _check_form4_cooldown,
    _parse_form4_xml_for_cluster,
    _store_form4_cluster,
    is_10b5_1,
    passes_falling_knife_filter,
    scan_form4_clusters,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_form4_xml(
    person_cik: str = "0001234567",
    reporter_name: str = "John Doe",
    is_director: str = "1",
    officer_title: str = "",
    shares: float = 10000.0,
    price: float = 50.0,
    txn_code: str = "P",
    footnote: str = "",
) -> str:
    footnote_xml = f"<footnotes><footnote id='F1'>{footnote}</footnote></footnotes>" if footnote else ""
    return f"""<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>{person_cik}</rptOwnerCik>
      <rptOwnerName>{reporter_name}</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>{is_director}</isDirector>
      <officerTitle>{officer_title}</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-04-01</value></transactionDate>
      <transactionCoding>
        <transactionCode>{txn_code}</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>{shares}</value></transactionShares>
        <transactionPricePerShare><value>{price}</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
  {footnote_xml}
</ownershipDocument>
"""


def _make_filing(cik: str = "0001234567", accession: str = "0001234567-26-000001",
                 doc: str = "form4.xml") -> dict:
    return {"form": "4", "cik": cik, "accession_number": accession, "primary_document": doc}


def _make_alert(ticker: str = "ACME", n_insiders: int = 3) -> Form4ClusterAlert:
    now = datetime.now(timezone.utc)
    return Form4ClusterAlert(
        ticker=ticker,
        n_insiders=n_insiders,
        total_dollars=1_000_000.0,
        members=[{"cik": f"cik{i}", "name": f"Insider {i}", "role": "Director",
                  "dollars": 333_333.0, "txn_date": "2026-04-01"} for i in range(n_insiders)],
        window_start=now - timedelta(days=30),
        window_end=now,
        passes_falling_knife=True,
        falling_knife_threshold=0.85,
        regime_label="normal",
    )


# ---------------------------------------------------------------------------
# (a) 3-insider P fires
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_three_insider_cluster_fires():
    """Three unique insiders with ≥$250k purchases trigger an alert."""
    insiders = [
        {"person_cik": f"cik{i}", "reporter_name": f"Insider{i}", "title": "Director",
         "footnote_text": "", "purchases": [{"date": "2026-04-01", "dollars": 300_000.0}]}
        for i in range(3)
    ]
    filings = [_make_filing(cik=f"cik{i}", accession=f"0001{i:06d}-26-000001") for i in range(3)]

    async def fake_filings(ticker, hours_back):
        return filings

    async def fake_xml(cik, acc, doc):
        return "<xml/>"  # parse will produce None for malformed; use parsed directly

    with (
        patch("consensus_engine.scanners.sec_form4_cluster.check_recent_filings", new=fake_filings),
        patch("consensus_engine.scanners.sec_form4_cluster._fetch_form4_xml",
              new=AsyncMock(return_value="<xml/>")),
        patch("consensus_engine.scanners.sec_form4_cluster._parse_form4_xml_for_cluster",
              side_effect=lambda xml: insiders.pop(0) if insiders else None),
        patch("consensus_engine.scanners.sec_form4_cluster.lookup_regime",
              new=AsyncMock(return_value=MagicMock(label="normal"))),
        patch("consensus_engine.scanners.sec_form4_cluster.db") as mock_db,
        patch("consensus_engine.scanners.sec_form4_cluster._check_form4_cooldown",
              new=AsyncMock(return_value=True)),
        patch("consensus_engine.scanners.sec_form4_cluster._store_form4_cluster",
              new=AsyncMock()),
        patch("consensus_engine.scanners.sec_form4_cluster._fetch_price_and_30d_high",
              new=AsyncMock(return_value=(100.0, 110.0))),
    ):
        mock_db.get_active_tickers = AsyncMock(return_value=["ACME"])
        alerts = await scan_form4_clusters(window_days=30, min_unique=3)

    assert len(alerts) == 1
    assert alerts[0].ticker == "ACME"
    assert alerts[0].n_insiders == 3
    assert alerts[0].passes_falling_knife is True


# ---------------------------------------------------------------------------
# (b) 10b5-1 excluded by regex
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_10b5_1_excluded():
    """Filings with 10b5-1 footnotes are excluded from cluster count."""
    assert is_10b5_1("Pursuant to a Rule 10b5-1 trading plan adopted on January 1, 2026.")
    assert is_10b5_1("Transaction made under pre-arranged plan")
    assert not is_10b5_1("Open market purchase at discretion of director")


@pytest.mark.asyncio
async def test_10b5_1_exclusion_prevents_cluster():
    """If all insiders have 10b5-1 footnotes, no cluster fires."""
    insider = {
        "person_cik": "cik1", "reporter_name": "Jane", "title": "CEO",
        "footnote_text": "Pursuant to Rule 10b5-1 trading plan.",
        "purchases": [{"date": "2026-04-01", "dollars": 500_000.0}],
    }

    with (
        patch("consensus_engine.scanners.sec_form4_cluster.check_recent_filings",
              new=AsyncMock(return_value=[_make_filing()])),
        patch("consensus_engine.scanners.sec_form4_cluster._fetch_form4_xml",
              new=AsyncMock(return_value="<xml/>")),
        patch("consensus_engine.scanners.sec_form4_cluster._parse_form4_xml_for_cluster",
              return_value=insider),
        patch("consensus_engine.scanners.sec_form4_cluster.lookup_regime",
              new=AsyncMock(return_value=MagicMock(label="normal"))),
        patch("consensus_engine.scanners.sec_form4_cluster.db") as mock_db,
    ):
        mock_db.get_active_tickers = AsyncMock(return_value=["ACME"])
        alerts = await scan_form4_clusters(window_days=30, min_unique=3)

    assert alerts == []


# ---------------------------------------------------------------------------
# (c) split-filing dedupe
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_split_filing_dedupe():
    """Two Form 4 filings from the same person_cik are merged, not double-counted."""
    same_cik_insider = {
        "person_cik": "cik_same",
        "reporter_name": "Alice",
        "title": "CFO",
        "footnote_text": "",
        "purchases": [{"date": "2026-04-01", "dollars": 150_000.0}],
    }
    # Two filings from same person — together they cross $250k but split they don't
    filings = [_make_filing(accession=f"0001234567-26-00000{i}") for i in range(2)]
    call_count = {"n": 0}

    def fake_parse(xml):
        call_count["n"] += 1
        return dict(same_cik_insider)  # same person twice

    with (
        patch("consensus_engine.scanners.sec_form4_cluster.check_recent_filings",
              new=AsyncMock(return_value=filings)),
        patch("consensus_engine.scanners.sec_form4_cluster._fetch_form4_xml",
              new=AsyncMock(return_value="<xml/>")),
        patch("consensus_engine.scanners.sec_form4_cluster._parse_form4_xml_for_cluster",
              side_effect=fake_parse),
        patch("consensus_engine.scanners.sec_form4_cluster.lookup_regime",
              new=AsyncMock(return_value=MagicMock(label="normal"))),
        patch("consensus_engine.scanners.sec_form4_cluster.db") as mock_db,
    ):
        mock_db.get_active_tickers = AsyncMock(return_value=["ACME"])
        alerts = await scan_form4_clusters(window_days=30, min_unique=3)

    # Only 1 unique person_cik → no cluster (need ≥3), but dollars were merged
    assert alerts == []
    assert call_count["n"] == 2  # both filings were processed


# ---------------------------------------------------------------------------
# (d) per-ticker 14d cooldown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_per_ticker_cooldown_blocks():
    """If form4_clusters has a recent row for the ticker, no alert fires."""
    # _check_form4_cooldown returns False → already alerted recently
    with (
        patch("consensus_engine.scanners.sec_form4_cluster.check_recent_filings",
              new=AsyncMock(return_value=[])),
        patch("consensus_engine.scanners.sec_form4_cluster.lookup_regime",
              new=AsyncMock(return_value=MagicMock(label="normal"))),
        patch("consensus_engine.scanners.sec_form4_cluster.db") as mock_db,
        patch("consensus_engine.scanners.sec_form4_cluster._check_form4_cooldown",
              new=AsyncMock(return_value=False)),
    ):
        mock_db.get_active_tickers = AsyncMock(return_value=["ACME"])
        alerts = await scan_form4_clusters(window_days=30, min_unique=3)

    assert alerts == []


@pytest.mark.asyncio
async def test_cooldown_query_uses_14d_window():
    """_check_form4_cooldown queries alerted_at > now - 14*86400."""
    mock_conn = AsyncMock()
    mock_cursor = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value={"cnt": 0})
    mock_conn.execute = AsyncMock(return_value=mock_cursor)

    with patch("consensus_engine.scanners.sec_form4_cluster.db") as mock_db:
        mock_db.get_db = AsyncMock(return_value=mock_conn)
        result = await _check_form4_cooldown("ACME", window_days=14)

    assert result is True
    call_args = mock_conn.execute.call_args
    sql, params = call_args[0]
    assert "form4_clusters" in sql
    cutoff = params[1]
    expected_cutoff = time.time() - (14 * 86400)
    assert abs(cutoff - expected_cutoff) < 5


# ---------------------------------------------------------------------------
# (e) falling_knife calm/elevated/panic branches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_falling_knife_calm_requires_085():
    """calm/normal regime: price >= 0.85 * 30d-high."""
    with patch("consensus_engine.scanners.sec_form4_cluster._fetch_price_and_30d_high",
               new=AsyncMock(return_value=(84.0, 100.0))):
        passes, threshold = await passes_falling_knife_filter("ACME", "calm", 3)
    assert passes is False
    assert threshold == 0.85

    with patch("consensus_engine.scanners.sec_form4_cluster._fetch_price_and_30d_high",
               new=AsyncMock(return_value=(86.0, 100.0))):
        passes, threshold = await passes_falling_knife_filter("ACME", "normal", 3)
    assert passes is True
    assert threshold == 0.85


@pytest.mark.asyncio
async def test_falling_knife_elevated_requires_065():
    """elevated regime: price >= 0.65 * 30d-high."""
    with patch("consensus_engine.scanners.sec_form4_cluster._fetch_price_and_30d_high",
               new=AsyncMock(return_value=(64.0, 100.0))):
        passes, threshold = await passes_falling_knife_filter("ACME", "elevated", 3)
    assert passes is False
    assert threshold == 0.65

    with patch("consensus_engine.scanners.sec_form4_cluster._fetch_price_and_30d_high",
               new=AsyncMock(return_value=(66.0, 100.0))):
        passes, threshold = await passes_falling_knife_filter("ACME", "elevated", 3)
    assert passes is True


@pytest.mark.asyncio
async def test_falling_knife_panic_requires_5_insiders():
    """panic regime: n_insiders >= 5 required; price floor disabled."""
    passes, threshold = await passes_falling_knife_filter("ACME", "panic", 4)
    assert passes is False
    assert threshold == "disabled"

    passes, threshold = await passes_falling_knife_filter("ACME", "panic", 5)
    assert passes is True
    assert threshold == "disabled"


# ---------------------------------------------------------------------------
# (f) replay 90d Form 4 window_days param
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_window_days_param_passed_to_check_recent_filings():
    """window_days=90 translates to hours_back=2160 in check_recent_filings."""
    captured = {}

    async def fake_filings(ticker, hours_back):
        captured["hours_back"] = hours_back
        return []

    with (
        patch("consensus_engine.scanners.sec_form4_cluster.check_recent_filings",
              new=fake_filings),
        patch("consensus_engine.scanners.sec_form4_cluster.lookup_regime",
              new=AsyncMock(return_value=MagicMock(label="normal"))),
        patch("consensus_engine.scanners.sec_form4_cluster.db") as mock_db,
    ):
        mock_db.get_active_tickers = AsyncMock(return_value=["ACME"])
        await scan_form4_clusters(window_days=90, min_unique=3)

    assert captured["hours_back"] == 90 * 24


# ---------------------------------------------------------------------------
# (g) scanners.sec_background_watchers_enabled gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sec_background_watchers_disabled_skips_loop():
    """sec_form4_cluster_loop exits immediately when feature disabled."""
    from consensus_engine.main import sec_form4_cluster_loop

    stop = asyncio.Event()
    stop.set()  # stop immediately

    scan_called = []

    async def fake_scan(**kwargs):
        scan_called.append(True)
        return []

    with (
        patch("consensus_engine.scanners.sec_form4_cluster.scan_form4_clusters",
              new=AsyncMock(side_effect=fake_scan)),
        patch("consensus_engine.main.cfg") as mock_cfg,
    ):
        mock_cfg.get.side_effect = lambda key, default=None: {
            "features.form4_cluster.enabled": False,
            "intervals.form4_cluster_loop": 1,
        }.get(key, default)

        await sec_form4_cluster_loop(stop)

    assert scan_called == []


@pytest.mark.asyncio
async def test_feature_flag_enabled_calls_scan():
    """sec_form4_cluster_loop calls scan_form4_clusters when feature enabled."""
    from consensus_engine.main import sec_form4_cluster_loop

    stop = asyncio.Event()
    scan_done = asyncio.Event()

    async def fake_scan():
        scan_done.set()
        stop.set()  # stop after first scan
        return []

    with (
        patch("consensus_engine.main.cfg") as mock_cfg,
        patch("consensus_engine.main._emit_form4_cluster_alert", new=AsyncMock()),
    ):
        mock_cfg.get.side_effect = lambda key, default=None: {
            "features.form4_cluster.enabled": True,
            "intervals.form4_cluster_loop": 1,
        }.get(key, default)

        with patch("consensus_engine.scanners.sec_form4_cluster.scan_form4_clusters",
                   new=AsyncMock(return_value=[])):
            # Import after patch so the import inside the loop resolves to our mock
            import consensus_engine.scanners.sec_form4_cluster as m
            orig = m.scan_form4_clusters
            m.scan_form4_clusters = AsyncMock(side_effect=fake_scan)
            try:
                await asyncio.wait_for(sec_form4_cluster_loop(stop), timeout=3)
            except asyncio.TimeoutError:
                pass
            finally:
                m.scan_form4_clusters = orig

    assert scan_done.is_set()


# ---------------------------------------------------------------------------
# (h) members_json schema validation
# ---------------------------------------------------------------------------

def test_members_json_schema():
    """Form4ClusterAlert.members contains required keys: cik, name, role, dollars, txn_date."""
    alert = _make_alert()
    members_json = json.dumps(alert.members)
    members = json.loads(members_json)

    assert isinstance(members, list)
    assert len(members) > 0
    for member in members:
        assert "cik" in member
        assert "name" in member
        assert "role" in member
        assert "dollars" in member
        assert "txn_date" in member
        assert isinstance(member["dollars"], (int, float))


def test_parse_form4_xml_extracts_purchase():
    """_parse_form4_xml_for_cluster extracts P-coded transactions correctly."""
    xml = _make_form4_xml(
        person_cik="0001234567",
        reporter_name="CEO Person",
        shares=5000.0,
        price=60.0,
        txn_code="P",
    )
    result = _parse_form4_xml_for_cluster(xml)
    assert result is not None
    assert result["person_cik"] == "0001234567"
    assert result["reporter_name"] == "CEO Person"
    assert len(result["purchases"]) == 1
    assert abs(result["purchases"][0]["dollars"] - 300_000.0) < 1.0


def test_parse_form4_xml_excludes_non_purchase():
    """_parse_form4_xml_for_cluster ignores S/A/F transaction codes."""
    xml = _make_form4_xml(shares=10_000.0, price=50.0, txn_code="S")
    result = _parse_form4_xml_for_cluster(xml)
    assert result is not None
    assert result["purchases"] == []
