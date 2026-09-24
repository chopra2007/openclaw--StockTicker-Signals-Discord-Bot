"""M9.1DG retained training-nine candidate-boundary record contracts."""

from dataclasses import replace
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.orb5_stage1_result import REQUIRED_DISABLED_RULES
from consensus_engine.retained_training_candidate_record import (
    RECORD_VERSION,
    build_retained_training_candidate_record,
    write_retained_training_candidate_record,
)
from consensus_engine.search_run_config import PLAYBOOKS, TRAINING_TICKERS
from consensus_engine.trade_alerts_models import RecordError
from test_retained_candidate_events import _market, _retained


def _record():
    return build_retained_training_candidate_record(_retained(), _market())


def test_records_exact_training_nine_totals_and_source_commitments():
    record = _record()

    assert record.version == RECORD_VERSION
    assert record.event_count == len(PLAYBOOKS) * len(TRAINING_TICKERS)
    assert record.session_count == len(TRAINING_TICKERS)
    assert record.status_totals == tuple(
        (playbook, status, len(TRAINING_TICKERS) if status == "UNAVAILABLE" else 0)
        for playbook in PLAYBOOKS
        for status in ("CANDIDATE", "NO_EVENT", "UNAVAILABLE")
    )
    assert record.ticker_totals == tuple(
        (ticker, status, len(PLAYBOOKS) if status == "UNAVAILABLE" else 0)
        for ticker in TRAINING_TICKERS
        for status in ("CANDIDATE", "NO_EVENT", "UNAVAILABLE")
    )
    assert record.source_identity_count == len(TRAINING_TICKERS) + len(_market())
    assert len(record.source_identity_sha256) == 64
    assert len(record.event_stream_sha256) == 64
    assert record.disabled_rules == REQUIRED_DISABLED_RULES
    assert record.as_dict()["gap_dependent_rules"] == "OFF_UNTESTED"


def test_record_refuses_held_out_scope_and_conflicting_output(tmp_path):
    with pytest.raises(RecordError, match="held-out ticker"):
        build_retained_training_candidate_record(
            _retained(TRAINING_TICKERS[:-1] + ("GOOGL",)), _market())

    path = tmp_path / "record.json"
    record = _record()
    write_retained_training_candidate_record(path, record)
    write_retained_training_candidate_record(path, record)
    changed = replace(record, event_count=record.event_count + 1)
    with pytest.raises(RecordError, match="conflicts"):
        write_retained_training_candidate_record(path, changed)


def test_recording_training_candidate_boundary_is_deterministic():
    record = _record()
    output = Path(os.environ["TMPDIR"], "m91dg-retained-training-candidate-record.json")
    write_retained_training_candidate_record(output, record)
    assert json.loads(output.read_text()) == record.as_dict()
