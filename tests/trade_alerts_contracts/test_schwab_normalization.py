"""M2.1 offline contracts for raw Schwab REST normalization."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sys

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip(
        "Requires scripts/testing/run_trade_alerts_contracts.py",
        allow_module_level=True,
    )


from consensus_engine.scanners import schwab_client
from consensus_engine.scanners.schwab_normalization import (
    normalize_schwab_bar,
    normalize_schwab_option_quote,
    normalize_schwab_quote,
)
from consensus_engine.trade_alerts_models import (
    Bar,
    OptionQuote,
    Quote,
    RecordError,
    SourceMetadata,
)


UTC = timezone.utc
QUOTE_MS = 1_782_863_991_793
TRADE_MS = 1_782_862_791_127
BAR_MS = 1_782_860_400_321
QUOTE_TIME = datetime.fromtimestamp(QUOTE_MS / 1000, tz=UTC)
TRADE_TIME = datetime.fromtimestamp(TRADE_MS / 1000, tz=UTC)
BAR_TIME = datetime.fromtimestamp(BAR_MS / 1000, tz=UTC)


def _metadata(instrument_id="AAPL", instrument_type="EQUITY", source_time=QUOTE_TIME, **changes):
    values = {
        "instrument_id": instrument_id,
        "instrument_type": instrument_type,
        "source": "SCHWAB",
        "source_time": source_time,
        "received_time": QUOTE_TIME + timedelta(milliseconds=100),
        "available_time": QUOTE_TIME + timedelta(milliseconds=250),
        "normalized_time": QUOTE_TIME + timedelta(milliseconds=200),
        "session": "2026-06-30",
        "sequence": None,
        "revision": 0,
        "data_mode": "REST_FIXTURE",
        "quality": "VALID",
    }
    values.update(changes)
    return SourceMetadata(**values)


def _raw_quote(**changes):
    quote = {
        "lastPrice": 289.0,
        "lastSize": 3,
        "bidPrice": 289.2,
        "askPrice": 289.4,
        "bidSize": 17,
        "askSize": 9,
        "quoteTime": QUOTE_MS,
        "tradeTime": TRADE_MS,
    }
    quote.update(changes)
    return {
        "symbol": "AAPL",
        "quote": quote,
        "regular": {"regularMarketLastPrice": 289.36},
    }


def _raw_option(**changes):
    contract = {
        "symbol": "AAPL  260701C00285000",
        "underlyingSymbol": "AAPL",
        "expirationDate": "2026-07-01",
        "putCall": "CALL",
        "strikePrice": 285.0,
        "last": 4.85,
        "bid": 4.5,
        "ask": 5.0,
        "bidSize": 10,
        "askSize": 11,
        "totalVolume": 39_590,
        "openInterest": 3_923,
        "volatility": 34.066,
        "tradeTimeInLong": TRADE_MS,
        "quoteTimeInLong": QUOTE_MS,
        "multiplier": 100,
        "nonStandard": True,
        "deliverableNote": "100 AAPL",
        "delta": 0.814,
        "gamma": 0.057,
        "theta": -0.427,
        "vega": 0.039,
        "rho": -0.005,
    }
    contract.update(changes)
    return contract


def test_quote_uses_raw_last_and_preserves_exact_milliseconds():
    quote = normalize_schwab_quote(
        _raw_quote(), record_id="quote-1", metadata=_metadata(), raw_symbol="AAPL",
        status="VALID", delayed=False,
    )

    assert isinstance(quote, Quote)
    assert quote.last == 289.0
    assert quote.last != 289.36
    assert quote.quote_time == QUOTE_TIME
    assert quote.quote_time.microsecond == 793_000
    assert quote.trade_time == TRADE_TIME
    assert (quote.bid_size, quote.ask_size, quote.last_size) == (17, 9, 3)


def test_raw_mock_and_legacy_quote_output_are_both_unchanged(monkeypatch):
    raw = _raw_quote()
    monkeypatch.setattr(schwab_client, "_get", lambda path, params=None: {"AAPL": raw})

    legacy = schwab_client.get_quote("AAPL")
    canonical = normalize_schwab_quote(
        raw, record_id="quote-legacy-proof", metadata=_metadata(), raw_symbol="AAPL",
        status="VALID", delayed=False,
    )

    assert legacy["c"] == 289.36
    assert legacy["t"] == TRADE_MS // 1000
    assert legacy["quote_time"] == QUOTE_MS // 1000
    assert canonical.last == 289.0
    assert canonical.quote_time.microsecond == 793_000


def test_quote_uses_raw_delayed_flag_when_present():
    raw = _raw_quote()
    raw["isDelayed"] = True
    quote = normalize_schwab_quote(
        raw, record_id="quote-delayed", metadata=_metadata(quality="STALE"),
        raw_symbol="AAPL", status="STALE", delayed=True,
    )
    assert quote.delayed is True and quote.status == "STALE"

    with pytest.raises(RecordError, match="delayed flag conflicts"):
        normalize_schwab_quote(
            raw, record_id="quote-delay-conflict", metadata=_metadata(),
            raw_symbol="AAPL", status="VALID", delayed=False,
        )


def test_quote_keeps_old_trade_separate_from_fresh_quote():
    quote = normalize_schwab_quote(
        _raw_quote(), record_id="quote-skew", metadata=_metadata(), raw_symbol="AAPL",
        status="VALID", delayed=False,
    )
    assert quote.quote_time - quote.trade_time == timedelta(seconds=1200, milliseconds=666)


def test_fresh_trade_does_not_refresh_older_bid_ask_source_time():
    metadata = _metadata(
        source_time=TRADE_TIME,
        received_time=QUOTE_TIME + timedelta(milliseconds=100),
        normalized_time=QUOTE_TIME + timedelta(milliseconds=200),
        available_time=QUOTE_TIME + timedelta(milliseconds=250),
    )
    quote = normalize_schwab_quote(
        _raw_quote(quoteTime=TRADE_MS, tradeTime=QUOTE_MS),
        record_id="quote-reverse-skew", metadata=metadata, raw_symbol="AAPL",
        status="VALID", delayed=False,
    )
    assert quote.quote_time == TRADE_TIME
    assert quote.trade_time == QUOTE_TIME
    assert quote.metadata.source_time == quote.quote_time


def test_quote_preserves_zero_but_drops_missing_sentinel_bool_and_nan():
    quote = normalize_schwab_quote(
        _raw_quote(lastPrice=0, lastSize=True, bidSize=-999, askSize=float("nan")),
        record_id="quote-missing", metadata=_metadata(), raw_symbol="AAPL",
        status="VALID", delayed=False,
    )
    assert quote.last == 0
    assert quote.last_size is None
    assert quote.bid_size is None
    assert quote.ask_size is None


def test_valid_quote_rejects_zero_side_but_nonvalid_quote_preserves_it():
    with pytest.raises(RecordError, match="positive bid and ask"):
        normalize_schwab_quote(
            _raw_quote(bidPrice=0), record_id="quote-zero-invalid",
            metadata=_metadata(), raw_symbol="AAPL", status="VALID", delayed=False,
        )

    quote = normalize_schwab_quote(
        _raw_quote(bidPrice=0, askPrice=0), record_id="quote-zero-preserved",
        metadata=_metadata(quality="UNKNOWN"), raw_symbol="AAPL",
        status="NO_TWO_SIDED", delayed=None,
    )
    assert quote.bid == 0 and quote.ask == 0


def test_huge_numeric_is_missing_instead_of_leaking_conversion_error():
    quote = normalize_schwab_quote(
        _raw_quote(lastPrice=10**1000), record_id="quote-huge",
        metadata=_metadata(quality="UNKNOWN"), raw_symbol="AAPL",
        status="NO_TWO_SIDED", delayed=None,
    )
    assert quote.last is None


@pytest.mark.parametrize(
    "metadata,status,delayed",
    [
        (_metadata(quality="STALE"), "STALE", True),
        (_metadata(quality="UNKNOWN"), "NO_TWO_SIDED", None),
        (_metadata(quality="DEGRADED_PROXY"), "INVALID", True),
    ],
)
def test_quote_carries_nonvalid_quality_without_upgrading(metadata, status, delayed):
    quote = normalize_schwab_quote(
        _raw_quote(), record_id=f"quote-{status}", metadata=metadata,
        raw_symbol="AAPL", status=status, delayed=delayed,
    )
    assert quote.metadata.quality == metadata.quality
    assert quote.status == status
    assert quote.delayed is delayed


@pytest.mark.parametrize(
    "entry,metadata,raw_symbol,match",
    [
        (_raw_quote(), replace(_metadata(), source="FINNHUB"), "AAPL", "source SCHWAB"),
        (_raw_quote(), _metadata(), "MSFT", "identity"),
        ({**_raw_quote(), "symbol": "MSFT"}, _metadata(), "AAPL", "entry symbol"),
        (_raw_quote(quoteTime=QUOTE_MS + 1_000), _metadata(), "AAPL", "availability"),
        (_raw_quote(quoteTime=True), _metadata(), "AAPL", "epoch-millisecond"),
        (_raw_quote(bidPrice=290, askPrice=289), _metadata(), "AAPL", "crossed"),
    ],
)
def test_quote_rejects_bad_source_identity_geometry_or_time(entry, metadata, raw_symbol, match):
    with pytest.raises(RecordError, match=match):
        normalize_schwab_quote(
            entry, record_id="quote-bad", metadata=metadata, raw_symbol=raw_symbol,
            status="VALID", delayed=False,
        )


@pytest.mark.parametrize(
    "metadata,status,delayed,match",
    [
        (_metadata(), "VALID", True, "non-delayed|delayed"),
        (_metadata(), "VALID", None, "non-delayed"),
        (_metadata(quality="UNKNOWN"), "VALID", False, "VALID quality"),
    ],
)
def test_quote_rejects_false_validity(metadata, status, delayed, match):
    with pytest.raises(RecordError, match=match):
        normalize_schwab_quote(
            _raw_quote(), record_id="quote-bad-state", metadata=metadata,
            raw_symbol="AAPL", status=status, delayed=delayed,
        )


def test_valid_quote_requires_actual_quote_time():
    metadata = _metadata(source_time=TRADE_TIME)
    with pytest.raises(RecordError, match="quote timestamp"):
        normalize_schwab_quote(
            _raw_quote(quoteTime=None), record_id="quote-no-quote-time",
            metadata=metadata, raw_symbol="AAPL", status="VALID", delayed=False,
        )


def test_quote_missing_raw_times_stays_unknown():
    metadata = _metadata(
        source_time=None,
        received_time=QUOTE_TIME,
        normalized_time=QUOTE_TIME,
        available_time=QUOTE_TIME,
        quality="UNKNOWN",
    )
    quote = normalize_schwab_quote(
        _raw_quote(quoteTime=None, tradeTime=0), record_id="quote-no-time",
        metadata=metadata, raw_symbol="AAPL", status="NO_TWO_SIDED", delayed=None,
    )
    assert quote.quote_time is None and quote.trade_time is None
    assert quote.metadata.source_time is None


def test_bar_preserves_raw_source_stamp_and_caller_supplied_boundaries():
    metadata = _metadata(
        source_time=BAR_TIME,
        received_time=BAR_TIME + timedelta(minutes=1, milliseconds=1),
        normalized_time=BAR_TIME + timedelta(minutes=1, milliseconds=3),
        available_time=BAR_TIME + timedelta(minutes=1, milliseconds=2),
    )
    bar = normalize_schwab_bar(
        {"datetime": BAR_MS, "open": 100, "high": 102, "low": 99, "close": 101, "volume": 0},
        record_id="bar-1", metadata=metadata, raw_symbol="AAPL",
        start_time=BAR_TIME - timedelta(minutes=1),
        end_time=BAR_TIME, is_final=True,
        adjustment_basis="PROVIDER_UNSPECIFIED",
    )
    assert isinstance(bar, Bar)
    assert bar.metadata.source_time == BAR_TIME
    assert bar.metadata.source_time.microsecond == 321_000
    assert bar.start_time == BAR_TIME - timedelta(minutes=1)
    assert bar.end_time == BAR_TIME
    assert bar.is_final is True and bar.volume == 0
    assert bar.adjustment_basis == "PROVIDER_UNSPECIFIED"


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"close": None}, "finite OHLCV"),
        ({"low": 103}, "geometry"),
        ({"datetime": True}, "epoch-millisecond"),
    ],
)
def test_bar_rejects_incomplete_geometry_and_bad_times(changes, match):
    raw = {"datetime": BAR_MS, "open": 100, "high": 102, "low": 99, "close": 101, "volume": 10}
    raw.update(changes)
    metadata = _metadata(
        source_time=BAR_TIME,
        received_time=BAR_TIME,
        normalized_time=BAR_TIME,
        available_time=BAR_TIME + timedelta(minutes=1),
    )
    with pytest.raises(RecordError, match=match):
        normalize_schwab_bar(
            raw, record_id="bar-bad", metadata=metadata, raw_symbol="AAPL",
            start_time=BAR_TIME,
            end_time=BAR_TIME + timedelta(minutes=1),
        )


def test_final_bar_rejects_availability_before_caller_supplied_end():
    metadata = _metadata(
        source_time=BAR_TIME,
        received_time=BAR_TIME,
        normalized_time=BAR_TIME,
        available_time=BAR_TIME,
    )
    with pytest.raises(RecordError, match="final bar cannot be available before its end"):
        normalize_schwab_bar(
            {"datetime": BAR_MS, "open": 100, "high": 102, "low": 99, "close": 101, "volume": 10},
            record_id="bar-premature-final", metadata=metadata, raw_symbol="AAPL",
            start_time=BAR_TIME, end_time=BAR_TIME + timedelta(minutes=1), is_final=True,
        )


def test_option_preserves_exact_adjustment_identity_and_signed_greeks():
    contract_id = "AAPL  260701C00285000"
    metadata = _metadata(contract_id, "OPTION")
    quote = normalize_schwab_option_quote(
        _raw_option(), record_id="option-1", metadata=metadata,
        raw_symbol=contract_id, underlying_id="AAPL", expiry=date(2026, 7, 1),
        option_type="CALL", status="VALID", delayed=False,
        open_interest_time=TRADE_TIME,
    )
    assert isinstance(quote, OptionQuote)
    assert (quote.contract_id, quote.underlying_id) == (contract_id, "AAPL")
    assert (quote.expiry, quote.option_type, quote.strike) == (date(2026, 7, 1), "CALL", 285.0)
    assert (quote.multiplier, quote.deliverable, quote.non_standard) == (100.0, "100 AAPL", True)
    assert quote.implied_volatility == pytest.approx(0.34066)
    assert (quote.delta, quote.gamma, quote.theta, quote.vega, quote.rho) == (
        0.814, 0.057, -0.427, 0.039, -0.005,
    )
    assert quote.open_interest == 3_923 and quote.open_interest_time == TRADE_TIME


def test_adjusted_option_root_does_not_have_to_equal_underlying():
    contract_id = "AAPL1  260701C00285000"
    quote = normalize_schwab_option_quote(
        _raw_option(symbol=contract_id), record_id="option-adjusted",
        metadata=_metadata(contract_id, "OPTION"), raw_symbol=contract_id,
        underlying_id="AAPL", expiry=date(2026, 7, 1), option_type="CALL",
        status="VALID", delayed=False,
    )
    assert quote.contract_id == contract_id
    assert quote.underlying_id == "AAPL"


def test_option_unknowns_and_real_zeros_remain_distinct():
    contract_id = "AAPL  260701C00285000"
    metadata = _metadata(contract_id, "OPTION", quality="UNKNOWN")
    quote = normalize_schwab_option_quote(
        _raw_option(
            last=0, bid=0, ask=0, bidSize=True, askSize=-999,
            totalVolume=0, openInterest=float("nan"), volatility=0,
            delta=0, gamma=-999, theta=None, vega=float("inf"), rho=False,
            multiplier=-999, nonStandard="false", deliverableNote="",
        ),
        record_id="option-unknowns", metadata=metadata, raw_symbol=contract_id,
        underlying_id="AAPL", expiry=date(2026, 7, 1), option_type="CALL",
        status="NO_TWO_SIDED", delayed=None,
    )
    assert (quote.last, quote.bid, quote.ask, quote.volume, quote.delta) == (0, 0, 0, 0, 0)
    assert quote.bid_size is None and quote.ask_size is None
    assert quote.open_interest is None and quote.open_interest_time is None
    assert quote.implied_volatility is None and quote.multiplier is None
    assert quote.gamma is None and quote.theta is None and quote.vega is None and quote.rho is None
    assert quote.non_standard is None and quote.deliverable is None


@pytest.mark.parametrize(
    "changes,raw_symbol,underlying,expiry,side,match",
    [
        ({"symbol": "MSFT  260701C00285000"}, "AAPL  260701C00285000", "AAPL", date(2026, 7, 1), "CALL", "identity"),
        ({"underlyingSymbol": "MSFT"}, "AAPL  260701C00285000", "AAPL", date(2026, 7, 1), "CALL", "underlying"),
        ({"putCall": "PUT"}, "AAPL  260701C00285000", "AAPL", date(2026, 7, 1), "CALL", "side"),
        ({}, "AAPL  260701C00285000", "AAPL", date(2026, 7, 2), "CALL", "symbol expiry"),
        ({"putCall": "PUT"}, "AAPL  260701C00285000", "AAPL", date(2026, 7, 1), "PUT", "symbol side"),
        ({"strikePrice": 286.0}, "AAPL  260701C00285000", "AAPL", date(2026, 7, 1), "CALL", "symbol strike"),
        ({"bid": 5.1, "ask": 5.0}, "AAPL  260701C00285000", "AAPL", date(2026, 7, 1), "CALL", "crossed"),
    ],
)
def test_option_rejects_mismatched_context_and_crossed_quotes(
    changes, raw_symbol, underlying, expiry, side, match,
):
    contract_id = "AAPL  260701C00285000"
    with pytest.raises(RecordError, match=match):
        normalize_schwab_option_quote(
            _raw_option(**changes), record_id="option-bad",
            metadata=_metadata(contract_id, "OPTION"), raw_symbol=raw_symbol,
            underlying_id=underlying, expiry=expiry, option_type=side,
            status="VALID", delayed=False,
        )


def test_archive_later_normalization_keeps_original_availability():
    contract_id = "AAPL  260701C00285000"
    original_available = QUOTE_TIME + timedelta(milliseconds=250)
    normalized_later = QUOTE_TIME + timedelta(days=30)
    metadata = _metadata(
        contract_id, "OPTION", available_time=original_available,
        normalized_time=normalized_later, revision=4,
    )
    quote = normalize_schwab_option_quote(
        _raw_option(), record_id="option-archive", metadata=metadata,
        raw_symbol=contract_id, underlying_id="AAPL", expiry=date(2026, 7, 1),
        option_type="CALL", status="VALID", delayed=False,
    )
    assert quote.metadata.available_time == original_available
    assert quote.metadata.normalized_time == normalized_later
    assert quote.metadata.revision == 4


def test_option_uses_chain_level_delayed_context_from_raw_response(monkeypatch):
    response = {
        "status": "SUCCESS",
        "numberOfContracts": 1,
        "isDelayed": True,
        "callExpDateMap": {"2026-07-01:1": {"285.0": [_raw_option()]}},
        "putExpDateMap": {},
    }
    monkeypatch.setattr(schwab_client, "_get", lambda path, params=None: response)
    raw_response = schwab_client._get("/chains", {})
    contract = raw_response["callExpDateMap"]["2026-07-01:1"]["285.0"][0]
    contract_id = contract["symbol"]
    quote = normalize_schwab_option_quote(
        contract, record_id="option-delayed",
        metadata=_metadata(contract_id, "OPTION", quality="STALE"),
        raw_symbol=contract_id, underlying_id="AAPL", expiry=date(2026, 7, 1),
        option_type="CALL", status="STALE", delayed=raw_response["isDelayed"],
    )
    assert quote.delayed is True and quote.status == "STALE"


def test_duplicate_normalization_is_deterministic_and_revisions_round_trip():
    first = normalize_schwab_quote(
        _raw_quote(), record_id="quote-rev-0", metadata=_metadata(revision=0),
        raw_symbol="AAPL", status="VALID", delayed=False,
    )
    duplicate = normalize_schwab_quote(
        _raw_quote(), record_id="quote-rev-0", metadata=_metadata(revision=0),
        raw_symbol="AAPL", status="VALID", delayed=False,
    )
    revision = normalize_schwab_quote(
        _raw_quote(lastPrice=289.1), record_id="quote-rev-1", metadata=_metadata(revision=1),
        raw_symbol="AAPL", status="VALID", delayed=False,
    )
    assert first.to_json() == duplicate.to_json()
    assert Quote.from_json(first.to_json()) == first
    assert revision.metadata.revision == 1 and revision.last == 289.1
    assert revision.record_id != first.record_id


def test_write_deterministic_normalization_proof():
    contract_id = "AAPL  260701C00285000"
    bar_metadata = _metadata(
        source_time=BAR_TIME,
        received_time=BAR_TIME + timedelta(minutes=1),
        normalized_time=BAR_TIME + timedelta(minutes=1),
        available_time=BAR_TIME + timedelta(minutes=1),
    )
    records = [
        normalize_schwab_bar(
            {"datetime": BAR_MS, "open": 100, "high": 102, "low": 99, "close": 101, "volume": 10},
            record_id="proof-bar", metadata=bar_metadata, raw_symbol="AAPL",
            start_time=BAR_TIME - timedelta(minutes=1), end_time=BAR_TIME,
        ),
        normalize_schwab_quote(
            _raw_quote(), record_id="proof-quote", metadata=_metadata(),
            raw_symbol="AAPL", status="VALID", delayed=False,
        ),
        normalize_schwab_option_quote(
            _raw_option(), record_id="proof-option", metadata=_metadata(contract_id, "OPTION"),
            raw_symbol=contract_id, underlying_id="AAPL", expiry=date(2026, 7, 1),
            option_type="CALL", status="VALID", delayed=False,
        ),
    ]
    assert all(type(record).from_json(record.to_json()) == record for record in records)
    proof = {"records": [json.loads(record.to_json()) for record in records]}
    Path("/tmp/m21-schwab-normalization-proof.json").write_text(
        json.dumps(proof, sort_keys=True, separators=(",", ":")) + "\n",
    )
    assert len(proof["records"]) == 3
