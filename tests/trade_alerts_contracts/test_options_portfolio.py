"""M4.7 supplied-record option and portfolio contracts."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.options_portfolio import (
    OptionChainEvidence, OptionRowEvidence, PortfolioCandidate, PortfolioManifest,
    ProducerRecovery,
    candidate_fingerprint, candidate_key, cooldown_allows, intent_expiry, intent_is_expired,
    project_portfolio, select_option,
)
from consensus_engine.trade_alerts_models import (
    AlertCandidate, ConfidenceBreakdown, OptionQuote, Quote, RecordError, RiskLevel,
    SourceMetadata, TargetLevel,
)
from consensus_engine import db
from test_cross_strategy_interaction import report as interaction_report, transition_fixture
from test_research_event_store import open_store


AT = datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)


def metadata(at=AT, *, instrument="SYNTH", kind="EQUITY"):
    return SourceMetadata(instrument, "SUPPLIED", at, at, at, at,
                          "2026-09-14", kind, data_mode="OFFLINE", quality="VALID")


def candidate(record_id="candidate", *, strategy="CRVOL_ORB5", direction="LONG",
              created=AT, trigger=100.0, stop=99.0, structure="structure"):
    sign = 1 if direction == "LONG" else -1
    return AlertCandidate(
        record_id=record_id, metadata=metadata(created), strategy_id=strategy,
        strategy_version="FROZEN_V1", direction=direction, alert_type="ACTIONABLE",
        setup_state="ALERT_TRIGGERED", strategy_lifecycle="DEVELOPMENT",
        evidence_stage="IMPLEMENTED", delivery_status="PENDING", structure_id=structure,
        trigger_price=trigger, alert_price=trigger,
        risk=RiskLevel(trigger, stop, abs(trigger-stop), "supplied", "SUPPLIED"),
        targets=(TargetLevel("T1", trigger + sign * 2, 2, "SUPPLIED"),),
        confidence=ConfidenceBreakdown(70, 70, 70, 70),
        input_record_ids=("input-1", "input-2"), feature_snapshot_id="feature",
        session_record_id="session", config_version="config", config_hash="0" * 64,
        created_at=created, expires_at=created + timedelta(minutes=5),
        data_quality="VALID", mechanically_valid=True)


def underlying(at=AT):
    return Quote(record_id="underlying", metadata=metadata(at), quote_time=at,
                 trade_time=at, bid=99.99, ask=100.01, last=100.0,
                 last_size=10, bid_size=10, ask_size=10, status="VALID", delayed=False)


def option(record_id="option-a", *, expiry=date(2026, 9, 18), right="CALL",
           delta=.60, bid=.99, ask=1.01, oi=1000, volume=1000, sizes=10,
           iv=.20, gamma=.04, theta=-.02, contract=None, at=AT):
    contract = contract or record_id
    return OptionQuote(
        record_id=record_id, metadata=metadata(at, instrument=contract, kind="OPTION"),
        contract_id=contract, underlying_id="SYNTH", expiry=expiry, strike=100.0,
        option_type=right, multiplier=100, deliverable="100 SHARES SYNTH",
        quote_time=at, trade_time=at, bid=bid, ask=ask, last=1.0,
        bid_size=sizes, ask_size=sizes, implied_volatility=iv, delta=delta,
        gamma=gamma, theta=theta, vega=.1, rho=.1, open_interest=oi,
        open_interest_time=at, volume=volume, non_standard=False,
        status="VALID", delayed=False)


def chain(*rows, row_age=1, complete=True, member=True, strategy="CRVOL_ORB5",
          direction="LONG", stop=99.0):
    item = candidate(strategy=strategy, direction=direction, stop=stop)
    return OptionChainEvidence(
        "chain", item, underlying(), tuple(OptionRowEvidence(
            row, row_age, True, True, True) for row in rows), AT, 1,
        complete, True, member)


def portfolio(row, *, arm="arm", experiment="experiment", atr=2, priority=0):
    recovery = ProducerRecovery("ARMED", row.structure_id, 1, 1, True,
                                row.created_at, row.created_at)
    return PortfolioCandidate(row, arm, "TAPE", experiment, atr, row.created_at,
                              priority, recovery, row.created_at + timedelta(hours=3))


def manifest(*rows, complete=True, required=True, releases=()):
    return PortfolioManifest("experiment", "OFFLINE", "RAW", "0" * 64,
                             AT + timedelta(hours=1), tuple(rows), complete,
                             required, tuple(releases))


def test_ordinary_score_and_complete_selection_preserve_stock_validity():
    result = select_option(chain(option()))
    assert result.recommendation.status == "RECOMMENDED"
    assert result.recommendation.contract_id == "option-a"
    assert result.scores[0].score == Decimal("91.500")
    assert result.stock_validity_unchanged is True


def test_ordinary_score_equality_passes_without_display_rounding():
    boundary = option(bid=.95, ask=1.05, gamma=0, theta=-.02)
    result = select_option(chain(boundary))
    assert result.recommendation.status == "RECOMMENDED"
    assert result.scores[0].score == Decimal("65.000")


@pytest.mark.parametrize("strategy", (
    "HOD_COMP_RS", "OR_FAILURE_REV", "FIRST_PULLBACK_VWAP"))
def test_other_first_four_policies_are_ordinary_only(strategy):
    result = select_option(chain(option(expiry=date(2026, 9, 14)), strategy=strategy))
    assert result.recommendation.status == "POOR"
    assert result.rejection_counts == (("NOT_SELECTED_BY_THIS_RESEARCH_POLICY", 1),)


def test_strict_same_day_boundaries_pass_and_unknown_membership_stays_ordinary_only():
    same_day = option(expiry=date(2026, 9, 14), delta=.58, bid=.975, ask=1.025,
                      gamma=0, theta=-.02)
    selected = select_option(chain(same_day))
    assert selected.recommendation.status == "RECOMMENDED"
    ordinary = select_option(replace(chain(option()), same_day_membership=None))
    assert "ORDINARY_DTE_ONLY / SAME_DAY_MEMBERSHIP_UNAVAILABLE" in ordinary.recommendation.reasons


@pytest.mark.parametrize("change,reason", (
    ({"complete_eligible_chain": False}, "ELIGIBLE_CHAIN_INCOMPLETE"),
    ({"regular_session": False}, "UNDERLYING_QUOTE_CONTEXT_UNAVAILABLE"),
))
def test_missing_chain_or_quote_context_is_unavailable_not_poor(change, reason):
    result = select_option(replace(chain(option()), **change))
    assert result.recommendation.status == "UNAVAILABLE"
    assert reason in result.recommendation.reasons


def test_missing_in_band_fields_and_stale_known_rows_have_different_results():
    missing = option()
    missing = replace(missing, gamma=None)
    unavailable = select_option(chain(missing))
    assert unavailable.recommendation.status == "UNAVAILABLE"
    stale = select_option(chain(option(at=AT - timedelta(seconds=4))))
    assert stale.recommendation.status == "POOR"
    assert stale.rejection_counts == (("STALE_OPTION_QUOTE", 1),)


def test_median_uses_all_in_band_iv_rows_before_later_filters():
    rows = (option("a", iv=.10, oi=99), option("b", iv=.20),
            option("c", iv=.30), option("d", iv=.40, oi=99))
    result = select_option(chain(*rows))
    selected = next(score for score in result.scores if score.contract_id == "b")
    assert selected.iv_fit == Decimal("80.0")


def test_full_rank_tuple_ends_with_canonical_contract_id():
    result = select_option(chain(option("b", contract="contract-b"),
                                 option("a", contract="contract-a")))
    assert result.recommendation.contract_id == "contract-a"


@pytest.mark.parametrize("direction,right,delta", (
    ("LONG", "CALL", .50), ("LONG", "CALL", .70),
    ("SHORT", "PUT", -.50), ("SHORT", "PUT", -.70),
))
def test_both_stock_directions_and_signed_delta_boundaries(direction, right, delta):
    stop = 99.0 if direction == "LONG" else 101.0
    supplied = chain(option(right=right, delta=delta), direction=direction, stop=stop)
    assert select_option(supplied).recommendation.status in ("RECOMMENDED", "POOR")


@pytest.mark.parametrize("expiry,expected", (
    (date(2026, 9, 15), "RECOMMENDED"),
    (date(2026, 9, 19), "RECOMMENDED"),
    (date(2026, 9, 20), "POOR"),
))
def test_ordinary_listed_expiry_boundaries(expiry, expected):
    assert select_option(chain(option(expiry=expiry))).recommendation.status == expected


@pytest.mark.parametrize("row_age,expected", ((3, "RECOMMENDED"), (3.000001, "POOR")))
def test_ordinary_quote_age_boundary(row_age, expected):
    assert select_option(chain(option(), row_age=row_age)).recommendation.status == expected


@pytest.mark.parametrize("change,reason", (
    ({"units_proved": False}, "MANDATORY_IN_BAND_FIELD_OR_PROOF_MISSING"),
    ({"greek_snapshot_proved": False}, "MANDATORY_IN_BAND_FIELD_OR_PROOF_MISSING"),
    ({"standard_deliverable_proved": False}, "STANDARD_CONTRACT_PROOF_UNAVAILABLE"),
))
def test_missing_mandatory_proof_is_unavailable(change, reason):
    supplied = OptionRowEvidence(option(), 1, True, True, True)
    result = select_option(replace(chain(option()), rows=(replace(supplied, **change),)))
    assert result.recommendation.status == "UNAVAILABLE"
    assert reason in result.recommendation.reasons


def test_future_option_provider_time_is_unavailable():
    row = option(at=AT + timedelta(microseconds=1))
    result = select_option(chain(row))
    assert result.recommendation.status == "UNAVAILABLE"
    assert "OPTION_IDENTITY_OR_AVAILABILITY_UNAVAILABLE" in result.recommendation.reasons


def test_score_components_and_zero_theta_branches_are_exact():
    result = select_option(chain(option()))
    score = result.scores[0]
    assert (score.spread_fit, score.delta_fit, score.liquidity_fit,
            score.dte_fit, score.iv_fit, score.greek_fit) == (
                Decimal("80.0"), Decimal("100"), Decimal("100.00"),
                Decimal("100"), Decimal("100"), Decimal("50"))
    positive = select_option(chain(option(gamma=.04, theta=0))).scores[0]
    zero = select_option(chain(option(gamma=0, theta=0))).scores[0]
    assert positive.greek_fit == 100 and zero.greek_fit == 0


def test_candidate_fingerprint_is_utf8_stable_and_namespace_sensitive():
    base = portfolio(candidate(structure="structure-é-α"))
    expected = sha256(json.dumps(candidate_key(base), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    assert candidate_fingerprint(base) == expected
    assert candidate_fingerprint(base) == candidate_fingerprint(replace(
        base, candidate=replace(base.candidate, input_record_ids=("input-2", "input-1"))))
    assert candidate_fingerprint(base) != candidate_fingerprint(replace(base, research_arm_id="other"))


def test_complete_batch_is_reception_order_invariant_and_anchor_does_not_chain():
    a = portfolio(candidate("a", created=AT, trigger=100, stop=99))
    b = portfolio(candidate("b", strategy="HOD_COMP_RS", created=AT + timedelta(seconds=180),
                            trigger=100.5, stop=99.5))
    c = portfolio(candidate("c", strategy="FIRST_PULLBACK_VWAP",
                            created=AT + timedelta(seconds=360), trigger=101, stop=100))
    first = project_portfolio(manifest(c, b, a))
    second = project_portfolio(manifest(a, c, b))
    assert first.to_json() == second.to_json()
    assert [len(group.member_fingerprints) for group in first.groups] == [2, 1]


def test_incomplete_batch_refuses_projection_but_retains_candidates():
    result = project_portfolio(manifest(portfolio(candidate()), complete=False))
    assert result.status == "GROUPING_UNAVAILABLE"
    assert result.retained_candidate_ids == ("candidate",)


def test_missing_recovery_facts_refuse_a_favourable_projection():
    row = portfolio(candidate())
    result = project_portfolio(manifest(replace(row, recovery=None)))
    assert result.status == "GROUPING_UNAVAILABLE"
    assert result.unavailable_reasons == ("RECOVERY_FACTS_UNAVAILABLE",)


def test_bare_checked_finding_is_not_original_release_proof():
    orb, reversal, declared = transition_fixture("LONG", "reversal")
    checked = interaction_report(orb, reversal, transitions=(declared,)).transitions[0]
    with pytest.raises(RecordError, match="original producer evidence"):
        manifest(portfolio(orb), portfolio(reversal), releases=(checked,))


def test_changed_canonical_release_value_cannot_transfer_owner():
    orb, reversal, _, release = transition_fixture(
        "LONG", "reversal", release_originals=True)
    source = next(row for row in release.supporting_records
                  if row.record_id == release.reversal_request.last_trade.record_id)
    changed = replace(source, last=source.last + 1)
    bad = replace(release, supporting_records=tuple(
        changed if row.record_id == changed.record_id else row
        for row in release.supporting_records))
    result = project_portfolio(manifest(
        portfolio(orb), portfolio(reversal), releases=(bad,)))
    assert len(result.groups) == 2
    assert all(group.release_record_id is None for group in result.groups)


def test_forged_nested_pass_cannot_hide_a_real_outside_range_close():
    orb, reversal, _, release = transition_fixture(
        "LONG", "reversal", release_originals=True)
    close = release.handoff_request.minute_close
    outside = replace(close, close=orb.trigger_price + 1)
    source = next(row for row in release.supporting_records if row.record_id == close.record_id)
    outside_source = replace(source, open=outside.close, high=outside.close,
                             low=outside.close, close=outside.close)
    bad = replace(
        release,
        handoff_request=replace(release.handoff_request, minute_close=outside),
        supporting_records=tuple(outside_source if row.record_id == source.record_id else row
                                 for row in release.supporting_records))
    result = project_portfolio(manifest(
        portfolio(orb), portfolio(reversal), releases=(bad,)))
    assert len(result.groups) == 2
    assert all(group.release_record_id is None for group in result.groups)


def test_opposite_direction_is_a_conflict_without_comparable_score_arbitration():
    long = portfolio(candidate("long"))
    short = portfolio(candidate("short", strategy="OR_FAILURE_REV", direction="SHORT", stop=101))
    result = project_portfolio(manifest(long, short))
    assert result.status == "RECORDED"
    assert len(result.groups) == 2
    # Equal mechanical times and priority tiers use the frozen fingerprint tie.
    incumbent, challenger = sorted((candidate_fingerprint(long), candidate_fingerprint(short)))
    assert result.groups[0].primary_fingerprint == incumbent
    assert result.groups[0].member_fingerprints == (incumbent,)
    assert result.groups[0].conflicts == (challenger,)
    assert result.groups[1].primary_fingerprint == challenger
    assert result.groups[1].member_fingerprints == (challenger,)
    assert result.groups[1].conflicts == ()
    assert all(group.confluence_fingerprints == () for group in result.groups)
    assert result.retained_candidate_ids == ("long", "short")
    assert result.to_json() == project_portfolio(manifest(short, long)).to_json()


@pytest.mark.parametrize("incumbent_direction", ("LONG", "SHORT"))
def test_earlier_opposite_candidate_keeps_ownership_despite_higher_challenger_score(incumbent_direction):
    challenger_direction = "SHORT" if incumbent_direction == "LONG" else "LONG"
    incumbent = portfolio(candidate("incumbent", direction=incumbent_direction,
                                    stop=99 if incumbent_direction == "LONG" else 101))
    challenger = portfolio(replace(candidate(
        "challenger", strategy="OR_FAILURE_REV", direction=challenger_direction,
        stop=99 if challenger_direction == "LONG" else 101,
        created=AT + timedelta(seconds=1)),
        confidence=ConfidenceBreakdown(95, 95, 95, 95)))
    result = project_portfolio(manifest(challenger, incumbent))
    assert result.status == "RECORDED"
    assert len(result.groups) == 2
    assert result.groups[0].primary_fingerprint == candidate_fingerprint(incumbent)
    assert result.groups[0].member_fingerprints == (candidate_fingerprint(incumbent),)
    assert result.groups[0].conflicts == (candidate_fingerprint(challenger),)
    assert result.groups[1].primary_fingerprint == candidate_fingerprint(challenger)
    assert result.retained_candidate_ids == ("challenger", "incumbent")
    assert result.to_json() == project_portfolio(manifest(incumbent, challenger)).to_json()


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_checked_orb_failure_release_transfers_the_recording_primary(direction):
    orb, reversal, declared, release = transition_fixture(
        direction, "reversal", release_originals=True)
    checked = interaction_report(orb, reversal, transitions=(declared,)).transitions[0]
    assert checked.status == "ACCEPTED"
    orb_row, reversal_row = portfolio(orb), portfolio(reversal)
    result = project_portfolio(manifest(orb_row, reversal_row, releases=(release,)))
    assert len(result.groups) == 1
    assert result.groups[0].anchor_fingerprint == candidate_fingerprint(orb_row)
    assert result.groups[0].primary_fingerprint == candidate_fingerprint(reversal_row)
    assert result.groups[0].released_from_fingerprint == candidate_fingerprint(orb_row)
    assert result.groups[0].release_record_id == "transition"
    assert result.groups[0].member_fingerprints == (
        candidate_fingerprint(orb_row), candidate_fingerprint(reversal_row))


def test_later_candidate_cannot_borrow_a_moved_reversal_anchor():
    orb, reversal, _, release = transition_fixture(
        "LONG", "reversal", release_originals=True)
    later = replace(candidate(
        "later", strategy="FIRST_PULLBACK_VWAP", direction=reversal.direction,
        created=reversal.created_at + timedelta(seconds=60), trigger=reversal.trigger_price,
        stop=reversal.risk.hard_stop), structure_id="later")
    result = project_portfolio(manifest(
        portfolio(orb), portfolio(reversal), portfolio(later), releases=(release,)))
    assert len(result.groups) == 2
    assert result.groups[0].anchor_fingerprint == candidate_fingerprint(portfolio(orb))
    assert result.groups[0].primary_fingerprint == candidate_fingerprint(portfolio(reversal))
    assert result.groups[1].primary_fingerprint == candidate_fingerprint(portfolio(later))


def test_expiry_and_mechanical_cooldown_boundaries_are_exact():
    row = portfolio(candidate())
    expires = intent_expiry(row)
    assert expires == AT + timedelta(seconds=120)
    assert not intent_is_expired(expires, expires - timedelta(microseconds=1))
    assert intent_is_expired(expires, expires)
    assert not cooldown_allows("HOD_COMP_RS", AT, AT + timedelta(seconds=599))
    assert cooldown_allows("HOD_COMP_RS", AT, AT + timedelta(seconds=600))
    with pytest.raises(RecordError):
        cooldown_allows("FIRST_PULLBACK_VWAP", AT, AT + timedelta(seconds=600))


def test_intent_deadline_uses_original_mechanical_time_not_wrapper_creation():
    alert = candidate(created=AT + timedelta(seconds=20))
    row = replace(portfolio(alert), mechanical_event_available_at=AT)
    assert intent_expiry(row) == AT + timedelta(seconds=120)


def test_projection_json_is_deterministic_and_keeps_every_independent_id():
    orb, reversal, _, release = transition_fixture(
        "LONG", "reversal", release_originals=True)
    rows = (portfolio(orb), portfolio(reversal),
            portfolio(candidate("independent", strategy="HOD_COMP_RS",
                                created=AT + timedelta(minutes=10))))
    result = project_portfolio(manifest(*rows, releases=(release,)))
    selection = select_option(chain(option()))
    recording = {
        "projection": json.loads(result.to_json()),
        "selection": selection.as_dict(),
    }
    assert recording["projection"]["retained_candidate_ids"] == [
        "independent", "orb", "reversal"]
    assert recording["projection"]["groups"][0]["anchor_fingerprint"] != \
        recording["projection"]["groups"][0]["primary_fingerprint"]
    assert recording["projection"]["recovery"]
    assert recording["projection"]["releases"]
    (Path(os.environ["TMPDIR"]) / "m4_7_options_portfolio.json").write_text(
        json.dumps(recording, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False) + "\n")


async def test_complete_projection_and_independent_candidates_persist_atomically(tmp_path):
    store, _ = await open_store(tmp_path / "portfolio.db")
    candidates = (candidate("a"), candidate("b", strategy="HOD_COMP_RS"))
    result = project_portfolio(manifest(*(portfolio(row) for row in candidates)))
    stored = await store.store_portfolio_projection(
        result, candidates, session="2026-09-14", recorded_at=AT)
    assert stored["kind"] == "PORTFOLIO_PROJECTION"
    assert json.loads(stored["record_json"])["retained_candidate_ids"] == ["a", "b"]
    restored = await store.restore_portfolio_projection(result.manifest_hash)
    assert restored["recovery"] == json.loads(result.to_json())["recovery"]
    assert (await store.read("a"))["kind"] == "CANDIDATE"
    with pytest.raises(RecordError, match="retain"):
        await store.store_portfolio_projection(result, candidates[:1],
                                                session="2026-09-14", recorded_at=AT)
    path = tmp_path / "portfolio.db"
    await db.close_db()
    reopened, _ = await open_store(path)
    reopened_facts = await reopened.restore_portfolio_projection(result.manifest_hash)
    assert reopened_facts["manifest_hash"] == result.manifest_hash
    await db.close_db()


async def test_conflicting_candidate_leaves_no_partial_recovery_bundle(tmp_path):
    store, _ = await open_store(tmp_path / "portfolio-conflict.db")
    original = candidate("a")
    await store.append(original, session="2026-09-14", recorded_at=AT)
    changed = replace(original, confidence=ConfidenceBreakdown(80, 80, 80, 80))
    other = candidate("b", strategy="HOD_COMP_RS")
    result = project_portfolio(manifest(portfolio(changed), portfolio(other)))
    with pytest.raises(RecordError, match="conflicts"):
        await store.store_portfolio_projection(
            result, (changed, other), session="2026-09-14", recorded_at=AT)
    assert await store.read("b") is None
    assert await store.read("m47:portfolio:" + result.manifest_hash) is None
    await db.close_db()
