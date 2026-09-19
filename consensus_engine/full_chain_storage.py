"""Offline, off-by-default storage tools for the full-chain collector.

The module has no network or live caller.  It publishes an option chain, an
open-interest snapshot and their proof as one immutable set.  Source parts are
never removed here; ``plan_retention`` only reports eligible paths.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
import json
import math
import os
import pickle
import sqlite3
import tempfile
from pathlib import Path
import resource
import time
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


CONTRACT_VERSION = "M02B_STORAGE_V2"
PACIFIC = ZoneInfo("America/Los_Angeles")
CHAIN_KEYS = ["captured_at_utc", "ticker", "contract_symbol"]
CHAIN_ORDER = ["captured_at_utc", "ticker", "expiration", "strike_price", "option_type"]
OI_COLUMNS = ["market_date", "captured_at_utc", "ticker", "contract_symbol",
              "expiration", "strike_price", "option_type", "open_interest"]


class StorageContractError(RuntimeError):
    """The requested write cannot satisfy the frozen storage contract."""


@dataclass(frozen=True)
class StoragePolicy:
    enabled: bool = False
    fixed_reserve_bytes: int = 12_000_000_000
    reserve_fraction: float = .15
    peak_memory_bytes: int = 1_500_000_000
    batch_bytes: int = 256_000_000
    wall_seconds: float = 900.0

    def __post_init__(self):
        if (type(self.enabled) is not bool or
                any(type(value) is not int or value < 0 for value in (
                    self.fixed_reserve_bytes, self.peak_memory_bytes, self.batch_bytes)) or
                not isinstance(self.reserve_fraction, (int, float)) or
                not math.isfinite(self.reserve_fraction) or not 0 <= self.reserve_fraction <= 1 or
                not isinstance(self.wall_seconds, (int, float)) or
                not math.isfinite(self.wall_seconds) or self.wall_seconds <= 0):
            raise StorageContractError("storage policy requires finite known limits")


@dataclass(frozen=True)
class OutputBounds:
    chain: int
    open_interest: int
    proof: int
    publication: int

    def __post_init__(self) -> None:
        if any(type(value) is not int or value < 0 for value in (
            self.chain, self.open_interest, self.proof, self.publication
        )):
            raise StorageContractError("every output bound must be a known nonnegative byte count")


def reserve_bytes(capacity: int, policy: StoragePolicy) -> int:
    return max(policy.fixed_reserve_bytes, math.ceil(capacity * policy.reserve_fraction))


def working_space_bytes(source: int, bounds: OutputBounds, existing: int, temporary: int) -> int:
    if any(type(value) is not int or value < 0 for value in (source, existing, temporary)):
        raise StorageContractError("storage sizes must be known nonnegative byte counts")
    members = bounds.chain + bounds.open_interest + bounds.proof + bounds.publication
    return max(((9 * source + 3) // 4), 2 * members) + existing + temporary


def check_admission(*, free: int, capacity: int, source: int, bounds: OutputBounds,
                    existing: int = 0, temporary: int = 0,
                    policy: StoragePolicy = StoragePolicy()) -> dict:
    if any(type(value) is not int or value < 0 for value in (free, capacity)):
        raise StorageContractError("filesystem sizes must be known nonnegative byte counts")
    needed = working_space_bytes(source, bounds, existing, temporary)
    reserve = reserve_bytes(capacity, policy)
    admitted = free - needed >= reserve
    return {"admitted": admitted, "free_bytes": free, "capacity_bytes": capacity,
            "working_bytes": needed, "reserve_bytes": reserve,
            "remaining_bytes": free - needed}


def _sha256(path: Path, guard: Callable[[], None] = lambda: None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            guard()
            digest.update(block)
    return digest.hexdigest()


def _record_hash(frame: pd.DataFrame) -> str:
    payload = frame.to_json(orient="records", date_format="iso", date_unit="us",
                            double_precision=15, force_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fixed_json(payload: dict) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def _flush_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _flush_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_bytes(path: Path, payload: bytes, limit: int, checkpoint: Callable[[str], None], name: str) -> None:
    if len(payload) > limit:
        raise StorageContractError(f"{name} exceeded its byte bound")
    temporary = path.with_suffix(path.suffix + ".tmp")
    checkpoint(f"{name}_temporary_write")
    if temporary.exists():
        with temporary.open("rb") as handle:
            old = handle.read(limit + 1)
        if len(old) > limit or not payload.startswith(old):
            raise StorageContractError(f"conflicting {name} temporary file")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        checkpoint(f"{name}_temporary_flush")
        os.fsync(handle.fileno())
    checkpoint(f"{name}_rename")
    os.replace(temporary, path)
    _flush_file(path)


class _BoundedFile:
    """Check each encoder write before it can consume disk space."""

    def __init__(self, path, limit, guard, name):
        self.handle = path.open("wb")
        self.limit, self.guard, self.name = limit, guard, name

    @property
    def closed(self):
        return self.handle.closed

    def writable(self):
        return True

    def tell(self):
        return self.handle.tell()

    def write(self, data):
        self.guard()
        if self.tell() + len(data) > self.limit:
            raise StorageContractError(f"{self.name} exceeded its byte bound")
        return self.handle.write(data)

    def flush(self):
        self.handle.flush()

    def close(self):
        self.handle.close()


def _batches(path, policy, guard):
    # One row is the smallest decodable batch. Parquet row-group metadata is
    # checked before decoding too, so an oversized compressed page fails closed.
    source = pq.ParquetFile(path)
    try:
        for group in range(source.num_row_groups):
            guard()
            if source.metadata.row_group(group).total_byte_size > policy.batch_bytes:
                raise StorageContractError("one decoded source batch exceeds the byte limit")
            for batch in source.iter_batches(batch_size=1, row_groups=[group]):
                guard()
                frame = batch.to_pandas()
                if batch.nbytes + int(frame.memory_usage(index=True, deep=True).sum()) > policy.batch_bytes:
                    raise StorageContractError("one decoded source batch exceeds the byte limit")
                yield frame
                guard()
    finally:
        source.close()


def _stream_hash(frames):
    digest = hashlib.sha256(b"[")
    count, columns = 0, None
    for frame in frames:
        columns = list(frame.columns)
        payload = frame.to_json(orient="records", date_format="iso", date_unit="us",
                                double_precision=15, force_ascii=True)[1:-1]
        if payload:
            if count:
                digest.update(b",")
            digest.update(payload.encode("utf-8"))
            count += len(frame)
    digest.update(b"]")
    return digest.hexdigest(), count, columns


def _write_records(frames, schema, path, limit, checkpoint, guard, name):
    temporary = path.with_suffix(path.suffix + ".tmp")
    checkpoint(f"{name}_temporary_write")
    output = _BoundedFile(temporary, limit, guard, name)
    digest = hashlib.sha256(b"[")
    count = 0
    try:
        with pq.ParquetWriter(output, schema, compression="zstd") as writer:
            for frame in frames:
                guard()
                table = pa.Table.from_pandas(frame, schema=schema, preserve_index=False)
                writer.write_table(table)
                payload = frame.to_json(orient="records", date_format="iso", date_unit="us",
                                        double_precision=15, force_ascii=True)[1:-1]
                if payload:
                    if count:
                        digest.update(b",")
                    digest.update(payload.encode("utf-8"))
                    count += len(frame)
                guard()
        output.flush()
    finally:
        output.close()
    digest.update(b"]")
    checkpoint(f"{name}_temporary_flush")
    _flush_file(temporary)
    checkpoint(f"{name}_rename")
    os.replace(temporary, path)
    _flush_file(path)
    expected = digest.hexdigest()
    actual, rows, columns = _stream_hash(_batches(path, guard.policy, guard))
    if actual != expected or rows != count or (rows and columns != schema.names):
        raise StorageContractError(f"{name} source-derived records did not verify")
    return {"path": path.name, "bytes": path.stat().st_size,
            "sha256": _sha256(path, guard), "record_sha256": expected,
            "columns": schema.names, "rows": count}


def _sql_value(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _merge_to_disk(parts, work, bounds, policy, checkpoint, guard):
    """Indexed disk merge; no accumulated DataFrame or unbounded sort in RAM.

    The scratch database is capped at C bytes, inside the doubled C/O/P/A
    allowance. It is never recovered or loaded from an earlier invocation.
    """
    schemas = []
    for path in parts:
        guard()
        schemas.append(pq.read_schema(path))
    schema = pa.unify_schemas(schemas, promote_options="permissive").remove_metadata()
    if any(column not in schema.names for column in CHAIN_KEYS):
        raise StorageContractError("source parts lack required columns")
    order = [column for column in CHAIN_ORDER if column in schema.names]
    guard()
    db = sqlite3.connect(work / "merge.sqlite")
    def execute(statement, values=()):
        guard()
        return db.execute(statement, values)
    def commit():
        guard()
        db.commit()
        guard()
    try:
        execute("PRAGMA journal_mode=OFF")
        execute("PRAGMA temp_store=FILE")
        execute("PRAGMA cache_size=-1024")
        execute(f"PRAGMA max_page_count={max(1, bounds.chain // 4096)}")
        sort_fields = ", ".join(f"s{i}" for i in range(len(order)))
        sort_order = ", ".join(f"s{i} IS NULL, s{i}" for i in range(len(order)))
        execute(f"CREATE TABLE chain (k BLOB PRIMARY KEY, {sort_fields}, seq INTEGER, payload BLOB)")
        execute(f"CREATE INDEX ordered_chain ON chain ({sort_order}, seq)")
        execute("CREATE TABLE oi (ticker, contract, payload BLOB, PRIMARY KEY(ticker, contract)) WITHOUT ROWID")
        seq = 0
        for path in parts:
            checkpoint("bounded_reading")
            for frame in _batches(path, policy, guard):
                guard()
                # Cast to one union schema, preserving full floating precision
                # and timestamp types in the scratch row payload.
                frame = pa.Table.from_pandas(frame.reindex(columns=schema.names),
                                             schema=schema, preserve_index=False).to_pandas()
                row = frame.iloc[0]
                if any(pd.isna(row[column]) for column in CHAIN_KEYS):
                    raise StorageContractError("source key is missing")
                key = pickle.dumps(tuple(_sql_value(row[column]) for column in CHAIN_KEYS), protocol=4)
                values = [key] + [_sql_value(row[column]) for column in order]
                values += [seq, pickle.dumps(frame, protocol=4)]
                execute(f"INSERT OR REPLACE INTO chain VALUES ({','.join('?' for _ in values)})", values)
                commit()
                guard()
                seq += 1
        oi_schema = pa.schema([schema.field(name) if name in schema.names else pa.field(name, pa.null())
                               for name in OI_COLUMNS])
        def chains():
            for (payload,) in execute(f"SELECT payload FROM chain ORDER BY {sort_order}, seq"):
                guard()
                frame = pickle.loads(payload)  # only this invocation's private scratch writes
                row = frame.iloc[0]
                if "open_interest" in frame and not pd.isna(row["open_interest"]):
                    oi = frame.reindex(columns=OI_COLUMNS)
                    guard()
                    execute("INSERT OR REPLACE INTO oi VALUES (?, ?, ?)", (
                        _sql_value(row["ticker"]), _sql_value(row["contract_symbol"]),
                        pickle.dumps(oi, protocol=4)))
                    commit()
                yield frame
        chain = _write_records(chains(), schema, work / "chain.parquet", bounds.chain,
                               checkpoint, guard, "chain")
        checkpoint("after_chain_before_open_interest")
        def interests():
            for (payload,) in execute("SELECT payload FROM oi ORDER BY ticker, contract"):
                guard()
                yield pickle.loads(payload)
        oi = _write_records(interests(), oi_schema, work / "open_interest.parquet",
                            bounds.open_interest, checkpoint, guard, "open_interest")
        return chain, oi
    except sqlite3.DatabaseError as error:
        raise StorageContractError(f"bounded scratch merge stopped: {error}") from error
    finally:
        db.close()


def _peak_bytes() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def _check_resource_budget(started: float, policy: StoragePolicy) -> None:
    if time.monotonic() - started > policy.wall_seconds:
        raise StorageContractError("compaction exceeded its wall-time budget")
    if _peak_bytes() > policy.peak_memory_bytes:
        raise StorageContractError("compaction exceeded its peak-memory budget")


def pointer_path(root: Path, day: date) -> Path:
    return root / "option_sets" / day.isoformat() / "CURRENT.json"


def _inside(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if root not in resolved.parents or path.is_symlink():
        raise StorageContractError("storage path escapes the configured data root")
    # Even an inward symlink makes path identity ambiguous during publication.
    if any(parent.is_symlink() for parent in path.parents if parent != root):
        raise StorageContractError("storage path contains a symlink")
    return resolved


def _inventory(root: Path) -> tuple[int, int]:
    """Count all retained sets and all incomplete/scratch bytes, across dates."""
    existing = temporary = 0
    # Legacy daily outputs also remain retained when using the new caller.
    for family in ("option_chains", "open_interest", "proof", "runs"):
        folder = root / family
        if folder.exists():
            _inside(root, folder)
            for path in folder.rglob("*"):
                _inside(root, path)
                if path.is_file():
                    if path.suffix == ".tmp":
                        temporary += path.stat().st_size
                    else:
                        existing += path.stat().st_size
    base = root / "option_sets"
    if not base.exists():
        return existing, temporary
    _inside(root, base)
    for path in base.rglob("*"):
        _inside(root, path)
        if not path.is_file():
            continue
        size = path.stat().st_size
        # A completed manifest alone does not qualify a set for reuse, but its
        # bytes still belong in E. All other folders and siblings belong in T.
        if path.name == "CURRENT.json" or (path.suffix != ".tmp" and
                (path.parent / "proof.json").is_file() and path.parent.parent.name == "sets"):
            existing += size
        else:
            temporary += size
    return existing, temporary


def _sources(root, parts, guard=lambda: None):
    items = []
    for path in parts:
        guard()
        _inside(root, path)
        items.append({"path": path.relative_to(root).as_posix(),
                      "bytes": path.stat().st_size, "sha256": _sha256(path, guard)})
    return items


def _identity(day, sources, complete_day):
    return hashlib.sha256(_fixed_json({"contract_version": CONTRACT_VERSION,
        "market_date": day.isoformat(), "sources": sources,
        "complete_day": complete_day})).hexdigest()


def publish_option_set(root: Path, day: date, part_paths: Iterable[Path], *,
                       bounds: OutputBounds, policy: StoragePolicy = StoragePolicy(),
                       free_bytes: int | None = None, capacity_bytes: int | None = None,
                       existing_bytes: int = 0, temporary_bytes: int = 0,
                       complete_day: bool = False,
                       checkpoint: Callable[[str], None] | None = None) -> dict:
    """Publish a verified offline set; explicit day completeness gates retention.

    Byte overrides support offline fixtures. On disk E/T are always inventoried;
    callers can only increase those allowances. Incomplete day is the default.
    """
    if not policy.enabled:
        raise StorageContractError("bounded compaction is off")
    started = time.monotonic()
    _check_resource_budget(started, policy)
    root = root.resolve()
    raw_parts = [Path(path).absolute() for path in part_paths]
    parts = sorted(_inside(root, path) for path in raw_parts)
    if not parts or len(set(parts)) != len(parts) or any(not path.is_file() for path in parts):
        raise StorageContractError("every source part must exist and be unique")
    if type(complete_day) is not bool:
        raise StorageContractError("day completeness must be explicit")
    if complete_day:
        day_parts = sorted((root / "option_parts" / day.isoformat()).glob("*.parquet"))
        if parts != [path.resolve() for path in day_parts]:
            raise StorageContractError("complete day must include every source part")
    source_bytes = sum(path.stat().st_size for path in parts)
    observed_existing, observed_temporary = _inventory(root)
    # Validate overrides before max(), including unknown and negative counts.
    working_space_bytes(source_bytes, bounds, existing_bytes, temporary_bytes)
    def admission_now():
        disk = os.statvfs(root)
        free = free_bytes if free_bytes is not None else disk.f_bavail * disk.f_frsize
        capacity = capacity_bytes if capacity_bytes is not None else disk.f_blocks * disk.f_frsize
        return check_admission(free=free, capacity=capacity, source=source_bytes,
            bounds=bounds, existing=max(existing_bytes, observed_existing),
            temporary=max(temporary_bytes, observed_temporary), policy=policy)
    admission = admission_now()
    if not admission["admitted"]:
        raise StorageContractError("compaction would cross the storage reserve")
    def guard():
        _check_resource_budget(started, policy)
        if not admission_now()["admitted"]:
            raise StorageContractError("compaction would cross the storage reserve")
    guard.policy = policy
    supplied_checkpoint = checkpoint or (lambda _name: None)
    def checkpoint(name):
        supplied_checkpoint(name)
        guard()
        if name == "pointer_rename":
            if _sources(root, parts, guard) != source_items:
                raise StorageContractError("source identity changed before publication")
            for member in ("chain", "open_interest"):
                item = proof[member]
                if _sha256(set_dir / item["path"], guard) != item["sha256"]:
                    raise StorageContractError("set member changed before publication")
            if _sha256(set_dir / "proof.json", guard) != pointer["manifest_sha256"]:
                raise StorageContractError("proof changed before publication")
    source_items = _sources(root, parts, guard)
    set_id = _identity(day, source_items, complete_day)
    day_root = _inside(root, root / "option_sets" / day.isoformat())
    set_dir = _inside(root, day_root / "sets" / set_id)
    pointer_file = _inside(root, pointer_path(root, day))
    current = read_published_option_set(root, day, guard=guard, policy=policy)
    if current and current["set_id"] == set_id:
        return {**current, "admission": admission, "published": True}
    # Never repair members through a pointer that currently names them, even
    # when the pointer or member is corrupt. Preserve the incident for review.
    if pointer_file.exists():
        try:
            old_pointer = json.loads(pointer_file.read_text())
        except (ValueError, OSError) as error:
            raise StorageContractError("conflicting publication pointer") from error
        if old_pointer.get("set_id") == set_id:
            raise StorageContractError("published set is invalid; recovery is blocked")
    guard()
    day_root.mkdir(parents=True, exist_ok=True)
    # Scratch files are created exclusively and never loaded on reopen. Their
    # combined bound is C for SQLite plus C/O/P for staged members, within W.
    work = Path(tempfile.mkdtemp(prefix=".working-", dir=day_root))
    # Retain scratch and incomplete outputs for a later recovery assessment.
    # This library has no deletion path, including on failure.
    chain, oi = _merge_to_disk(parts, work, bounds, policy, checkpoint, guard)
    checkpoint("after_open_interest_before_proof")
    if _sources(root, parts, guard) != source_items:
        raise StorageContractError("source identity changed during compaction")
    proof = {"contract_version": CONTRACT_VERSION, "market_date": day.isoformat(),
             "set_id": set_id, "sources": source_items, "chain": chain,
             "open_interest": {**oi, "missing_data": oi["rows"] == 0},
             "complete": oi["rows"] > 0, "complete_day": complete_day}
    _atomic_bytes(work / "proof.json", _fixed_json(proof), bounds.proof, checkpoint, "proof")
    # Existing unpublished members may be reused only when their complete
    # bytes agree. Unknown and conflicting files are retained, never fixed
    # by overwriting them. Temporary siblings must be valid output prefixes.
    if set_dir.exists():
        for member in set_dir.iterdir():
            _inside(root, member)
            name = member.name.removesuffix(".tmp")
            expected = work / name
            if name not in ("chain.parquet", "open_interest.parquet", "proof.json") or not member.is_file():
                raise StorageContractError("conflicting unpublished member")
            if member.name.endswith(".tmp"):
                with member.open("rb") as old, expected.open("rb") as new:
                    while block := old.read(1024 * 1024):
                        guard()
                        if block != new.read(len(block)):
                            raise StorageContractError("conflicting temporary member")
            elif _sha256(member, guard) != _sha256(expected, guard):
                raise StorageContractError("conflicting unpublished member")
    guard()
    set_dir.mkdir(parents=True, exist_ok=True)
    for name in ("chain.parquet", "open_interest.parquet", "proof.json"):
        guard()
        destination = _inside(root, set_dir / name)
        if not destination.exists():
            os.replace(work / name, destination)
    checkpoint("after_members_before_pointer")
    checkpoint("set_directory_flush")
    _flush_dir(set_dir)
    _flush_dir(set_dir.parent)
    if not proof["complete"]:
        return {"set_id": set_id, "set_directory": str(set_dir), "proof": proof,
                "published": False, "missing_data": True, "admission": admission}
    if _sources(root, parts, guard) != source_items:
        raise StorageContractError("source identity changed before publication")
    pointer = {"contract_version": CONTRACT_VERSION, "market_date": day.isoformat(),
               "set_id": set_id, "manifest_sha256": _sha256(set_dir / "proof.json", guard)}
    _atomic_bytes(pointer_file, _fixed_json(pointer), bounds.publication,
                  checkpoint, "pointer")
    checkpoint("pointer_parent_directory_flush")
    _flush_dir(day_root)
    result = read_published_option_set(root, day, guard=guard, policy=policy)
    if result is None:
        raise StorageContractError("published set did not verify")
    guard()
    return {**result, "published": True, "admission": admission,
            "output_bytes": {"chain": chain["bytes"], "open_interest": oi["bytes"],
                             "proof": (set_dir / "proof.json").stat().st_size,
                             "publication": pointer_file.stat().st_size,
                             "scratch": (work / "merge.sqlite").stat().st_size},
            "minute_files": len(parts), "option_rows": chain["rows"],
            "open_interest_rows": oi["rows"], "elapsed_seconds": time.monotonic() - started,
            "peak_memory_bytes": _peak_bytes()}


def read_published_option_set(root: Path, day: date, *, allow_set_id: str | None = None,
                              guard: Callable[[], None] | None = None,
                              policy: StoragePolicy = StoragePolicy()) -> dict | None:
    root = root.resolve()
    started = time.monotonic()
    if guard is None:
        guard = lambda: _check_resource_budget(started, policy)
    try:
        path = _inside(root, pointer_path(root, day))
        if not path.exists():
            return None
        pointer = json.loads(path.read_text(encoding="utf-8"))
        set_id = pointer["set_id"]
        if not isinstance(set_id, str) or len(set_id) != 64 or any(c not in "0123456789abcdef" for c in set_id):
            return None
        if allow_set_id is not None and set_id != allow_set_id:
            return None
        if pointer.get("market_date") != day.isoformat() or pointer.get("contract_version") != CONTRACT_VERSION:
            return None
        folder = _inside(root, path.parent / "sets" / set_id)
        proof_path = _inside(root, folder / "proof.json")
        if _sha256(proof_path, guard) != pointer["manifest_sha256"]:
            return None
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        if (proof.get("set_id") != set_id or proof.get("contract_version") != CONTRACT_VERSION
                or proof.get("market_date") != day.isoformat() or proof.get("complete") is not True
                or type(proof.get("complete_day")) is not bool):
            return None
        sources = proof["sources"]
        paths = [item["path"] for item in sources]
        if not paths or paths != sorted(set(paths)):
            return None
        if any(Path(name).is_absolute() or ".." in Path(name).parts for name in paths):
            return None
        if _sources(root, [root / name for name in paths], guard) != sources:
            return None
        if _identity(day, sources, proof["complete_day"]) != set_id:
            return None
        for member in ("chain", "open_interest"):
            item = proof[member]
            if item["path"] != member + ".parquet":
                return None
            member_path = _inside(root, folder / item["path"])
            if _sha256(member_path, guard) != item["sha256"] or member_path.stat().st_size != item["bytes"]:
                return None
            schema = pq.read_schema(member_path)
            record_hash, count, _ = _stream_hash(_batches(member_path, policy, guard))
            if schema.names != item["columns"] or count != item["rows"] or record_hash != item["record_sha256"]:
                return None
            if member == "open_interest" and (count == 0 or item.get("missing_data") is not False):
                return None
        return {"set_id": set_id, "pointer": str(path), "set_directory": str(folder), "proof": proof}
    except (OSError, KeyError, TypeError, ValueError, StorageContractError):
        return None


def recover_option_set(root: Path, day: date) -> dict | None:
    """Validate current sources and the complete pointed set; never promote files."""
    return read_published_option_set(root, day)


def plan_retention(root: Path, *, today: date, legal_holds: Iterable[Path] = (),
                   now: datetime | None = None) -> list[dict]:
    """Dry-run only. A verified complete-day pointer starts the seven-day clock."""
    root = root.resolve()
    now = now or datetime.combine(today, datetime.min.time(), tzinfo=PACIFIC)
    if now.tzinfo is None:
        raise StorageContractError("retention time must include its time zone")
    holds = {Path(path).resolve() for path in legal_holds}
    planned = []
    candidates = list((root / "option_parts").glob("*/*.parquet"))
    candidates += list((root / "option_sets").glob("*/sets/*/*.tmp"))
    candidates += list(root.glob(".notified-*"))
    for path in sorted(candidates):
        try:
            resolved = _inside(root, path)
        except StorageContractError:
            continue
        if any(hold == resolved or hold in resolved.parents for hold in holds):
            continue
        reason = None
        if resolved.parent.parent == root / "option_parts":
            try:
                market_day = date.fromisoformat(path.parent.name)
            except ValueError:
                continue
            published = read_published_option_set(root, market_day)
            if not published or not published["proof"]["complete_day"]:
                continue
            named = {item["path"] for item in published["proof"]["sources"]}
            current_parts = {item.relative_to(root).as_posix()
                             for item in path.parent.glob("*.parquet")}
            if current_parts != named:
                continue
            pointer = Path(published["pointer"])
            verified_day = datetime.fromtimestamp(pointer.stat().st_mtime, PACIFIC).date()
            if (resolved.relative_to(root).as_posix() in named and
                    today >= max(market_day, verified_day) + timedelta(days=7)):
                reason = "verified minute part retained 7 days after publication"
        elif path.name.startswith(".notified-"):
            try:
                marker_day = date.fromisoformat(path.name.removeprefix(".notified-"))
            except ValueError:
                continue
            if path.stat().st_size == 0 and today >= marker_day + timedelta(days=30):
                reason = "notification marker older than 30 days"
        else:
            try:
                market_day = date.fromisoformat(path.parents[2].name)
            except ValueError:
                continue
            published = recover_option_set(root, market_day)
            if not published or Path(published["set_directory"]) != path.parent:
                continue
            name = path.name.removesuffix(".tmp")
            if name not in ("chain.parquet", "open_interest.parquet", "proof.json"):
                continue
            # Unknown/partial/conflicting siblings remain held. A byte-identical
            # stale sibling is redundant only after recovery validates the set.
            if _sha256(path) != _sha256(path.with_name(name)):
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime, PACIFIC)
            if now.timestamp() - modified.timestamp() >= 24 * 60 * 60:
                reason = "verified temporary duplicate retained through recovery for 24 hours"
        if reason:
            planned.append({"path": str(resolved), "reason": reason})
    return planned
