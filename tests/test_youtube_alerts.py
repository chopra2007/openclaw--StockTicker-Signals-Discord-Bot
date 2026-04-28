"""Integration tests for Layer 4: price sanity gate in alert pipeline."""
import pytest

from consensus_engine.models import (
    CandidateSignal, CandidateSetup, Direction, Conviction,
)


@pytest.mark.asyncio
async def test_price_sanity_blocks_nvda_850(monkeypatch):
    """Layer 4 integration: alert is not sent when price level deviates >25% from any split factor."""
    from consensus_engine.scanners import youtube as scanner

    sig = CandidateSignal(
        ticker="NVDA", direction=Direction.LONG, conviction=Conviction.HIGH,
        mention_count=1, classifier_confidence=0.9, evidence_span_ids=[],
        context="",
    )
    setup = CandidateSetup(
        ticker="NVDA", entry_low=850.0, entry_high=855.0,
        stop=820.0, targets=[920.0],
        timeframe="swing", setup_type="breakout", context="",
        evidence_span_ids=[], classifier_confidence=0.9,
        catalyst_date=None, catalyst_desc=None,
    )

    sent_messages = []

    async def _stub_send(msg):
        sent_messages.append(msg)

    monkeypatch.setattr(scanner, "_send_youtube_alert", _stub_send)

    async def _stub_live_price(ticker):
        return 145.0  # Real NVDA price during incident

    monkeypatch.setattr(scanner, "_safe_live_price", _stub_live_price)

    await scanner._send_two_stage_alerts(
        display_name="TestChannel",
        signals=[sig], levels=[], setups=[setup], catalysts=[],
        bundle_spans=[], min_confidence=0.5, require_verified=False,
    )

    assert sent_messages == []
    assert sig.suppressed is True
    assert sig.suppression_reason == "price_sanity"
