"""Vision go-live smoke test (item F, deep-dive-2026-06-08).

NOT part of the routine suite (marked `smoke`, excluded by pytest.ini addopts). The
flag-flip gate in session_close.sh runs ONLY this, ONLY when wolf.vision.enabled is flipped
OFF->ON — it feeds a REAL saved Wolf chart through item A's actual retry/rotation path and
asserts >=1 level. Last session's vision false-done flipped the flag with the chain returning
zero levels; this is the check that would have blocked that push.

It hits the live OpenRouter vision pool on purpose (the only honest "does it really read a
chart" check). It fails — and blocks the push — if the free pool can't produce a level after
the real per-chart retry budget, which is the correct outcome when vision isn't reliable yet.
"""
from pathlib import Path

import pytest

_CHART = Path(__file__).resolve().parent.parent / "fixtures" / "charts" / "nq_5m.jpg"


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_vision_reads_a_real_chart():
    from consensus_engine.analysis import wolf_vision

    assert _CHART.exists(), f"missing chart fixture {_CHART}"
    data = _CHART.read_bytes()
    # Full retry/rotation path (item A) against the live free-vision pool.
    parsed = await wolf_vision._call_vision_image(data, "image/jpeg", chart_hash="smoke")
    assert parsed is not None, "vision chain returned nothing — all pool models failed"
    validated = wolf_vision._validate(parsed)
    assert len(validated["levels"]) >= 1 or validated["instrument"], (
        "vision read produced zero levels AND no instrument — feature does not meet its goal"
    )
