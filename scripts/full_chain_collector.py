#!/usr/bin/env python3
"""TODO #109 forward stock and full-options-chain collection from Schwab.

The owner confirmed with Schwab support that raw option chains may be stored for
personal use and testing. Each regular-session poll therefore saves a bounded
Schwab chain alongside the synchronized stock quote. The after-session job
compacts those minute parts into one daily parquet file.

Commands:
  stock-poll   Save one synchronized stock quote snapshot when inside 04:00-17:00 Pacific.
  daily        Save minute stock bars, events, option rows, open interest, and a proof report.
  verify       Rebuild the proof report for one date without network calls.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time as clock_time, timedelta, timezone
import json
import logging
import math
import numpy as np
import os
from pathlib import Path
import re
import sys
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


def _json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _write_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            default=_json_default,
        ) + "\n",
        encoding="utf-8",
    )
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


def option_poll_allowed(now: datetime) -> bool:
    now_pt = now.astimezone(PT)
    bounds = session_bounds(now_pt.date())
    if bounds is None:
        return False
    opened, closed = (stamp.astimezone(PT) for stamp in bounds)
    return opened <= now_pt <= closed


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
    option_result = capture_option_poll(settings, captured, quotes)
    if captured.astimezone(PT).minute % 5 == 0:
        capture_trade_halts(settings, day)
    return {
        "skipped": False, "requested": len(symbols), "written": len(frame),
        "path": str(path), "options": option_result,
    }


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


def _option_part_path(settings: dict, captured: datetime) -> Path:
    captured_pt = captured.astimezone(PT)
    return (
        data_root(settings) / "option_parts" / captured_pt.date().isoformat()
        / f"{captured_pt.strftime('%H%M%S')}.parquet"
    )


def _option_rows(ticker: str, chain, quote: dict, captured: datetime,
                 strike_band_pct: float) -> pd.DataFrame:
    spot = _finite(chain.underlying_price) or _finite(quote.get("c"))
    if spot is None:
        return pd.DataFrame()
    low, high = spot * (1 - strike_band_pct), spot * (1 + strike_band_pct)
    rows = []
    for option_type, source in (("CALL", chain.calls), ("PUT", chain.puts)):
        if source is None or source.empty:
            continue
        selected = source[source["strike"].between(low, high, inclusive="both")]
        for contract in selected.itertuples(index=False):
            values = contract._asdict()
            last_trade = values.get("lastTradeDate")
            rows.append({
                "market_date": captured.astimezone(PT).date().isoformat(),
                "captured_at_utc": captured.astimezone(UTC).isoformat(),
                "ticker": ticker,
                "contract_symbol": values.get("contractSymbol"),
                "option_type": option_type,
                "expiration": values.get("expiry"),
                "strike_price": _finite(values.get("strike")),
                "bid": _finite(values.get("bid")),
                "ask": _finite(values.get("ask")),
                "bid_size": _finite(values.get("bidSize")),
                "ask_size": _finite(values.get("askSize")),
                "last": _finite(values.get("lastPrice")),
                "mark": _finite(values.get("mark")),
                "volume": _finite(values.get("volume")),
                "open_interest": _finite(values.get("openInterest")),
                "implied_volatility": _finite(values.get("impliedVolatility")),
                "delta": _finite(values.get("delta")),
                "gamma": _finite(values.get("gamma")),
                "theta": _finite(values.get("theta")),
                "vega": _finite(values.get("vega")),
                "rho": _finite(values.get("rho")),
                "provider_quote_time_ms": values.get("providerQuoteTime") or 0,
                "last_trade_time": None if pd.isna(last_trade) else str(last_trade),
                "multiplier": _finite(values.get("multiplier")),
                "non_standard": bool(values.get("nonStandard", False)),
                "deliverable_note": str(values.get("deliverableNote") or ""),
                "chain_is_delayed": bool(chain.is_delayed),
                "chain_underlying_price": _finite(chain.underlying_price),
                "underlying_last": _finite(quote.get("c")),
                "underlying_bid": _finite(quote.get("bid")),
                "underlying_ask": _finite(quote.get("ask")),
            })
    return pd.DataFrame(rows)


def capture_option_poll(settings: dict, captured: datetime, quotes: dict) -> dict:
    if not option_poll_allowed(captured):
        return {"skipped": True, "reason": "outside option session"}
    symbols = universe(settings, "options")
    nearest = int(settings["capture"]["nearest_expirations"])
    strike_count = int(settings["capture"]["strike_count"])
    band = float(settings["capture"]["strike_band_pct"])
    workers = int(settings["capture"]["option_workers"])
    frames = []
    errors = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                schwab_client.get_option_chain, ticker,
                nearest=nearest, strike_count=strike_count,
            ): ticker
            for ticker in symbols
        }
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                chain = future.result()
                if chain is None:
                    errors[ticker] = "no chain returned"
                    continue
                frame = _option_rows(ticker, chain, quotes.get(ticker, {}), captured, band)
                if frame.empty:
                    errors[ticker] = "no contracts inside strike band"
                else:
                    frames.append(frame)
            except Exception as exc:
                errors[ticker] = f"{type(exc).__name__}: {exc}"
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    path = _option_part_path(settings, captured)
    if not result.empty:
        _atomic_write_parquet(result, path)
    if not result.empty and not result["chain_is_delayed"].eq(False).all():
        errors["delayed"] = "one or more Schwab chains were marked delayed"
    if not result.empty and errors:
        log.warning("option poll was partial: %s", ", ".join(sorted(errors)))
    if result.empty:
        _notify_once(captured.astimezone(PT).date(), "Schwab option poll saved no rows")
    return {
        "skipped": False, "requested": len(symbols), "names_written": len(frames),
        "rows_written": len(result), "errors": errors, "path": str(path),
    }


def compact_option_day(settings: dict, day: date) -> dict:
    parts_dir = data_root(settings) / "option_parts" / day.isoformat()
    part_paths = sorted(parts_dir.glob("*.parquet"))
    if not part_paths:
        raise RuntimeError("no Schwab option minute files landed")
    options = pd.concat((pd.read_parquet(path) for path in part_paths), ignore_index=True)
    options = options.drop_duplicates(
        subset=["captured_at_utc", "ticker", "contract_symbol"], keep="last",
    ).sort_values(["captured_at_utc", "ticker", "expiration", "strike_price", "option_type"])
    _atomic_write_parquet(options, _day_path(settings, "option_chains", day))
    open_interest = (
        options.dropna(subset=["open_interest"])
        .sort_values("captured_at_utc")
        .groupby(["ticker", "contract_symbol"], as_index=False)
        .tail(1)[["market_date", "captured_at_utc", "ticker", "contract_symbol",
                  "expiration", "strike_price", "option_type", "open_interest"]]
    )
    if not open_interest.empty:
        _atomic_write_parquet(open_interest, _day_path(settings, "open_interest", day))
    return {
        "minute_files": len(part_paths), "option_rows": len(options),
        "open_interest_rows": len(open_interest),
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
        if {"bid", "ask"}.issubset(options.columns):
            quoted = options.dropna(subset=["bid", "ask"])
            checks["option_spreads_sane"] = bool(len(quoted) and
                                                  (quoted["bid"] <= quoted["ask"]).all())
        else:
            checks["option_spreads_sane"] = False
        checks["option_chains_real_time"] = (
            "chain_is_delayed" in options.columns
            and options["chain_is_delayed"].eq(False).all()
        )
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
        option_summary = compact_option_day(settings, day)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        _notify_once(day, error)
        log.error("option compaction failed: %s", error)
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
    print(json.dumps(result, indent=2, sort_keys=True, default=_json_default))
    if args.command == "daily" and not result.get("skipped") and (
        result.get("option_error") or not result.get("proof_passed")
    ):
        return 1
    if args.command == "verify" and not result.get("passed"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
