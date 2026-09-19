"""M9.1A bulk loader: retained `core17-1y` files verified and converted offline."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.core17_bar_loader import (
    iter_ohlcv_1m_records,
    reverse_symbol_map,
    verify_retained_files,
)
from consensus_engine.trade_alerts_models import RecordError


UTC = timezone.utc
START = datetime(2026, 8, 21, 13, 30, tzinfo=UTC)
TS_NS = int(START.timestamp()) * 1_000_000_000


def _write_manifest(tmp_path: Path, filename: str, content: bytes) -> Path:
    (tmp_path / filename).write_bytes(content)
    manifest = {
        "job_id": "TEST-JOB",
        "files": [
            {
                "filename": filename,
                "size": len(content),
                "hash": f"sha256:{hashlib.sha256(content).hexdigest()}",
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    return manifest_path


def test_verify_retained_files_accepts_matching_hash_and_size(tmp_path):
    manifest_path = _write_manifest(tmp_path, "sample.dbn.zst", b"retained-bytes")
    verified = verify_retained_files(manifest_path, tmp_path)
    assert len(verified) == 1
    assert verified[0].filename == "sample.dbn.zst"
    assert verified[0].sha256 == hashlib.sha256(b"retained-bytes").hexdigest()
    assert verified[0].size == len(b"retained-bytes")


def test_verify_retained_files_rejects_hash_mismatch(tmp_path):
    manifest_path = _write_manifest(tmp_path, "sample.dbn.zst", b"retained-bytes")
    (tmp_path / "sample.dbn.zst").write_bytes(b"tampered-byte!")
    with pytest.raises(RecordError, match="sha256"):
        verify_retained_files(manifest_path, tmp_path)


def test_verify_retained_files_rejects_missing_file(tmp_path):
    manifest_path = _write_manifest(tmp_path, "sample.dbn.zst", b"retained-bytes")
    (tmp_path / "sample.dbn.zst").unlink()
    with pytest.raises(RecordError, match="missing on disk"):
        verify_retained_files(manifest_path, tmp_path)


def test_reverse_symbol_map_builds_instrument_id_to_symbol():
    symbology = {
        "mappings": {
            "SPY": [{"start_date": "2026-08-01", "end_date": "2026-09-01", "symbol": "15144"}],
            "QQQ": [{"start_date": "2026-08-01", "end_date": "2026-09-01", "symbol": "13340"}],
        },
        "not_found": [],
        "partial": [],
    }
    reverse = reverse_symbol_map(symbology)
    assert reverse == {15144: "SPY", 13340: "QQQ"}


def test_reverse_symbol_map_rejects_unresolved_symbol():
    symbology = {"mappings": {"SPY": [{"symbol": "15144"}]}, "not_found": ["QQQ"], "partial": []}
    with pytest.raises(RecordError, match="unresolved"):
        reverse_symbol_map(symbology)


def test_reverse_symbol_map_rejects_duplicate_instrument_id():
    symbology = {
        "mappings": {
            "SPY": [{"symbol": "15144"}],
            "QQQ": [{"symbol": "15144"}],
        },
        "not_found": [],
        "partial": [],
    }
    with pytest.raises(RecordError, match="more than one symbol"):
        reverse_symbol_map(symbology)


@dataclass(frozen=True)
class FakeOhlcvRow:
    """Duck-typed stand-in for `databento_dbn.OHLCVMsg`; not the real SDK type."""

    instrument_id: int
    ts_event: int
    open: int
    high: int
    low: int
    close: int
    volume: int
    publisher_id: int = 1


def _row(**changes):
    values = dict(instrument_id=15144, ts_event=TS_NS, open=100_000_000_000,
                  high=102_000_000_000, low=99_000_000_000, close=101_000_000_000, volume=1234)
    values.update(changes)
    return FakeOhlcvRow(**values)


CONDITIONS = {"2026-08-21": "available"}
SYMBOLS = {15144: "SPY"}
HASH = "a3a8de614f9ac54507e61bfdeb05ce69713a6a4b68235cf9188b67939b5fc9b3"


def test_iter_ohlcv_1m_records_converts_row_using_bar_close_as_context_time():
    records = list(iter_ohlcv_1m_records(
        [_row()], dataset="EQUS.MINI", source_file_sha256=HASH,
        instrument_symbols=SYMBOLS, condition_by_date=CONDITIONS, record_id_prefix="t",
    ))
    assert len(records) == 1
    record = records[0]
    assert record.bar.start_time == START
    assert record.bar.metadata.received_time == START + timedelta(minutes=1)
    assert record.bar.metadata.received_time == record.bar.end_time
    assert record.provider_condition == "AVAILABLE"
    assert record.original_availability == "UNKNOWN"


def test_iter_ohlcv_1m_records_marks_degraded_condition():
    records = list(iter_ohlcv_1m_records(
        [_row()], dataset="EQUS.MINI", source_file_sha256=HASH,
        instrument_symbols=SYMBOLS, condition_by_date={"2026-08-21": "degraded"},
        record_id_prefix="t",
    ))
    assert records[0].provider_condition == "DEGRADED"


def test_iter_ohlcv_1m_records_rejects_unmapped_instrument():
    with pytest.raises(RecordError, match="not in the resolved symbol map"):
        list(iter_ohlcv_1m_records(
            [_row(instrument_id=999)], dataset="EQUS.MINI", source_file_sha256=HASH,
            instrument_symbols=SYMBOLS, condition_by_date=CONDITIONS, record_id_prefix="t",
        ))


def test_iter_ohlcv_1m_records_rejects_unknown_session_date():
    with pytest.raises(RecordError, match="not in the retained condition list"):
        list(iter_ohlcv_1m_records(
            [_row()], dataset="EQUS.MINI", source_file_sha256=HASH,
            instrument_symbols=SYMBOLS, condition_by_date={}, record_id_prefix="t",
        ))
