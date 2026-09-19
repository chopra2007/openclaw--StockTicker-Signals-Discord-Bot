"""M0.2F retained source manifest and offline Databento minute adapter."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.databento_minute_bars import (
    DATASET_IDENTITIES,
    DatabentoMinuteContext,
    RetainedMinuteSource,
    normalize_databento_ohlcv_1m,
)
from consensus_engine.trade_alerts_models import RecordError


UTC = timezone.utc
START = datetime(2026, 8, 21, 13, 30, tzinfo=UTC)
TS_NS = int(START.timestamp()) * 1_000_000_000
XNYS_HASH = "7a5cfcff20c3b84d071f986f29d35e57abc74b2c96cba0de4cde97f0c9182f6c"
EQUS_HASH = "a3a8de614f9ac54507e61bfdeb05ce69713a6a4b68235cf9188b67939b5fc9b3"


def context(dataset="XNYS.PILLAR", **changes):
    values = dict(
        dataset=dataset, raw_symbol="SPY", instrument_id=15144, session="2026-08-21",
        received_time=START + timedelta(minutes=1),
        available_time=START + timedelta(minutes=1),
        normalized_time=START + timedelta(minutes=2),
        source_file_sha256=XNYS_HASH if dataset == "XNYS.PILLAR" else EQUS_HASH,
        provider_condition="AVAILABLE",
    )
    values.update(changes)
    return DatabentoMinuteContext(**values)


def row(**changes):
    values = dict(publisher_id=1, instrument_id=15144, ts_event=TS_NS, open=100_000_000_000,
                  high=102_000_000_000, low=99_000_000_000,
                  close=101_000_000_000, volume=1234)
    values.update(changes)
    return values


def test_retained_source_manifest_preserves_both_inventories_and_unknowns():
    symbols = ("SPY", "QQQ", "XLB", "XLC", "XLE", "XLF", "XLI", "XLK",
               "XLP", "XLRE", "XLU", "XLV", "XLY")
    xnys = RetainedMinuteSource(
        "XNYS.PILLAR", "xnys-pillar_ohlcv-1m_13-etfs.dbn.zst", XNYS_HASH,
        70512738, 4257208, symbols, "2023-01-01T00:00:00Z", "2026-08-22T00:00:00Z",
        1672531200000000000, 1787356800000000000, 912, 11500, 10450,
        ("2023-01-24", "2023-12-04", "2023-12-11", "2024-08-08"), True,
    )
    equs = RetainedMinuteSource(
        "EQUS.MINI", "equs-mini_ohlcv-1m_13-etfs.dbn.zst", EQUS_HASH,
        78549051, 4483742, symbols, "2023-03-28T00:00:00Z", "2026-08-22T00:00:00Z",
        1679961600000000000, 1787356800000000000, 854, 11009, 10859,
        tuple(f"degraded-{number:02d}" for number in range(15)), True,
    )
    assert xnys.as_dict()["publisher_identity"] == "DIRECT_NYSE_INTEGRATED"
    assert equs.as_dict()["venue_identity"] == "ANONYMIZED"
    assert xnys.record_count + equs.record_count == 8740950
    assert all(source.as_dict()["finality"] == "UNKNOWN" for source in (xnys, equs))
    assert all(source.has_opening_gaps for source in (xnys, equs))


def test_each_dataset_keeps_its_own_publisher_venue_and_source_hash():
    direct = normalize_databento_ohlcv_1m(row(), record_id="direct", context=context())
    derived = normalize_databento_ohlcv_1m(
        row(), record_id="derived", context=context("EQUS.MINI"))
    assert direct.dataset != derived.dataset
    assert (direct.publisher_identity, direct.venue_identity) == DATASET_IDENTITIES["XNYS.PILLAR"]
    assert (derived.publisher_identity, derived.venue_identity) == DATASET_IDENTITIES["EQUS.MINI"]
    assert direct.source_file_sha256 == XNYS_HASH
    assert derived.source_file_sha256 == EQUS_HASH
    assert direct.bar.metadata.source == "XNYS.PILLAR"
    assert derived.bar.metadata.source == "EQUS.MINI"


def test_raw_message_time_and_fixed_values_are_preserved_without_finality_claim():
    result = normalize_databento_ohlcv_1m(row(), record_id="bar", context=context())
    assert result.raw_ts_event_ns == TS_NS
    assert result.raw_publisher_id == 1
    assert result.bar.start_time == START and result.bar.end_time == START + timedelta(minutes=1)
    assert (result.bar.open, result.bar.high, result.bar.low, result.bar.close) == (100, 102, 99, 101)
    assert result.bar.volume == 1234
    assert not result.bar.is_final
    assert result.original_availability == result.finality == result.correction_state == "UNKNOWN"
    assert result.bar.metadata.quality == "UNKNOWN"


def test_provider_degraded_date_remains_visible_and_unusable_as_valid_source():
    result = normalize_databento_ohlcv_1m(
        row(), record_id="degraded", context=context(provider_condition="DEGRADED"))
    assert result.provider_condition == "DEGRADED"
    assert result.bar.metadata.quality == "DEGRADED_PROXY"
    assert not result.bar.is_final


@pytest.mark.parametrize("change,match", [
    ({"instrument_id": 17675}, "identity"),
    ({"ts_event": TS_NS + 1}, "losing nanoseconds"),
    ({"ts_event": TS_NS + 1_000_000_000}, "align to a minute"),
    ({"open": 0}, "positive fixed-point"),
    ({"volume": -1}, "non-negative integer"),
])
def test_wrong_identity_time_or_value_is_rejected(change, match):
    with pytest.raises(RecordError, match=match):
        normalize_databento_ohlcv_1m(row(**change), record_id="bad", context=context())


def test_missing_row_is_never_turned_into_a_zero_volume_bar():
    missing = row()
    missing.pop("volume")
    with pytest.raises(RecordError, match="fields"):
        normalize_databento_ohlcv_1m(missing, record_id="missing", context=context())
    with pytest.raises(RecordError, match="positive fixed-point"):
        normalize_databento_ohlcv_1m(row(open=0, high=0, low=0, close=0, volume=0),
                                     record_id="manufactured", context=context())


def test_recorded_source_identity_proof_is_deterministic():
    records = [
        normalize_databento_ohlcv_1m(row(), record_id="xnys", context=context()),
        normalize_databento_ohlcv_1m(row(), record_id="equs", context=context("EQUS.MINI")),
    ]
    proof = {
        "evidence": "SYNTHETIC_ROWS_AND_RETAINED_INVENTORY_ONLY",
        "records": [record.as_dict() for record in records],
        "feeds_combined": False,
        "missing_intervals_certified_no_trade": False,
        "qualifying_source": False,
    }
    encoded = json.dumps(proof, sort_keys=True, indent=2) + "\n"
    output = Path("/tmp/m02f-databento-minute-source-proof.json")
    output.write_text(encoded)
    assert output.read_text() == encoded
    assert records[0].as_dict() != records[1].as_dict()
