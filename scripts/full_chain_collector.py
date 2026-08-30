#!/usr/bin/env python3
"""TODO #109 forward stock and licensed full-options-chain collection.

Stock quotes come from Schwab. Raw option rows never come from Schwab because
that account's personal-use terms forbid storing a per-strike chain. Instead,
the daily job downloads Databento's historical OPRA CBBO-1m rows after the
15-minute delay, then stores only the configured strikes and expirations.

Commands:
  stock-poll   Save one synchronized stock quote snapshot when inside 04:00-17:00 Pacific.
  daily        Save minute stock bars, events, option rows, open interest, and a proof report.
  verify       Rebuild the proof report for one date without network calls.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time as clock_time, timedelta, timezone
import json
import logging
import math
import os
from pathlib import Path
import re
import sys
from typing import Iterable
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from consensus_engine.scanners import schwab_client
from consensus_engine.utils.time_context import session_bounds

PT = ZoneInfo("America/Los_Angeles")
UTC = timezone.utc
CONFIG_PATH = ROOT / "config" / "full_chain_collector.yaml"
NOTIFICATION_LOG = Path("/root/task_system/notifications.log")

log = logging.getLogger("full_chain_collector")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def load_settings(path: Path = CONFIG_PATH) -> dict:
    with path.open(encoding="utf-8") as handle:
        settings = yaml.safe_load(handle) or {}
    if not isinstance(settings, dict):
        raise ValueError(f"invalid collector settings in {path}")
    return settings


def universe(settings: dict, kind: str) -> list[str]:
    section = settings["universe"]
    trade = list(section["trade_names"])
    if kind == "options":
        values = trade + list(section["option_context"])
        if section.get("collect_spx_forward"):
            values.append("SPX")
    elif kind == "stocks":
        values = trade + list(section["stock_context"])
        if section.get("collect_spx_forward"):
            values.append("SPX")
    else:
        raise ValueError(f"unknown universe kind: {kind}")
    return list(dict.fromkeys(str(value).upper() for value in values))


def data_root(settings: dict) -> Path:
    return Path(settings["capture"]["data_root"])


def _day_path(settings: dict, category: str, day: date, suffix: str = ".parquet") -> Path:
    return data_root(settings) / category / f"{day.isoformat()}{suffix}"


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _atomic_write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False, compression="zstd")
    os.replace(tmp, path)


def _append_parquet(frame: pd.DataFrame, path: Path, keys: list[str]) -> None:
    if frame.empty:
        return
    if path.exists():
        old = pd.read_parquet(path)
        frame = pd.concat([old, frame], ignore_index=True)
    frame = frame.drop_duplicates(subset=keys, keep="last").sort_values(keys)
    _atomic_write_parquet(frame, path)


def _write_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _session_metadata(day: date) -> dict:
    bounds = session_bounds(day)
    if bounds is None:
        return {"market_date": day.isoformat(), "is_trading_day": False}
    opened, closed = bounds
    open_pt = opened.astimezone(PT)
    close_pt = closed.astimezone(PT)
    return {
        "market_date": day.isoformat(),
        "is_trading_day": True,
        "open_pacific": open_pt.isoformat(),
        "close_pacific": close_pt.isoformat(),
        "early_close": close_pt.time() < clock_time(13, 0),
    }


def stock_poll_allowed(now: datetime) -> bool:
    now_pt = now.astimezone(PT)
    if session_bounds(now_pt.date()) is None:
        return False
    return clock_time(4, 0) <= now_pt.time().replace(tzinfo=None) <= clock_time(17, 0)


def capture_stock_poll(settings: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    if not stock_poll_allowed(now):
        return {"skipped": True, "reason": "outside collection window"}
    symbols = universe(settings, "stocks")
    quotes = schwab_client.get_quotes(symbols)
    captured = now.astimezone(UTC)
    day = captured.astimezone(PT).date()
    session = _session_metadata(day)
    rows = []
    for ticker in symbols:
        quote = quotes.get(ticker)
        if not quote:
            continue
        rows.append({
            "market_date": day.isoformat(),
            "captured_at_utc": captured.isoformat(),
            "ticker": ticker,
            "last": _finite(quote.get("c")),
            "bid": _finite(quote.get("bid")),
            "ask": _finite(quote.get("ask")),
            "bid_size": _finite(quote.get("bid_size")),
            "ask_size": _finite(quote.get("ask_size")),
            "quote_time": quote.get("quote_time"),
            "trade_time": quote.get("t"),
            "open": _finite(quote.get("o")),
            "high": _finite(quote.get("h")),
            "low": _finite(quote.get("l")),
            "volume": _finite(quote.get("v")),
            "halt_status": quote.get("halt_status"),
            "shortable": quote.get("shortable"),
            "hard_to_borrow": quote.get("hard_to_borrow"),
            "htb_rate": _finite(quote.get("htb_rate")),
            "early_close": session.get("early_close", False),
        })
    frame = pd.DataFrame(rows)
    path = _day_path(settings, "stock_quotes", day)
    _append_parquet(frame, path, ["captured_at_utc", "ticker"])
    if captured.astimezone(PT).minute % 5 == 0:
        capture_trade_halts(settings, day)
    return {"skipped": False, "requested": len(symbols), "written": len(frame), "path": str(path)}


def capture_trade_halts(settings: dict, day: date) -> pd.DataFrame:
    """Save Nasdaq Trader's current halt time and reason code every five minutes."""
    import requests

    url = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"
    rows = []
    try:
        response = requests.get(url, timeout=10, headers={"User-Agent": "OpenClaw/1.0"})
        response.raise_for_status()
        root = ET.fromstring(response.content)
        captured = datetime.now(UTC).isoformat()
        for item in root.findall(".//item"):
            values = {re.sub(r"^.*}", "", child.tag): (child.text or "").strip()
                      for child in list(item)}
            symbol = values.get("IssueSymbol") or values.get("symbol")
            if not symbol:
                continue
            rows.append({
                "captured_at_utc": captured,
                "ticker": symbol.upper(),
                "halt_date": values.get("HaltDate"),
                "halt_time": values.get("HaltTime"),
                "reason_code": values.get("ReasonCode"),
                "resume_date": values.get("ResumptionDate"),
                "resume_quote_time": values.get("ResumptionQuoteTime"),
                "resume_trade_time": values.get("ResumptionTradeTime"),
                "source": url,
            })
    except Exception as exc:
        log.warning("trade-halt feed skipped: %s", exc)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        wanted = set(universe(settings, "stocks"))
        frame = frame[frame["ticker"].isin(wanted)]
        _append_parquet(frame, _day_path(settings, "halts", day),
                        ["ticker", "halt_date", "halt_time"])
    return frame


def capture_stock_bars(settings: dict, day: date) -> pd.DataFrame:
    rows = []
    start = datetime.combine(day, clock_time(4, 0), PT)
    end = datetime.combine(day, clock_time(17, 1), PT)
    for ticker in universe(settings, "stocks"):
        try:
            frame = schwab_client.get_price_history(
                ticker, interval="1m", start=start, end=end, extended_hours=True,
            )
        except Exception as exc:  # one ticker must not drop the entire day
            log.warning("stock bars skipped for %s: %s", ticker, exc)
            continue
        if frame is None or frame.empty:
            continue
        item = frame.reset_index().rename(columns={"Date": "timestamp"})
        first = item.columns[0]
        if "timestamp" not in item.columns:
            item = item.rename(columns={first: "timestamp"})
        item["timestamp"] = pd.to_datetime(item["timestamp"], utc=True)
        item.insert(1, "ticker", ticker)
        item.columns = [str(column).lower() for column in item.columns]
        rows.append(item)
    result = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if not result.empty:
        _atomic_write_parquet(result, _day_path(settings, "stock_bars", day))
    return result


def capture_events(settings: dict, day: date) -> pd.DataFrame:
    """Save earnings times, dividends, and splits as observed on this date."""
    import yfinance as yf

    captured = datetime.now(UTC).isoformat()
    rows: list[dict] = []
    for ticker in universe(settings, "stocks"):
        try:
            history = yf.Ticker(ticker).history(period="3mo", actions=True, auto_adjust=False)
            if history is not None and not history.empty:
                for stamp, values in history.iterrows():
                    dividend = _finite(values.get("Dividends")) or 0.0
                    split = _finite(values.get("Stock Splits")) or 0.0
                    if dividend:
                        rows.append({"captured_at_utc": captured, "ticker": ticker,
                                     "event": "dividend", "event_time": pd.Timestamp(stamp).isoformat(),
                                     "value": dividend, "source": "yfinance"})
                    if split:
                        rows.append({"captured_at_utc": captured, "ticker": ticker,
                                     "event": "split", "event_time": pd.Timestamp(stamp).isoformat(),
                                     "value": split, "source": "yfinance"})
            earnings = yf.Ticker(ticker).get_earnings_dates(limit=12)
            if earnings is not None and not earnings.empty:
                for stamp, values in earnings.iterrows():
                    event_time = pd.Timestamp(stamp)
                    if event_time.tzinfo is None:
                        event_time = event_time.tz_localize(PT)
                    event_day = event_time.astimezone(PT).date()
                    if day - timedelta(days=7) <= event_day <= day + timedelta(days=180):
                        rows.append({"captured_at_utc": captured, "ticker": ticker,
                                     "event": "earnings", "event_time": event_time.isoformat(),
                                     "value": _finite(values.get("EPS Estimate")),
                                     "source": "yfinance"})
        except Exception as exc:
            log.warning("events skipped for %s: %s", ticker, exc)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.drop_duplicates(subset=["ticker", "event", "event_time"], keep="last")
        _atomic_write_parquet(frame, _day_path(settings, "events", day))
    return frame


def _parent_from_raw_symbol(raw_symbol: str) -> str:
    parent = str(raw_symbol)[:6].strip().upper()
    return "SPX" if parent == "SPXW" else parent


def select_contracts(definitions: pd.DataFrame, spots: dict[str, float], day: date,
                     strike_band_pct: float, nearest_expirations: int) -> pd.DataFrame:
    if definitions.empty:
        return definitions.copy()
    frame = definitions.copy()
    if "raw_symbol" not in frame.columns and "symbol" in frame.columns:
        frame["raw_symbol"] = frame["symbol"]
    frame["ticker"] = frame["raw_symbol"].map(_parent_from_raw_symbol)
    frame["expiration"] = pd.to_datetime(frame["expiration"], utc=True, errors="coerce")
    frame["strike_price"] = pd.to_numeric(frame["strike_price"], errors="coerce")
    selected = []
    for ticker, spot in spots.items():
        if isinstance(spot, (tuple, list)):
            spot_low, spot_high = map(float, spot)
        else:
            spot_low = spot_high = float(spot)
        if not spot_low or not spot_high or not all(map(math.isfinite, (spot_low, spot_high))):
            continue
        group = frame[(frame["ticker"] == ticker) & (frame["expiration"].dt.date >= day)]
        expirations = sorted(group["expiration"].dropna().dt.date.unique())[:nearest_expirations]
        low = spot_low * (1 - strike_band_pct)
        high = spot_high * (1 + strike_band_pct)
        group = group[
            group["expiration"].dt.date.isin(expirations)
            & group["strike_price"].between(low, high, inclusive="both")
        ]
        selected.append(group)
    if not selected:
        return frame.iloc[0:0].copy()
    result = pd.concat(selected, ignore_index=True)
    return result.drop_duplicates(subset=["raw_symbol"])


def _spot_ranges(settings: dict, day: date) -> dict[str, float | tuple[float, float]]:
    bar_path = _day_path(settings, "stock_bars", day)
    if bar_path.exists():
        bars = pd.read_parquet(bar_path)
        bars = bars[bars["ticker"].isin(universe(settings, "options"))]
        grouped = bars.groupby("ticker").agg(low=("low", "min"), high=("high", "max"))
        return {str(ticker): (float(row.low), float(row.high))
                for ticker, row in grouped.iterrows()}
    quote_path = _day_path(settings, "stock_quotes", day)
    if not quote_path.exists():
        return {}
    quotes = pd.read_parquet(quote_path).sort_values("captured_at_utc")
    quotes = quotes.dropna(subset=["last"]).groupby("ticker", as_index=False).tail(1)
    return {str(row.ticker): float(row.last) for row in quotes.itertuples()}


def _open_interest_only(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "stat_type" not in frame.columns:
        return frame.iloc[0:0].copy()
    values = frame["stat_type"]
    normalized = values.astype(str).str.lower()
    return frame[(values == 9) | normalized.isin({"9", "open_interest", "stattype.open_interest"})]


def _chunks(values: list[str], size: int = 1200) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _frame_from_dbn(store) -> pd.DataFrame:
    frame = store.to_df()
    if frame.empty:
        return frame.reset_index()
    frame = frame.reset_index()
    if "symbol" not in frame.columns and "raw_symbol" in frame.columns:
        frame["symbol"] = frame["raw_symbol"]
    return frame


def _download_frames(client, dataset: str, symbols: list[str], schema: str,
                     start: str, end: str, max_cost: float) -> tuple[pd.DataFrame, float]:
    costs = []
    groups = list(_chunks(symbols))
    for group in groups:
        costs.append(client.metadata.get_cost(
            dataset=dataset, symbols=group, stype_in="raw_symbol",
            schema=schema, start=start, end=end,
        ))
    total = float(sum(costs))
    if total > max_cost:
        raise RuntimeError(
            f"{schema} request would cost ${total:.2f}, above the ${max_cost:.2f} daily limit"
        )
    frames = []
    for group in groups:
        store = client.timeseries.get_range(
            dataset=dataset, symbols=group, stype_in="raw_symbol", stype_out="raw_symbol",
            schema=schema, start=start, end=end,
        )
        frame = _frame_from_dbn(store)
        if not frame.empty:
            frames.append(frame)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(), total)


def _merge_option_frames(cbbo: pd.DataFrame, ohlcv: pd.DataFrame,
                         definitions: pd.DataFrame) -> pd.DataFrame:
    if cbbo.empty:
        return cbbo
    frame = cbbo.copy()
    time_col = "ts_recv" if "ts_recv" in frame.columns else frame.columns[0]
    frame["minute"] = pd.to_datetime(frame[time_col], utc=True).dt.floor("min")
    frame["symbol"] = frame["symbol"].astype(str)
    if not ohlcv.empty:
        bars = ohlcv.copy()
        bar_time = "ts_event" if "ts_event" in bars.columns else (
            "ts_recv" if "ts_recv" in bars.columns else bars.columns[0]
        )
        bars["minute"] = pd.to_datetime(bars[bar_time], utc=True).dt.floor("min")
        keep = [column for column in ("symbol", "minute", "open", "high", "low", "close", "volume")
                if column in bars.columns]
        frame = frame.merge(bars[keep].drop_duplicates(["symbol", "minute"]),
                            on=["symbol", "minute"], how="left")
    defs = definitions[["raw_symbol", "ticker", "expiration", "strike_price"]].copy()
    defs = defs.rename(columns={"raw_symbol": "symbol"})
    frame = frame.merge(defs, on="symbol", how="left")
    frame["option_type"] = frame["symbol"].str[12:13]
    return frame


def _attach_underlying(settings: dict, day: date, options: pd.DataFrame) -> pd.DataFrame:
    path = _day_path(settings, "stock_quotes", day)
    if options.empty or not path.exists():
        return options
    quotes = pd.read_parquet(path)
    quotes["minute"] = pd.to_datetime(quotes["captured_at_utc"], utc=True).dt.floor("min")
    quotes = quotes.rename(columns={"last": "underlying_last", "bid": "underlying_bid",
                                    "ask": "underlying_ask"})
    keep = ["ticker", "minute", "underlying_last", "underlying_bid", "underlying_ask"]
    return options.merge(quotes[keep].drop_duplicates(["ticker", "minute"]),
                         on=["ticker", "minute"], how="left")


def download_option_session(settings: dict, day: date) -> dict:
    key = os.environ.get("DATABENTO_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Databento access key is missing")
    import databento as db

    parents = [f"{ticker}.OPT" for ticker in universe(settings, "options")]
    if settings["universe"].get("collect_spx_forward"):
        parents.append("SPXW.OPT")
    start = datetime.combine(day, clock_time(6, 30), PT).astimezone(UTC).isoformat()
    end = datetime.combine(day, clock_time(13, 1), PT).astimezone(UTC).isoformat()
    client = db.Historical(key)
    dataset = settings["capture"]["databento_dataset"]
    daily_limit = float(settings["capture"]["max_daily_cost_usd"])
    definition_end = (day + timedelta(days=1)).isoformat()
    definition_cost = float(client.metadata.get_cost(
        dataset=dataset, schema="definition", symbols=parents, stype_in="parent",
        start=day.isoformat(), end=definition_end,
    ))
    if definition_cost > daily_limit:
        raise RuntimeError(
            f"definition request would cost ${definition_cost:.2f}, "
            f"above the ${daily_limit:.2f} daily limit"
        )
    definitions = _frame_from_dbn(client.timeseries.get_range(
        dataset=dataset, schema="definition",
        symbols=parents, stype_in="parent", start=day.isoformat(),
        end=definition_end,
    ))
    spots = _spot_ranges(settings, day)
    chosen = select_contracts(
        definitions, spots, day,
        float(settings["capture"]["strike_band_pct"]),
        int(settings["capture"]["nearest_expirations"]),
    )
    raw_symbols = chosen["raw_symbol"].astype(str).tolist()
    if not raw_symbols:
        raise RuntimeError("no option contracts matched the configured expirations and strike band")
    remaining = max(0.0, daily_limit - definition_cost)
    cbbo, cbbo_cost = _download_frames(
        client, dataset, raw_symbols, "cbbo-1m", start, end, remaining,
    )
    remaining = max(0.0, remaining - cbbo_cost)
    ohlcv, ohlcv_cost = _download_frames(
        client, dataset, raw_symbols, "ohlcv-1m", start, end, remaining,
    )
    remaining = max(0.0, remaining - ohlcv_cost)
    stats_start = datetime.combine(day, clock_time(0, 0), UTC).isoformat()
    stats_end = datetime.combine(day + timedelta(days=1), clock_time(0, 0), UTC).isoformat()
    stats, stats_cost = _download_frames(
        client, dataset, raw_symbols, "statistics", stats_start, stats_end, remaining,
    )
    stats = _open_interest_only(stats)
    options = _merge_option_frames(cbbo, ohlcv, chosen)
    options = _attach_underlying(settings, day, options)
    _atomic_write_parquet(options, _day_path(settings, "option_chains", day))
    if not stats.empty:
        _atomic_write_parquet(stats, _day_path(settings, "open_interest", day))
    return {
        "contracts": len(raw_symbols), "option_rows": len(options), "statistics_rows": len(stats),
        "estimated_cost_usd": round(
            definition_cost + cbbo_cost + ohlcv_cost + stats_cost, 6
        ),
    }


def verify_day(settings: dict, day: date) -> dict:
    report = {"market_date": day.isoformat(), "checked_at_utc": datetime.now(UTC).isoformat()}
    session = _session_metadata(day)
    report["session"] = session
    checks = {}
    quote_path = _day_path(settings, "stock_quotes", day)
    bar_path = _day_path(settings, "stock_bars", day)
    option_path = _day_path(settings, "option_chains", day)
    oi_path = _day_path(settings, "open_interest", day)
    checks["stock_quotes_exist"] = quote_path.exists()
    checks["stock_bars_exist"] = bar_path.exists()
    checks["option_chain_exists"] = option_path.exists()
    checks["open_interest_exists"] = oi_path.exists()
    if quote_path.exists():
        quotes = pd.read_parquet(quote_path)
        regular = quotes[quotes["ticker"].isin(universe(settings, "stocks"))]
        checks["all_stock_names_seen"] = set(universe(settings, "stocks")).issubset(set(regular["ticker"]))
        sane = regular.dropna(subset=["bid", "ask"])
        checks["stock_spreads_sane"] = bool(len(sane) and (sane["bid"] <= sane["ask"]).all())
        report["stock_quote_rows"] = len(quotes)
        quote_minutes = pd.to_datetime(quotes["captured_at_utc"], utc=True).dt.floor("min")
        checks["stock_minutes_cover_session"] = quote_minutes.nunique() >= 300
    if bar_path.exists():
        bars = pd.read_parquet(bar_path)
        checks["stock_bars_have_all_names"] = set(universe(settings, "stocks")).issubset(
            set(bars["ticker"])
        )
        report["stock_bar_rows"] = len(bars)
    if option_path.exists():
        options = pd.read_parquet(option_path)
        checks["option_rows_present"] = len(options) > 0
        if {"bid_px_00", "ask_px_00"}.issubset(options.columns):
            quoted = options.dropna(subset=["bid_px_00", "ask_px_00"])
            checks["option_spreads_sane"] = bool(len(quoted) and
                                                  (quoted["bid_px_00"] <= quoted["ask_px_00"]).all())
        else:
            checks["option_spreads_sane"] = False
        checks["underlying_same_minute_present"] = (
            "underlying_last" in options.columns
            and options["underlying_last"].notna().mean() >= 0.95
        )
        checks["expiration_count_bounded"] = (
            "expiration" in options.columns
            and options.groupby("ticker")["expiration"].nunique().max()
            <= int(settings["capture"]["nearest_expirations"])
        )
        report["option_rows"] = len(options)
        checks["all_option_names_seen"] = set(universe(settings, "options")).issubset(
            set(options["ticker"])
        )
        if "strike_price" in options.columns:
            band = float(settings["capture"]["strike_band_pct"])
            ranges = _spot_ranges(settings, day)
            in_band = []
            for row in options[["ticker", "strike_price"]].dropna().itertuples(index=False):
                bounds = ranges.get(row.ticker)
                if bounds is None:
                    in_band.append(False)
                    continue
                low_spot, high_spot = bounds if isinstance(bounds, tuple) else (bounds, bounds)
                in_band.append(low_spot * (1 - band) <= row.strike_price <= high_spot * (1 + band))
            checks["strikes_in_configured_band"] = bool(in_band and all(in_band))
        else:
            checks["strikes_in_configured_band"] = False
    if oi_path.exists():
        open_interest = pd.read_parquet(oi_path)
        checks["open_interest_rows_present"] = len(open_interest) > 0
        report["open_interest_rows"] = len(open_interest)
    report["checks"] = checks
    report["passed"] = bool(checks) and all(checks.values())
    _write_json(report, _day_path(settings, "proof", day, suffix=".json"))
    return report


def _notify_once(day: date, message: str) -> None:
    marker = Path(f"/home/openclaw/.openclaw/research-data/todo-109/.notified-{day.isoformat()}")
    if marker.exists():
        return
    try:
        NOTIFICATION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with NOTIFICATION_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"[{datetime.now(PT).isoformat()}] TODO #109 collector: {message}\n")
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except OSError:
        pass


def run_daily(settings: dict, day: date) -> dict:
    session = _session_metadata(day)
    _write_json(session, _day_path(settings, "sessions", day, suffix=".json"))
    if not session["is_trading_day"]:
        return {"skipped": True, "reason": "not a trading day"}
    bars = capture_stock_bars(settings, day)
    events = capture_events(settings, day)
    option_summary = None
    error = None
    try:
        option_summary = download_option_session(settings, day)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        _notify_once(day, error)
        log.error("option download failed: %s", error)
    proof = verify_day(settings, day)
    summary = {
        "skipped": False, "stock_bar_rows": len(bars), "event_rows": len(events),
        "options": option_summary, "option_error": error, "proof_passed": proof["passed"],
    }
    _write_json(summary, _day_path(settings, "runs", day, suffix=".json"))
    return summary


def parse_day(value: str | None) -> date:
    if not value or value == "today":
        return datetime.now(PT).date()
    return date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("stock-poll", "daily", "verify"))
    parser.add_argument("--date", default="today")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args()
    settings = load_settings(args.config)
    day = parse_day(args.date)
    if args.command == "stock-poll":
        result = capture_stock_poll(settings)
    elif args.command == "daily":
        result = run_daily(settings, day)
    else:
        result = verify_day(settings, day)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    if args.command == "daily" and not result.get("skipped") and (
        result.get("option_error") or not result.get("proof_passed")
    ):
        return 1
    if args.command == "verify" and not result.get("passed"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
