"""M9.1A bulk loader: retained `core17-1y` OHLCV-1m files into canonical bars.

This is item (1) of the M9.1 build-scope split recorded in ROADMAP.md
("M9.1 build-scope inventory"). It does two separate, independently testable
things:

- `verify_retained_files` checks on-disk files against a batch-job manifest's
  recorded sha256, without contacting Databento or trusting file names alone.
- `iter_ohlcv_1m_records` converts already-decoded OHLCV-1m rows (duck-typed,
  not the live `databento` package) plus a resolved instrument-id-to-symbol
  map and a per-date provider condition into `DatabentoMinuteRecord` objects
  via the existing `normalize_databento_ohlcv_1m` adapter. It raises rather
  than skipping on any row it cannot place (unmapped instrument, unlisted
  session date), matching D-104's fail-closed rule.

`open_core17_ohlcv_1m_file` is a thin integration wrapper around the real
`databento.DBNStore` and the real retained files. It is not exercised by the
offline contract tests (the retained files and the `databento` package's
decode path are outside the protected sandbox); `iter_ohlcv_1m_records` is
exercised directly with synthetic rows instead.

No network call, no purchase, no signal generation and no parameter or return
calculation happens anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping
from zoneinfo import ZoneInfo

from consensus_engine.databento_minute_bars import (
    DatabentoMinuteContext,
    DatabentoMinuteRecord,
    normalize_databento_ohlcv_1m,
)
from consensus_engine.trade_alerts_models import RecordError

_MINUTE = timedelta(minutes=1)
_UTC = timezone.utc
_PACIFIC = ZoneInfo("America/Los_Angeles")


@dataclass(frozen=True)
class VerifiedFile:
    """One retained file whose bytes matched its manifest sha256 on disk."""

    filename: str
    sha256: str
    size: int


def verify_retained_files(manifest_path: Path, files_dir: Path) -> tuple[VerifiedFile, ...]:
    """Hash every `*.dbn.zst` file the batch-job manifest lists and confirm it matches.

    Reads only local files; makes no network call. Raises `RecordError` on any
    missing file, size mismatch or hash mismatch rather than proceeding with
    an unverified file.
    """
    manifest = json.loads(manifest_path.read_text())
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise RecordError("manifest has no files list")
    verified: list[VerifiedFile] = []
    for entry in entries:
        filename = entry.get("filename")
        if not isinstance(filename, str) or not filename.endswith(".dbn.zst"):
            continue
        recorded_hash = entry.get("hash")
        if not isinstance(recorded_hash, str) or not recorded_hash.startswith("sha256:"):
            raise RecordError(f"{filename} has no recorded sha256")
        recorded_hash = recorded_hash[len("sha256:") :]
        recorded_size = entry.get("size")
        path = files_dir / filename
        if not path.is_file():
            raise RecordError(f"{filename} is listed in the manifest but missing on disk")
        digest = hashlib.sha256()
        actual_size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                actual_size += len(chunk)
        if isinstance(recorded_size, int) and actual_size != recorded_size:
            raise RecordError(f"{filename} size does not match the manifest")
        actual_hash = digest.hexdigest()
        if actual_hash != recorded_hash:
            raise RecordError(f"{filename} sha256 does not match the manifest")
        verified.append(VerifiedFile(filename=filename, sha256=actual_hash, size=actual_size))
    if not verified:
        raise RecordError("manifest listed no *.dbn.zst files")
    return tuple(verified)


def reverse_symbol_map(symbology: Mapping[str, Any]) -> dict[int, str]:
    """Build instrument_id -> raw_symbol from one file's `DBNStore.symbology`.

    Raises `RecordError` on an unresolved, partial or duplicate mapping rather
    than guessing a symbol for an ambiguous instrument id.
    """
    mappings = symbology.get("mappings")
    if not isinstance(mappings, Mapping) or not mappings:
        raise RecordError("symbology has no mappings")
    if symbology.get("not_found"):
        raise RecordError("symbology reports unresolved symbols")
    if symbology.get("partial"):
        raise RecordError("symbology reports partially resolved symbols")
    reverse: dict[int, str] = {}
    for raw_symbol, intervals in mappings.items():
        if not intervals:
            raise RecordError(f"{raw_symbol} has no resolved instrument id")
        for interval in intervals:
            try:
                instrument_id = int(interval["symbol"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RecordError(f"{raw_symbol} mapping is not a numeric instrument id") from exc
            if instrument_id in reverse and reverse[instrument_id] != raw_symbol:
                raise RecordError(f"instrument id {instrument_id} maps to more than one symbol")
            reverse[instrument_id] = raw_symbol
    return reverse


def iter_ohlcv_1m_records(
    rows: Iterable[Any],
    *,
    dataset: str,
    source_file_sha256: str,
    instrument_symbols: Mapping[int, str],
    condition_by_date: Mapping[str, str],
    record_id_prefix: str,
    instrument_type: str = "ETF",
    instrument_types: Mapping[str, str] | None = None,
) -> Iterator[DatabentoMinuteRecord]:
    """Convert already-decoded OHLCV-1m rows into canonical `DatabentoMinuteRecord`.

    `rows` are duck-typed objects with `instrument_id`, `ts_event`, `open`,
    `high`, `low`, `close`, `volume`, `publisher_id` attributes, matching the
    fields the real `databento_dbn.OHLCVMsg` exposes; this function never
    imports the `databento` package. Every row must resolve to a known
    instrument and a known session-condition date, or this raises rather than
    dropping the row silently. Context received/available/normalized times are
    all set to the bar's own close instant (`start + 1 minute`): the batch
    file carries no real receipt-latency timestamp, so this records the
    earliest instant the bar could exist rather than inventing a latency
    figure. Original availability/finality/point-in-time stay the recorded
    `UNKNOWN` gap `normalize_databento_ohlcv_1m` already sets.

    `instrument_type` is the caller's label for every row in this file: `ETF`
    (default, the original core-17 files) or `EQUITY` for a stock file. It is
    stated by the caller, never guessed from the symbol.

    `instrument_types` (raw symbol -> `ETF`/`EQUITY`) gives a true type per
    ticker for a file that mixes stocks and ETFs. When supplied it wins over
    `instrument_type`, and a symbol missing from it is skipped, never given
    the default label: the caller has not declared it, so it is not read
    (this keeps sealed held-out names out of a run that names only its own).

    `condition_by_date` keys are Pacific calendar dates, matching the session
    `normalize_databento_ohlcv_1m` derives from each bar's own event time. The
    retained `condition.json` dates coincide with this for every observed
    trading-hours bar (US market hours never cross the Pacific day boundary);
    this is stated, not independently reverified against provider
    documentation.
    """
    for index, row in enumerate(rows):
        instrument_id = row.instrument_id
        raw_symbol = instrument_symbols.get(instrument_id)
        if raw_symbol is None:
            raise RecordError(f"row {index} instrument_id {instrument_id} is not in the resolved symbol map")
        start = datetime.fromtimestamp(row.ts_event / 1_000_000_000, _UTC)
        if start.microsecond:
            start = start.replace(microsecond=0)
        session = start.astimezone(_PACIFIC).date().isoformat()
        condition = condition_by_date.get(session)
        if condition is None:
            raise RecordError(f"row {index} session {session} is not in the retained condition list")
        row_type = instrument_type
        if instrument_types is not None:
            row_type = instrument_types.get(raw_symbol)
            if row_type is None:
                continue
        provider_condition = "AVAILABLE" if condition == "available" else "DEGRADED"
        close_instant = start + _MINUTE
        context = DatabentoMinuteContext(
            dataset=dataset,
            raw_symbol=raw_symbol,
            instrument_id=instrument_id,
            session=session,
            received_time=close_instant,
            available_time=close_instant,
            normalized_time=close_instant,
            source_file_sha256=source_file_sha256,
            provider_condition=provider_condition,
            instrument_type=row_type,
        )
        record = {
            "publisher_id": row.publisher_id,
            "instrument_id": row.instrument_id,
            "ts_event": row.ts_event,
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "volume": row.volume,
        }
        yield normalize_databento_ohlcv_1m(
            record,
            record_id=f"{record_id_prefix}:{raw_symbol}:{row.ts_event}",
            context=context,
        )


def open_core17_ohlcv_1m_file(
    job_dir: Path, dbn_filename: str, instrument_types: Mapping[str, str] | None = None,
) -> Iterator[DatabentoMinuteRecord]:
    """Integration wrapper: verify, decode and convert one real retained monthly file.

    Not exercised by the offline contract tests: it imports `databento` and
    reads the retained files outside the protected sandbox. Kept thin on
    purpose so `iter_ohlcv_1m_records` carries the tested conversion logic.
    `instrument_types` is passed through as the true per-ticker type (D-115);
    without it every bar keeps the old default `ETF` label.
    """
    import databento as db  # local import: keep the SDK dependency out of the protected sandbox path

    verified = {item.filename: item for item in verify_retained_files(job_dir / "manifest.json", job_dir)}
    if dbn_filename not in verified:
        raise RecordError(f"{dbn_filename} is not a verified file in {job_dir}")
    condition_entries = json.loads((job_dir / "condition.json").read_text())
    condition_by_date = {entry["date"]: entry["condition"] for entry in condition_entries}
    store = db.DBNStore.from_file(job_dir / dbn_filename)
    if store.dataset not in ("XNYS.PILLAR", "EQUS.MINI"):
        raise RecordError("retained file dataset is unsupported")
    instrument_symbols = reverse_symbol_map(store.symbology)
    yield from iter_ohlcv_1m_records(
        store,
        dataset=store.dataset,
        source_file_sha256=verified[dbn_filename].sha256,
        instrument_symbols=instrument_symbols,
        condition_by_date=condition_by_date,
        record_id_prefix=f"core17-1y:{dbn_filename}",
        instrument_types=instrument_types,
    )
