"""M9.1EM closed offline result-shard contracts."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

import consensus_engine.retained_stage3_result_shard as subject
from consensus_engine.orb5_stage1_result import REQUIRED_DISABLED_RULES
from consensus_engine.retained_stage3_d108_evaluation import (
    run_retained_stage3_d108_evaluation,
)
from consensus_engine.trade_alerts_models import RecordError
from test_retained_stage3_d108_evaluation import _fingerprint as input_fingerprint
from test_retained_stage3_d108_evaluation import _held_out_source


@pytest.fixture(scope="module")
def evaluation_source():
    held_out = _held_out_source()
    return run_retained_stage3_d108_evaluation(
        held_out, frozen_input_sha256=input_fingerprint(held_out),
    )


def _fingerprint(source):
    return hashlib.sha256(json.dumps(
        source.as_dict(), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def test_publishes_exact_frozen_offline_result_and_keeps_alert_and_live_closed(
    evaluation_source,
):
    source_sha256 = _fingerprint(evaluation_source)
    shard = subject.publish_retained_stage3_result_shard(
        evaluation_source, frozen_evaluation_sha256=source_sha256,
    )

    assert shard.version == subject.RUN_VERSION
    assert shard.source_evaluation == evaluation_source
    assert shard.frozen_evaluation_sha256 == source_sha256
    assert shard.selected_candidate_id == evaluation_source.evaluation.candidate_id
    assert shard.d108_passed is evaluation_source.evaluation.passed
    assert shard.disabled_rules == REQUIRED_DISABLED_RULES
    assert shard.offline_result_complete and shard.result_shard_released
    assert not shard.alert_released and not shard.live_action
    assert shard.as_dict()["source_evaluation"] == evaluation_source.as_dict()


@pytest.mark.parametrize("case", (
    "wrong_version", "wrong_policy", "wrong_rules", "incomplete",
    "not_run", "already_released", "alert_released", "live_action",
    "wrong_candidate", "wrong_trade_count", "changed_measure",
))
def test_rejects_changed_result_or_an_open_boundary(case, evaluation_source):
    source = evaluation_source
    if case == "wrong_version":
        source = replace(source, version="FORGED")
    elif case == "wrong_policy":
        source = replace(source, d108_policy_version="FORGED")
    elif case == "wrong_rules":
        source = replace(source, disabled_rules=())
    elif case == "incomplete":
        source = replace(source, evaluation_complete=False)
    elif case == "not_run":
        source = replace(source, d108_evaluation_run=False)
    elif case == "already_released":
        source = replace(source, result_shard_released=True)
    elif case == "alert_released":
        source = replace(source, alert_released=True)
    elif case == "live_action":
        source = replace(source, live_action=True)
    elif case == "wrong_candidate":
        source = replace(source, evaluation=replace(source.evaluation, candidate_id="FORGED"))
    elif case == "wrong_trade_count":
        source = replace(source, evaluation=replace(
            source.evaluation, trade_count=source.evaluation.trade_count + 1,
        ))
    else:
        source = replace(source, evaluation=replace(
            source.evaluation,
            profit=replace(source.evaluation.profit, mean_r=99.0),
        ))

    with pytest.raises(RecordError):
        subject.publish_retained_stage3_result_shard(
            source, frozen_evaluation_sha256=_fingerprint(evaluation_source),
        )


@pytest.mark.parametrize("fingerprint", (None, "", "0" * 64, "not-a-digest"))
def test_rejects_unavailable_or_wrong_frozen_fingerprint(evaluation_source, fingerprint):
    with pytest.raises(RecordError, match="independently frozen fingerprint"):
        subject.publish_retained_stage3_result_shard(
            evaluation_source, frozen_evaluation_sha256=fingerprint,
        )


def test_recorded_result_shard_is_deterministic_and_keeps_alert_and_live_closed(
    evaluation_source,
):
    source_sha256 = _fingerprint(evaluation_source)
    payload = subject.publish_retained_stage3_result_shard(
        evaluation_source, frozen_evaluation_sha256=source_sha256,
    ).as_dict()
    assert payload == subject.publish_retained_stage3_result_shard(
        evaluation_source, frozen_evaluation_sha256=source_sha256,
    ).as_dict()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    recording = {
        "version": subject.RUN_VERSION,
        "source_sha256": source_sha256,
        "shard_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
        "result": payload,
        "gap_dependent_rules": "OFF_UNTESTED",
        "result_shard_released": True,
        "alert_or_live_released": False,
    }
    rendered = json.dumps(recording, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91em-retained-stage3-result-shard.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert json.loads(output.read_text()) == recording
