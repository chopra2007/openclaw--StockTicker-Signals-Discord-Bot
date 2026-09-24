"""M9.1EN parent engineering-pilot disposition contracts."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

import consensus_engine.retained_stage3_pilot_disposition as subject
from consensus_engine.orb5_stage1_result import REQUIRED_DISABLED_RULES
from consensus_engine.retained_stage3_result_shard import publish_retained_stage3_result_shard
from consensus_engine.trade_alerts_models import RecordError
from test_retained_stage3_d108_evaluation import _fingerprint as evaluation_fingerprint
from test_retained_stage3_result_shard import evaluation_source


@pytest.fixture(scope="module")
def result_shard(evaluation_source):
    return publish_retained_stage3_result_shard(
        evaluation_source,
        frozen_evaluation_sha256=evaluation_fingerprint(evaluation_source),
    )


def _fingerprint(source):
    return hashlib.sha256(json.dumps(
        source.as_dict(), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def test_records_exact_offline_result_and_closes_promotion_alert_and_live(result_shard):
    source_sha256 = _fingerprint(result_shard)
    result = subject.publish_retained_stage3_pilot_disposition(
        result_shard, frozen_result_shard_sha256=source_sha256,
    )

    assert result.version == subject.RUN_VERSION
    assert result.source_result_shard == result_shard
    assert result.frozen_result_shard_sha256 == source_sha256
    assert result.selected_candidate_id == result_shard.selected_candidate_id
    assert result.d108_passed is result_shard.d108_passed
    assert result.disposition == "ENGINEERING_PILOT_ONLY"
    assert result.disabled_rules == REQUIRED_DISABLED_RULES
    assert result.gap_dependent_rules == "OFF_UNTESTED"
    assert result.engineering_pilot_complete
    assert not any((result.promotion_released, result.alert_released, result.live_action))
    assert result.as_dict()["source_result_shard"] == result_shard.as_dict()


@pytest.mark.parametrize("case", (
    "wrong_version", "wrong_rules", "incomplete", "unreleased_shard",
    "alert_released", "live_action", "changed_candidate", "changed_result",
    "changed_evaluation",
))
def test_rejects_changed_shard_or_an_open_release_boundary(case, result_shard):
    source = result_shard
    if case == "wrong_version":
        source = replace(source, version="FORGED")
    elif case == "wrong_rules":
        source = replace(source, disabled_rules=())
    elif case == "incomplete":
        source = replace(source, offline_result_complete=False)
    elif case == "unreleased_shard":
        source = replace(source, result_shard_released=False)
    elif case == "alert_released":
        source = replace(source, alert_released=True)
    elif case == "live_action":
        source = replace(source, live_action=True)
    elif case == "changed_candidate":
        source = replace(source, selected_candidate_id="FORGED")
    elif case == "changed_result":
        source = replace(source, d108_passed=not source.d108_passed)
    else:
        source = replace(source, source_evaluation=replace(
            source.source_evaluation,
            evaluation=replace(source.source_evaluation.evaluation, passed=False),
        ))

    with pytest.raises(RecordError):
        subject.publish_retained_stage3_pilot_disposition(
            source, frozen_result_shard_sha256=_fingerprint(result_shard),
        )


@pytest.mark.parametrize("fingerprint", (None, "", "0" * 64, "not-a-digest"))
def test_rejects_unavailable_or_wrong_frozen_fingerprint(result_shard, fingerprint):
    with pytest.raises(RecordError, match="independently frozen fingerprint"):
        subject.publish_retained_stage3_pilot_disposition(
            result_shard, frozen_result_shard_sha256=fingerprint,
        )


def test_recorded_pilot_disposition_is_deterministic_and_keeps_every_release_closed(
    result_shard,
):
    source_sha256 = _fingerprint(result_shard)
    payload = subject.publish_retained_stage3_pilot_disposition(
        result_shard, frozen_result_shard_sha256=source_sha256,
    ).as_dict()
    assert payload == subject.publish_retained_stage3_pilot_disposition(
        result_shard, frozen_result_shard_sha256=source_sha256,
    ).as_dict()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    recording = {
        "version": subject.RUN_VERSION,
        "source_sha256": source_sha256,
        "disposition_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
        "result": payload,
        "exact_offline_d108_passed": payload["d108_passed"],
        "gap_dependent_rules": "OFF_UNTESTED",
        "promotion_alert_or_live_released": False,
    }
    rendered = json.dumps(recording, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91en-retained-stage3-pilot-disposition.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert json.loads(output.read_text()) == recording
