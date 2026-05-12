"""Tests for Layer 4: price sanity gate."""
import pytest

from consensus_engine.analysis.price_sanity import check_price_plausible


@pytest.mark.parametrize("level,live,expected_ok,expected_reason", [
    # Hallucinated NVDA case
    (850.0, 145.0, False, "implausible_ratio"),
    # Identity
    (145.0, 145.0, True,  "ok"),
    # Within tolerance
    (180.0, 145.0, True,  "ok"),    # 1.24×
    (115.0, 145.0, True,  "ok"),    # ~0.79×
    # Edge of tolerance — fails (genuinely in gap between 1× upper=181.25 and 2× lower=217.5)
    (200.0, 145.0, False, "implausible_ratio"),  # 1.38× — gap between 1× and 2×
    # Stock split factors
    (290.0, 145.0, True,  "ok"),    # 2× split
    (14.5,  145.0, True,  "ok"),    # 1/10 — pre-split level
    (29.0,  145.0, True,  "ok"),    # 1/5 — pre-split
    (725.0, 145.0, True,  "ok"),    # 5× — post-split level seen in old video
    # Degenerate live price → fail-open
    (850.0, None,  True,  "no_live_price"),
    (850.0, 0.0,   True,  "no_live_price"),
    # Degenerate level price → fail
    (0.0,   145.0, False, "implausible_zero"),
    (-5.0,  145.0, False, "implausible_zero"),
])
def test_check_price_plausible(level, live, expected_ok, expected_reason):
    res = check_price_plausible(level, live)
    assert res.accepted is expected_ok
    assert res.reason == expected_reason


def test_real_nvda_incident_blocked():
    """The exact NVDA hallucination from vkqchQQnm88: 845-855 entry on a $145 stock."""
    for level in (845.0, 855.0, 820.0, 920.0):
        res = check_price_plausible(level, 145.0)
        assert res.accepted is False, f"level {level} should be blocked"


def test_year_range_fails_closed_when_spot_none():
    """W1: when live quote unavailable AND snippet has calendar marker AND price is
    integer year in (1900, 2100), fail-closed with 'no_live_price_year_range' so the
    MSFT-$2024 class doesn't leak through during Finnhub outages."""
    res = check_price_plausible(2024.0, None, source_snippet="Q2 of 2024")
    assert res.accepted is False
    assert res.reason == "no_live_price_year_range"


def test_year_range_fail_open_when_no_snippet():
    """Without snippet context, fall back to legacy fail-open on spot=None."""
    res = check_price_plausible(2024.0, None)
    assert res.accepted is True
    assert res.reason == "no_live_price"


def test_year_range_fail_open_without_calendar_marker():
    """Snippet present but no calendar marker → preserve fail-open."""
    res = check_price_plausible(2024.0, None, source_snippet="the price target is two thousand")
    assert res.accepted is True
    assert res.reason == "no_live_price"


def test_year_range_does_not_block_when_live_price_close():
    """If we have a live quote, the regular ratio check handles things —
    year-range branch only kicks in when live is None/0."""
    res = check_price_plausible(2024.0, 2000.0, source_snippet="Q2 of 2024")
    assert res.accepted is True
    assert res.reason == "ok"
