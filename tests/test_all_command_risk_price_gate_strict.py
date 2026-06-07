"""#24 (full-audit-2026-06-06) — widen the risk-section price gate.

`quality_bar.risk_section_violations` historically caught ONLY the stop-loss
price literal inside the `## Risk Considerations` section. Item #24 adds a
`strict` mode (flag `all_command.risk_price_gate_strict`, default OFF) that ALSO
catches a leaked entry / target / buy-zone price — a `$NN.NN`/`$N,NNN` token OR
a bare number within +/-30% of current_price — while NOT false-positiving on
percentages, 4-digit years, or `[evidence:N]` citation tags.

Asserts:
  * strict ON: a Risk bullet naming tp1 (a target price) trips the gate.
  * strict ON: a clean Risk section with only %/dates/[evidence] does NOT
    false-positive.
  * strict OFF: only the stop-loss literal is caught (the historical behavior),
    a target-price leak is ignored.
"""
from __future__ import annotations

from consensus_engine.alerts.all_command import quality_bar as qb


# current_price=100, sl=95, tp1=110 (within +/-30% of 100), tp2=120, tp3=130.
_PRICE_LEVELS = [95.0, 110.0, 120.0, 130.0, 98.0, 100.0, 100.0]
_CURRENT_PRICE = 100.0


def test_strict_trips_on_leaked_target_price():
    # A Risk bullet that names tp1 (110) — a target price the prompt bans here.
    narrative = (
        "**TL;DR:** Long.\n## Risk Considerations\n"
        "* Failure to reclaim 110 caps the upside thesis [evidence:1].\n"
        "## Trade Plan\n| x |\n"
    )
    v = qb.risk_section_violations(
        narrative,
        stop_price=95.0,
        price_levels=_PRICE_LEVELS,
        current_price=_CURRENT_PRICE,
        strict=True,
    )
    assert v, "strict gate should flag the leaked target price"
    assert "110" in v[0]


def test_strict_trips_on_dollar_magnitude_token():
    # A `$NN.NN` token (entry/support price) is a leak regardless of proximity.
    narrative = (
        "**TL;DR:** Long.\n## Risk Considerations\n"
        "* The setup fails if it loses $102.50 support [evidence:1].\n"
        "## Trade Plan\n| x |\n"
    )
    v = qb.risk_section_violations(
        narrative,
        stop_price=95.0,
        current_price=_CURRENT_PRICE,
        strict=True,
    )
    assert v and "$102.50" in v[0]


def test_strict_no_false_positive_on_clean_section():
    # Only percentages, a date, and [evidence:N] tags — no share-price leak.
    narrative = (
        "**TL;DR:** Long.\n## Risk Considerations\n"
        "* China export curbs cut revenue 12% in 2026 [evidence:1].\n"
        "* Earnings on 2026-07-15 (20 days out); expected move 8% [evidence:2].\n"
        "## Trade Plan\n| x |\n"
    )
    v = qb.risk_section_violations(
        narrative,
        stop_price=95.0,
        price_levels=_PRICE_LEVELS,
        current_price=_CURRENT_PRICE,
        strict=True,
    )
    assert v == [], f"strict gate false-positived on a clean section: {v}"


def test_strict_no_false_positive_on_evidence_or_year_near_price():
    # A 4-digit year and an [evidence:95] index that happen to sit near
    # current_price (100) must be masked out before the bare-number scan.
    narrative = (
        "## Risk Considerations\n"
        "* FDA decision expected in 2026 weighs on the thesis [evidence:95].\n"
        "## Trade Plan\n"
    )
    v = qb.risk_section_violations(
        narrative,
        stop_price=88.0,
        current_price=_CURRENT_PRICE,
        strict=True,
    )
    assert v == [], f"year/evidence index should not false-positive: {v}"


def test_flag_off_catches_only_stop_literal():
    # strict OFF == historical behavior: the stop literal trips it...
    narrative_stop = (
        "**TL;DR:** Long.\n## Risk Considerations\n"
        "* A break below $95.00 ends the thesis.\n## Trade Plan\n| x |\n"
    )
    v_stop = qb.risk_section_violations(narrative_stop, stop_price=95.0, strict=False)
    assert v_stop and "95" in v_stop[0]


def test_flag_off_ignores_target_price_leak():
    # ...but a leaked TARGET price (not the stop) is ignored when strict is OFF.
    narrative_tp = (
        "**TL;DR:** Long.\n## Risk Considerations\n"
        "* Failure to reclaim 110 caps the upside thesis [evidence:1].\n"
        "## Trade Plan\n| x |\n"
    )
    v_tp = qb.risk_section_violations(
        narrative_tp,
        stop_price=95.0,
        price_levels=_PRICE_LEVELS,
        current_price=_CURRENT_PRICE,
        strict=False,
    )
    assert v_tp == [], f"flag OFF must ignore non-stop price leaks: {v_tp}"


def test_flag_off_byte_identical_to_legacy_two_arg_call():
    # The new params default to behavior-preserving values: a 2-arg call (the
    # historical signature) returns exactly what strict=False with the same
    # stop_price returns.
    narrative = (
        "**TL;DR:** Long.\n## Risk Considerations\n"
        "* A break below $95.00 ends it.\n## Trade Plan\n| x |\n"
    )
    legacy = qb.risk_section_violations(narrative, 95.0)
    explicit_off = qb.risk_section_violations(narrative, 95.0, strict=False)
    assert legacy == explicit_off
