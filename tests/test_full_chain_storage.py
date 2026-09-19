from __future__ import annotations

from datetime import date, datetime, timedelta
from dataclasses import replace
from zoneinfo import ZoneInfo
from types import SimpleNamespace
import errno
import hashlib
import json
import os
from pathlib import Path

import pandas as pd
import pytest
import consensus_engine.full_chain_storage as storage

from consensus_engine.full_chain_storage import (
    OutputBounds,
    StorageContractError,
    StoragePolicy,
    check_admission,
    plan_retention,
    pointer_path,
    publish_option_set,
    read_published_option_set,
    recover_option_set,
    working_space_bytes,
)


DAY = date(2026, 8, 31)
BOUNDS = OutputBounds(2_000_000, 1_000_000, 100_000, 4096)
POLICY = StoragePolicy(enabled=True, fixed_reserve_bytes=100,
                       reserve_fraction=.15, peak_memory_bytes=1_500_000_000,
                       batch_bytes=1_000_000, wall_seconds=60)
CHECKPOINTS = (
    "bounded_reading",
    "chain_temporary_write", "chain_temporary_flush", "chain_rename",
    "after_chain_before_open_interest",
    "open_interest_temporary_write", "open_interest_temporary_flush", "open_interest_rename",
    "after_open_interest_before_proof",
    "proof_temporary_write", "proof_temporary_flush", "proof_rename",
    "after_members_before_pointer", "set_directory_flush",
    "pointer_temporary_write", "pointer_temporary_flush", "pointer_rename",
    "pointer_parent_directory_flush",
)


def _rows(captured="2026-08-31T13:31:00+00:00", oi=100):
    return pd.DataFrame([{
        "market_date": DAY.isoformat(), "captured_at_utc": captured,
        "ticker": "AAPL", "contract_symbol": "AAPL-C100", "expiration": "2026-09-04",
        "strike_price": 100.0, "option_type": "CALL", "open_interest": oi,
        "bid": 1.0, "ask": 1.2,
    }])


def _part(root: Path, name: str, frame=None) -> Path:
    path = root / "option_parts" / DAY.isoformat() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    (frame if frame is not None else _rows()).to_parquet(path, index=False)
    return path


def _publish(root: Path, parts, **kwargs):
    return publish_option_set(root, DAY, parts, bounds=BOUNDS, policy=POLICY,
                              free_bytes=20_000_000, capacity_bytes=20_000_000,
                              **kwargs)


def _member_bytes(result):
    folder = Path(result["set_directory"])
    pointer = Path(result["pointer"])
    return tuple((folder / name).read_bytes() for name in
                 ("chain.parquet", "open_interest.parquet", "proof.json")) + (pointer.read_bytes(),)


def test_compaction_source_and_compact_records_match(tmp_path):
    first = _part(tmp_path, "093100.parquet", _rows(oi=100))
    duplicate = pd.concat([_rows(oi=101), _rows("2026-08-31T13:32:00+00:00", 102)])
    second = _part(tmp_path, "093200.parquet", duplicate)
    result = _publish(tmp_path, [first, second])
    proof = result["proof"]
    chain = pd.read_parquet(Path(result["set_directory"]) / "chain.parquet")
    oi = pd.read_parquet(Path(result["set_directory"]) / "open_interest.parquet")
    assert len(chain) == 2 and list(chain["open_interest"]) == [101, 102]
    assert len(oi) == 1 and oi.iloc[0]["open_interest"] == 102
    assert [item["path"] for item in proof["sources"]] == [first.relative_to(tmp_path).as_posix(), second.relative_to(tmp_path).as_posix()]
    assert first.exists() and second.exists()
    assert proof["chain"]["rows"] == 2 and proof["open_interest"]["rows"] == 1


def test_compaction_retry_reopens_to_identical_output(tmp_path):
    part = _part(tmp_path, "093100.parquet")
    first = _publish(tmp_path, [part])
    before = _member_bytes(first)
    second = _publish(tmp_path, [part])
    assert second["set_id"] == first["set_id"]
    assert _member_bytes(second) == before
    _part(tmp_path, "093100.parquet", _rows(oi=999))
    changed = _publish(tmp_path, [part])
    assert changed["set_id"] != first["set_id"]


@pytest.mark.parametrize("checkpoint_name", CHECKPOINTS)
@pytest.mark.parametrize("with_prior", (False, True), ids=("without-prior", "with-prior"))
def test_compaction_interruption_preserves_parts_and_previous_output(
    tmp_path, checkpoint_name, with_prior, request
):
    old = _part(tmp_path, "093100.parquet")
    prior = _publish(tmp_path, [old]) if with_prior else None
    prior_bytes = _member_bytes(prior) if prior else None
    new = _part(tmp_path, "093200.parquet", _rows("2026-08-31T13:32:00+00:00", 200))
    def stop(name):
        if name == checkpoint_name:
            raise InterruptedError("synthetic stop")
    with pytest.raises(InterruptedError, match="synthetic stop"):
        _publish(tmp_path, [old, new], checkpoint=stop)
    visible = read_published_option_set(tmp_path, DAY)
    if visible is None and prior is None:
        pass
    elif visible is not None and prior is not None and visible["set_id"] == prior["set_id"]:
        assert _member_bytes(visible) == prior_bytes
    else:
        # A stop after pointer replacement may expose the complete new set.
        assert checkpoint_name in ("pointer_parent_directory_flush",)
        assert visible is not None
    assert old.exists() and new.exists()
    if prior:
        assert tuple((Path(prior["set_directory"]) / name).read_bytes() for name in
                     ("chain.parquet", "open_interest.parquet", "proof.json")) == prior_bytes[:3]
    _record_recovery(checkpoint_name, with_prior, [old, new], prior, visible,
                     "interruption" if "stop" in locals() else "disk-full", request.node.nodeid)


def test_compaction_recovers_or_rejects_stale_temporary_file(tmp_path):
    part = _part(tmp_path, "093100.parquet")
    published = _publish(tmp_path, [part])
    pointer = pointer_path(tmp_path, DAY)
    folder = Path(published["set_directory"])
    stale = folder / "chain.parquet.tmp"
    stale.write_bytes(b"stale")
    assert read_published_option_set(tmp_path, DAY)["set_id"] == published["set_id"]
    proof = folder / "proof.json"
    original = proof.read_bytes()
    proof.write_bytes(b"corrupt")
    assert read_published_option_set(tmp_path, DAY) is None
    proof.write_bytes(original)
    assert read_published_option_set(tmp_path, DAY)["set_id"] == published["set_id"]
    assert pointer.exists() and part.exists() and stale.exists()


@pytest.mark.parametrize("checkpoint_name", CHECKPOINTS)
@pytest.mark.parametrize("with_prior", (False, True), ids=("without-prior", "with-prior"))
def test_compaction_disk_full_never_deletes_or_replaces_verified_data(
    tmp_path, checkpoint_name, with_prior, request
):
    old = _part(tmp_path, "093100.parquet")
    prior = _publish(tmp_path, [old]) if with_prior else None
    pointer_before = Path(prior["pointer"]).read_bytes() if prior else None
    prior_bytes = _member_bytes(prior) if prior else None
    new = _part(tmp_path, "093200.parquet", _rows("2026-08-31T13:32:00+00:00", 200))
    def full(name):
        if name == checkpoint_name:
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
    with pytest.raises(OSError) as error:
        _publish(tmp_path, [old, new], checkpoint=full)
    assert error.value.errno == errno.ENOSPC
    visible = read_published_option_set(tmp_path, DAY)
    if visible is None and prior is None:
        pass
    elif prior is not None and visible is not None and visible["set_id"] == prior["set_id"]:
        assert Path(prior["pointer"]).read_bytes() == pointer_before
    else:
        assert checkpoint_name in ("pointer_parent_directory_flush",)
        assert visible is not None
    assert old.exists() and new.exists()
    if prior:
        assert tuple((Path(prior["set_directory"]) / name).read_bytes() for name in
                     ("chain.parquet", "open_interest.parquet", "proof.json")) == prior_bytes[:3]
    _record_recovery(checkpoint_name, with_prior, [old, new], prior, visible,
                     "interruption" if "stop" in locals() else "disk-full", request.node.nodeid)


def test_storage_reserve_refuses_write_before_crossing_limit():
    bounds = OutputBounds(10, 20, 30, 40)
    policy = StoragePolicy(enabled=True, fixed_reserve_bytes=100, reserve_fraction=.15)
    needed = 2 * (10 + 20 + 30 + 40) + 5 + 6
    exact = check_admission(free=100 + needed, capacity=500, source=1,
                            bounds=bounds, existing=5, temporary=6, policy=policy)
    below = check_admission(free=99 + needed, capacity=500, source=1,
                            bounds=bounds, existing=5, temporary=6, policy=policy)
    assert exact["admitted"] is True and exact["working_bytes"] == needed
    assert below["admitted"] is False
    with pytest.raises(StorageContractError, match="known nonnegative"):
        OutputBounds(10, 20, -1, 40)


def test_retention_dry_run_respects_age_hold_and_partial_date(tmp_path):
    old_day = DAY - timedelta(days=8)
    part = tmp_path / "option_parts" / old_day.isoformat() / "093100.parquet"
    part.parent.mkdir(parents=True)
    _rows().assign(market_date=old_day.isoformat()).to_parquet(part, index=False)
    # A part without a complete published set is never eligible.
    assert plan_retention(tmp_path, today=DAY) == []
    marker = tmp_path / f".notified-{(DAY - timedelta(days=30)).isoformat()}"
    marker.touch()
    assert plan_retention(tmp_path, today=DAY) == [
        {"path": str(marker.resolve()), "reason": "notification marker older than 30 days"}
    ]
    assert plan_retention(tmp_path, today=DAY, legal_holds=[marker]) == []


def test_compaction_stays_inside_memory_batch_and_time_budgets(tmp_path):
    part = _part(tmp_path, "093100.parquet")
    more = [_part(tmp_path, f"multi-{i:02}.parquet", _rows(f"2026-08-31T13:{i+32:02}:00+00:00", i))
            for i in range(12)]
    result = _publish(tmp_path, [part, *more])
    assert result["option_rows"] == 13
    assert result["output_bytes"]["scratch"] <= BOUNDS.chain
    Path("/tmp/m02b-full-chain-storage-measurements.json").write_text(json.dumps({
        "synthetic_only": True,
        "source_bytes": sum(path.stat().st_size for path in [part, *more]),
        "output_bytes": result["output_bytes"],
        "peak_memory_bytes": result["peak_memory_bytes"],
        "elapsed_seconds": result["elapsed_seconds"],
    }, sort_keys=True) + "\n")
    assert result["elapsed_seconds"] <= POLICY.wall_seconds
    assert result["peak_memory_bytes"] <= POLICY.peak_memory_bytes
    tiny = StoragePolicy(enabled=True, fixed_reserve_bytes=0, reserve_fraction=0,
                         peak_memory_bytes=1_500_000_000, batch_bytes=1,
                         wall_seconds=60)
    other_part = _part(tmp_path / "other", "093100.parquet")
    with pytest.raises(StorageContractError, match="source batch"):
        publish_option_set(tmp_path / "other", DAY, [other_part], bounds=BOUNDS, policy=tiny,
                           free_bytes=20_000_000, capacity_bytes=20_000_000)




RECOVERY_RECORDS = []


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_recovery(checkpoint_name, with_prior, sources, prior, visible, state, case_id):
    RECOVERY_RECORDS.append({
        "case_id": case_id, "checkpoint": checkpoint_name, "with_prior": with_prior, "state": state,
        "reader_visible_set_id": visible["set_id"] if visible else None,
        "prior_set_id": prior["set_id"] if prior else None,
        "source_hashes": {p.name: _hash(p) if p.exists() else None for p in sources},
        "prior_pointer_sha256": hashlib.sha256(storage._fixed_json({
            "contract_version": storage.CONTRACT_VERSION, "market_date": DAY.isoformat(),
            "set_id": prior["set_id"],
            "manifest_sha256": hashlib.sha256(storage._fixed_json(prior["proof"])).hexdigest(),
        })).hexdigest() if prior else None,
        "expected_prior_member_hashes": {
            "chain.parquet": prior["proof"]["chain"]["sha256"],
            "open_interest.parquet": prior["proof"]["open_interest"]["sha256"],
            "proof.json": hashlib.sha256(storage._fixed_json(prior["proof"])).hexdigest(),
        } if prior else {},
        "expected_prior_source_hashes": {item["path"]: item["sha256"]
                                         for item in prior["proof"]["sources"]} if prior else {},
        "reader_visible_member_hashes": {
            name: _hash(Path(visible["set_directory"]) / name)
            for name in ("chain.parquet", "open_interest.parquet", "proof.json")
        } if visible else {},
        "retained_prior_member_hashes": {
            name: _hash(Path(prior["set_directory"]) / name)
            for name in ("chain.parquet", "open_interest.parquet", "proof.json")
        } if prior else {},
    })


@pytest.mark.parametrize("missing", ["column", "null"])
@pytest.mark.parametrize("with_prior", [False, True])
def test_missing_open_interest_never_publishes(tmp_path, missing, with_prior):
    old = _part(tmp_path, "old.parquet")
    prior = _publish(tmp_path, [old]) if with_prior else None
    before = _member_bytes(prior) if prior else None
    frame = _rows(oi=None)
    if missing == "column":
        frame = frame.drop(columns="open_interest")
    new = _part(tmp_path, "new.parquet", frame)
    result = _publish(tmp_path, [new])
    assert result["published"] is False and result["missing_data"] is True
    assert result["proof"]["complete"] is False
    assert pd.read_parquet(Path(result["set_directory"]) / "open_interest.parquet").empty
    if prior:
        assert _member_bytes(prior) == before
        assert recover_option_set(tmp_path, DAY)["set_id"] == prior["set_id"]
    else:
        assert recover_option_set(tmp_path, DAY) is None
        assert not pointer_path(tmp_path, DAY).exists()
    assert not plan_retention(tmp_path, today=DAY + timedelta(days=800))


def test_tied_rows_keep_last_in_sorted_part_and_row_order(tmp_path):
    a = _part(tmp_path, "a.parquet", pd.concat([_rows(oi=1), _rows(oi=2)]))
    b = _part(tmp_path, "b.parquet", pd.concat([_rows(oi=3), _rows(oi=4)]))
    result = _publish(tmp_path, [b, a])
    for member in ("chain", "open_interest"):
        actual = pd.read_parquet(Path(result["set_directory"]) / f"{member}.parquet")
        expected = _rows(oi=4)
        if member == "open_interest":
            expected = expected[storage.OI_COLUMNS]
        pd.testing.assert_frame_equal(actual, expected)
        assert result["proof"][member]["record_sha256"] == storage._record_hash(expected)


@pytest.mark.parametrize("field", ["chain", "open_interest", "proof", "publication"])
def test_each_output_bound_stops_before_publication(tmp_path, field):
    old = _part(tmp_path, "old.parquet")
    prior = _publish(tmp_path, [old])
    before = _member_bytes(prior)
    new = _part(tmp_path, "new.parquet", _rows(oi=2))
    with pytest.raises(StorageContractError, match="byte bound|scratch merge"):
        publish_option_set(tmp_path, DAY, [old, new], bounds=replace(BOUNDS, **{field: 1}),
                           policy=POLICY, free_bytes=20_000_000, capacity_bytes=20_000_000)
    assert _member_bytes(prior) == before
    assert recover_option_set(tmp_path, DAY)["set_id"] == prior["set_id"]
    assert old.exists() and new.exists()


@pytest.mark.parametrize("term", ["chain", "open_interest", "proof", "publication", "existing", "temporary"])
def test_every_admission_term_is_required(term):
    bounds = OutputBounds(10, 20, 30, 40)
    args = dict(source=1, bounds=bounds, existing=5, temporary=6)
    before = working_space_bytes(**args)
    if term in ("existing", "temporary"):
        args[term] += 1
        expected = 1
    else:
        args["bounds"] = replace(bounds, **{term: getattr(bounds, term) + 1})
        expected = 2
    assert working_space_bytes(**args) == before + expected
    assert working_space_bytes(1000, OutputBounds(1, 1, 1, 1), 0, 0) == 2250
    # A source multiplier alone does not cover expanded complete outputs.
    assert before > 2.25 * args["source"]


@pytest.mark.parametrize("bad", [None, -1, 1.5, True])
@pytest.mark.parametrize("term", ["chain", "open_interest", "proof", "publication", "existing", "temporary"])
def test_unknown_or_invalid_admission_terms_block(term, bad):
    with pytest.raises(StorageContractError, match="known nonnegative"):
        if term in ("existing", "temporary"):
            working_space_bytes(1, BOUNDS, **{term: bad, "temporary" if term == "existing" else "existing": 0})
        else:
            replace(BOUNDS, **{term: bad})


@pytest.mark.parametrize("capacity, reserve", [(500, 100), (1000, 150)])
def test_fixed_and_fraction_reserves_allow_exact_boundary(capacity, reserve):
    bounds = OutputBounds(1, 1, 1, 1)
    for offset, admitted in [(0, True), (-1, False)]:
        result = check_admission(free=reserve + 8 + offset, capacity=capacity,
                                 source=1, bounds=bounds, policy=POLICY)
        assert result["reserve_bytes"] == reserve
        assert result["admitted"] is admitted


def test_retained_and_temporary_bytes_are_discovered_without_caller_counts(tmp_path):
    part = _part(tmp_path, "a.parquet")
    prior = _publish(tmp_path, [part])
    stale = tmp_path / "option_sets" / "2020-01-01" / "sets" / "incomplete" / "chain.parquet.tmp"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"unpublished" * 100)
    legacy = tmp_path / "option_chains" / "old.parquet"
    legacy.parent.mkdir()
    legacy.write_bytes(b"legacy retained output")
    existing, temporary = storage._inventory(tmp_path)
    assert existing >= sum(len(b) for b in _member_bytes(prior)) + legacy.stat().st_size
    assert temporary >= stale.stat().st_size
    new = _part(tmp_path, "b.parquet", _rows(oi=2))
    result = _publish(tmp_path, [part, new])
    assert result["admission"]["working_bytes"] == working_space_bytes(
        part.stat().st_size + new.stat().st_size, BOUNDS, existing, temporary)
    # An understated caller allowance cannot replace either observed term.
    with pytest.raises(StorageContractError, match="reserve"):
        publish_option_set(tmp_path, DAY, [part, new], bounds=BOUNDS, policy=POLICY,
                           free_bytes=2 * sum((BOUNDS.chain, BOUNDS.open_interest, BOUNDS.proof, BOUNDS.publication)) + 100,
                           capacity_bytes=1, existing_bytes=0, temporary_bytes=0)


@pytest.mark.parametrize("point", ["chain_temporary_write", "open_interest_temporary_write", "proof_temporary_write", "pointer_temporary_write"])
def test_reserve_is_rechecked_at_each_output_write(tmp_path, monkeypatch, point):
    part = _part(tmp_path, "a.parquet")
    prior = _publish(tmp_path, [part])
    before = _member_bytes(prior)
    new = _part(tmp_path, "b.parquet", _rows(oi=2))
    free = [20_000_000]
    monkeypatch.setattr(storage.os, "statvfs", lambda _: SimpleNamespace(
        f_bavail=free[0], f_frsize=1, f_blocks=20_000_000))
    def drop(name):
        if name == point:
            free[0] = 100
    with pytest.raises(StorageContractError, match="reserve"):
        publish_option_set(tmp_path, DAY, [part, new], bounds=BOUNDS, policy=POLICY, checkpoint=drop)
    assert _member_bytes(prior) == before


@pytest.mark.parametrize("failure", ["peak", "time"])
@pytest.mark.parametrize("point", ["bounded_reading", "chain_temporary_write", "open_interest_temporary_write", "proof_temporary_write", "pointer_temporary_write"])
def test_forced_resource_limit_stops_before_changing_prior(tmp_path, monkeypatch, failure, point):
    old = _part(tmp_path, "a.parquet")
    prior = _publish(tmp_path, [old])
    before = _member_bytes(prior)
    parts = [old] + [_part(tmp_path, f"b{i}.parquet", _rows(oi=i)) for i in range(4)]
    breached = [False]
    monkeypatch.setattr(storage, "_peak_bytes", lambda: POLICY.peak_memory_bytes + 1 if breached[0] and failure == "peak" else 1)
    monkeypatch.setattr(storage.time, "monotonic", lambda: 1000 if breached[0] and failure == "time" else 0)
    def breach(name):
        if name == point:
            breached[0] = True
    with pytest.raises(StorageContractError, match="peak-memory|wall-time"):
        _publish(tmp_path, parts, checkpoint=breach)
    assert _member_bytes(prior) == before
    assert all(path.exists() for path in parts)


@pytest.mark.parametrize("change", ["missing", "changed", "proof-conflict"])
def test_current_source_identities_gate_reader_recovery_and_retention(tmp_path, change, request):
    part = _part(tmp_path, "a.parquet")
    prior = _publish(tmp_path, [part], complete_day=True)
    before = _member_bytes(prior)
    if change == "missing":
        part.rename(part.with_suffix(".held"))
    elif change == "changed":
        _part(tmp_path, "a.parquet", _rows(oi=999))
    else:
        proof_path = Path(prior["set_directory"]) / "proof.json"
        proof = json.loads(proof_path.read_text())
        proof["sources"][0]["sha256"] = "0" * 64
        proof_path.write_bytes(storage._fixed_json(proof))
        pointer = json.loads(Path(prior["pointer"]).read_text())
        pointer["manifest_sha256"] = _hash(proof_path)
        Path(prior["pointer"]).write_bytes(storage._fixed_json(pointer))
    assert read_published_option_set(tmp_path, DAY) is None
    assert recover_option_set(tmp_path, DAY) is None
    assert plan_retention(tmp_path, today=DAY + timedelta(days=800)) == []
    if change != "proof-conflict":
        assert _member_bytes(prior) == before
    _record_recovery("reopen", True, [part], prior, None,
                     "source-" + change, request.node.nodeid)


@pytest.mark.parametrize("point", ["bounded_reading", "after_members_before_pointer", "pointer_rename"])
def test_source_changes_during_build_cannot_publish(tmp_path, point):
    old = _part(tmp_path, "a.parquet")
    prior = _publish(tmp_path, [old])
    before = _member_bytes(prior)
    new = _part(tmp_path, "b.parquet", _rows(oi=2))
    def change(name):
        if name == point:
            _part(tmp_path, "b.parquet", _rows(oi=999))
    with pytest.raises(StorageContractError, match="source identity"):
        _publish(tmp_path, [old, new], checkpoint=change)
    assert _member_bytes(prior) == before


@pytest.mark.parametrize("escape", ["source", "source-symlink", "output-symlink", "pointer-id", "member-path"])
def test_paths_cannot_escape_data_root(tmp_path, escape):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    part = _part(root, "a.parquet")
    outside_part = _part(outside, "a.parquet")
    if escape == "source":
        with pytest.raises(StorageContractError, match="escapes"):
            _publish(root, [outside_part])
    elif escape == "source-symlink":
        link = part.with_name("link.parquet")
        link.symlink_to(outside_part)
        with pytest.raises(StorageContractError, match="escapes|symlink"):
            _publish(root, [link])
    elif escape == "output-symlink":
        (root / "option_sets").symlink_to(outside, target_is_directory=True)
        with pytest.raises(StorageContractError, match="escapes|symlink"):
            _publish(root, [part])
    else:
        prior = _publish(root, [part])
        pointer_path_ = Path(prior["pointer"])
        pointer = json.loads(pointer_path_.read_text())
        if escape == "pointer-id":
            pointer["set_id"] = "../../outside"
        else:
            proof_path = Path(prior["set_directory"]) / "proof.json"
            proof = json.loads(proof_path.read_text())
            proof["chain"]["path"] = str(outside_part)
            proof_path.write_bytes(storage._fixed_json(proof))
            pointer["manifest_sha256"] = _hash(proof_path)
        pointer_path_.write_bytes(storage._fixed_json(pointer))
        assert recover_option_set(root, DAY) is None
    assert outside_part.exists()


def test_retention_all_classes_boundaries_and_holds(tmp_path):
    part = _part(tmp_path, "a.parquet")
    published = _publish(tmp_path, [part], complete_day=True)
    pointer = Path(published["pointer"])
    verified = datetime(2026, 9, 10, 12, tzinfo=ZoneInfo("America/Los_Angeles"))
    os.utime(pointer, (verified.timestamp(), verified.timestamp()))
    # An old market date cannot start the clock before verified publication.
    assert not plan_retention(tmp_path, today=date(2026, 9, 16))
    planned = plan_retention(tmp_path, today=date(2026, 9, 17))
    assert [r["path"] for r in planned] == [str(part)]
    assert not plan_retention(tmp_path, today=date(2026, 9, 17), legal_holds=[part.parent])
    for age in (749, 750, 751):
        day = DAY - timedelta(days=age)
        for family in ("option_chains", "stock_quotes", "stock_bars", "halts", "events",
                       "sessions", "open_interest", "reports", "proofs"):
            path = tmp_path / family / f"{day.isoformat()}.parquet"
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"held research input")
    for age in (29, 30, 31):
        marker = tmp_path / f".notified-{(DAY - timedelta(days=age)).isoformat()}"
        marker.touch()
    named = {Path(item["path"]).name for item in plan_retention(tmp_path, today=DAY)}
    assert named == {f".notified-{(DAY - timedelta(days=age)).isoformat()}" for age in (30, 31)}
    # Unknown newly added parts and a source with absent proof never qualify.
    extra = _part(tmp_path, "extra.parquet")
    assert str(extra) not in {r["path"] for r in plan_retention(tmp_path, today=date(2026, 9, 17))}


@pytest.mark.parametrize("age_seconds, eligible", [(86399, False), (86400, True), (86401, True)])
@pytest.mark.parametrize("state", ["valid", "unknown", "partial", "conflicting", "missing-source"])
def test_temporary_retention_requires_recovery_and_full_24_hours(tmp_path, age_seconds, eligible, state):
    part = _part(tmp_path, "a.parquet")
    published = _publish(tmp_path, [part])
    folder = Path(published["set_directory"])
    temporary = folder / "chain.parquet.tmp"
    temporary.write_bytes((folder / "chain.parquet").read_bytes())
    if state == "unknown":
        temporary = temporary.rename(folder / "unknown.tmp")
    elif state == "partial":
        temporary.write_bytes(temporary.read_bytes()[:10])
    elif state == "conflicting":
        temporary.write_bytes(b"conflict")
    elif state == "missing-source":
        part.rename(part.with_suffix(".held"))
    now = datetime(2026, 9, 10, 12, tzinfo=ZoneInfo("America/Los_Angeles"))
    stamp = now.timestamp() - age_seconds
    os.utime(temporary, (stamp, stamp))
    planned = plan_retention(tmp_path, today=now.date(), now=now)
    assert bool(planned) is (eligible and state == "valid")
    assert temporary.exists()
    assert not plan_retention(tmp_path, today=now.date(), now=now, legal_holds=[folder])


@pytest.mark.parametrize("checkpoint_name", CHECKPOINTS)
@pytest.mark.parametrize("with_prior", [False, True])
def test_retry_after_each_checkpoint_has_identical_members(tmp_path, checkpoint_name, with_prior, request):
    old = _part(tmp_path, "a.parquet")
    prior = _publish(tmp_path, [old]) if with_prior else None
    old_bytes = _member_bytes(prior) if prior else None
    new = _part(tmp_path, "b.parquet", _rows(oi=2))
    def stop(name):
        if name == checkpoint_name:
            raise InterruptedError("retry boundary")
    with pytest.raises(InterruptedError):
        _publish(tmp_path, [old, new], checkpoint=stop)
    visible = recover_option_set(tmp_path, DAY)
    _record_recovery(checkpoint_name, with_prior, [old, new], prior, visible, "before-retry", request.node.nodeid)
    recovered = _publish(tmp_path, [old, new])
    before = _member_bytes(recovered)
    assert _member_bytes(_publish(tmp_path, [old, new])) == before
    if prior:
        assert tuple((Path(prior["set_directory"]) / name).read_bytes() for name in
                     ("chain.parquet", "open_interest.parquet", "proof.json")) == old_bytes[:3]
    _record_recovery(checkpoint_name, with_prior, [old, new], prior, recovered, "after-retry", request.node.nodeid)


@pytest.mark.parametrize("checkpoint_name", CHECKPOINTS)
@pytest.mark.parametrize("with_prior", [False, True])
@pytest.mark.parametrize("state", ["complete", "partial", "missing", "corrupt", "conflicting"])
def test_recovery_matrix_retains_sources_and_prior(tmp_path, checkpoint_name, with_prior, state, request):
    old = _part(tmp_path, "a.parquet")
    prior = _publish(tmp_path, [old]) if with_prior else None
    prior_hashes = {name: _hash(Path(prior["set_directory"]) / name) for name in
                    ("chain.parquet", "open_interest.parquet", "proof.json")} if prior else {}
    new = _part(tmp_path, "b.parquet", _rows(oi=2))
    source_hashes = [_hash(old), _hash(new)]
    def stop(name):
        if name == checkpoint_name:
            raise InterruptedError("recovery boundary")
    with pytest.raises(InterruptedError):
        _publish(tmp_path, [old, new], checkpoint=stop)
    # Materialize a fully checked but unpublished new set, then supply each
    # explicit member state on reopen. The pointer continues to select one set.
    built = _publish(tmp_path, [old, new])
    folder = Path(built["set_directory"])
    pointer = Path(built["pointer"])
    if prior:
        proof = Path(prior["set_directory"]) / "proof.json"
        pointer.write_bytes(storage._fixed_json({"contract_version": storage.CONTRACT_VERSION,
            "market_date": DAY.isoformat(), "set_id": prior["set_id"], "manifest_sha256": _hash(proof)}))
    else:
        pointer.rename(pointer.with_name("UNPUBLISHED.json"))
    if state == "partial":
        (folder / "open_interest.parquet").rename(folder / "open_interest.parquet.tmp")
    elif state == "missing":
        (folder / "open_interest.parquet").rename(tmp_path / "held-open-interest.parquet")
    elif state == "corrupt":
        (folder / "chain.parquet").write_bytes(b"corrupt")
    elif state == "conflicting":
        (folder / "proof.json").write_bytes(b"{}")
    visible = recover_option_set(tmp_path, DAY)
    assert (visible["set_id"] if visible else None) == (prior["set_id"] if prior else None)
    if state in ("corrupt", "conflicting"):
        with pytest.raises(StorageContractError, match="conflicting"):
            _publish(tmp_path, [old, new])
    else:
        recovered = _publish(tmp_path, [old, new])
        assert recovered["set_id"] == built["set_id"]
    assert [_hash(old), _hash(new)] == source_hashes
    assert {name: _hash(Path(prior["set_directory"]) / name) for name in prior_hashes} == prior_hashes
    _record_recovery(checkpoint_name, with_prior, [old, new], prior,
                     recover_option_set(tmp_path, DAY), state, request.node.nodeid)



def test_complete_day_requires_entire_selected_part_inventory(tmp_path):
    first = _part(tmp_path, "a.parquet")
    second = _part(tmp_path, "b.parquet", _rows(oi=2))
    with pytest.raises(StorageContractError, match="every source part"):
        _publish(tmp_path, [first], complete_day=True)
    result = _publish(tmp_path, [first, second])
    assert result["proof"]["complete_day"] is False
    assert plan_retention(tmp_path, today=DAY + timedelta(days=800)) == []


def test_latest_missing_interest_uses_last_nonmissing_chain_value(tmp_path):
    first = _part(tmp_path, "a.parquet", _rows(oi=7))
    second = _part(tmp_path, "b.parquet", _rows("2026-08-31T13:32:00+00:00", None))
    result = _publish(tmp_path, [first, second])
    interest = pd.read_parquet(Path(result["set_directory"]) / "open_interest.parquet")
    assert interest.iloc[0]["open_interest"] == 7
    assert interest.iloc[0]["captured_at_utc"] == "2026-08-31T13:31:00+00:00"


@pytest.mark.parametrize("member", ["chain.parquet", "open_interest.parquet", "proof.json"])
@pytest.mark.parametrize("state", ["missing", "corrupt"])
def test_invalid_published_members_are_never_overwritten_on_retry(tmp_path, member, state):
    source = _part(tmp_path, "a.parquet")
    result = _publish(tmp_path, [source])
    path = Path(result["set_directory"]) / member
    if state == "missing":
        path.rename(tmp_path / ("held-" + member))
    else:
        path.write_bytes(b"invalid member")
    before = path.read_bytes() if path.exists() else None
    pointer_before = Path(result["pointer"]).read_bytes()
    assert recover_option_set(tmp_path, DAY) is None
    with pytest.raises(StorageContractError, match="published set is invalid"):
        _publish(tmp_path, [source])
    assert (path.read_bytes() if path.exists() else None) == before
    assert Path(result["pointer"]).read_bytes() == pointer_before


def test_output_reserve_is_checked_between_encoder_writes(tmp_path, monkeypatch):
    part = _part(tmp_path, "a.parquet")
    calls = []
    free = [20_000_000]
    monkeypatch.setattr(storage.os, "statvfs", lambda _: SimpleNamespace(
        f_bavail=free[0], f_frsize=1, f_blocks=20_000_000))
    actual = storage._BoundedFile.write
    def observed(self, data):
        calls.append(self.name)
        if calls.count("chain") == 2:
            free[0] = 0
        return actual(self, data)
    monkeypatch.setattr(storage._BoundedFile, "write", observed)
    with pytest.raises(StorageContractError, match="reserve"):
        publish_option_set(tmp_path, DAY, [part], bounds=BOUNDS, policy=POLICY)
    assert not pointer_path(tmp_path, DAY).exists()
    assert part.exists()


def test_m02b_storage_proof_recording(tmp_path):
    part = _part(tmp_path, "093100.parquet")
    result = _publish(tmp_path, [part])
    proof = result["proof"]
    record = {
        "contract_version": proof["contract_version"], "set_id": result["set_id"],
        "source_sha256": proof["sources"][0]["sha256"],
        "chain_record_sha256": proof["chain"]["record_sha256"],
        "open_interest_record_sha256": proof["open_interest"]["record_sha256"],
        "admission": result["admission"],
        "set_manifest": proof,
        "output_bytes": result["output_bytes"],
        "recovery_cases": RECOVERY_RECORDS,
    }
    Path("/tmp/m02b-full-chain-storage-proof.json").write_text(
        json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
