"""Protect the M5.1 typed, append-only research event store.

The store persists supplied immutable facts and full attribution in a temporary
database. Tests verify idempotent replay, conflicting id/fingerprint and
link-kind rejection, atomic rollback, reopen preservation, and that the store
satisfies the injected M4.6 intent/result boundary. No strategy, option ranker,
outcome rule, live sender, or M5.5 recovery is built or claimed here.
"""

from dataclasses import replace
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.alert_delivery import DiscordSink, RenderedAlert, deliver_candidate
from consensus_engine.candidate_assembly import assemble_candidate
from consensus_engine import db
from consensus_engine.event_store import EVENT_STORE_VERSION, ResearchEventStore, TABLE, _links_for
from consensus_engine.opening_range_features import build_opening_range_snapshot
from consensus_engine.trade_alerts_models import (
    Bar, DeliveryRecord, FeatureSnapshot, RecordError,
)
from test_alert_delivery import bound_assembly, candidate, sender
from test_adapters_delivery import _Response, _Session
from test_candidate_assembly import facts
from test_confidence import request
from test_opening_range_features import history
from test_strategy_interface import START


def assembled(row, session):
    return replace(bound_assembly(row, session), candidate=row)


async def open_store(path):
    db.DB_PATH = str(path)
    db._db = None
    conn = await db.init_db()
    return ResearchEventStore(conn), conn


async def test_typed_facts_are_append_only_and_idempotent(tmp_path):
    store, conn = await open_store(tmp_path / "research.db")
    row, session = candidate()
    stored = await store.append(row, session=session.session, recorded_at=row.created_at)
    assert stored["kind"] == "CANDIDATE"
    assert stored["fingerprint"] == hashlib.sha256(row.to_json().encode()).hexdigest()
    again = await store.append(row, session=session.session, recorded_at=row.created_at)
    assert again == stored
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        await conn.execute(f"UPDATE {TABLE} SET record_json='{{}}' WHERE record_id=?", (row.record_id,))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        await conn.execute(f"DELETE FROM {TABLE} WHERE record_id=?", (row.record_id,))
    await db.close_db()


async def test_conflicting_facts_reuse_id_rejected(tmp_path):
    store, _ = await open_store(tmp_path / "conflict.db")
    row, session = candidate()
    await store.append(row, session=session.session, recorded_at=row.created_at)
    changed = replace(row, structure_id="DIFFERENT_STRUCTURE")
    with pytest.raises(RecordError, match="conflicts"):
        await store.append(changed, session=session.session, recorded_at=row.created_at)
    await db.close_db()


async def test_assembly_round_trip_reopen_and_kinds(tmp_path):
    path = tmp_path / "assembly.db"
    store, _ = await open_store(path)
    source = history(changed=lambda bars: [Bar.from_json(row.to_json()) for row in bars])
    opening = build_opening_range_snapshot(record_id="m51-opening", evaluated_at=START,
                                           symbol="SYNTH", instrument_type="EQUITY",
                                           minute_history=source)
    opening = FeatureSnapshot.from_json(opening.to_json())
    supplied = replace(request(direction="LONG", parents=(opening.record_id,)),
                       context=replace(request(direction="LONG").context,
                                       features=(*request(direction="LONG").context.features, opening)))
    assembly = assemble_candidate(**facts(direction="LONG", alert_type="ACTIONABLE", supplied=supplied))
    row = assembly.candidate
    stored = await store.store_assembly(assembly)
    assert stored["kind"] == "CANDIDATE"
    kinds = {item["kind"] for item in await store.read_all()}
    assert {"CANDIDATE", "CONFIGURATION", "FEATURE_SNAPSHOT"} <= kinds
    await db.close_db()
    reopened, _ = await open_store(path)
    after = await reopened.read(row.record_id)
    assert after == stored
    schema = await (await reopened._connection.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version=36")).fetchone()
    assert schema[0] == 1
    await db.close_db()


async def test_intent_and_result_satisfy_injected_delivery_boundary(tmp_path):
    store, _ = await open_store(tmp_path / "delivery.db")
    row, session = candidate()
    transport = _Session([_Response(body={"id": "synthetic-confirmation"})])
    clock = _Clock()
    result = await deliver_candidate(
        row, session=session, assembly=assembled(row, session), record_id="m51-delivery",
        at=START, save_intent=store.save_intent, save_result=store.save_result,
        mode="offline_test", sink=DiscordSink(sender(transport, clock)))
    assert result.record.status == "CONFIRMED_DELIVERED"
    assert (await store.read("m51-delivery"))["kind"] == "DELIVERY"
    assert (await store.read("m51-delivery:started")) is not None
    assert (await store.read("m51-delivery:result")) is not None
    await db.close_db()


async def test_repeat_pending_intent_is_refused(tmp_path):
    store, _ = await open_store(tmp_path / "repeat.db")
    row, session = candidate()
    transport = _Session([_Response(body={"id": "ok"})])
    clock = _Clock()
    await deliver_candidate(
        row, session=session, assembly=assembled(row, session), record_id="m51-delivery-2",
        at=START, save_intent=store.save_intent, save_result=store.save_result,
        mode="offline_test", sink=DiscordSink(sender(transport, clock)))
    pending = DeliveryRecord(record_id="m51-delivery-2", candidate_id=row.record_id,
                             attempted_at=START, sink="recording", status="PENDING")
    with pytest.raises(RecordError, match="conflicts"):
        await store.save_intent(_Intent(pending, assembled(row, session)))
    await db.close_db()


async def test_atomic_rollback_leaves_no_partial_bundle(tmp_path):
    store, conn = await open_store(tmp_path / "rollback.db")
    row, session = candidate()
    await conn.executescript("""
        CREATE TRIGGER m51_forced_failure BEFORE INSERT ON trade_alerts_research_events_v1
        WHEN NEW.kind = 'CANDIDATE' BEGIN
            SELECT RAISE(FAIL, 'synthetic research write failure');
        END;
    """)
    with pytest.raises(sqlite3.IntegrityError, match="synthetic research write failure"):
        await store.save_intent(_Intent(
            DeliveryRecord(record_id="m51-atomic", candidate_id=row.record_id,
                           attempted_at=START, sink="recording", status="PENDING"),
            assembled(row, session)))
    assert await store.read_all() == ()
    assert await store.read("m51-atomic") is None
    await db.close_db()


class _Intent:
    def __init__(self, record, assembly):
        self.record = record
        self.assembly = assembly
        self.rendered = RenderedAlert(assembly.candidate)


class _Clock:
    def __init__(self):
        self.at = START

    def __call__(self):
        return self.at

    async def sleep(self, seconds):
        self.at += timedelta(seconds=seconds)


async def test_full_assembly_retry_and_shared_inputs_are_idempotent(tmp_path):
    store, _ = await open_store(tmp_path / "bundles.db")
    assembly = assemble_candidate(**facts())
    await store.store_assembly(assembly)
    before = await store.read_all()
    await store.store_assembly(assembly)
    assert await store.read_all() == before
    other = assemble_candidate(**facts(record_id="another-candidate"))
    await store.store_assembly(other)
    assert len(await store.read_all()) == len(before) + 2
    envelope = await store.read("m51:assembly:" + assembly.candidate.record_id)
    payload = json.loads(envelope["record_json"])
    assert payload["confidence_result"] == assembly.as_dict()["confidence_result"]
    assert payload["context"] == assembly.as_dict()["context"]
    await db.close_db()


@pytest.mark.parametrize("target_first", (True, False))
async def test_conflicting_link_kind_rejected_in_both_orders(tmp_path, target_first):
    store, _ = await open_store(tmp_path / "links.db")
    row, session = candidate()
    # A configuration record cannot satisfy a feature link, even if it arrives later.
    wrong = replace(session, record_id=row.feature_snapshot_id)
    first, second = (wrong, row) if target_first else (row, wrong)
    await store.append(first, session=session.session, recorded_at=START)
    before = await store.read_all()
    with pytest.raises(RecordError, match="conflicts"):
        await store.append(second, session=session.session, recorded_at=START)
    assert await store.read_all() == before
    await db.close_db()


def primary_feature_pair(assembly, field, target_first):
    candidate = assembly.candidate
    feature = next(row for row in assembly.context.features
                   if row.record_id == candidate.feature_snapshot_id)
    suffix = f"{field}-{target_first}"
    feature_id = f"repair-feature-{suffix}"
    candidate = replace(candidate, record_id=f"repair-candidate-{suffix}",
                        feature_snapshot_id=feature_id,
                        input_record_ids=(feature_id,))
    changes = {"instrument_id": "OTHER", "instrument_type": "ETF",
               "session": "2026-07-07"}
    feature = replace(feature, record_id=feature_id,
                      metadata=replace(feature.metadata, **{field: changes[field]}))
    return (feature, candidate) if target_first else (candidate, feature)


async def reject_primary_feature_mismatch(store, assembly, field, target_first):
    first, second = primary_feature_pair(assembly, field, target_first)
    await store.append(first, session=first.metadata.session, recorded_at=START)
    before = await store.read_all()
    with pytest.raises(RecordError, match="conflicts"):
        await store.append(second, session=second.metadata.session, recorded_at=START)
    assert await store.read_all() == before
    assert await store.read(second.record_id) is None
    if not target_first:
        primary = next(link for link in await store.links(first.record_id)
                       if link["role"] == "FEATURELINK")
        assert primary["status"] == "UNAVAILABLE"
    return {"field": field, "target_first": target_first,
            "rejected": True, "stored_facts_unchanged": True,
            "rejected_record_absent": True}


async def test_primary_feature_identity_rejected_in_both_orders(tmp_path):
    store, _ = await open_store(tmp_path / "primary-link.db")
    assembly = assemble_candidate(**facts())
    for field in ("instrument_id", "instrument_type", "session"):
        for target_first in (True, False):
            await reject_primary_feature_mismatch(store, assembly, field, target_first)
    await db.close_db()


async def test_primary_feature_identity_bundle_rolls_back(tmp_path):
    store, _ = await open_store(tmp_path / "primary-bundle.db")
    assembly = assemble_candidate(**facts())
    for field in ("instrument_id", "instrument_type", "session"):
        for target_first in (True, False):
            first, second = primary_feature_pair(assembly, field, target_first)
            # Include a valid earlier write to prove rollback of the whole bundle.
            records = (assembly.context.session, first, second)
            rows = [store._prepare(row, session=row.metadata.session if hasattr(row, "metadata")
                                   else row.session, recorded_at=START, links=_links_for(row))
                    for row in records]
            before = await store.read_all()
            with pytest.raises(RecordError, match="conflicts"):
                await store._write(rows)
            assert await store.read_all() == before
    await db.close_db()


async def test_missing_links_remain_visible_and_later_resolve(tmp_path):
    store, _ = await open_store(tmp_path / "missing.db")
    assembly = assemble_candidate(**facts())
    row = assembly.candidate
    await store.append(row, session=assembly.context.session.session, recorded_at=START)
    original = await store.read(row.record_id)
    assert all(link["status"] == "UNAVAILABLE" for link in await store.links(row.record_id))
    await store.store_assembly(assembly)
    assert all(link["status"] == "RESOLVED" for link in await store.links(row.record_id))
    assert await store.read(row.record_id) == original
    await db.close_db()


async def test_conflicting_link_inside_bundle_rolls_back(tmp_path):
    store, _ = await open_store(tmp_path / "bundle-links.db")
    assembly = assemble_candidate(**facts())
    # Feature ancestry may refer to raw inputs or features, never configuration.
    features = tuple(replace(row, input_record_ids=(*row.input_record_ids,
                            assembly.context.session.record_id))
                     for row in assembly.context.features)
    # Exercise the transaction directly with canonical facts, so the kind
    # check must work even when its target is part of this same transaction.
    rows = [store._prepare(assembly.context.session, session=assembly.context.session.session,
                          recorded_at=START)]
    rows += [store._prepare(row, session=row.metadata.session, recorded_at=START,
                           links=[(assembly.context.session.record_id, "INPUTLINK")])
             for row in features]
    with pytest.raises(RecordError, match="conflicts"):
        await store._write(rows)
    assert await store.read_all() == ()
    await db.close_db()


async def test_session_conflict_and_changed_bundle_do_not_mutate_facts(tmp_path):
    store, _ = await open_store(tmp_path / "identity.db")
    assembly = assemble_candidate(**facts())
    await store.store_assembly(assembly)
    before = await store.read_all()
    with pytest.raises(RecordError, match="session"):
        await store.append(assembly.candidate, session="2026-07-07", recorded_at=START)
    altered = replace(assembly, reasons=("ALTERED",))
    with pytest.raises(RecordError):
        await store.store_assembly(altered)
    assert await store.read_all() == before
    await db.close_db()


async def test_same_pending_intent_cannot_send_twice(tmp_path):
    store, _ = await open_store(tmp_path / "no-resend.db")
    row, session = candidate()
    assembly = assembled(row, session)
    await deliver_candidate(row, session=session, assembly=assembly, record_id="no-resend",
                            at=START, save_intent=store.save_intent, save_result=store.save_result)
    before = await store.read_all()
    with pytest.raises(RecordError, match="conflicts"):
        await deliver_candidate(row, session=session, assembly=assembly, record_id="no-resend",
                                at=START, save_intent=store.save_intent,
                                save_result=store.save_result)
    assert await store.read_all() == before
    await db.close_db()


async def test_all_supported_canonical_kinds_reopen_without_losing_bytes(tmp_path):
    from test_domain_models import _all_records
    supported = {"SessionRecord", "Bar", "Quote", "OptionQuote", "CatalystEvent",
                 "FeatureSnapshot", "StrategyStateTransition", "AlertCandidate",
                 "SuppressionEvent", "OptionRecommendation", "DeliveryRecord"}
    records = [row for row in _all_records() if type(row).__name__ in supported]
    session_record = next(row for row in records if type(row).__name__ == "SessionRecord")
    records = [replace(row, config_hash=session_record.config_hash)
               if type(row).__name__ == "AlertCandidate" else row for row in records]
    path = tmp_path / "all-kinds.db"
    store, _ = await open_store(path)
    for row in records:
        session = row.metadata.session if hasattr(row, "metadata") else getattr(row, "session", "2026-07-06")
        await store.append(row, session=session, recorded_at=START)
    before = await store.read_all()
    assert len(before) == len(supported)
    for row in records:
        assert (await store.read(row.record_id))["record_json"] == row.to_json()
    await db.close_db()
    store, _ = await open_store(path)
    assert await store.read_all() == before
    await db.close_db()


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
async def test_recording_pipeline_retains_full_facts_retry_and_reopen(tmp_path, direction):
    from consensus_engine.trade_alerts_models import ConfluenceLink, OptionRecommendation
    from test_candidate_assembly import suppression
    source = history(changed=lambda bars: [Bar.from_json(row.to_json()) for row in bars])
    opening = build_opening_range_snapshot(record_id="m51-opening", evaluated_at=START,
                                           symbol="SYNTH", instrument_type="EQUITY",
                                           minute_history=source)
    supplied = request(direction=direction, parents=(opening.record_id,))
    supplied = replace(supplied, context=replace(supplied.context,
                       features=(*supplied.context.features, opening)))
    component = assemble_candidate(**facts(direction=direction, supplied=supplied,
                                           record_id="m51-component")).candidate
    assembly = assemble_candidate(**facts(
        direction=direction, supplied=supplied, component_candidates=(component,),
        confluence=(ConfluenceLink(component.strategy_id, component.record_id),)))
    row, session = assembly.candidate, assembly.context.session
    options = OptionRecommendation(record_id="m51-options", candidate_id=row.record_id,
                                   status="UNAVAILABLE", ranked_at=START,
                                   reasons=("NO_SUPPLIED_CHAIN",), policy_version="FIXTURE_ONLY")
    path = tmp_path / "pipeline.db"
    store, _ = await open_store(path)
    await store.store_history(source, record_id="m51-history", session=session.session,
                              recorded_at=START)
    assert json.loads((await store.read("m51-history"))["record_json"]) == {
        "store_version": EVENT_STORE_VERSION, **source.as_dict()}
    await store.store_history(source, record_id="m51-history", session=session.session,
                              recorded_at=START)
    await store.store_assembly(assembly)
    saved = await store.read_all()
    await store.store_assembly(assembly)
    assert await store.read_all() == saved
    result = await deliver_candidate(row, session=session, assembly=assembly,
                                     record_id="m51-recording", at=START, options=options,
                                     save_intent=store.save_intent, save_result=store.save_result)
    suppressed = suppression(assembly.context, row, record_id="m51-suppression")
    await store.append(suppressed, session=session.session, recorded_at=START)
    assert (await store.read(component.record_id))["record_json"] == component.to_json()
    assert (await store.read(suppressed.record_id))["record_json"] == suppressed.to_json()
    assert result.reason == "RECORDING_ONLY"
    assert result.record.status == "REJECTED_BEFORE_SEND"
    assert row.confidence.final_score == 66
    assert row.risk.risk_per_share == 1
    assert row.targets[0].r_multiple == 2
    envelope = json.loads((await store.read("m51:intent:m51-recording"))["record_json"])
    assert envelope["assembly"] == assembly.as_dict()
    assert envelope["options"] == options.as_dict()
    assert envelope["text"] == result.rendered.text
    receipt = json.loads((await store.read("m51:result:" + result.record.record_id))["record_json"])
    assert receipt == {"store_version": EVENT_STORE_VERSION, **result.as_dict()}
    before = await store.read_all()
    await store.save_result(result)
    assert await store.read_all() == before
    await db.close_db()
    reopened, _ = await open_store(path)
    assert await reopened.read_all() == before
    assert (await reopened.read(row.record_id))["record_json"] == row.to_json()
    proof = {"store_version": EVENT_STORE_VERSION, "direction": direction,
             "candidate": row.as_dict(), "options": options.as_dict(),
             "delivery": result.as_dict(), "full_assembly_preserved": True,
             "reopen_equal": True, "row_count": len(before),
             "stored": [{"id": item["record_id"], "kind": item["kind"],
                         "fingerprint": item["fingerprint"],
                         "links": list(await reopened.links(item["record_id"]))}
                        for item in before]}
    proof["primary_feature_rejections"] = [
        await reject_primary_feature_mismatch(reopened, assembly, field, target_first)
        for field in ("instrument_id", "instrument_type", "session")
        for target_first in (True, False)]
    after_rejections = await reopened.read_all()
    await db.close_db()
    reopened, _ = await open_store(path)
    assert await reopened.read_all() == after_rejections
    assert (await reopened.read(row.record_id))["record_json"] == row.to_json()
    proof["rejection_reopen_equal"] = True
    text = json.dumps(proof, sort_keys=True, separators=(",", ":"))
    assert len(text.encode()) < 100_000
    Path(f"/tmp/m51-research-event-store-{direction.lower()}-proof.json").write_text(text)
    await db.close_db()


@pytest.mark.parametrize("target_first", (True, False))
@pytest.mark.parametrize("role", ("configuration", "option"))
async def test_same_kind_wrong_identity_cannot_resolve_link(tmp_path, target_first, role):
    from test_domain_models import _all_records, _option_quote
    store, _ = await open_store(tmp_path / "wrong-identity.db")
    if role == "configuration":
        original, target = candidate()
        linked = replace(original, config_hash="b" * 64)
    else:
        linked = next(row for row in _all_records() if type(row).__name__ == "OptionRecommendation")
        target = _option_quote()
        linked = replace(linked, contract_id="OTHER  260710C00100000")
    first, second = (target, linked) if target_first else (linked, target)
    await store.append(first, session="2026-07-06", recorded_at=START)
    before = await store.read_all()
    with pytest.raises(RecordError, match="conflicts"):
        await store.append(second, session="2026-07-06", recorded_at=START)
    assert await store.read_all() == before
    await db.close_db()


async def test_two_store_owners_cannot_overwrite_same_id(tmp_path):
    import asyncio
    store, conn = await open_store(tmp_path / "concurrent.db")
    other = ResearchEventStore(conn)
    row, session = candidate()
    changed = replace(row, structure_id="OTHER_STRUCTURE")
    outcomes = await asyncio.gather(
        store.append(row, session=session.session, recorded_at=START),
        other.append(changed, session=session.session, recorded_at=START),
        return_exceptions=True)
    assert sum(isinstance(item, RecordError) for item in outcomes) == 1
    saved = await store.read(row.record_id)
    assert saved["record_json"] in (row.to_json(), changed.to_json())
    assert len(await store.read_all()) == 1
    await db.close_db()
