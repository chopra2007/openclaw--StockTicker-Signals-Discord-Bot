"""Tests for SEC EDGAR filing checker."""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from consensus_engine.scanners.sec_edgar import (
    check_recent_filings, classify_filing_significance, _get_cik,
)


def _make_submissions_response(forms, hours_ago_list):
    """Build a fake SEC submissions JSON with given forms and ages."""
    now = datetime.now(timezone.utc)
    filing_dates = []
    acceptance_times = []
    accession_numbers = []

    for i, (form, hours_ago) in enumerate(zip(forms, hours_ago_list)):
        dt = now - timedelta(hours=hours_ago)
        filing_dates.append(dt.strftime("%Y-%m-%d"))
        acceptance_times.append(dt.isoformat())
        accession_numbers.append(f"0000000001-24-{i:06d}")

    return {
        "cik": "0000320193",
        "entityType": "operating",
        "name": "APPLE INC",
        "tickers": ["AAPL"],
        "filings": {
            "recent": {
                "form": forms,
                "filingDate": filing_dates,
                "acceptanceDateTime": acceptance_times,
                "accessionNumber": accession_numbers,
            }
        },
    }


@pytest.mark.asyncio
async def test_classify_filing_8k():
    """8-K filings should be significant."""
    filings = [{"form": "8-K", "filing_date": "2026-03-26", "acceptance_datetime": "", "accession_number": ""}]
    significant, summary = classify_filing_significance(filings)
    assert significant is True
    assert "8-K" in summary
    assert "material event" in summary


@pytest.mark.asyncio
async def test_classify_filing_form4():
    """Form 4 (insider trading) should be significant."""
    filings = [
        {"form": "4", "filing_date": "2026-03-26", "acceptance_datetime": "", "accession_number": ""},
        {"form": "4", "filing_date": "2026-03-26", "acceptance_datetime": "", "accession_number": ""},
    ]
    significant, summary = classify_filing_significance(filings)
    assert significant is True
    assert "Form 4 x2" in summary


@pytest.mark.asyncio
async def test_classify_filing_empty():
    """No filings should not be significant."""
    significant, summary = classify_filing_significance([])
    assert significant is False
    assert summary == ""


@pytest.mark.asyncio
async def test_classify_multiple_forms():
    """Multiple form types should all appear in summary."""
    filings = [
        {"form": "8-K", "filing_date": "2026-03-26", "acceptance_datetime": "", "accession_number": ""},
        {"form": "10-Q", "filing_date": "2026-03-25", "acceptance_datetime": "", "accession_number": ""},
        {"form": "4", "filing_date": "2026-03-25", "acceptance_datetime": "", "accession_number": ""},
    ]
    significant, summary = classify_filing_significance(filings)
    assert significant is True
    assert "8-K" in summary
    assert "10-Q" in summary
    assert "Form 4" in summary


@pytest.mark.asyncio
async def test_check_recent_filings_filters_old():
    """Only filings within hours_back should be returned."""
    # 8-K filed 12h ago (should match), 10-Q filed 72h ago (should not)
    response = _make_submissions_response(["8-K", "10-Q"], [12, 72])

    import consensus_engine.scanners.sec_edgar as sec_mod
    sec_mod._ticker_to_cik = {"TEST": "0000000001"}

    with patch("consensus_engine.scanners.sec_edgar.rate_limiter") as mock_rl:
        mock_rl.acquire = AsyncMock(return_value=True)
        mock_rl.report_success = MagicMock()

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=response)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("consensus_engine.scanners.sec_edgar.get_session",
                   new_callable=AsyncMock, return_value=mock_session):
            results = await check_recent_filings("TEST", hours_back=48)

    assert len(results) == 1
    assert results[0]["form"] == "8-K"


@pytest.mark.asyncio
async def test_ticker_map_retries_once_and_recovers(monkeypatch):
    import consensus_engine.scanners.sec_edgar as sec_mod

    sec_mod._ticker_to_cik = {}
    sec_mod._ticker_map_retry_after = 0.0

    failed = MagicMock()
    failed.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
    failed.__aexit__ = AsyncMock(return_value=False)

    recovered_resp = AsyncMock()
    recovered_resp.status = 200
    recovered_resp.json = AsyncMock(return_value={
        "0": {"ticker": "TEST", "cik_str": 1},
    })
    recovered = MagicMock()
    recovered.__aenter__ = AsyncMock(return_value=recovered_resp)
    recovered.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get = MagicMock(side_effect=[failed, recovered])
    sleep = AsyncMock()
    report = AsyncMock()
    monkeypatch.setattr(sec_mod, "get_session", AsyncMock(return_value=session))
    monkeypatch.setattr(sec_mod.asyncio, "sleep", sleep)
    monkeypatch.setattr(sec_mod.rate_limiter, "report_success", MagicMock())
    monkeypatch.setattr("consensus_engine.alerts.ops_alert.report_ops_state", report)

    assert await sec_mod._load_ticker_map() is True
    assert sec_mod._ticker_to_cik == {"TEST": "0000000001"}
    assert session.get.call_count == 2
    sleep.assert_awaited_once_with(1.0)
    report.assert_awaited_once()
    assert report.await_args.kwargs["down"] is False


@pytest.mark.asyncio
async def test_ticker_map_reports_outage_after_all_retries_fail(monkeypatch):
    import consensus_engine.scanners.sec_edgar as sec_mod

    sec_mod._ticker_to_cik = {}
    sec_mod._ticker_map_retry_after = 0.0

    failed = MagicMock()
    failed.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
    failed.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=failed)
    report = AsyncMock()
    failure = MagicMock()
    monkeypatch.setattr(sec_mod, "get_session", AsyncMock(return_value=session))
    monkeypatch.setattr(sec_mod.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(sec_mod.rate_limiter, "report_failure", failure)
    monkeypatch.setattr("consensus_engine.alerts.ops_alert.report_ops_state", report)

    assert await sec_mod._load_ticker_map() is False
    assert session.get.call_count == 3
    failure.assert_called_once_with("sec_edgar")
    report.assert_awaited_once()
    assert report.await_args.kwargs["down"] is True
