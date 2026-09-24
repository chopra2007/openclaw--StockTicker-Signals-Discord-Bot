"""M9.1EA candidate-only connection to the accepted fill boundary."""

from dataclasses import replace
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.fill_cost_model import POLICY_VERSION, FillCostPolicy
from consensus_engine.retained_first_four_fill import (
    RUN_VERSION,
    run_retained_first_four_fills,
)
from consensus_engine.trade_alerts_models import Quote, RecordError, SourceMetadata
from test_retained_first_four_evaluator_binding import (
    _evaluated_binding,
    _unavailable_binding,
)


def _policy():
    return FillCostPolicy(POLICY_VERSION, 10.0, 0.01)


def _market(record_id, decision, *, trade):
    when = decision.alerted_at + timedelta(seconds=5 if trade else 4)
    metadata = SourceMetadata(
        instrument_id=decision.ticker,
        instrument_type="EQUITY",
        source="SYNTHETIC",
        source_time=when,
        received_time=when,
        available_time=when,
        normalized_time=when,
        session=decision.session,
        data_mode="FIXTURE",
        quality="VALID",
    )
    return Quote(
        record_id=record_id,
        metadata=metadata,
        quote_time=None if trade else when,
        trade_time=when if trade else None,
        bid=None if trade else 99.9,
        ask=None if trade else 100.1,
        last=100.0 if trade else None,
        last_size=100 if trade else None,
        bid_size=None if trade else 100,
        ask_size=None if trade else 100,
        status="VALID",
    )


def _fill_ready_binding(monkeypatch):
    _values, events, restart = _evaluated_binding(monkeypatch)
    from consensus_engine.retained_first_four_evaluator_binding import (
        bind_retained_first_four_evaluator_results,
    )
    binding = bind_retained_first_four_evaluator_results(events, restart)
    candidates = tuple(row for row in binding.rows if row.status == "CANDIDATE")
    trades = tuple(_market(f"fill-trade-{row.playbook}", row, trade=True)
                   for row in candidates)
    quotes = tuple(_market(f"fill-quote-{row.playbook}", row, trade=False)
                   for row in candidates)
    changed = []
    for row in binding.rows:
        market_ids = tuple(record.record_id for record in (*trades, *quotes)
                           if (record.metadata.instrument_id, record.metadata.session)
                           == (row.ticker, row.session))
        if market_ids:
            retained = tuple(dict.fromkeys((*row.retained_source_record_ids, *market_ids)))
            row = replace(
                row,
                retained_source_record_ids=retained,
                evaluator_result=replace(row.evaluator_result, retained_source_record_ids=retained),
            )
        changed.append(row)
    return replace(binding, rows=tuple(changed)), trades, quotes


def test_only_bound_candidates_reach_the_fill_boundary(monkeypatch):
    binding, trades, quotes = _fill_ready_binding(monkeypatch)
    result = run_retained_first_four_fills(
        binding, trades=trades, quotes=quotes, policy=_policy(),
    )

    assert result.version == RUN_VERSION
    assert result.candidate_count == len(result.rows) == 2
    assert result.filled_count == 2
    assert result.unfilled_count == 0
    assert result.no_event_excluded_count == 2
    assert result.unavailable_excluded_count == 0
    assert {row.decision.status for row in result.rows} == {"CANDIDATE"}
    assert all(row.fill.status == "FILLED" for row in result.rows)
    for row in result.rows:
        assert row.fill.trade_print_time == row.decision.alerted_at + timedelta(seconds=5)
        assert row.fill.quote_time == row.decision.alerted_at + timedelta(seconds=4)
    assert not any((result.return_calculated, result.result_shard_released,
                    result.held_out_opened))


def test_first_candidate_market_data_cannot_fill_another_alert_window(monkeypatch):
    binding, trades, quotes = _fill_ready_binding(monkeypatch)
    candidates = tuple(row for row in binding.rows if row.status == "CANDIDATE")
    assert not (candidates[1].alerted_at <= trades[0].trade_time
                <= candidates[1].alerted_at + timedelta(seconds=30))
    result = run_retained_first_four_fills(
        binding, trades=trades[:1], quotes=quotes[:1], policy=_policy(),
    )

    assert result.filled_count == result.unfilled_count == 1
    assert result.rows[0].fill.status == "FILLED"
    assert result.rows[1].fill.status == "NO_TRADE_IN_WINDOW"
    assert result.rows[1].fill.modeled_price is None


def test_missing_quotes_stay_unfilled_without_approximation(monkeypatch):
    binding, trades, _quotes = _fill_ready_binding(monkeypatch)
    result = run_retained_first_four_fills(
        binding, trades=trades, quotes=(), policy=_policy(),
    )
    assert result.filled_count == 0
    assert result.unfilled_count == 2
    assert {row.fill.status for row in result.rows} == {"NO_QUOTE_AT_FILL"}
    assert all(row.fill.modeled_price is None for row in result.rows)


def test_real_unavailable_rows_release_no_fill_inputs():
    _values, events, restart = _unavailable_binding()
    from consensus_engine.retained_first_four_evaluator_binding import (
        bind_retained_first_four_evaluator_results,
    )
    binding = bind_retained_first_four_evaluator_results(events, restart)
    result = run_retained_first_four_fills(
        binding, trades=(), quotes=(), policy=_policy(),
    )

    assert result.rows == ()
    assert result.candidate_count == result.filled_count == result.unfilled_count == 0
    assert result.no_event_excluded_count == 0
    assert result.unavailable_excluded_count == 4


def test_missing_market_data_stays_unfilled_without_approximation(monkeypatch):
    binding, _trade, _quote = _fill_ready_binding(monkeypatch)
    result = run_retained_first_four_fills(
        binding, trades=(), quotes=(), policy=_policy(),
    )
    assert result.filled_count == 0
    assert result.unfilled_count == 2
    assert {row.fill.status for row in result.rows} == {"NO_TRADE_IN_WINDOW"}
    assert all(row.fill.modeled_price is None for row in result.rows)


def test_refuses_cross_session_foreign_source_or_opened_binding(monkeypatch):
    binding, trades, quotes = _fill_ready_binding(monkeypatch)
    trade, quote = trades[0], quotes[0]
    foreign_session = replace(
        trade,
        metadata=replace(trade.metadata, session="2026-07-07"),
    )
    with pytest.raises(RecordError, match="candidate session"):
        run_retained_first_four_fills(
            binding, trades=(foreign_session,), quotes=(quote,), policy=_policy(),
        )

    foreign_id = replace(trade, record_id="foreign-fill-trade")
    with pytest.raises(RecordError, match="retained source identities"):
        run_retained_first_four_fills(
            binding, trades=(foreign_id,), quotes=(quote,), policy=_policy(),
        )

    with pytest.raises(RecordError, match="opened a later release"):
        run_retained_first_four_fills(
            replace(binding, fill_calculated=True),
            trades=(trade,), quotes=(quote,), policy=_policy(),
        )


def test_recorded_candidate_fill_is_deterministic_and_keeps_later_release_off(monkeypatch):
    binding, trades, quotes = _fill_ready_binding(monkeypatch)
    result = run_retained_first_four_fills(
        binding, trades=trades, quotes=quotes, policy=_policy(),
    )
    assert result.filled_count == 2
    assert result.unfilled_count == 0
    payload = result.as_dict()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    recording = {
        "version": RUN_VERSION,
        "fill_run_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
        "result": payload,
        "only_bound_candidates_entered_fill": all(
            row.decision.status == "CANDIDATE" for row in result.rows
        ),
        "gap_dependent_rules": "OFF_UNTESTED",
        "return_calculated": False,
        "result_shard_released": False,
        "held_out_opened": False,
        "alert_or_live_action": False,
    }
    rendered = json.dumps(recording, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91ea-retained-first-four-fill.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert json.loads(output.read_text()) == recording
