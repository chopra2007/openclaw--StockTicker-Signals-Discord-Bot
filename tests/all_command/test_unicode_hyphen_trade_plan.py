"""The narrator model sometimes writes U+2011 (non-breaking hyphen) instead of "-".

Live !all NVDA 2026-10-05: the Trade Plan row came back as "Stop‑Loss", so the
SL line vanished from the card, and "; high‑vol data unavailable" slipped past
the apology scrub.
"""
from consensus_engine.alerts.all_command.embed import _reformat_trade_plan
from consensus_engine.alerts.all_command.output_filter import _scrub_internal_tags


def test_stop_loss_row_with_unicode_hyphen_keeps_sl_line():
    narrative = (
        "## Trade Plan\n"
        "| Parameter | Level |\n"
        "|---|---|\n"
        "| Buy Zone | $237.69 – $238.90 |\n"
        "| Stop‑Loss | $229.32 |\n"
        "| TP1 | $260.00 |\n"
    )
    out = _reformat_trade_plan(narrative)
    assert "**SL:** $229.32" in out


def test_high_vol_apology_with_unicode_hyphen_is_scrubbed():
    out = _scrub_internal_tags("±$9 / 6d (0.7×ATR×√6; high‑vol data unavailable)")
    assert "unavailable" not in out
    assert "0.7×ATR×√6)" in out
