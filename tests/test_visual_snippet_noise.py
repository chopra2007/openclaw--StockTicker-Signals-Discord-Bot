"""B1: strip label noise from chart visual_evidence before the narrator sees it."""
from consensus_engine.alerts.all_command.aggregator import (
    _is_useful_visual_row,
    _build_yt_visual_snippets,
)


def _row(value, kind="label"):
    return {"value": value, "kind": kind, "channel_name": "Cheddar", "where_seen": "chart"}


def test_drops_title_cards_promo_codes_bare_tickers():
    assert not _is_useful_visual_row(_row("The Stock Market", "label"))   # title card
    assert not _is_useful_visual_row(_row("WICKED50", "label"))           # promo code
    assert not _is_useful_visual_row(_row("SAVE20", "other"))             # promo code
    assert not _is_useful_visual_row(_row("AAPL", "ticker"))              # bare ticker
    assert not _is_useful_visual_row(_row("Subscribe", "label"))         # digit-less label
    assert not _is_useful_visual_row(_row("", "price"))                   # empty


def test_keeps_prices_dates_and_numeric_annotations():
    assert _is_useful_visual_row(_row("381.61", "price"))
    assert _is_useful_visual_row(_row("61.8%", "label"))                  # fib level
    assert _is_useful_visual_row(_row("$52.9M premium", "other"))         # flow row
    assert _is_useful_visual_row(_row("gamma 13.3B", "label"))            # annotation
    assert _is_useful_visual_row(_row("2026-06-20", "date"))             # expiry


def test_snippets_render_only_useful_and_cap_at_15():
    rows = (
        [_row("The Stock Market", "label"), _row("WICKED50", "label"), _row("AAPL", "ticker")]
        + [_row(str(740 + i), "price") for i in range(20)]
    )
    out = _build_yt_visual_snippets(rows)
    assert len(out) == 15                       # capped, noise excluded from the cap
    assert all("chart shows" in s for s in out)
    assert not any("Stock Market" in s or "WICKED50" in s or "chart shows AAPL" in s for s in out)
