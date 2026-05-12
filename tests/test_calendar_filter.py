"""Tests for W1 A-T0 calendar-year-as-price filter."""
import pytest

from consensus_engine.analysis.calendar_filter import is_calendar_year_in_context


@pytest.mark.parametrize("price,snippet,ticker,expected", [
    # MSFT-$2024 leak: Gemini extracts 2024.0 from "Q2 of 2024" → reject
    (2024.0, "our number one draft pick for Q2 of 2024 is Microsoft", "MSFT", True),
    (2023.0, "fiscal 2023 revenue grew", "AAPL", True),
    (1999.0, "back in 1999 when this stock split", "INTC", True),
    (2025.0, "by 2025 the new product line", "TSLA", True),
    (2026.0, "in October 2026 earnings call", "GOOG", True),
    # Carve-out: high-priced ticker → allow (BRK.A trades ~$700k but tier list still passes)
    (2024.0, "Q2 of 2024", "BRK.A", False),
    (2024.0, "fiscal 2024", "NVR", False),
    # Asset-proximity backstop: current_price within 5% of price → allow
    (2024.0, "Q2 of 2024", "MSFT", False),  # with current_price=2000, 2024 is 1.2% away → allow
    # Out of year window → allow
    (180.0, "Q2 2024 numbers were", "MSFT", False),
    (1899.0, "Q2 1899", "X", False),
    (2101.0, "Q2 2101", "X", False),
    # Fractional price (real price) → allow even in window
    (2024.50, "Q2 of 2024", "MSFT", False),
    # No snippet → fall back to allow (conservative without context)
    (2024.0, None, "MSFT", False),
    (2024.0, "", "MSFT", False),
    # No calendar marker in snippet → allow
    (2024.0, "the price target is exactly two thousand twenty four dollars", "MSFT", False),
    # Non-numeric → allow (defensive)
    ("nope", "Q2 of 2024", "MSFT", False),
])
def test_is_calendar_year_in_context(price, snippet, ticker, expected):
    # Only pass current_price for the asset-proximity backstop row
    current_price = 2000.0 if ticker == "MSFT" and price == 2024.0 and snippet == "Q2 of 2024" else None
    # The first MSFT row (carve-out behavior expected True) uses no current_price
    if ticker == "MSFT" and price == 2024.0 and snippet and snippet.startswith("our number one"):
        current_price = None
    assert is_calendar_year_in_context(price, snippet, ticker, current_price=current_price) is expected


def test_msft_2024_state_json_row_201_repro():
    """Exact reproduction of the MSFT $2024 leak from state.json row 201."""
    snippet = "So our number one draft pick for Q2 of 2024 is Microsoft"
    assert is_calendar_year_in_context(2024.0, snippet, "MSFT") is True


def test_brk_a_in_year_window_allowed():
    """BRK.A class A trades ~$700k; we never see 2024 from BRK.A but the carve-out
    is a defensive backstop against future false-positives on truly high-priced tickers."""
    assert is_calendar_year_in_context(2024.0, "Q2 of 2024 BRK.A", "BRK.A") is False


def test_amd_679_class_not_caught_here():
    """A-T0 only handles year-range; AMD $679 anchors require the distance penalty (W3),
    not this filter. Confirming we don't accidentally over-reject."""
    assert is_calendar_year_in_context(679.0, "Q2 of 2024 AMD target", "AMD") is False
