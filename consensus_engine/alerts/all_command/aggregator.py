"""Top-level orchestrator for the !all command.

Owns the 60s deadline, parallel data gather, anchor pipeline, gap-fill,
synthesis LLM call, and the final embed-send + vault-write fan-out. Wraps
everything in a single `cache.all_with_single_flight` so concurrent
`!all NVDA` invocations share one compute pass and subsequent calls within
15min hit the cache.

Per plan §4 / §6.3 — invoked from `_handle_all` in commands.py (PR5).
Partial source failures are absorbed inline (`<source>: unavailable`)
rather than aborting (D13).
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

from consensus_engine import config as cfg
from consensus_engine.alerts.all_command import (
    cache,
    discord_history,
    embed as embed_mod,
    gap_fill,
    levels,
    narrator,
    output_filter,
    structured_fields,
    vault_writer,
)
from consensus_engine.alerts.discord import (
    send_command_embed_reply,
    send_command_reply,
)
from consensus_engine.utils.rate_limiter import rate_limiter
from consensus_engine.utils.tickers import is_valid_ticker_format

log = logging.getLogger("consensus_engine.alerts.all_command.aggregator")

_DEADLINE_SECONDS = 160.0
_GAP_FILL_BUDGET = 20.0
_SYNTHESIS_MIN_BUDGET = 10.0
_PARITY_LOG_PATH = Path(
    "/home/openclaw/.openclaw/workspace"
    "/.claude/discover/discord-bot-improvements/parity-results.jsonl"
)


def _remaining(start: float, total: float = _DEADLINE_SECONDS) -> float:
    """Seconds remaining vs the deadline ceiling.

    Raised 80s→160s: the synthesis per-model timeout is `min(90, _remaining)`
    (narrator._invoke_synthesis). With an 80s ceiling and gather+gap_fill+
    sanitize eating ~40-65s, synthesis only inherited ~40s — but a free-tier
    model needs ~70s for the real prompt (probed: gpt-oss-120b = 70.7s on a
    4.5K-token prompt). The 40s cap cut every model off mid-response, walked
    the whole chain to exhaustion, and forced the data-only fallback. 160s
    leaves synthesis the full 90s it caps at. gap_fill stays capped by
    _GAP_FILL_BUDGET; this only widens the synthesis window."""
    return max(0.0, total - (time.monotonic() - start))


def _is_exc(x: Any) -> bool:
    return isinstance(x, BaseException)


def _result_or_default(x: Any, default: Any) -> Any:
    """Treat exceptions as missing data; otherwise return as-is."""
    if _is_exc(x) or x is None:
        return default
    return x


def _has_value(val: Any) -> bool:
    """A source contributed if it returned non-None, non-exception, non-empty."""
    if val is None or _is_exc(val):
        return False
    if isinstance(val, (list, dict, str, tuple, set)) and not val:
        return False
    return True


def _classify_sources(items: list[tuple[str, Any]]) -> tuple[list[str], list[str]]:
    """Split (label, value) gather results into (sources_surfaced, source_failures).

    PR2 (B2 fix): pre-PR2 the aggregator only tracked `source_status`, which
    was actually a list of failure labels — so the embed footer's
    `sources: {len(source_status)}` reported 0 on a healthy run. Now both
    lists are populated in one pass: a label goes into `failures` if its
    raw result was an exception, otherwise into `surfaced` iff it carries
    non-empty data.
    """
    surfaced: list[str] = []
    failures: list[str] = []
    for label, val in items:
        s = _source_label(label, val)
        if s:
            failures.append(s)
        elif _has_value(val):
            surfaced.append(label)
    return surfaced, failures


def _source_label(name: str, raw: Any) -> Optional[str]:
    """Render `<source>: unavailable` if the gather slot raised."""
    if _is_exc(raw):
        return f"{name}: unavailable"
    return None


async def _safe_call(coro_factory, default):
    """Run a 0-arg coroutine factory; on any exception return `default`."""
    try:
        return await coro_factory()
    except Exception as exc:  # noqa: BLE001 — D13 partial failure
        log.warning("aggregator._safe_call: %s -> %s", coro_factory, exc)
        return default


async def _score_ticker_safe(ticker: str):
    """Run cross_reference.score_ticker with graceful failure."""
    try:
        from consensus_engine.cross_reference import score_ticker
        return await score_ticker(ticker)
    except Exception as exc:  # noqa: BLE001
        log.warning("aggregator._score_ticker_safe: $%s failed: %s", ticker, exc)
        return None


async def _verify_technical_safe(ticker: str, direction: str):
    try:
        from consensus_engine.analysis.technical import verify_technical
        return await verify_technical(ticker, direction)
    except Exception as exc:  # noqa: BLE001
        log.debug("aggregator._verify_technical_safe: %s", exc)
        return None


async def _db_call(name: str, *args, **kwargs):
    """Call a function on consensus_engine.db by name, with graceful failure.

    Returns the function's result, or None if the function does not exist or
    raises. Lets the orchestrator survive against partial DB schema/feature
    availability across deployments (D13).
    """
    try:
        from consensus_engine import db
        fn = getattr(db, name, None)
        if fn is None:
            return None
        return await fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        log.warning("aggregator._db_call(%s) raised: %s", name, exc)
        return None


async def _scanner_call(module_path: str, attr: str, *args, **kwargs):
    """Import-and-call a scanner function with graceful failure."""
    try:
        import importlib
        mod = importlib.import_module(module_path)
        fn = getattr(mod, attr, None)
        if fn is None:
            return None
        result = fn(*args, **kwargs)
        if asyncio.iscoroutine(result):
            return await result
        return result
    except Exception as exc:  # noqa: BLE001
        log.warning("aggregator._scanner_call(%s.%s) raised: %s", module_path, attr, exc)
        return None


async def _gather_all_sources(ticker: str) -> dict:
    """Run the parallel data gather. Per-source failures degrade gracefully."""
    ticker_meta_task = _db_call("get_ticker_metadata", ticker)
    score_task = _score_ticker_safe(ticker)
    tech_long_task = _verify_technical_safe(ticker, "long")
    tech_short_task = _verify_technical_safe(ticker, "short")
    twitter_task = _db_call("get_twitter_signals", ticker, window_seconds=1800)
    social_task = _db_call("get_social_signals", ticker, window_seconds=3600)
    yt_signals_task = _db_call("get_youtube_signals_for_ticker", ticker, days=7)
    yt_options_task = _db_call("get_youtube_options_for_ticker", ticker, days=7)
    yt_levels_task = _db_call("get_youtube_levels_for_ticker", ticker, days=7)
    yt_evidence_task = _db_call("get_youtube_evidence_for_ticker", ticker, days=7)
    yt_visual_task = _db_call("get_youtube_visual_evidence_for_ticker", ticker, days=7)
    alert_history_task = _db_call("get_alert_history_for_ticker", ticker, limit=30, days=30)
    decision_snapshots_task = _db_call("get_decision_snapshots", ticker, days=14)
    next_earnings_task = _scanner_call(
        "consensus_engine.scanners.earnings_calendar",
        "fetch_next_earnings_for_ticker",
        ticker,
    )
    recent_earnings_task = _scanner_call(
        "consensus_engine.scanners.earnings_calendar",
        "fetch_recent_earnings_for_ticker",
        ticker,
    )
    daily_candles_task = _scanner_call(
        "consensus_engine.analysis.patterns",
        "fetch_daily_candles",
        ticker,
    )

    news_task = _scanner_call("consensus_engine.scanners.news", "news_cascade", ticker)
    sec_task = _scanner_call(
        "consensus_engine.scanners.sec_edgar", "check_recent_filings", ticker, hours_back=168,
    )
    options_task = _scanner_call(
        "consensus_engine.scanners.options", "check_unusual_options", ticker, executor=None,
    )
    options_flow_task = _db_call("get_options_flow_for_ticker", ticker, days=7)
    trends_task: asyncio.Future = asyncio.ensure_future(asyncio.sleep(0, result={}))
    if cfg.get("precision_engine.serpapi_enabled", False):
        trends_task = asyncio.ensure_future(
            _scanner_call(
                "consensus_engine.scanners.social",
                "scan_google_trends_serpapi",
                [ticker],
            )
        )
    apewisdom_task = _scanner_call(
        "consensus_engine.scanners.social", "get_apewisdom_for_ticker", ticker,
    )

    name_for_filter = None
    ticker_meta = await ticker_meta_task
    if isinstance(ticker_meta, dict):
        name = ticker_meta.get("name") or ticker_meta.get("company_name")
        if name:
            name_for_filter = str(name)

    chat_task = discord_history.fetch_chat_24h_ticker_filtered(ticker, name_for_filter)
    brief_task = discord_history.fetch_brief_last_3()
    vault_path = cfg.get("vault.path", "")
    vault_task = vault_writer.read_existing_vault(ticker, vault_path)

    # #6 !all levers — appended LAST so the positional unpack below stays stable.
    # max-pain (yfinance option chain) + peer relative strength (yfinance closes).
    max_pain_task = _scanner_call(
        "consensus_engine.scanners.options", "compute_max_pain", ticker, executor=None,
    )
    peer_strength_task = _scanner_call(
        "consensus_engine.analysis.peer_comparison", "compute_relative_strength", ticker,
    )
    snapshot_task = _scanner_call(
        "consensus_engine.scanners.snapshot", "fetch_ticker_snapshot", ticker,
    )

    results = await asyncio.gather(
        score_task,
        tech_long_task,
        tech_short_task,
        twitter_task,
        social_task,
        yt_signals_task,
        yt_options_task,
        yt_levels_task,
        yt_evidence_task,
        yt_visual_task,
        alert_history_task,
        decision_snapshots_task,
        next_earnings_task,
        recent_earnings_task,
        daily_candles_task,
        news_task,
        sec_task,
        options_task,
        options_flow_task,
        trends_task,
        apewisdom_task,
        chat_task,
        brief_task,
        vault_task,
        max_pain_task,
        peer_strength_task,
        snapshot_task,
        return_exceptions=True,
    )
    (
        score_result, tech_long, tech_short, twitter_signals, social_signals,
        yt_signals, yt_options, yt_levels, yt_evidence, yt_visual, alert_history,
        decision_snapshots, next_earnings_iso, recent_earnings_recap, daily_candles, news_catalyst, sec_filings, options_unusual,
        options_flow_recent,
        trends, apewisdom, chat_msgs, brief_msgs, prior_vault,
        max_pain, peer_strength, snapshot,
    ) = results

    # Classify each source as surfaced (non-empty data) or failed (exception).
    sources_surfaced, source_failures = _classify_sources([
        ("score", score_result),
        ("technical_long", tech_long),
        ("technical_short", tech_short),
        ("twitter_db", twitter_signals),
        ("social_db", social_signals),
        ("youtube_signals_db", yt_signals),
        ("youtube_options_db", yt_options),
        ("youtube_levels_db", yt_levels),
        ("youtube_evidence_db", yt_evidence),
        ("youtube_visual_db", yt_visual),
        ("alert_history_db", alert_history),
        ("decision_snapshots_db", decision_snapshots),
        ("earnings_calendar", next_earnings_iso),
        ("recent_earnings", recent_earnings_recap),
        ("news", news_catalyst),
        ("sec", sec_filings),
        ("options", options_unusual),
        ("options_flow_recent", options_flow_recent),
        ("trends", trends),
        ("apewisdom", apewisdom),
        ("chat_24h", chat_msgs),
        ("brief_last3", brief_msgs),
        ("prior_vault", prior_vault),
        ("max_pain", max_pain),
        ("peer_strength", peer_strength),
        ("snapshot_db", snapshot),
    ])

    return {
        "ticker_meta": ticker_meta if isinstance(ticker_meta, dict) else {},
        "company_name": name_for_filter,
        "score": _result_or_default(score_result, None),
        "technical_long": _result_or_default(tech_long, None),
        "technical_short": _result_or_default(tech_short, None),
        "twitter_signals": _result_or_default(twitter_signals, []),
        "social_signals": _result_or_default(social_signals, []),
        "yt_signals": _result_or_default(yt_signals, []),
        "yt_options": _result_or_default(yt_options, []),
        "yt_levels": _result_or_default(yt_levels, []),
        "yt_evidence": _result_or_default(yt_evidence, []),
        "yt_visual_evidence": _result_or_default(yt_visual, []),
        "alert_history": _result_or_default(alert_history, []),
        "decision_snapshots": _result_or_default(decision_snapshots, []),
        "next_earnings_iso": _result_or_default(next_earnings_iso, None) if isinstance(next_earnings_iso, str) else None,
        "recent_earnings_recap": recent_earnings_recap if isinstance(recent_earnings_recap, dict) else None,
        "daily_candles": daily_candles if isinstance(daily_candles, list) else [],
        "chart_pattern": _detect_chart_pattern(daily_candles if isinstance(daily_candles, list) else _swing_candles(_result_or_default(tech_long, None))),
        "news_catalyst": _result_or_default(news_catalyst, None),
        "sec_filings": _result_or_default(sec_filings, []),
        "options_unusual": _result_or_default(options_unusual, None),
        "options_flow_recent": _result_or_default(options_flow_recent, []),
        "trends": _result_or_default(trends, {}),
        "apewisdom": _result_or_default(apewisdom, None),
        "chat_msgs": _result_or_default(chat_msgs, []),
        "brief_msgs": _result_or_default(brief_msgs, []),
        "prior_vault": _result_or_default(prior_vault, None),
        "max_pain": _result_or_default(max_pain, None),
        "peer_strength": _result_or_default(peer_strength, None),
        "snapshot": _result_or_default(snapshot, None),
        "sources_surfaced": sources_surfaced,
        "source_failures": source_failures,
    }


def _swing_candles(technical_long) -> list[dict]:
    """Best-effort list-of-dict candles for swing extraction."""
    if technical_long is None:
        return []
    raw = (getattr(technical_long, "candles", None)
           or getattr(technical_long, "candles_raw", None))
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        highs = raw.get("h") or raw.get("highs") or []
        lows = raw.get("l") or raw.get("lows") or []
        n = min(len(highs), len(lows))
        return [{"high": float(highs[i]), "low": float(lows[i])} for i in range(n)]
    return []


def _detect_chart_pattern(swing_candles: list[dict]) -> Optional[dict]:
    """Run the pattern library over swing candles, return the best hit or None."""
    if not swing_candles:
        return None
    try:
        from consensus_engine.analysis import patterns
        return patterns.detect_all(swing_candles)
    except Exception as exc:  # noqa: BLE001 — pattern detection never raises into gather
        log.warning("aggregator._detect_chart_pattern raised: %s", exc)
        return None


def _current_price(technical_long) -> Optional[float]:
    """Best-effort current price from technical result."""
    if technical_long is None:
        return None
    for attr in ("current_price", "last_price", "price"):
        v = getattr(technical_long, attr, None)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _atr_from_candles(technical_long) -> Optional[float]:
    """Pull ATR(14) from technical result if available."""
    if technical_long is None:
        return None
    for attr in ("atr14", "atr", "atr_14"):
        v = getattr(technical_long, attr, None)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _earnings_iso(decision_snapshots) -> Optional[str]:
    """Extract a next-earnings ISO date from any source we have."""
    if not isinstance(decision_snapshots, list):
        return None
    for row in decision_snapshots:
        if isinstance(row, dict):
            for key in ("next_earnings", "earnings_date", "earnings"):
                v = row.get(key)
                if v:
                    return str(v)
    return None


def _build_news_snippets(news_catalyst, gap_fill_result) -> list[str]:
    """News catalyst body + web-harvested gap-fill snippets (PR4)."""
    out: list[str] = []
    body = getattr(news_catalyst, "catalyst_body", None) if news_catalyst else None
    if body:
        out.append(str(body))
    if isinstance(gap_fill_result, dict):
        for key in ("harvested_anchors_snippets",
                    "eight_k_summary_snippets",
                    "event_date_snippets"):
            for snip in gap_fill_result.get(key, []) or []:
                if snip:
                    out.append(str(snip))
    return out[:20]


# #13 — SEC insider evidence. Form-4 detail is fetched for at most this many
# of the most-recent Form 4 filings, and the whole fetch is time-boxed.
_FORM4_ENRICH_LIMIT = 5
_FORM4_ENRICH_TIMEOUT = 12.0


def _fmt_insider_shares(v) -> str:
    """Render a share count: 240000.0 -> '240,000'."""
    try:
        return f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return str(v if v is not None else "?")


def _fmt_insider_price(v) -> str:
    """Render a per-share price suffix: 52.5 -> ' at $52.50'; 0/None -> ''."""
    try:
        p = float(v)
    except (TypeError, ValueError):
        return ""
    return f" at ${p:.2f}" if p else ""


def _format_insider_section(fetched: list) -> list[str]:
    """Render the per-insider lines per the #13 significance rule.

    Open-market purchases/sales are shown in full (name, title, shares,
    price, date), grouped per insider; routine awards / option exercises /
    tax withholding / gifts are collapsed to a count. A filing set whose
    aggregate open-market value clears the configured buy/sell floor is
    flagged NOTABLE. Returns [] when no Form-4 transactions were fetched.
    """
    from consensus_engine.alerts.commands import _fmt_insider_name
    from consensus_engine.scanners.sec_edgar import (
        _OPEN_MARKET_TX_TYPES, compute_insider_value,
    )

    all_txs = [t for _f, txs in fetched for t in (txs or [])]
    if not all_txs:
        return []
    open_market = [t for t in all_txs
                   if t.get("transaction_type") in _OPEN_MARKET_TX_TYPES]
    routine_count = len(all_txs) - len(open_market)
    if not open_market:
        return ["Recent Form 4 filings were routine awards / option "
                "exercises / tax withholding — no open-market conviction trades."]

    buy_floor = cfg.get("sec_watcher.min_insider_dollars_buy", 100000)
    sell_floor = cfg.get("sec_watcher.min_insider_dollars_sell", 1000000)
    notable = (compute_insider_value(all_txs, "Buy") >= buy_floor
               or compute_insider_value(all_txs, "Sell") >= sell_floor)

    out = [("NOTABLE — " if notable else "")
           + "open-market insider (Form 4) transactions:"]
    grouped: dict[str, list] = {}
    titles: dict[str, str] = {}
    for t in open_market:
        name = str(t.get("reporter_name") or "Unknown")
        grouped.setdefault(name, []).append(t)
        titles[name] = str(t.get("title") or "Insider")
    for raw_name, insider_txs in grouped.items():
        display = _fmt_insider_name(raw_name)
        for t in insider_txs:
            out.append(
                f"  - {display} ({titles[raw_name]}) — "
                f"{t.get('direction', '?')} {_fmt_insider_shares(t.get('shares'))} "
                f"shares{_fmt_insider_price(t.get('price'))} "
                f"on {t.get('date') or '?'}."
            )
    if routine_count:
        out.append(f"  plus {routine_count} routine award / option "
                   f"transaction(s) (collapsed).")
    return out


def _format_sec_evidence_block(sec_filings: list, fetched: list,
                               partial: bool) -> str:
    """Build the one deterministic SEC evidence block string (#13).

    Replaces the dead _build_sec_snippets. The block bypasses the LLM
    sanitize step — it is factual SEC disclosure, not hostile external text.
    """
    dict_filings = [f for f in (sec_filings or []) if isinstance(f, dict)]
    if not dict_filings:
        return "No recent SEC filings."
    forms = [f"{f.get('form', '?')} ({f.get('filing_date', '?')})"
             for f in dict_filings[:12]]
    lines: list[str] = ["Recent SEC filings: " + ", ".join(forms) + "."]

    insider = _format_insider_section(fetched)
    if insider:
        lines.extend(insider)
        if partial:
            lines.append("(Some insider detail unavailable — SEC fetch timed "
                         "out; the above is partial.)")
    elif partial:
        lines.append("Recent Form 4 filings present; insider detail "
                     "unavailable (SEC fetch timed out).")
    elif any(f.get("form") == "4" for f in dict_filings):
        lines.append("Recent Form 4 filings present; insider detail "
                     "could not be retrieved.")
    else:
        lines.append("No recent insider (Form 4) activity.")
    return "\n".join(lines)


async def _fetch_form4_safe(filing: dict) -> tuple[dict, list]:
    """Fetch one Form-4 filing's transactions; one bad filing never voids the
    rest (returns an empty transaction list on any failure)."""
    from consensus_engine.scanners.sec_edgar import fetch_form4_details
    try:
        if not await rate_limiter.acquire("sec_edgar"):
            return filing, []
        txs = await fetch_form4_details(
            filing.get("cik", ""),
            filing.get("accession_number", ""),
            filing.get("primary_document", ""),
        )
        return filing, list(txs or [])
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — D13 partial failure
        log.debug("aggregator._fetch_form4_safe: %s", exc)
        return filing, []


async def _enrich_form4_insiders(sec_filings: list, deadline: float) -> dict:
    """Fetch Form-4 insider detail and build the deterministic SEC evidence
    block. Returns {"block": <str>, "partial": <bool>}.

    The Form-4 fetch is bounded by _FORM4_ENRICH_TIMEOUT (and never longer
    than `deadline`); on timeout the block is built from whatever completed
    and `partial` is True.
    """
    filings = sec_filings if isinstance(sec_filings, list) else []
    form4 = [f for f in filings
             if isinstance(f, dict) and f.get("form") == "4"][:_FORM4_ENRICH_LIMIT]
    partial = False
    fetched: list[tuple[dict, list]] = []
    if form4:
        timeout = max(0.0, min(_FORM4_ENRICH_TIMEOUT, deadline))
        tasks = [asyncio.create_task(_fetch_form4_safe(f)) for f in form4]
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout)
        except asyncio.TimeoutError:
            partial = True
        for t in tasks:
            if t.done() and not t.cancelled() and t.exception() is None:
                fetched.append(t.result())
            else:
                t.cancel()
        if partial:
            await asyncio.gather(*tasks, return_exceptions=True)
    return {
        "block": _format_sec_evidence_block(filings, fetched, partial),
        "partial": partial,
    }


def _build_twitter_snippets(twitter_signals) -> list[str]:
    """Pull raw_text / source_detail strings from twitter_signals rows (PR4)."""
    out: list[str] = []
    if isinstance(twitter_signals, list):
        for row in twitter_signals[:30]:
            if isinstance(row, dict):
                txt = row.get("raw_text") or row.get("source_detail") or ""
                if txt:
                    out.append(str(txt))
    return out


def _build_social_snippets(social_signals) -> list[str]:
    """Pull raw_text from reddit/wsb/apewisdom social_signals rows (PR4)."""
    out: list[str] = []
    if isinstance(social_signals, list):
        for row in social_signals[:30]:
            if isinstance(row, dict):
                txt = row.get("raw_text") or row.get("source_detail") or ""
                if txt:
                    src = row.get("source_type", "social")
                    out.append(f"[{src}] {txt}")
    return out


def _build_yt_evidence_snippets(yt_evidence) -> list[str]:
    """Pull context_text + source_snippet from youtube_evidence rows (PR4)."""
    out: list[str] = []
    if isinstance(yt_evidence, list):
        for row in yt_evidence[:10]:
            if isinstance(row, dict):
                ch = row.get("channel_name", "?")
                ctx = row.get("context_text") or row.get("source_snippet") or row.get("condition_text") or ""
                if ctx:
                    out.append(f"[{ch}] {ctx}")
    return out


def _visual_band_filter(rows, price: float, band_pct: float):
    """Task C Phase 2: drop chart-axis NOISE from attributed visual rows.

    A `kind=='price'` row is kept only when it sits within `band_pct` of the
    ticker's live `price` — this removes generic Y-axis gridlines (e.g. 0/10/20
    on a $98 stock) AND numbers mis-attributed from a different ticker the video
    also covered (they won't be near this ticker's price). Non-price rows
    (labels, tickers, $-exposure, greeks, dates) are NOT price levels, so the
    band must not touch them — they pass through. When no live price is known
    we can't disprove anything, so everything passes through unchanged.
    """
    if not isinstance(rows, list):
        return []
    if not price or price <= 0:
        return rows
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if (r.get("kind") or "").strip().lower() != "price":
            out.append(r)
            continue
        try:
            val = float(str(r.get("value", "")).replace(",", "").replace("$", "").strip())
        except (TypeError, ValueError):
            out.append(r)  # unparseable as a number — keep, don't silently drop
            continue
        if abs(val / price - 1.0) <= band_pct:
            out.append(r)
        # else: outside the band → gridline / mis-scaled / wrong-ticker → drop
    return out


# B1: a promo/coupon code like "WICKED50" / "SAVE20" — letters then digits, no spaces.
_PROMO_CODE_RE = re.compile(r"^[A-Za-z]{3,}\d{1,4}$")


def _is_useful_visual_row(row) -> bool:
    """B1: keep only chart items worth showing the narrator; drop label noise.

    Title cards ("The Stock Market"), promo codes ("WICKED50") and bare ticker
    labels reach visual_evidence and clutter the alert. Keep prices, dates, and
    any label/annotation that carries a number (fib %, $ premium, gamma value,
    "max pain 740"). Drop bare tickers, promo codes, and digit-less labels.
    """
    if not isinstance(row, dict):
        return False
    val = str(row.get("value") or "").strip()
    if not val:
        return False
    kind = (row.get("kind") or "").strip().lower()
    if kind == "ticker":
        return False  # narrator already knows the ticker; a bare symbol adds nothing
    if kind in ("price", "date"):
        return True
    # label / other: useful only if it carries a number; never if it's a promo
    # code. Promo codes are a single token with no spaces ("WICKED50"); real
    # annotations have spaces ("RSI 71", "max pain 740"), so match the raw value.
    if _PROMO_CODE_RE.match(val):
        return False
    return any(ch.isdigit() for ch in val)


def _build_yt_visual_snippets(yt_visual) -> list[str]:
    """Render on-screen chart numbers (visual_evidence) for the narrator."""
    out: list[str] = []
    if isinstance(yt_visual, list):
        for row in yt_visual:
            if not _is_useful_visual_row(row):
                continue
            val = row.get("value")
            ch = row.get("channel_name", "?")
            where = row.get("where_seen") or row.get("where") or "on chart"
            out.append(f"[{ch}] chart shows {val} ({where})")
            if len(out) >= 15:
                break
    return out


def _build_technical_short_dict(tech_short) -> dict:
    """Coerce technical_short scanner result into a JSON-friendly dict (PR4)."""
    if tech_short is None:
        return {}
    if isinstance(tech_short, dict):
        return {k: v for k, v in tech_short.items() if isinstance(v, (int, float, str, bool, type(None)))}
    out: dict = {}
    for attr in ("rsi", "macd", "ema_9", "ema_21", "vwap", "current_price",
                 "atr14", "rvol", "price_change_pct"):
        v = getattr(tech_short, attr, None)
        if v is not None:
            out[attr] = v
    return out


def _structured_data_summary(data: dict) -> str:
    """JSON summary of structured (non-hostile) data fed to the synthesis prompt."""
    summary = {
        "news_passed": bool(getattr(data.get("news_catalyst"), "passed", False))
                       if data.get("news_catalyst") else False,
        "sec_filing_count": len(data.get("sec_filings") or []),
        "options_unusual": bool(
            getattr(data.get("options_unusual"), "has_unusual_activity", False)
        ) if data.get("options_unusual") else False,
        # #18: recent autonomous-detected unusual options FLOW (top by premium).
        "options_flow_recent": [
            {"side": r.get("side"), "strike": r.get("strike"), "expiry": r.get("expiry"),
             "premium_usd": r.get("premium_usd"), "vol_oi_ratio": r.get("vol_oi_ratio")}
            for r in (data.get("options_flow_recent") or [])[:5] if isinstance(r, dict)
        ],
        "trends": data.get("trends") or {},
        "alert_history_count": len(data.get("alert_history") or []),
    }
    try:
        return json.dumps(summary, default=str)
    except Exception:  # noqa: BLE001
        return "{}"


async def _compute_all(ticker: str, start: float) -> dict:
    """The actual compute path under the cache single-flight. Returns the cache payload."""
    stage_t: dict[str, float] = {}
    _t = lambda: time.monotonic() - start
    data = await _gather_all_sources(ticker)
    stage_t["gather"] = _t()
    score_result = data["score"]
    if score_result is None and not data.get("technical_long") and not data.get("news_catalyst"):
        # Per D13: abort only if score gate cannot be evaluated AT ALL
        # (no technicals AND no catalyst). Emit a minimal embed instead.
        log.warning(
            "aggregator: $%s score+technical+catalyst all unavailable; emitting minimal embed",
            ticker,
        )

    # Anchor pipeline.
    yt_levels = data["yt_levels"] if isinstance(data["yt_levels"], list) else []
    swing_candles = _swing_candles(data["technical_long"])
    yt_anchors = levels.extract_anchors_from_youtube_levels(yt_levels)
    swing_anchors = levels.extract_swing_levels(swing_candles)
    initial_anchors = levels.cluster_anchors(yt_anchors + swing_anchors, 0.005)

    # Gap-fill: run only if any trigger fires.
    earnings_iso_str = _earnings_iso(data["decision_snapshots"]) or data.get("next_earnings_iso")
    sec_filings_list = data["sec_filings"] if isinstance(data["sec_filings"], list) else []
    # Step 10 (revised 2026-05-26): direction_source feature flag.
    # Original Step 10 had the "legacy" path read `breakdown.direction` —
    # but ScoreBreakdown has no `direction` field, so that getattr() always
    # returned None and "legacy" was always "neutral". That made the parity
    # log compare a broken stub field against the new helper, producing
    # the misleading 73% disagreement signal in the first soak window.
    #
    # Both paths now compute meaningful directions:
    #   "legacy"     = compute_direction(score_breakdown) — the existing function
    #                  the embed already uses; returns BULLISH/BEARISH/NEUTRAL.
    #   "structured" = compute_direction_from_fields(asdict(breakdown)) — Agent C's
    #                  dict-based wrapper around the same field-sum logic; returns
    #                  LONG/SHORT/NEUTRAL.
    # They implement the same logic on the same fields and should now agree
    # nearly 100% of the time. The flag remains so a future divergent
    # implementation can be soak-tested via the same gate.
    _score_bd_raw = getattr(score_result, "breakdown", None)
    _legacy_direction = structured_fields.compute_direction(_score_bd_raw)
    _bd_dict: dict = (
        dataclasses.asdict(_score_bd_raw)
        if _score_bd_raw is not None and dataclasses.is_dataclass(_score_bd_raw)
        else {}
    )
    _structured_direction = structured_fields.compute_direction_from_fields(_bd_dict)
    # Normalize label sets for the parity comparison — BULLISH/LONG and
    # BEARISH/SHORT mean the same thing across the two label conventions.
    _DIRECTION_SYNONYMS = {
        "bullish": "long", "long": "long",
        "bearish": "short", "short": "short",
        "neutral": "neutral",
    }
    _legacy_normalized = _DIRECTION_SYNONYMS.get(_legacy_direction.lower(), _legacy_direction.lower())
    _structured_normalized = _DIRECTION_SYNONYMS.get(_structured_direction.lower(), _structured_direction.lower())
    # Parity log — fires on every aggregator run.
    try:
        _PARITY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _parity_entry = json.dumps({
            "event_id": f"{ticker}:{int(start)}",
            "ticker": ticker,
            "legacy_direction": _legacy_direction,
            "structured_direction": _structured_direction,
            "agree": _legacy_normalized == _structured_normalized,
            "ts": time.time(),
        })
        with _PARITY_LOG_PATH.open("a") as _pf:
            _pf.write(_parity_entry + "\n")
    except Exception as _pex:  # noqa: BLE001
        log.debug("aggregator: parity log write failed: %s", _pex)
    _direction_source = cfg.get("all_command.direction_source", "legacy")
    if _direction_source == "structured":
        direction_str = _structured_direction
    else:
        direction_str = _legacy_direction
    gap_deadline = time.time() + min(_GAP_FILL_BUDGET, _remaining(start))
    # Feature E — sector label for the macro-risk query disambiguation. The
    # peer_strength result's "group" is a human-readable sector/industry name
    # ("Semiconductors", "Technology"); far better in a search query than the
    # ETF symbol from sector_map.yaml. Empty string when unavailable.
    _peer_strength = data.get("peer_strength")
    _macro_sector = ""
    if isinstance(_peer_strength, dict):
        _macro_sector = str(_peer_strength.get("group") or "")
    try:
        gap_fill_result = await gap_fill.run_gap_fill(
            ticker=ticker,
            anchors_count=len(initial_anchors),
            sec_filings=sec_filings_list,
            has_event_date=bool(earnings_iso_str),
            direction=direction_str,
            deadline=gap_deadline,
            company_name=data.get("company_name") or "",
            sector=_macro_sector,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("aggregator: gap_fill failed: %s", exc)
        gap_fill_result = {
            "harvested_anchors_snippets": [],
            "eight_k_summary_snippets": [],
            "event_date_snippets": [],
            "catalyst_research_snippets": [],
            "macro_risk_snippets": [],
        }

    stage_t["gap_fill"] = _t()
    web_anchor_snippets = list(gap_fill_result.get("harvested_anchors_snippets", []))
    web_anchors = levels.extract_anchors_from_search_snippets(
        web_anchor_snippets,
        current_price=_current_price(data["technical_long"]) or 0.0,
    )

    all_anchors = levels.cluster_anchors(initial_anchors + web_anchors, 0.005)
    current_price = _current_price(data["technical_long"]) or 0.0
    supports, resistances = levels.rank_anchors(all_anchors, current_price, ticker=ticker)
    # TODO #10/#12 — pre-compute ATR + direction + earnings_days here so
    # select_trade_plan can apply the drawdown sanity gate + ATR fallback +
    # horizon-aware short-window gate. Variables are re-computed below in
    # the structured-fields block (same inputs, same values — harmless
    # redundancy in exchange for a smaller diff).
    _atr14_for_plan = _atr_from_candles(data["technical_long"])
    _score_bd_for_plan = (
        getattr(score_result, "breakdown", None) if score_result is not None else None
    )
    _direction_for_plan = structured_fields.compute_direction(_score_bd_for_plan)
    _earnings_days_for_plan = None
    if earnings_iso_str:
        try:
            from datetime import datetime as _dt, date as _date
            _ed = _dt.strptime(earnings_iso_str, "%Y-%m-%d").date()
            # BUG-1: use local date (matches structured_fields.compute_next_catalyst_days);
            # _dt.utcnow().date() drifted 1 day ahead for ~7h each PT evening, so the
            # trade-plan earnings proximity disagreed with the embed's Next Catalyst field.
            _d = (_ed - _date.today()).days
            if _d >= 0:
                _earnings_days_for_plan = _d
        except (ValueError, TypeError):
            pass
    trade_plan = levels.select_trade_plan(
        supports, resistances,
        spot=current_price,
        atr14=_atr14_for_plan,
        direction=_direction_for_plan,
        earnings_days=_earnings_days_for_plan,
    )

    # Structured fields.
    score_breakdown = (
        getattr(score_result, "breakdown", None) if score_result is not None else None
    )
    direction = structured_fields.compute_direction(score_breakdown)
    final_score = (
        getattr(score_breakdown, "total", 0)
        if score_breakdown is not None else 0
    )
    confidence = structured_fields.compute_confidence_label(final_score)
    earnings_iso = _earnings_iso(data["decision_snapshots"]) or data.get("next_earnings_iso")
    timeframe = structured_fields.compute_breakout_timeframe(
        ticker, earnings_iso, data["options_unusual"],
    )
    atr14 = _atr_from_candles(data["technical_long"])
    magnitude = structured_fields.compute_magnitude(atr14, current_price)

    sl = trade_plan.get("sl") if trade_plan else None
    tp1 = trade_plan.get("tp1") if trade_plan else None
    tp2 = trade_plan.get("tp2") if trade_plan else None
    tp3 = trade_plan.get("tp3") if trade_plan else None
    # Iter4: LOW confidence no longer wipes the trade plan — D3 is overridden
    # by user feedback (Gemini provides actionable SL/TP without confidence
    # gating). PR3's anchor-count gate is the single source of truth for
    # whether levels exist; the LOW label still renders in the embed banner.
    # NEUTRAL direction still wipes because SL/TP labels are direction-
    # dependent (a "TP1 above price" only makes sense for BULLISH).
    if direction == "NEUTRAL":
        sl = tp1 = tp2 = tp3 = None
        magnitude = "TBD"
        timeframe = "TBD"
    # #6 A3 — reward:risk of the plan (after the NEUTRAL wipe so it stays None
    # there). Gated on the trade_plan's own confidence to skip ATR-fallback plans.
    risk_reward = structured_fields.compute_risk_reward(
        current_price, sl, tp1, direction,
        trade_plan.get("confidence") if trade_plan else None,
    )

    # Iter5: compute the entry zone from supports + current price so the
    # embed answers the prompt's "buying level" requirement directly.
    buy_low, buy_high = structured_fields.compute_buy_zone(
        current_price, supports, direction,
    )

    # W4 swing-realism: compute new structured fields. Old fields above
    # remain populated for backward compat and emergency revert via the
    # `all_command.swing_v2_enabled=false` flag (consumed by embed,
    # narrator, vault_writer at render time).
    # TODO #13 — fetch forward-dated NASDAQ catalysts (earnings + dividends)
    # so AMD/TSLA-style tickers without near-earnings get a real catalyst
    # surfaced in the embed + narrator prompt instead of "—".
    try:
        from consensus_engine.scanners import nasdaq_calendar
        nasdaq_events = await nasdaq_calendar.fetch_forward_catalysts(
            ticker, forward_days=60,
        )
        # NOTE: weekly options expiry was previously appended here as a
        # guaranteed forward-catalyst fallback. Removed per user iter5
        # feedback — mechanical Friday expiries are not substantive
        # catalysts; surfacing them was fake-substance. Real catalysts
        # come from Commit 7 (web mining for partnerships / product
        # launches / regulatory dates).
    except Exception as exc:  # noqa: BLE001
        log.warning("aggregator: nasdaq_calendar fetch failed: %s", exc)
        nasdaq_events = []
    next_catalyst_days, next_catalyst_kind, next_catalyst_mechanism = (
        structured_fields.compute_next_catalyst(
            earnings_iso, data["options_unusual"], extra_events=nasdaq_events,
        )
    )
    swing_horizon_days, swing_horizon_band, _swing_note = (
        structured_fields.compute_swing_horizon(
            current_price, tp1, atr14, earnings_iso,
        )
    )
    expected_move_typical, expected_move_high_vol, magnitude_band_label = (
        structured_fields.compute_magnitude_band(
            atr14, swing_horizon_days, current_price, atr_90d_high_pct=None,
        )
    )

    structured = structured_fields.StructuredFields(
        direction=direction,
        confidence_label=confidence,
        sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
        breakout_timeframe=timeframe,
        magnitude_label=magnitude,
        current_price=current_price if current_price else None,
        buy_zone_low=buy_low,
        buy_zone_high=buy_high,
        earnings_date=earnings_iso,
        next_catalyst_days=next_catalyst_days,
        swing_horizon_days=swing_horizon_days,
        swing_horizon_band=swing_horizon_band,
        expected_move_typical=expected_move_typical,
        expected_move_high_vol=expected_move_high_vol,
        magnitude_band_label=magnitude_band_label,
        next_catalyst_kind=next_catalyst_kind,
        next_catalyst_mechanism=next_catalyst_mechanism,
        max_pain=data.get("max_pain"),
        peer_strength=data.get("peer_strength"),
        snapshot=data.get("snapshot"),
        risk_reward=risk_reward,
        relative_volume=structured_fields.compute_relative_volume(
            data.get("daily_candles") if isinstance(data.get("daily_candles"), list) else []
        ),
    )

    # Sanitize hostile text. PR4: split SearXNG into news+sec+gap-fill blocks
    # and route the 6 previously-discarded sources to their own batches.
    news_snippets = _build_news_snippets(data["news_catalyst"], gap_fill_result)
    # Commit 13/14: SerpAPI catalysts are prepared here but NOT passed
    # through sanitize_hostile_text — the sanitize LLM batch routinely
    # fails on free-tier and truncates content to 50 chars (Commit 14
    # raised that to 500 in narrator._batch_summarize, but bypassing
    # entirely is safer for content we know is already clean). They
    # get prepended into sanitized["news"] AFTER sanitize returns,
    # below.
    catalyst_snips_raw = gap_fill_result.get("catalyst_research_snippets") or []
    catalyst_as_news = []
    for s in catalyst_snips_raw[:6]:
        if not isinstance(s, str) or not s.strip():
            continue
        if s.startswith("[cat_") and "] " in s:
            s = s.split("] ", 1)[1]
        catalyst_as_news.append(s)
    # Feature E — recent macro/sector/regulatory risk rows. Unlike catalysts,
    # KEEP the [macro_risk] tag so the narrator can tell macro risk apart from
    # company catalysts when citing it in the Risk Considerations section.
    macro_risk_raw = gap_fill_result.get("macro_risk_snippets") or []
    macro_as_news = [
        s for s in macro_risk_raw[:5]
        if isinstance(s, str) and s.strip()
    ]
    # #13: build the deterministic SEC evidence block (Form-4 insider detail).
    sec_evidence = await _enrich_form4_insiders(
        data["sec_filings"], _remaining(start),
    )
    sec_block = sec_evidence["block"]
    twitter_msgs = _build_twitter_snippets(data["twitter_signals"])
    social_msgs = _build_social_snippets(data["social_signals"])
    # Task C Phase 2: filter attributed chart numbers to those near the live
    # price (drops axis gridlines + cross-ticker noise) before they reach the AI.
    _visual_band = float(cfg.get("youtube.visual.proximity_band_pct", 0.10))
    _visual_price = _current_price(data["technical_long"]) or 0.0
    _visual_rows = _visual_band_filter(data.get("yt_visual_evidence", []), _visual_price, _visual_band)
    yt_evidence_msgs = _build_yt_evidence_snippets(data["yt_evidence"]) + _build_yt_visual_snippets(_visual_rows)
    chat_msgs = data["chat_msgs"] if isinstance(data["chat_msgs"], list) else []
    brief_msgs = data["brief_msgs"] if isinstance(data["brief_msgs"], list) else []
    prior_vault = data["prior_vault"] or ""

    # #13: the SEC evidence block is deterministic, trusted disclosure — it
    # bypasses the LLM sanitize step entirely (sec_snippets=[] below). The
    # all_command.sanitize_enabled flag gates only the hostile-text batch for
    # the remaining external sources; when off they get a plain truncation.
    if cfg.get("all_command.sanitize_enabled", True):
        sanitized = await narrator.sanitize_hostile_text(
            searxng_snippets=[],   # PR4 split: news+sec routed below
            chat_msgs=chat_msgs,
            brief_msgs=brief_msgs,
            vault_text=prior_vault,
            news_snippets=news_snippets,
            sec_snippets=[],
            twitter_msgs=twitter_msgs,
            social_msgs=social_msgs,
            yt_evidence_msgs=yt_evidence_msgs,
        )
    else:
        sanitized = {
            "searxng": [],
            "chat": [narrator._sanitize_text(m) for m in chat_msgs],
            "brief": [narrator._sanitize_text(m) for m in brief_msgs],
            "vault": narrator._sanitize_text(prior_vault),
            "news": [narrator._sanitize_text(m) for m in news_snippets],
            "sec": [],
            "twitter": [narrator._sanitize_text(m) for m in twitter_msgs],
            "social": [narrator._sanitize_text(m) for m in social_msgs],
            "yt_evidence": [narrator._sanitize_text(m) for m in yt_evidence_msgs],
        }
    # Inject the deterministic SEC block (single element -> _CAP_SEC keeps it).
    sanitized["sec"] = [sec_block] if sec_block else []
    # Commit 14: prepend catalysts AFTER sanitize so they reach the
    # synthesis LLM uncorrupted. The sanitize batch was destroying
    # them to 50 chars on free-tier failures.
    if catalyst_as_news or macro_as_news:
        sanitized["news"] = (
            macro_as_news + catalyst_as_news + (sanitized.get("news") or [])
        )
    stage_t["sanitize"] = _t()

    sources_surfaced = list(data["sources_surfaced"])
    source_failures = list(data["source_failures"])

    # Synthesis (skip if budget too tight).
    if _remaining(start) < _SYNTHESIS_MIN_BUDGET:
        narrative = output_filter.render_data_only_fallback(
            structured, score_breakdown, sources_surfaced,
            sec_evidence_block=sec_block,
        )
        narrative_status = "skipped_low_budget"
    else:
        narrative, narrative_status = await narrator.synthesize_narrative(
            ticker=ticker,
            structured=structured,
            score_breakdown=score_breakdown,
            sanitized_searxng=sanitized.get("searxng", []),
            sanitized_chat=sanitized.get("chat", []),
            sanitized_brief=sanitized.get("brief", []),
            vault_summary=sanitized.get("vault", ""),
            structured_data_json=_structured_data_summary(data),
            deadline_seconds=_remaining(start),
            sources_surfaced=sources_surfaced,
            sanitized_news=sanitized.get("news", []),
            sanitized_sec=sanitized.get("sec", []),
            sanitized_twitter=sanitized.get("twitter", []),
            sanitized_social=sanitized.get("social", []),
            sanitized_yt_signals=data["yt_signals"] if isinstance(data["yt_signals"], list) else [],
            sanitized_yt_options=data["yt_options"] if isinstance(data["yt_options"], list) else [],
            sanitized_yt_evidence=sanitized.get("yt_evidence", []),
            sanitized_technical_short=_build_technical_short_dict(data["technical_short"]),
            recent_earnings_recap=data.get("recent_earnings_recap"),
            chart_pattern=data.get("chart_pattern"),
            catalyst_research=gap_fill_result.get("catalyst_research_snippets") or [],
        )
        if narrative_status != "ok":
            narrative = output_filter.render_data_only_fallback(
                structured, score_breakdown, sources_surfaced,
                sec_evidence_block=sec_block,
            )
    stage_t["synthesize"] = _t()

    # Build embed + render vault markdown.
    embed_payload = embed_mod.build_embed(
        ticker=ticker,
        structured=structured,
        score_breakdown=score_breakdown,
        narrative=narrative,
        sources_used=sources_surfaced,
        cache_age_seconds=None,
        yt_signals=data["yt_signals"] if isinstance(data["yt_signals"], list) else None,
    )
    anchors_used: list[levels.Anchor] = list(supports[:6]) + list(resistances[:6])
    vault_md = vault_writer.render_all_command_markdown(
        ticker=ticker,
        structured=structured,
        score_breakdown=score_breakdown,
        narrative=narrative,
        sources_used=sources_surfaced,
        alert_history=data["alert_history"] if isinstance(data["alert_history"], list) else [],
        anchors_used=anchors_used,
    )
    stage_t["render"] = _t()
    stage_breakdown = " ".join(f"{k}={v:.1f}s" for k, v in stage_t.items())
    if trade_plan and trade_plan.get("suppression_reason"):
        plan_status = f'trade_plan=partial reason="{trade_plan["suppression_reason"]}"'
    elif trade_plan:
        plan_status = "trade_plan=populated"
    else:
        plan_status = "trade_plan=missing"
    log.info(
        "aggregator: $%s narrative_status=%s anchors=%d (sup=%d res=%d) %s elapsed=%.1fs stages=[%s]",
        ticker, narrative_status, len(all_anchors),
        len(supports), len(resistances), plan_status,
        time.monotonic() - start, stage_breakdown,
    )

    # PR7 quality-bar telemetry: 12 fields covering all 9 acceptance criteria
    # so live runs can be measured against the same checks as the pytest suite.
    from consensus_engine.alerts.all_command import quality_bar as _qb
    stage_synth_ms = max(0, int((stage_t.get("synthesize", 0.0)
                                 - stage_t.get("sanitize", 0.0)) * 1000))
    log.info(
        "quality_bar: ticker=%s sources_surfaced=%d sources_failed=%d "
        "anchors_total=%d sl=%s tp1=%s narrative_chars=%d narrative_status=%s "
        "stage_synth_ms=%d numbered_facts=%d catalyst_bullets=%d risk_bullets=%d",
        ticker, len(sources_surfaced), len(source_failures), len(all_anchors),
        sl if sl is not None else "None",
        tp1 if tp1 is not None else "None",
        len(narrative), narrative_status,
        stage_synth_ms,
        _qb.count_numbered_facts(narrative),
        _qb.count_catalyst_bullets(narrative),
        _qb.count_risk_bullets(narrative),
    )
    return {
        "embed": embed_payload,
        "vault_md": vault_md,
        "cached_at": time.time(),
    }


async def handle_all(
    ticker: str,
    channel_id: str,
    message_id: str,
) -> None:
    """Top-level !all entry point. Idempotent under the 15-min cache.

    Side-effects:
    - Sends "Analyzing $TICKER..." plain reply (always).
    - Sends an embed reply with structured fields + narrative.
    - Writes `<vault>/tickers/<TICKER>-all.md` (atomic, separate from Atlas).
    - Caches the embed + vault markdown for 15 min.

    Per plan §6.3: all exceptions are caught and logged here so that
    `_handle_all`'s `asyncio.create_task` callback sees a clean completion.
    """
    if not is_valid_ticker_format(ticker):
        log.warning("aggregator.handle_all: invalid ticker %r", ticker)
        await send_command_reply(
            channel_id, message_id,
            f"Invalid ticker `{ticker}`.",
        )
        return

    await send_command_reply(
        channel_id, message_id, f"Analyzing `${ticker}`...",
    )
    start = time.monotonic()

    async def _compute() -> dict:
        return await _compute_all(ticker, start)

    try:
        payload = await cache.all_with_single_flight(ticker, _compute)
    except Exception as exc:  # noqa: BLE001
        log.error("aggregator.handle_all: $%s compute failed: %s", ticker, exc)
        await send_command_reply(
            channel_id, message_id,
            f"`!all {ticker}` failed: internal error. Try again in a minute.",
        )
        return

    if not isinstance(payload, dict) or "embed" not in payload:
        log.error("aggregator.handle_all: malformed payload for $%s", ticker)
        await send_command_reply(
            channel_id, message_id,
            f"`!all {ticker}` failed: malformed payload.",
        )
        return

    embed_payload = dict(payload["embed"])

    vault_md = payload.get("vault_md", "")
    vault_path = cfg.get("vault.path", "")

    await asyncio.gather(
        send_command_embed_reply(channel_id, message_id, embed_payload),
        vault_writer.write_all_command_vault(ticker, vault_md, vault_path),
        return_exceptions=True,
    )
