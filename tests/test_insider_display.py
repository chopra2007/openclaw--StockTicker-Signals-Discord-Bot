"""Shared insider (Form 4) display renderer — aggregation + formatting."""
from __future__ import annotations

from consensus_engine.alerts import insider_display as ins


def _tx(reporter, title, direction, shares, price, tx_type,
        date="2026-06-26", security="Common Stock"):
    return {
        "reporter_name": reporter, "title": title, "security": security,
        "date": date, "shares": shares, "price": price,
        "direction": direction, "transaction_type": tx_type,
    }


# ── aggregation ────────────────────────────────────────────────────────────

def test_many_fills_collapse_to_one_block():
    """49 open-market fills of one insider on one day -> a single summary."""
    fills = [_tx("Mehrotra Sanjay", "President and CEO", "Sell", 1000.0, 100.0,
                 "Open Market Sale") for _ in range(49)]
    summaries, routine = ins.aggregate_insiders(fills)
    assert routine == 0
    assert len(summaries) == 1
    s = summaries[0]
    assert s.name == "Sanjay Mehrotra"      # LAST FIRST -> First Last
    assert s.role == "CEO"
    assert s.direction == "Sell"
    assert s.shares == 49000.0
    assert s.value == 49000.0 * 100.0
    assert s.avg_price == 100.0
    assert s.n_fills == 49


def test_routine_transactions_are_counted_not_listed():
    """Awards / option exercises are excluded from blocks and counted."""
    txs = [
        _tx("Smith Jane", "CEO", "Buy", 5000.0, 12.0, "Open Market Purchase"),
        _tx("Doe John", "Director", "Buy", 1000.0, 0.0, "Award/Grant"),
        _tx("Doe John", "Director", "Sell", 500.0, 0.0, "Option Exercise"),
        _tx("Doe John", "Director", "Sell", 200.0, 0.0, "Tax Withholding"),
    ]
    summaries, routine = ins.aggregate_insiders(txs)
    assert routine == 3
    assert len(summaries) == 1
    assert summaries[0].name == "Jane Smith"


def test_buys_and_sells_same_insider_same_day_split():
    """A buy and a sell by one insider on one day are two separate blocks."""
    txs = [
        _tx("Doe Jane", "CFO", "Buy", 1000.0, 50.0, "Open Market Purchase"),
        _tx("Doe Jane", "CFO", "Sell", 2000.0, 55.0, "Open Market Sale"),
    ]
    summaries, routine = ins.aggregate_insiders(txs)
    assert routine == 0
    assert {s.direction for s in summaries} == {"Buy", "Sell"}
    assert len(summaries) == 2


def test_same_insider_different_dates_split():
    txs = [
        _tx("Doe Jane", "CFO", "Sell", 1000.0, 50.0, "Open Market Sale", date="2026-06-25"),
        _tx("Doe Jane", "CFO", "Sell", 2000.0, 55.0, "Open Market Sale", date="2026-06-26"),
    ]
    summaries, _ = ins.aggregate_insiders(txs)
    assert len(summaries) == 2
    assert {s.date for s in summaries} == {"2026-06-25", "2026-06-26"}


def test_sorted_by_value_desc():
    txs = [
        _tx("Small Sam", "Director", "Buy", 100.0, 10.0, "Open Market Purchase"),
        _tx("Big Ben", "CEO", "Buy", 100000.0, 20.0, "Open Market Purchase"),
    ]
    summaries, _ = ins.aggregate_insiders(txs)
    assert summaries[0].name == "Ben Big"   # $2M before $1k
    assert summaries[0].value > summaries[1].value


def test_all_routine_returns_no_summaries():
    txs = [_tx("Doe John", "Director", "Buy", 1000.0, 0.0, "Award/Grant")]
    summaries, routine = ins.aggregate_insiders(txs)
    assert summaries == []
    assert routine == 1


def test_empty_input():
    assert ins.aggregate_insiders([]) == ([], 0)
    assert ins.aggregate_insiders(None) == ([], 0)


# ── formatting helpers ─────────────────────────────────────────────────────

def test_compact_dollar_boundaries():
    assert ins._compact_dollar(46_300_000) == "~$46.3M"
    assert ins._compact_dollar(190_000) == "~$190K"
    assert ins._compact_dollar(50_000) == "~$50K"
    assert ins._compact_dollar(4_200) == "~$4,200"
    assert ins._compact_dollar(1_250_000_000) == "~$1.2B"
    assert ins._compact_dollar("bad") == "~$0"


def test_avg_cents_boundary_at_100():
    assert ins._fmt_avg(1158.3) == "$1,158"
    assert ins._fmt_avg(100.0) == "$100"
    assert ins._fmt_avg(99.99) == "$99.99"
    assert ins._fmt_avg(17.35) == "$17.35"


def test_date_format_and_fallback():
    assert ins._fmt_date("2026-06-26") == "Jun 26"
    assert ins._fmt_date("2026-06-05") == "Jun 5"      # no leading zero
    assert ins._fmt_date("not-a-date") == "not-a-date"
    assert ins._fmt_date("") == "?"


def test_fill_pluralization():
    assert ins._fmt_fills(1) == "1 fill"
    assert ins._fmt_fills(49) == "49 fills"


def test_title_abbreviation_and_fallback():
    assert ins._abbrev_title("President and CEO") == "CEO"
    assert ins._abbrev_title("Chief Financial Officer") == "CFO"
    assert ins._abbrev_title("Chief Legal & Corp Affairs Ofc") == "Chief Legal"
    assert ins._abbrev_title("VP, Chief Accounting Officer") == "CAO"
    assert ins._abbrev_title("Director") == "Director"
    assert ins._abbrev_title("10% Owner") == "10% Owner"
    assert ins._abbrev_title("") == "Insider"
    # Unknown long title is trimmed, never guessed.
    long = ins._abbrev_title("EVP, Worldwide Field Operations and Sales")
    assert long.endswith("…") and len(long) <= 18


# ── renderers ──────────────────────────────────────────────────────────────

def _one_ceo_sell():
    fills = [_tx("Mehrotra Sanjay", "President and CEO", "Sell", 1000.0, 100.0,
                 "Open Market Sale") for _ in range(49)]
    return ins.aggregate_insiders(fills)


def test_render_cards_shape():
    summaries, routine = _one_ceo_sell()
    out = ins.render_cards(summaries, routine)
    assert out.startswith("```") and out.rstrip().endswith("```")
    assert "🔴 Sanjay Mehrotra — CEO" in out
    assert "─" in out                       # underline
    assert "Shares   49,000" in out
    assert "Avg      $100" in out
    assert "Value    ~$4.9M" in out
    assert "Date     Jun 26 · 49 fills" in out


def test_render_cards_routine_line_and_note():
    summaries, _ = _one_ceo_sell()
    out = ins.render_cards(summaries, 6, note="+3 more insiders")
    assert "+6 routine award / option transactions" in out
    assert "+3 more insiders" in out


def test_render_all_field_is_bold_no_code_block():
    summaries, routine = _one_ceo_sell()
    out = ins.render_all_field(summaries, routine)
    assert "```" not in out
    assert "🔴 **Sanjay Mehrotra** — CEO" in out
    assert "Shares **49,000**" in out
    assert "Avg **$100**" in out
    assert "Value **~$4.9M**" in out
    assert "Jun 26 · 49 fills" in out


def test_render_all_field_trims_to_cap():
    # Many distinct insiders; a tiny cap forces a trailing "+N more insider(s)".
    txs = [_tx(f"Person{i:02d} Aa", "Director", "Buy", 100.0 + i, 10.0,
               "Open Market Purchase") for i in range(20)]
    summaries, routine = ins.aggregate_insiders(txs)
    out = ins.render_all_field(summaries, routine, max_chars=200)
    assert "more insider(s)" in out
    assert len(out) <= 260


def test_render_evidence_notable_flag():
    summaries, routine = _one_ceo_sell()
    lines = ins.render_evidence(summaries, routine, True)
    assert lines[0].startswith("NOTABLE — ")
    assert "Sanjay Mehrotra (CEO) — Sell 49,000 shares" in lines[1]
    assert "(49 fills)" in lines[1]
    not_notable = ins.render_evidence(summaries, routine, False)
    assert not not_notable[0].startswith("NOTABLE")


def test_render_evidence_routine_only_and_empty():
    assert ins.render_evidence([], 3, False)[0].lower().startswith("recent form 4")
    assert ins.render_evidence([], 0, False) == []
