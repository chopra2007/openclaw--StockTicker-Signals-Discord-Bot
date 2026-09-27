#!/usr/bin/env python3
"""Write M9.1ER readiness counts from the two audited saved bar files."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sys

import pyarrow.dataset as ds
import dotenv


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# This offline research script needs only record classes.  Do not let the
# application import path inspect the machine's live environment file.
dotenv.load_dotenv = lambda *args, **kwargs: False
dotenv.main.load_dotenv = dotenv.load_dotenv

from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.retained_history_batches import RetainedHistoryBatches, SessionHistory
from consensus_engine.saved_market_data_readiness import count_saved_bar_readiness
from consensus_engine.search_run_config import TRAINING_TICKERS
from consensus_engine.trade_alerts_models import Bar, SourceMetadata
from consensus_engine.utils.time_context import as_utc, session_bounds


BINDING = ROOT / "trade_alerts_build_docs/M9_1EQ_AUDITED_INPUT_BINDING.json"
AUDIT = ROOT / "trade_alerts_build_docs/M9_1EP_SAVED_DATA_QUALIFICATION.json"
OUTPUT = ROOT / "trade_alerts_build_docs/M9_1ER_DEVELOPMENT_READINESS_COUNTS.json"
DATA_ROOT = ROOT / ".omc/research/professional-day-trader-methods"
TYPES = {ticker: ("ETF" if ticker in {"SPY", "QQQ", "XLV", "USO"} else "EQUITY")
         for ticker in TRAINING_TICKERS}


class _CachedHistoryBatch(HistoryBatch):
    """Reuse identical as-of views requested by several frozen adapters."""

    def __post_init__(self):
        super().__post_init__()
        object.__setattr__(self, "_coverage_cache", {})

    def coverage_at(self, evaluated_at):
        if evaluated_at not in self._coverage_cache:
            self._coverage_cache[evaluated_at] = super().coverage_at(evaluated_at)
        return self._coverage_cache[evaluated_at]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _batch(dataset: str, digest: str, ticker: str, session: str,
           rows: list[dict]) -> HistoryBatch:
    bounds = session_bounds(date.fromisoformat(session))
    if bounds is None:
        raise ValueError(f"saved row uses non-session date {session}")
    opened, closed = map(as_utc, bounds)
    bars = []
    for row in sorted(rows, key=lambda value: value["minute"]):
        start = opened + timedelta(minutes=int(row["minute"]) - 570)
        end = start + timedelta(minutes=1)
        metadata = SourceMetadata(
            instrument_id=ticker, instrument_type=TYPES[ticker], source=dataset,
            source_time=start, received_time=end, available_time=end,
            normalized_time=end, session=session, revision=0,
            data_mode="AUDITED_SAVED_PARQUET_OHLCV_1M", quality="UNKNOWN",
        )
        bars.append(Bar(
            record_id=f"m91er:{dataset}:{digest}:{ticker}:{session}:{row['minute']}",
            metadata=metadata, start_time=start, end_time=end, is_final=False,
            open=float(row["open"]), high=float(row["high"]), low=float(row["low"]),
            close=float(row["close"]), volume=int(row["volume"]),
            adjustment_basis="SAVED_PARQUET_UNPROVEN",
            price_convention="USD_PER_SHARE", volume_convention="SHARES",
        ))
    request = HistoryRequest(symbol=ticker, start=opened, end=closed)
    conventions = HistoryConventions(
        timestamp="START", session="PREMARKET_AND_REGULAR",
        adjustment_basis="SAVED_PARQUET_UNPROVEN", price="USD_PER_SHARE",
        volume="SHARES", coverage_basis=dataset + "_AUDITED_SAVED_BAR_SUBSET",
        finality="PROVISIONAL", publication="BATCH",
        evidence_reference="M9_1EP_SAVED_DATA_QUALIFICATION.json",
    )
    return _CachedHistoryBatch(request, dataset, conventions, tuple(bars))


def _load(path: Path, dataset: str, digest: str,
          development_dates: tuple[str, ...]) -> RetainedHistoryBatches:
    source = ds.dataset(path, format="parquet")
    table = source.to_table(
        filter=(ds.field("symbol").isin(list(TRAINING_TICKERS))
                & ds.field("date").isin(list(development_dates))),
        columns=["date", "symbol", "minute", "open", "high", "low", "close", "volume"],
    )
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in table.to_pylist():
        grouped[(row["symbol"], row["date"])].append(row)
    batches = {(ticker, day): _batch(dataset, digest, ticker, day, rows)
               for (ticker, day), rows in grouped.items()}
    histories = []
    skipped = []
    without_prior = []
    for ticker in TRAINING_TICKERS:
        previous = None
        for day in development_dates:
            batch = batches.get((ticker, day))
            if batch is None:
                skipped.append((ticker, day, "NO_USABLE_BARS"))
                continue
            if previous is None:
                without_prior.append((ticker, day))
            histories.append(SessionHistory(ticker, day, batch, previous))
            previous = batch
    return RetainedHistoryBatches(tuple(histories), tuple(skipped), tuple(without_prior))


def build_record() -> dict:
    binding = json.loads(BINDING.read_text())
    audit = json.loads(AUDIT.read_text())
    frozen_sample = tuple(audit["cross_dataset_agreement"]["sample_dates"])
    development_count = len(frozen_sample) * 60 // 100
    dates = frozen_sample[:development_count]
    source_rows = []
    for source in binding["source_files"]:
        path = DATA_ROOT / Path(source["path"]).name
        if _sha256(path) != source["sha256"]:
            raise ValueError(f"audited source hash changed: {path.name}")
        dataset = "EQUS.MINI" if "equs" in path.name else "XNYS.PILLAR"
        result = count_saved_bar_readiness(
            binding, _load(path, dataset, source["sha256"], dates),
            development_dates=dates, instrument_types=TYPES)
        source_rows.append({"dataset": dataset, "path": source["path"],
                            "sha256": source["sha256"], "counts": result.as_dict()})
    return {
        "version": "M91ER_DEVELOPMENT_READINESS_RECORD_V1",
        "scope_reference": "M9.1EP frozen 40-date audit sample; first 60% development dates only",
        "frozen_sample_dates": list(frozen_sample),
        "development_dates": list(dates),
        "reserved_non_development_dates": list(frozen_sample[development_count:]),
        "sources": source_rows,
        "held_out_tickers_read": [],
        "held_out_evaluation": "CLOSED",
        "return_calculated": False,
        "promotion_or_live_release": False,
        "network_used": False,
        "spend_usd": 0,
    }


def main() -> None:
    OUTPUT.write_text(json.dumps(build_record(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
