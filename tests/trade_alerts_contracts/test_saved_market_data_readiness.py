"""M9.1ER development-only saved-bar readiness contracts."""

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.saved_market_data_binding import bind_saved_bar_inputs
from consensus_engine.saved_market_data_readiness import count_saved_bar_readiness
from consensus_engine.retained_history_batches import RetainedHistoryBatches, SessionHistory
from consensus_engine.search_run_config import TRAINING_TICKERS
from consensus_engine.trade_alerts_models import RecordError
from tests.trade_alerts_contracts.test_saved_market_data_binding import _audit
from tests.trade_alerts_contracts.test_hod_comp_rs_research_adapter import history


DATES = ("2026-08-20", "2026-08-21")
SCRIPT = Path("/workspace/scripts/research/run_saved_market_data_readiness.py")
PUBLISHED = Path("/workspace/trade_alerts_build_docs/M9_1ER_DEVELOPMENT_READINESS_COUNTS.json")


def _batches(ticker="LLY"):
    batch = history(ticker, minutes=390, day=DATES[-1])
    return RetainedHistoryBatches(
        (SessionHistory(ticker, DATES[-1], batch, None),),
        tuple((name, day, "NO_USABLE_BARS") for name in TRAINING_TICKERS if name != ticker
              for day in DATES),
        ((ticker, DATES[-1]),),
    )


def _types():
    return {ticker: ("ETF" if ticker in {"SPY", "QQQ", "XLV", "USO"} else "EQUITY")
            for ticker in TRAINING_TICKERS}


def test_counts_only_bound_inputs_and_keeps_every_unsupported_rule_off():
    result = count_saved_bar_readiness(
        bind_saved_bar_inputs(_audit()), _batches(), development_dates=DATES,
        instrument_types=_types())
    payload = result.as_dict()
    assert payload["development_tickers"] == list(TRAINING_TICKERS)
    assert payload["missing_tickers"] == [name for name in TRAINING_TICKERS if name != "LLY"]
    assert payload["sessions_requested"] == len(TRAINING_TICKERS) * len(DATES)
    assert payload["sessions_used"] == 1
    assert len(payload["enabled_input_counts"]) == 11
    assert len(payload["disabled_inputs"]) == 11
    assert all(row["status"] == "OFF_UNTESTED" for row in payload["disabled_inputs"])
    assert all(row["dependent_rules"] == "OFF_UNTESTED"
               for row in payload["d104_gaps"].values())
    assert payload["held_out_evaluation"] == "CLOSED"
    assert not any((payload["return_calculated"], payload["promotion_or_live_release"],
                    payload["network_used"]))


@pytest.mark.parametrize("case", ("held_out", "open_result", "wrong_adapter", "bad_dates"))
def test_rejects_scope_or_binding_drift(case):
    binding = bind_saved_bar_inputs(_audit())
    batches = _batches()
    dates = DATES
    if case == "held_out":
        batches = _batches("BRK.B")
    elif case == "open_result":
        binding["held_out_evaluation"]["status"] = "OPEN"
    elif case == "wrong_adapter":
        binding["adapter_run_version"] = "changed"
    else:
        dates = tuple(reversed(DATES))
    with pytest.raises(RecordError):
        count_saved_bar_readiness(binding, batches, development_dates=dates,
                                  instrument_types=_types())


def test_recorded_readiness_is_deterministic_and_contains_no_result(tmp_path):
    binding = bind_saved_bar_inputs(_audit())
    first = count_saved_bar_readiness(
        binding, _batches(), development_dates=DATES, instrument_types=_types()).as_dict()
    second = count_saved_bar_readiness(
        deepcopy(binding), _batches(), development_dates=DATES, instrument_types=_types()).as_dict()
    assert first == second
    rendered = json.dumps(first, indent=2, sort_keys=True) + "\n"
    output = Path(os.environ["TMPDIR"], "m91er-saved-readiness-proof.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert "profit" not in rendered and "return_r" not in rendered


def _research_script():
    spec = importlib.util.spec_from_file_location("m91er_research_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_saved_file_loader_reads_exact_dates_not_intervening_dates(tmp_path, monkeypatch):
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = []
    for day in ("2026-08-18", "2026-08-19", "2026-08-20"):
        rows.append({"date": day, "symbol": "LLY", "minute": 570,
                     "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
                     "volume": 1})
    rows.append(dict(rows[0], symbol="BRK.B"))
    source = tmp_path / "dates.parquet"
    pq.write_table(pa.Table.from_pylist(rows), source)
    script = _research_script()
    dates = ("2026-08-18", "2026-08-20")
    real_dataset = script.ds.dataset
    materialized = []

    class ObservedDataset:
        def __init__(self, *args, **kwargs):
            self.source = real_dataset(*args, **kwargs)

        def to_table(self, **kwargs):
            table = self.source.to_table(**kwargs)
            materialized.extend((row["symbol"], row["date"])
                                for row in table.to_pylist())
            return table

    monkeypatch.setattr(script.ds, "dataset", ObservedDataset)
    batches = script._load(source, "TEST", "digest", dates)
    # Inspect rows at materialization, before _load can discard any dates.
    assert materialized == [("LLY", day) for day in dates]
    assert [(item.ticker, item.session) for item in batches.histories] == materialized
    result = count_saved_bar_readiness(
        bind_saved_bar_inputs(_audit()), batches, development_dates=dates,
        instrument_types=_types())
    assert result.sessions_used == len(dates)
    assert result.sessions_requested == len(TRAINING_TICKERS) * len(dates)
    assert all(day in dates for _, day, _ in result.skipped)


@pytest.mark.timeout(600)
def test_recorded_real_24_date_readiness_is_deterministic_and_matches_published_proof(monkeypatch):
    script = _research_script()
    output = Path(os.environ["TMPDIR"], "M9_1ER_DEVELOPMENT_READINESS_COUNTS.json")
    monkeypatch.setattr(script, "OUTPUT", output)
    # Execute the real entry point with unchanged audited sources and bindings.
    # Each controller repeatability process rebuilds this full recording.
    script.main()
    actual = json.loads(output.read_text())
    assert actual == json.loads(PUBLISHED.read_text())
    assert output.read_bytes() == PUBLISHED.read_bytes()
    assert actual["development_dates"] == actual["frozen_sample_dates"][:24]
    assert [row["counts"]["moments_called"] for row in actual["sources"]] == [7392, 7392]
    assert actual["held_out_tickers_read"] == []
    assert actual["held_out_evaluation"] == "CLOSED"
    assert all(row["status"] == "OFF_UNTESTED" for source in actual["sources"]
               for row in source["counts"]["disabled_inputs"])
    assert all(gap["dependent_rules"] == "OFF_UNTESTED" for source in actual["sources"]
               for gap in source["counts"]["d104_gaps"].values())
    assert not any(actual[key] for key in (
        "return_calculated", "promotion_or_live_release", "network_used", "spend_usd"))
