"""I5 (signal-features-2026-06-09) — graduate SEC by role + open-market $.

Today `sec_pts` is a flat +15 on any significant SEC filing. Behind
`features.sec_graduated_scoring.enabled` it becomes:
  +8   any Form-4 (the floor)
  +15  an open-market BUY > $250k
  +20  the same large buy by a canonical C-suite role (CEO/CFO/COO/President/PEO/PFO)

Mandatory safeguards asserted here:
  - 10b5-1 / plan-coded buy            -> capped at +8, NO negative branch
  - plan footnote ABSENT (unparseable) -> capped at +8 (cannot rule out a plan)
  - net selling (no qualifying buy)    -> WITHHOLDS the buy credit, never subtracts
  - unknown / Director role            -> +8, never +20
  - stale transaction date             -> demoted to the +8 floor
  - flag OFF                           -> flat +15 (byte-identical)

The 2-tuple `_run_sec_check` contract is unchanged; graduation rides on the
separate `_run_sec_graduation` helper, so all existing SEC mocks keep working.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine import config as cfg
from consensus_engine.cross_reference import (
    _canonicalize_sec_role,
    _graduate_sec_pts,
    _is_txn_recent,
    _run_sec_graduation,
    _SecGraduation,
    score_ticker,
)
from consensus_engine.utils.xref_cache import clear_xref_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_xref_cache()
    yield
    clear_xref_cache()


_RECENT = datetime.now(timezone.utc).strftime("%Y-%m-%d")
_STALE = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")

_FORM4_FILING = {
    "form": "4", "filing_date": _RECENT, "cik": "0000320193",
    "accession_number": "0000320193-26-000077", "primary_document": "form4.xml",
}


def _xml(*, title: str, code: str, shares: float, price: float,
         date: str, footnote: str | None) -> str:
    """Build a minimal Form-4 XML with one non-derivative transaction."""
    is_officer = "1" if title else "0"
    fn = (f"<footnotes><footnote id=\"F1\">{footnote}</footnote></footnotes>"
          if footnote is not None else "")
    return f"""<ownershipDocument>
      <reportingOwner><reportingOwnerId><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId>
        <reportingOwnerRelationship><isOfficer>{is_officer}</isOfficer>
          <officerTitle>{title}</officerTitle></reportingOwnerRelationship>
      </reportingOwner>
      <nonDerivativeTable><nonDerivativeTransaction>
        <transactionCoding><transactionCode>{code}</transactionCode></transactionCoding>
        <transactionAmounts>
          <transactionShares><value>{shares}</value></transactionShares>
          <transactionPricePerShare><value>{price}</value></transactionPricePerShare>
        </transactionAmounts>
        <transactionDate><value>{date}</value></transactionDate>
      </nonDerivativeTransaction></nonDerivativeTable>
      {fn}
    </ownershipDocument>"""


def _flag_on(monkeypatch):
    """Force ONLY features.sec_graduated_scoring.enabled ON; all else default."""
    real_get = cfg.get
    monkeypatch.setattr(
        cfg, "get",
        lambda k, d=None: True if k == "features.sec_graduated_scoring.enabled"
        else real_get(k, d),
    )


def _patch_sec(xml_str: str):
    """Patch the SEC fetch path used by both _run_sec_check and _run_sec_graduation."""
    return (
        patch("consensus_engine.scanners.sec_edgar.check_recent_filings",
              new=AsyncMock(return_value=[_FORM4_FILING])),
        patch("consensus_engine.scanners.sec_form4_cluster._fetch_form4_xml",
              new=AsyncMock(return_value=xml_str)),
        patch("consensus_engine.utils.rate_limiter.rate_limiter.acquire",
              new=AsyncMock(return_value=True)),
    )


# ── Layer 1: pure helpers ──────────────────────────────────────────────────

def test_role_canonicalization():
    for t in ("Chief Executive Officer", "CEO", "PEO", "Chief Financial Officer",
              "CFO", "PFO", "Chief Operating Officer", "COO", "President"):
        assert _canonicalize_sec_role(t) == "csuite", t
    for t in ("Director", "10% Owner", "Vice President", "VP of Sales", "", "Insider"):
        assert _canonicalize_sec_role(t) == "other", t


def test_recency_gate():
    assert _is_txn_recent(_RECENT, 5) is True
    assert _is_txn_recent(_STALE, 5) is False
    assert _is_txn_recent("", 5) is False          # missing -> stale
    assert _is_txn_recent("garbage", 5) is False   # unparseable -> stale


def test_graduate_tiers_pure():
    base = _SecGraduation(has_form4=True, max_buy_dollars=0.0,
                          reporter_role="other", plan_flag_seen=True)
    assert _graduate_sec_pts(base, 15) == 8                       # any Form-4

    large = _SecGraduation(has_form4=True, max_buy_dollars=300_000,
                           reporter_role="other", plan_flag_seen=True)
    assert _graduate_sec_pts(large, 15) == 15                     # >$250k buy

    csuite = _SecGraduation(has_form4=True, max_buy_dollars=10_000_000,
                            reporter_role="csuite", plan_flag_seen=True)
    assert _graduate_sec_pts(csuite, 15) == 20                    # C-suite buy

    planned = _SecGraduation(has_form4=True, max_buy_dollars=10_000_000,
                             reporter_role="csuite", is_planned=True,
                             plan_flag_seen=True)
    assert _graduate_sec_pts(planned, 15) == 8                    # 10b5-1 -> cap +8

    no_fn = _SecGraduation(has_form4=True, max_buy_dollars=10_000_000,
                           reporter_role="csuite", plan_flag_seen=False)
    assert _graduate_sec_pts(no_fn, 15) == 8                      # footnote absent -> +8

    sell = _SecGraduation(has_form4=True, max_buy_dollars=0.0,
                          reporter_role="other", net_selling=True,
                          plan_flag_seen=True)
    assert _graduate_sec_pts(sell, 15) == 8                       # withhold, never <8

    none = _SecGraduation(has_form4=False)
    assert _graduate_sec_pts(none, 0) == 0


# ── Layer 2: _run_sec_graduation parses real Form-4 XML ────────────────────

@pytest.mark.asyncio
async def test_graduation_parses_csuite_buy():
    xml_str = _xml(title="Chief Executive Officer", code="P", shares=20000,
                   price=50.0, date=_RECENT, footnote="Open-market purchase, personal funds.")
    p1, p2, p3 = _patch_sec(xml_str)
    with p1, p2, p3:
        grad = await _run_sec_graduation("AAPL")
    assert grad.has_form4 is True
    assert grad.reporter_role == "csuite"
    assert grad.max_buy_dollars == pytest.approx(1_000_000.0)
    assert grad.is_planned is False
    assert grad.plan_flag_seen is True
    assert grad.net_selling is False


@pytest.mark.asyncio
async def test_graduation_detects_net_selling():
    xml_str = _xml(title="Director", code="S", shares=5000, price=100.0,
                   date=_RECENT, footnote="Open-market sale.")
    p1, p2, p3 = _patch_sec(xml_str)
    with p1, p2, p3:
        grad = await _run_sec_graduation("AAPL")
    assert grad.has_form4 is True
    assert grad.max_buy_dollars == 0.0
    assert grad.net_selling is True


# ── Layer 3: full score_ticker path (flag ON) ─────────────────────────────

async def _sec_pts_via_score(ticker, xml_str) -> int:
    p1, p2, p3 = _patch_sec(xml_str)
    with p1, p2, p3, \
         patch("consensus_engine.cross_reference._run_news_cascade",
               new=AsyncMock(return_value=None)), \
         patch("consensus_engine.cross_reference._run_social_check",
               new=AsyncMock(return_value={})), \
         patch("consensus_engine.cross_reference._run_technical",
               new=AsyncMock(return_value=None)), \
         patch("consensus_engine.cross_reference._run_other_analysts",
               new=AsyncMock(return_value=[])), \
         patch("consensus_engine.cross_reference._run_options_check",
               new=AsyncMock(return_value=None)), \
         patch("consensus_engine.cross_reference._get_youtube_context",
               new=AsyncMock(return_value=None)), \
         patch("consensus_engine.cross_reference._run_llm_score",
               new=AsyncMock(return_value=(0.0, ""))):
        result = await score_ticker(ticker, base_score=0)
    return result.breakdown.sec_filing


@pytest.mark.asyncio
async def test_score_csuite_buy_is_20(monkeypatch):
    _flag_on(monkeypatch)
    xml_str = _xml(title="Chief Executive Officer", code="P", shares=20000,
                   price=50.0, date=_RECENT, footnote="Open-market purchase.")
    assert await _sec_pts_via_score("AAPL", xml_str) == 20


@pytest.mark.asyncio
async def test_score_director_award_is_8(monkeypatch):
    _flag_on(monkeypatch)
    # Award (code A) -> no open-market buy parsed -> Form-4 floor only.
    xml_str = _xml(title="Director", code="A", shares=1000, price=0.0,
                   date=_RECENT, footnote="Restricted stock award.")
    assert await _sec_pts_via_score("AAPL", xml_str) == 8


@pytest.mark.asyncio
async def test_score_plan_coded_buy_is_8_no_negative(monkeypatch):
    _flag_on(monkeypatch)
    xml_str = _xml(title="Chief Executive Officer", code="P", shares=20000,
                   price=50.0, date=_RECENT,
                   footnote="Transaction made under a Rule 10b5-1 trading plan.")
    pts = await _sec_pts_via_score("AAPL", xml_str)
    assert pts == 8          # capped, NOT +20
    assert pts >= 0          # never a negative branch


@pytest.mark.asyncio
async def test_score_net_sell_withholds_not_subtracts(monkeypatch):
    _flag_on(monkeypatch)
    xml_str = _xml(title="Chief Financial Officer", code="S", shares=5000,
                   price=100.0, date=_RECENT, footnote="Open-market sale.")
    pts = await _sec_pts_via_score("AAPL", xml_str)
    assert pts == 8          # buy credit withheld -> Form-4 floor
    assert pts >= 0          # never subtracts


@pytest.mark.asyncio
async def test_score_stale_csuite_buy_demoted_to_8(monkeypatch):
    _flag_on(monkeypatch)
    xml_str = _xml(title="Chief Executive Officer", code="P", shares=20000,
                   price=50.0, date=_STALE, footnote="Open-market purchase.")
    assert await _sec_pts_via_score("AAPL", xml_str) == 8   # recency gate demotes


# ── Layer 4: flag OFF is byte-identical (+15 flat) ─────────────────────────

@pytest.mark.asyncio
async def test_score_flag_off_is_flat_15():
    # No _flag_on -> conftest force-off keeps the feature dark.
    xml_str = _xml(title="Chief Executive Officer", code="P", shares=20000,
                   price=50.0, date=_RECENT, footnote="Open-market purchase.")
    assert await _sec_pts_via_score("AAPL", xml_str) == 15  # legacy flat +15
