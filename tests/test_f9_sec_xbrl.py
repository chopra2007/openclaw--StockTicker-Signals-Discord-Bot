"""F9 (#76 menu) — SEC XBRL fundamentals feed.

Covers:
  1. reuse: sec_xbrl imports sec_edgar's CIK resolver + UA (no second map).
  2. parse_fundamentals on a synthetic companyfacts payload — revenue-tag
     fallback, quarterly duration filter, YoY + margin math.
  3. embed: the 🏢 Fundamentals field appears ON and is ABSENT (byte-identical)
     when fundamentals is None.
"""
from __future__ import annotations

import inspect

from consensus_engine.scanners import sec_xbrl
from consensus_engine.alerts.all_command import embed as embed_mod


def test_reuses_sec_edgar_resolver_and_ua():
    src = inspect.getsource(sec_xbrl)
    assert "from consensus_engine.scanners.sec_edgar import" in src
    # the imported symbols are the shared resolver + UA, not a re-implementation
    assert sec_xbrl._get_cik.__module__ == "consensus_engine.scanners.sec_edgar"
    assert "OpenClaw" in sec_xbrl._USER_AGENT


def _pt(start, end, val, fy, fp, filed):
    return {"start": start, "end": end, "val": val, "fy": fy, "fp": fp, "filed": filed}


def _facts():
    # Filer reports revenue ONLY under RevenueFromContractWithCustomer* (the NVDA hazard):
    return {"facts": {"us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            _pt("2025-01-27", "2025-04-27", 44_000_000_000, 2027, "Q1", "2025-05-28"),  # ~90d
            _pt("2024-01-29", "2024-04-28", 26_000_000_000, 2026, "Q1", "2024-05-22"),  # prior-year Q1
        ]}},
        "NetIncomeLoss": {"units": {"USD": [
            _pt("2025-01-27", "2025-04-27", 18_775_000_000, 2027, "Q1", "2025-05-28"),
        ]}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": [
            _pt("2025-01-27", "2025-04-27", 0.76, 2027, "Q1", "2025-05-28"),
        ]}},
        "Assets": {"units": {"USD": [
            {"end": "2025-04-27", "val": 120_000_000_000, "filed": "2025-05-28"},  # instant (no start)
        ]}},
    }}}


def test_parse_revenue_tag_fallback_and_math():
    rows, tag = sec_xbrl.parse_fundamentals(_facts())
    assert tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
    latest = rows[0]
    assert latest["revenue"] == 44_000_000_000
    assert latest["fiscal_period"] == "2027 Q1"
    # YoY = (44 - 26) / 26 ≈ 0.692
    assert abs(latest["revenue_yoy"] - (44_000_000_000 - 26_000_000_000) / 26_000_000_000) < 1e-6
    # net margin = 18.775 / 44 ≈ 0.4267
    assert abs(latest["net_margin"] - 18_775_000_000 / 44_000_000_000) < 1e-6
    assert latest["assets"] == 120_000_000_000  # instantaneous matched on end date


def test_parse_annual_only_yields_no_quarters():
    # A 12-month duration is NOT a quarter -> filtered out.
    annual = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        _pt("2024-01-01", "2024-12-31", 100_000_000_000, 2024, "FY", "2025-02-01")]}}}}}
    rows, tag = sec_xbrl.parse_fundamentals(annual)
    assert rows == [] and tag is None


def test_format_line_plain_english():
    line = sec_xbrl.format_fundamentals_line({
        "fiscal_period": "2027 Q1", "revenue": 44_062_000_000, "revenue_yoy": 0.69,
        "net_margin": 0.426, "eps_diluted": 0.76})
    assert "Rev $44.1B" in line and "+69% YoY" in line and "net margin 43%" in line


class _Struct:
    def __init__(self):
        self.direction = "LONG"
        self.current_price = 100.0
        self.snapshot = None
        self.tweets_today = None

    def __getattr__(self, k):
        return None


def _build(fundamentals):
    from consensus_engine.models import ScoreBreakdown
    return embed_mod.build_embed(
        ticker="NVDA", structured=_Struct(), score_breakdown=ScoreBreakdown(base=30),
        narrative="", sources_used=[], cache_age_seconds=None, fundamentals=fundamentals)


def test_embed_field_present_when_on_absent_when_off():
    row = {"fiscal_period": "2027 Q1", "revenue": 44_062_000_000, "revenue_yoy": 0.69,
           "net_margin": 0.426, "eps_diluted": 0.76}
    on = _build(row)
    off = _build(None)
    on_names = [f["name"] for f in on["fields"]]
    off_names = [f["name"] for f in off["fields"]]
    assert "🏢 Fundamentals" in on_names
    assert "🏢 Fundamentals" not in off_names
    # OFF path is byte-identical to passing nothing at all
    assert off["fields"] == _build(None)["fields"]
