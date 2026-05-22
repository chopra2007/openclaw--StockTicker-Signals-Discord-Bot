"""#13 — SEC Form-4 insider detail in the !all evidence block."""
from __future__ import annotations

from consensus_engine.alerts.all_command import aggregator, output_filter
from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.models import ScoreBreakdown


def _tx(reporter, title, direction, shares, price, tx_type, date="2026-05-20"):
    return {
        "reporter_name": reporter, "title": title, "security": "Common Stock",
        "date": date, "shares": shares, "price": price,
        "direction": direction, "transaction_type": tx_type,
    }


_FILING = {
    "form": "4", "filing_date": "2026-05-20", "cik": "0000320193",
    "accession_number": "0000000001-26-000001", "primary_document": "f.xml",
}


def test_insider_section_shows_open_market_trade_in_full():
    """An open-market purchase renders with name, title, shares, and price."""
    txs = [_tx("SMITH JANE", "CEO", "Buy", 50000.0, 12.0, "Open Market Purchase")]
    joined = "\n".join(aggregator._format_insider_section([(_FILING, txs)]))
    assert "JANE SMITH" in joined          # _fmt_insider_name reverses LAST FIRST
    assert "CEO" in joined
    assert "50,000" in joined
    assert "$12.00" in joined
    # 50,000 x $12 = $600k clears the $100k buy floor -> NOTABLE.
    assert "NOTABLE" in joined


def test_insider_section_collapses_routine_filings():
    """Awards / option exercises are collapsed to a count, not detailed."""
    txs = [
        _tx("SMITH JANE", "CEO", "Buy", 50000.0, 12.0, "Open Market Purchase"),
        _tx("DOE JOHN", "Director", "Buy", 1000.0, 0.0, "Award/Grant"),
        _tx("DOE JOHN", "Director", "Buy", 500.0, 0.0, "Option Exercise"),
    ]
    joined = "\n".join(aggregator._format_insider_section([(_FILING, txs)]))
    assert "plus 2 routine" in joined
    assert "Award/Grant" not in joined     # routine rows are not detailed


def test_insider_section_routine_only_states_no_conviction_trades():
    """Form 4s that are entirely routine produce the defined empty-state line."""
    txs = [_tx("DOE JOHN", "Director", "Buy", 1000.0, 0.0, "Award/Grant")]
    lines = aggregator._format_insider_section([(_FILING, txs)])
    assert lines and "routine" in lines[0].lower()
    assert "NOTABLE" not in "\n".join(lines)


def test_insider_section_empty_when_no_transactions():
    """No fetched transactions -> empty list (block-level handles the state)."""
    assert aggregator._format_insider_section([]) == []
    assert aggregator._format_insider_section([(_FILING, [])]) == []


def test_sec_evidence_block_empty_states():
    """No filings -> 'No recent SEC filings'; non-Form-4 only -> no insider."""
    assert aggregator._format_sec_evidence_block([], [], False) == (
        "No recent SEC filings."
    )
    block = aggregator._format_sec_evidence_block(
        [{"form": "8-K", "filing_date": "2026-05-19"}], [], False,
    )
    assert "8-K" in block
    assert "No recent insider (Form 4) activity." in block


def test_sec_evidence_block_includes_insider_detail():
    """A filing set with an open-market trade surfaces the insider in the block."""
    txs = [_tx("SMITH JANE", "CEO", "Buy", 50000.0, 12.0, "Open Market Purchase")]
    block = aggregator._format_sec_evidence_block(
        [_FILING], [(_FILING, txs)], False,
    )
    assert "Recent SEC filings:" in block
    assert "JANE SMITH" in block
    assert "50,000" in block


def test_sec_evidence_block_partial_flag_noted():
    """A timed-out fetch with no rows is flagged as partial in the block."""
    block = aggregator._format_sec_evidence_block([_FILING], [], True)
    assert "timed out" in block.lower()


async def test_enrich_form4_insiders_no_filings():
    """No SEC filings -> empty-state block, partial False, never raises."""
    out = await aggregator._enrich_form4_insiders([], 12.0)
    assert out["partial"] is False
    assert out["block"] == "No recent SEC filings."


def test_render_data_only_fallback_appends_sec_block():
    """render_data_only_fallback appends the SEC evidence block when supplied,
    and is unchanged (two lines) when it is not."""
    s = StructuredFields(direction="BULLISH", confidence_label="HIGH")
    sb = ScoreBreakdown(news_catalyst=20)
    out = output_filter.render_data_only_fallback(
        s, sb, ["a"], sec_evidence_block="Insider X bought 1,000 shares.",
    )
    assert "Insider X bought 1,000 shares." in out
    assert "SEC insider activity" in out
    assert output_filter.render_data_only_fallback(s, sb, ["a"]).count("\n") == 1
