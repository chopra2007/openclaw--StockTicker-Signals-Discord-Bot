"""Options flow scanner.

Uses yfinance options chain to detect unusual activity:
- Volume/OpenInterest ratio > 3x with volume > 100 contracts
- Computes put/call ratio from total volumes

Runs in a ThreadPoolExecutor since yfinance is blocking.
"""

import logging
import time
from typing import Optional

from consensus_engine import config as _cfg
from consensus_engine.models import OptionsResult, FlowHit
from consensus_engine.utils.yahoo_limit import get_yahoo_semaphore  # C20

log = logging.getLogger("consensus_engine.scanner.options")

_UNUSUAL_RATIO_THRESHOLD = 3.0
_MIN_VOLUME = 100
_SWEEP_RATIO_THRESHOLD = 5.0

# C13 (reliability-hardening): a Yahoo option-chain fetch outage used to look
# identical to "genuinely no unusual flow" — both produced an empty result via a
# silent `except: pass`. Count chain-fetch failures and, when EVERY attempted
# fetch for a ticker failed, emit ONE systemic WARNING (distinct from the quiet
# empty result of a clean scan). Returned data is unchanged (signal-first); this
# is observability only. The counter is process-lifetime (read by the C5 health
# surface); under C20's small concurrency cap the increment is effectively safe.
_fetch_failure_count = 0


def _note_chain_fetch(where: str, ticker: str, attempted: int, failed: int) -> None:
    """Record option-chain fetch outcomes and surface a systemic outage once."""
    global _fetch_failure_count
    _fetch_failure_count += failed
    if attempted and failed == attempted:
        log.warning(
            "%s: ALL %d option-chain fetch(es) failed for $%s "
            "(Yahoo outage/throttle?) — distinct from 'no flow'",
            where, attempted, ticker,
        )
    elif failed:
        log.debug("%s: %d/%d option-chain fetch(es) failed for $%s",
                  where, failed, attempted, ticker)


def _flow_tier(hit) -> str:
    """"sweep" | "base" — the rare, higher-conviction alert tier
    (options-flow-buyresell-sweeps). Not a real multi-exchange sweep (we only
    have one chain snapshot, no tick/venue data) — "sweep" here means the
    print cleared 2 dimensions we DO have: a distinctly higher vol/OI bar (the
    measured >= options_flow.sweep_vol_oi bucket) AND an aggressive,
    through-the-quote fill (classify_flow_side's AA/BB, not just at-ask/at-bid).
    Either alone stays "base"."""
    sweep_vol_oi = _cfg.get("options_flow.sweep_vol_oi", 50.0)
    if (hit.vol_oi_ratio >= sweep_vol_oi
            and getattr(hit, "flow_side", "") in ("BUY", "SELL")
            and getattr(hit, "flow_side_note", "") in ("AA", "BB")):
        return "sweep"
    return "base"


def _detect_unusual_activity(chain) -> OptionsResult:
    """Detect unusual activity from a yfinance option_chain result.

    Args:
        chain: yfinance option_chain namedtuple with .calls and .puts DataFrames

    Returns:
        OptionsResult with detected unusual activity. ticker field is empty — caller fills it.
    """
    calls = chain.calls
    puts = chain.puts

    unusual_calls = False
    unusual_puts = False
    max_call_ratio = 0.0
    max_put_ratio = 0.0
    top_contract = ""
    total_call_vol = 0.0
    total_put_vol = 0.0

    # I6 (signal-features-2026-06-09): track the single dominant (highest
    # single-strike premium) UNUSUAL contract so the scorer can graduate
    # options_pts by premium ALIGNED with the tweet direction. Premium is the
    # same notional estimate the #18 flow watcher uses (lastPrice * vol * 100).
    # These fields are populated unconditionally (cheap); the scoring flag
    # decides whether they change the score. dominant_side stays "" (ambiguous)
    # unless one side has strictly more premium than the other.
    dom_call_premium = 0.0
    dom_call_ts = 0.0
    dom_put_premium = 0.0
    dom_put_ts = 0.0

    if calls is not None and not calls.empty:
        # C8: itertuples (faster than iterrows; same values). getattr replaces
        # row.get so a missing column still falls back to a default. The NaN
        # guard (v == v) is unchanged: numpy NaN is truthy, so `nan or 0` stays
        # NaN and poisons total_call_vol -> put_call_ratio comes out NaN -> 0.00.
        for row in calls.itertuples(index=False):
            _v = getattr(row, "volume", 0); vol = float(_v if _v == _v else 0)
            _o = getattr(row, "openInterest", 0); oi = float(_o if _o == _o else 0)
            total_call_vol += vol
            if vol < _MIN_VOLUME or oi == 0:
                continue
            ratio = vol / oi
            if ratio > max_call_ratio:
                max_call_ratio = ratio
                top_contract = str(getattr(row, "contractSymbol", ""))
            if ratio >= _UNUSUAL_RATIO_THRESHOLD:
                unusual_calls = True
                _p = getattr(row, "lastPrice", 0); premium = float(_p if _p == _p else 0) * vol * 100.0
                if premium > dom_call_premium:
                    dom_call_premium = premium
                    dom_call_ts = _ts_to_epoch(getattr(row, "lastTradeDate", None))

    if puts is not None and not puts.empty:
        for row in puts.itertuples(index=False):
            _v = getattr(row, "volume", 0); vol = float(_v if _v == _v else 0)
            _o = getattr(row, "openInterest", 0); oi = float(_o if _o == _o else 0)
            total_put_vol += vol
            if vol < _MIN_VOLUME or oi == 0:
                continue
            ratio = vol / oi
            if ratio > max_put_ratio:
                max_put_ratio = ratio
            if ratio >= _UNUSUAL_RATIO_THRESHOLD:
                unusual_puts = True
                _p = getattr(row, "lastPrice", 0); premium = float(_p if _p == _p else 0) * vol * 100.0
                if premium > dom_put_premium:
                    dom_put_premium = premium
                    dom_put_ts = _ts_to_epoch(getattr(row, "lastTradeDate", None))

    put_call_ratio = (total_put_vol / total_call_vol) if total_call_vol > 0 else 0.0

    # Dominant side = whichever side has strictly more unusual single-strike
    # premium. A tie (or no unusual contracts) -> "" (ambiguous), which the
    # scorer treats as 0 graduation (never a sign — Pan-Poteshman safeguard).
    if dom_call_premium > dom_put_premium:
        dominant_side, premium_notional, dominant_last_trade_ts = "call", dom_call_premium, dom_call_ts
    elif dom_put_premium > dom_call_premium:
        dominant_side, premium_notional, dominant_last_trade_ts = "put", dom_put_premium, dom_put_ts
    else:
        dominant_side, premium_notional, dominant_last_trade_ts = "", 0.0, 0.0

    return OptionsResult(
        ticker="",  # filled in by caller
        unusual_calls=unusual_calls,
        unusual_puts=unusual_puts,
        max_call_ratio=round(max_call_ratio, 2),
        max_put_ratio=round(max_put_ratio, 2),
        put_call_ratio=round(put_call_ratio, 2),
        top_contract=top_contract,
        premium_notional=round(premium_notional, 2),
        dominant_side=dominant_side,
        dominant_last_trade_ts=dominant_last_trade_ts,
        total_call_vol=total_call_vol,
        total_put_vol=total_put_vol,
    )


def _combine_chains(chains):
    """Merge several option_chain results into one calls/puts pair so aggregate
    stats (put/call ratio, per-side max vol/OI) span multiple expirations.
    A single chain (nearest=1, the default) round-trips unchanged."""
    import pandas as pd
    from types import SimpleNamespace
    call_frames = [c.calls for c in chains
                   if c is not None and getattr(c, "calls", None) is not None and not c.calls.empty]
    put_frames = [c.puts for c in chains
                  if c is not None and getattr(c, "puts", None) is not None and not c.puts.empty]
    calls = pd.concat(call_frames, ignore_index=True) if call_frames else None
    puts = pd.concat(put_frames, ignore_index=True) if put_frames else None
    return SimpleNamespace(calls=calls, puts=puts)


# ---------------------------------------------------------------------------
# #57: Schwab real-time chain PRIMARY source. Each fetch below tries Schwab
# first (flag-gated by the caller) and returns None on ANY failure so the
# caller falls through to the UNCHANGED yfinance block — the bot never goes
# dark. Schwab is real-time (isDelayed:False) with native greeks + IV.
# ---------------------------------------------------------------------------
def _schwab_chain_obj(ticker: str, *, nearest: Optional[int] = None,
                      to_date: Optional[str] = None):
    """Schwab Chain (all-expiry .calls/.puts DataFrames in yfinance column
    shape + .underlying_price + .by_expiry) or None on any failure. Blocking —
    call inside the executor thread. Pass `nearest` so high-expiration tickers
    (SPY/QQQ) don't 502 on a full-chain fetch."""
    try:
        from consensus_engine.scanners import schwab_client
        return schwab_client.get_option_chain(ticker, nearest=nearest, to_date=to_date)
    except Exception as ex:
        log.debug("schwab chain fetch failed for %s: %s", ticker, ex)
        return None


def _schwab_unusual_chains(ticker: str, nearest: int):
    """Nearest `nearest` expirations as yfinance-shaped (.calls/.puts) chains for
    check_unusual_options. None -> caller falls back to yfinance."""
    ch = _schwab_chain_obj(ticker, nearest=max(1, nearest))
    if ch is None or not ch.expirations:
        return None
    return [ch.by_expiry(e) for e in ch.expirations[:max(1, nearest)]] or None


def _schwab_flow_chains(ticker: str, nearest: int):
    """(spot, [(expiry, chain), ...]) for scan_options_flow. None -> yfinance."""
    ch = _schwab_chain_obj(ticker, nearest=max(1, nearest))
    if ch is None or not ch.expirations:
        return None
    chains = [(e, ch.by_expiry(e)) for e in ch.expirations[:max(1, nearest)]]
    return (ch.underlying_price or 0.0), chains


async def check_unusual_options(ticker: str, executor, nearest: int = 1) -> Optional[OptionsResult]:
    """Check for unusual options activity on a ticker.

    Fetches the `nearest` soonest-expiry option chains via yfinance (blocking,
    runs in executor) and aggregates across them. nearest=1 (default) keeps the
    original single-expiry behaviour; the !options command passes nearest=2 so
    its put/call split and per-side max vol/OI cover the SAME 2 expirations the
    headline flow scan uses (otherwise the two disagree). Returns None on error.
    """
    import asyncio

    def _fetch():
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            expirations = t.options
            if not expirations:
                return None
            chains = []
            attempted = failed = 0
            for e in expirations[:max(1, nearest)]:
                attempted += 1
                try:
                    chains.append(t.option_chain(e))
                except Exception:
                    failed += 1
            _note_chain_fetch("check_unusual_options", ticker, attempted, failed)
            return chains or None
        except Exception as e:
            log.warning("yfinance options fetch error for %s: %s", ticker, e)
            return None

    loop = asyncio.get_running_loop()
    chains = None
    # #57: Schwab real-time chain PRIMARY (no Yahoo semaphore — not a Yahoo hit).
    if _cfg.get("features.schwab_options.enabled", False):
        try:
            chains = await loop.run_in_executor(executor, _schwab_unusual_chains, ticker, nearest)
        except Exception as e:
            log.warning("schwab unusual fetch error for %s: %s", ticker, e)
            chains = None
    if not chains:
        try:
            # C20: bound concurrent Yahoo hits process-wide (released the instant
            # the fetch returns; never held across an alert decision).
            async with get_yahoo_semaphore():
                chains = await loop.run_in_executor(executor, _fetch)
        except Exception as e:
            log.warning("run_in_executor error for %s: %s", ticker, e)
            return None
    if not chains:
        return None

    result = _detect_unusual_activity(_combine_chains(chains))
    result.ticker = ticker

    if result.has_unusual_activity:
        log.info(
            "Unusual options for $%s: calls=%s (max_ratio=%.1f) puts=%s (max_ratio=%.1f) p/c=%.2f",
            ticker, result.unusual_calls, result.max_call_ratio,
            result.unusual_puts, result.max_put_ratio, result.put_call_ratio,
        )
    else:
        log.debug("No unusual options for $%s (max_call_ratio=%.1f)", ticker, result.max_call_ratio)

    return result


async def scan_unusual_options_market(watchlist: list[str], executor=None) -> list[dict]:
    """Scan a watchlist for unusual options activity across all tickers.

    Returns list of dicts: {ticker, direction, max_ratio, top_contract, put_call_ratio}.
    """
    results = []
    for ticker in watchlist:
        try:
            result = await check_unusual_options(ticker, executor)
            if result and result.has_unusual_activity:
                direction = "CALL" if result.unusual_calls else "PUT"
                results.append({
                    "ticker": ticker,
                    "direction": direction,
                    "max_ratio": max(result.max_call_ratio, result.max_put_ratio),
                    "top_contract": result.top_contract,
                    "put_call_ratio": result.put_call_ratio,
                })
        except Exception as e:
            log.debug("Options sweep scan error for %s: %s", ticker, e)
    results.sort(key=lambda r: r["max_ratio"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# #18: near-real-time unusual options FLOW (autonomous watcher + !all feed)
# ---------------------------------------------------------------------------

def _ts_to_epoch(ts) -> float:
    """Convert a yfinance lastTradeDate (pandas Timestamp) to epoch seconds."""
    try:
        return float(ts.timestamp())
    except Exception:
        return 0.0


def classify_flow_side(last_price: float, bid: float, ask: float) -> tuple:
    """Classify a trade as buyer- or seller-initiated from its price vs. the
    same-snapshot bid/ask (options-flow-buyresell-sweeps).

    This is a SNAPSHOT PROXY, not tick-based: our bid/ask come from a chain
    snapshot, and the trade may be up to `max_staleness_min` old, so it is a
    probability call (same as real flow tools), one notch weaker since it
    isn't tick-level. Every degenerate input (missing/zero/NaN bid or ask,
    crossed/zero-spread quote, missing/NaN last_price) fails CLOSED to
    AMBIGUOUS rather than guess.

    Returns (side, note):
      side: "BUY" | "SELL" | "AMBIGUOUS"
      note: "AA" (aggressive, print above ask) | "at-ask" (within 25% of the
            spread from the ask) | "at-bid" | "BB" (aggressive, print below
            bid) | "" (AMBIGUOUS)
    """
    if (not bid or bid != bid or not ask or ask != ask
            or ask <= bid or not last_price or last_price != last_price):
        return "AMBIGUOUS", ""
    if last_price > ask:
        return "BUY", "AA"
    if last_price < bid:
        return "SELL", "BB"
    band = 0.25 * (ask - bid)
    if last_price >= ask - band:
        return "BUY", "at-ask"
    if last_price <= bid + band:
        return "SELL", "at-bid"
    return "AMBIGUOUS", ""


def _scan_chain_for_flow(
    ticker, chain, expiry, spot, *,
    min_vol_oi, min_volume, min_premium, max_stale_sec, now,
    relative_baseline_enabled=False, relative_multiplier=3.0, baseline=None,
) -> list:
    """Pull qualifying FlowHits out of one expiry's calls+puts DataFrames.

    A contract qualifies when it traded >= min_vol_oi x its open interest, at
    least min_volume contracts, and >= min_premium notional (lastPrice*vol*100).
    Contracts whose last trade is older than max_stale_sec are skipped so we
    never alert on stale / closed-market data.

    #18 relative baseline gate: when relative_baseline_enabled is True, a contract
    must ALSO clear premium >= relative_multiplier * baseline (the ticker's
    trailing mean premium). The relative gate is SKIPPED when baseline is None
    (<10 rows history; cold-start) so we never reject everything early on — the
    flat absolute floor still applies. This is sync (runs in a thread executor);
    the baseline is pre-fetched by the async caller and passed in.
    """
    hits = []
    for df, side in ((chain.calls, "CALL"), (chain.puts, "PUT")):
        if df is None or getattr(df, "empty", True):
            continue
        for row in df.itertuples(index=False):  # C8: itertuples; getattr defaults
            _v = getattr(row, "volume", 0); vol = float(_v if _v == _v else 0)
            _o = getattr(row, "openInterest", 0); oi = float(_o if _o == _o else 0)
            _p = getattr(row, "lastPrice", 0); last_price = float(_p if _p == _p else 0)
            _bid = getattr(row, "bid", 0); bid = float(_bid if _bid == _bid else 0)
            _ask = getattr(row, "ask", 0); ask = float(_ask if _ask == _ask else 0)
            if oi <= 0 or vol < min_volume:
                continue
            ratio = vol / oi
            premium = last_price * vol * 100.0
            if ratio < min_vol_oi or premium < min_premium:
                continue
            if (relative_baseline_enabled and baseline is not None
                    and premium < relative_multiplier * baseline):
                continue  # #18: below this ticker's own trailing baseline
            lt = _ts_to_epoch(getattr(row, "lastTradeDate", None))
            if max_stale_sec and lt and (now - lt) > max_stale_sec:
                continue  # stale / closed-market data — don't alert on it
            # C12: lt==0.0 means the timestamp was unparseable, so the original
            # guard above (which needs a truthy lt) silently SKIPPED the staleness
            # check — a fail-OPEN. This contract already cleared the vol/premium/
            # ratio gates (real activity), so we never DROP it (that would lose a
            # real instant-flow signal); when the flag is on we TAG it as
            # unverified (surfaced in the alert) and log it. Flag OFF = unchanged.
            staleness_unverified = False
            if max_stale_sec and not lt and _cfg.get("options_flow.staleness_failclosed", False):
                staleness_unverified = True
                log.warning(
                    "options_flow: %s %s unverifiable lastTradeDate "
                    "[staleness unverified] — allowing (cleared size gates)",
                    ticker, str(getattr(row, "contractSymbol", "")),
                )
            flow_side, flow_side_note = classify_flow_side(last_price, bid, ask)
            hits.append(FlowHit(
                ticker=ticker, side=side,
                strike=float(getattr(row, "strike", 0) or 0), expiry=expiry,
                volume=int(vol), open_interest=int(oi),
                vol_oi_ratio=round(ratio, 2), premium_usd=round(premium, 2),
                last_trade_ts=lt, spot=spot,
                contract_symbol=str(getattr(row, "contractSymbol", "")),
                staleness_unverified=staleness_unverified,
                bid=bid, ask=ask,
                flow_side=flow_side, flow_side_note=flow_side_note,
            ))
    return hits


async def _fetch_flow_chains(ticker: str, executor, nearest: int, use_schwab: bool = False):
    """Fetch spot + the nearest `nearest` expirations' chains.

    #57: when use_schwab, try the Schwab real-time chain first (the caller decides
    — on-demand !options passes features.schwab_options.enabled, the autonomous
    flow-loop additionally requires flow_loop_enabled). Falls back to blocking yf
    in the executor on any failure so alerts never go dark."""
    import asyncio

    def _f():
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            exps = t.options
            if not exps:
                return 0.0, []
            spot = 0.0
            fi = getattr(t, "fast_info", None)
            if fi is not None:
                for k in ("lastPrice", "last_price", "regularMarketPrice"):
                    try:
                        v = fi.get(k) if hasattr(fi, "get") else getattr(fi, k, None)
                    except Exception:
                        v = None
                    if v:
                        spot = float(v)
                        break
            chains = []
            attempted = failed = 0
            for e in exps[:nearest]:
                attempted += 1
                try:
                    chains.append((e, t.option_chain(e)))
                except Exception:
                    failed += 1
            _note_chain_fetch("scan_options_flow", ticker, attempted, failed)
            return spot, chains
        except Exception as ex:
            log.debug("flow fetch error for %s: %s", ticker, ex)
            return 0.0, []

    loop = asyncio.get_running_loop()
    if use_schwab:
        try:
            res = await loop.run_in_executor(executor, _schwab_flow_chains, ticker, nearest)
        except Exception as ex:
            log.debug("schwab flow fetch error for %s: %s", ticker, ex)
            res = None
        if res and res[1]:
            return res
    try:
        async with get_yahoo_semaphore():  # C20
            return await loop.run_in_executor(executor, _f)
    except Exception as ex:
        log.debug("flow executor error for %s: %s", ticker, ex)
        return 0.0, []


def _flow_relative_ratio(hit, baselines: dict) -> float:
    """#17: a FlowHit's premium relative to its ticker's trailing baseline.

    ratio = premium / max(baseline, premium*0.1). When the baseline is None
    (cold-start, <10 rows) it falls back to premium*0.1 so an under-sampled
    ticker isn't artificially inflated to a huge ratio by a near-zero divisor."""
    baseline = baselines.get(hit.ticker)
    denom = max(baseline or 0.0, hit.premium_usd * 0.1)
    if denom <= 0:
        return 0.0
    return hit.premium_usd / denom


async def scan_options_flow(
    tickers: list[str], executor=None, *,
    min_vol_oi: float = 5.0, min_volume: int = 500,
    min_premium: float = 250_000.0, max_staleness_min: int = 60,
    nearest_expirations: int = 2,
    selection_mode: str = "premium",
    relative_baseline_enabled: bool = False,
    relative_multiplier: float = 3.0,
    baselines: dict | None = None,
    use_schwab: bool | None = None,
) -> list:
    """Scan tickers for unusual options FLOW (free yfinance ~15-min data).

    Returns every qualifying FlowHit across all tickers, sorted (largest first).
    selection_mode "premium" (default) sorts by raw premium — current behavior.
    selection_mode "relative" (#17) sorts by premium/baseline ratio (vol_oi
    tiebreak) so high-conviction single names outrank mega-cap ETFs.
    relative_baseline_enabled (#18) adds a per-ticker baseline gate inside the
    scan. baselines is a pre-fetched ticker -> trailing-mean-premium dict
    (pre-fetched in the async caller because the db helper is async and the
    per-chain scan is sync); None entries are cold-start (gate skipped).

    The caller dedups to one alert per ticker.
    """
    now = time.time()
    max_stale_sec = max_staleness_min * 60 if max_staleness_min else 0
    baselines = baselines or {}
    # #57: default the Schwab source to the on-demand flag. The autonomous
    # flow-loop caller passes use_schwab explicitly (enabled AND flow_loop_enabled)
    # so its alerts don't switch to Schwab data until a live shadow-compare is done.
    if use_schwab is None:
        use_schwab = bool(_cfg.get("features.schwab_options.enabled", False))
    out: list = []
    for tk in tickers:
        try:
            spot, chains = await _fetch_flow_chains(tk, executor, nearest_expirations, use_schwab)
            for expiry, chain in chains:
                out.extend(_scan_chain_for_flow(
                    tk, chain, expiry, spot or 0.0,
                    min_vol_oi=min_vol_oi, min_volume=min_volume,
                    min_premium=min_premium, max_stale_sec=max_stale_sec, now=now,
                    relative_baseline_enabled=relative_baseline_enabled,
                    relative_multiplier=relative_multiplier,
                    baseline=baselines.get(tk),
                ))
        except Exception as ex:
            log.debug("scan_options_flow error for %s: %s", tk, ex)
    if selection_mode == "relative":
        out.sort(key=lambda h: (_flow_relative_ratio(h, baselines), h.vol_oi_ratio),
                 reverse=True)
    else:
        out.sort(key=lambda h: h.premium_usd, reverse=True)
    if out:
        log.info("options_flow: %d qualifying contract(s) across %d ticker(s)",
                 len(out), len({h.ticker for h in out}))
    return out


def format_flow_alert(hit) -> str:
    """Render a FlowHit as an unusual-activity Discord alert (Alert Philosophy).

    TODO #97/#98: this signal was measured at the next tradeable open —
    profit factor 1.03, win rate 47.4%, on 2,281 events. It is NOT a proven
    money-maker, so the wording below reports what was actually observed
    (which option side traded, and how heavy the volume was against open
    interest) rather than a stock-direction call. The real BUY/SELL/AMBIGUOUS
    transaction-side tag (from classify_flow_side) is appended separately
    when options_flow.side_collect is on (mirrors the [staleness unverified]
    tag idiom) — that describes what actually printed and is unchanged.
    The rare "sweep" tier (_flow_tier) gets a distinct 🔥 SWEEP header so the
    two tiers are visually distinguishable at a glance; its option P&L is
    equally unproven and gets no separate claim here.
    """
    flow_side = getattr(hit, "flow_side", "") or ""
    direction = "🟢 CALL-side activity" if hit.side == "CALL" else "🔴 PUT-side activity"
    prem_m = hit.premium_usd / 1_000_000.0
    spot_txt = f" | spot ${hit.spot:,.2f}" if hit.spot else ""
    # C12: be honest when we couldn't verify the contract's last-trade freshness.
    stale_txt = " _[staleness unverified]_" if getattr(hit, "staleness_unverified", False) else ""
    side_txt = ""
    if _cfg.get("options_flow.side_collect", False) and flow_side:
        note = f" ({hit.flow_side_note})" if getattr(hit, "flow_side_note", "") else ""
        side_txt = f" _[side: {flow_side}{note}]_"
    # User's call (2026-08-09): keep the header "SWEEP", no disclaimer footer.
    header = "🔥 **SWEEP**" if _flow_tier(hit) == "sweep" else "⚡ **UNUSUAL OPTIONS FLOW**"
    return (
        f"{header} — `${hit.ticker}` {direction}\n"
        f"**{hit.side}** {hit.expiry} ${hit.strike:g} strike{spot_txt}\n"
        f"Volume **{hit.volume:,}** vs OI {hit.open_interest:,} "
        f"(**{hit.vol_oi_ratio:.1f}x** — volume above open interest) | "
        f"premium **${prem_m:.2f}M**{stale_txt}{side_txt}\n"
        f"_Unusual option activity — not a confirmed trade signal._"
    )


# ---------------------------------------------------------------------------
# Max-pain (#6 lever) — the strike where the most open options expire
# worthless; acts like a price magnet into expiry. FREE: reuses the same
# yfinance option-chain data as the flow scanner. Embed-field only.
# ---------------------------------------------------------------------------

def _third_friday(year: int, month: int):
    """Date of the 3rd Friday of (year, month) — the standard monthly opex."""
    from datetime import date
    d = date(year, month, 1)
    # weekday(): Mon=0 .. Fri=4. First Friday offset, then +14 days.
    first_friday = 1 + ((4 - d.weekday()) % 7)
    return date(year, month, first_friday + 14)


def _max_pain_for_chain(chain) -> Optional[tuple]:
    """Max-pain strike for one expiry.
    Returns (strike, total_oi, call_oi_sum, put_oi_sum) or None.

    Max pain = the settle price S that minimises total in-the-money payout
    to option *holders*: sum over calls of OI*max(0,S-K) plus over puts of
    OI*max(0,K-S). Payout is piecewise-linear with breakpoints only at
    listed strikes, so evaluating S over the listed strikes is exact (no
    fine grid needed). Ties broken toward the strike nearest the mid of the
    strike range (deterministic).
    """
    import numpy as np

    calls, puts = chain.calls, chain.puts
    call_oi: dict = {}
    put_oi: dict = {}
    for df, dst in ((calls, call_oi), (puts, put_oi)):
        if df is None or getattr(df, "empty", True):
            continue
        for row in df.itertuples(index=False):  # C7/C8: itertuples; getattr defaults
            k = getattr(row, "strike", None)
            oi = getattr(row, "openInterest", None)
            try:
                k = float(k)
                oi = float(oi) if oi == oi else 0.0  # NaN -> 0
            except (TypeError, ValueError):
                continue
            if k <= 0:
                continue
            dst[k] = dst.get(k, 0.0) + max(0.0, oi)

    strikes = sorted(set(call_oi) | set(put_oi))
    total_oi = sum(call_oi.values()) + sum(put_oi.values())
    if len(strikes) < 2 or total_oi <= 0:
        return None

    mid = strikes[len(strikes) // 2]

    # C7: vectorized payout over all listed strikes. Payout is piecewise-linear
    # with breakpoints only at strikes, so evaluating at the strikes is exact.
    # payout(S_i) = sum_j call_oi[j]*max(0, S_i-K_j) + sum_j put_oi[j]*max(0, K_j-S_i).
    # numpy's matmul/maximum are C ops that release the GIL. The dict-building
    # above is preserved verbatim, so OI aggregation (dup strikes, NaN->0, k>0,
    # max(0,oi)) is byte-identical to the prior loop.
    K = np.array(strikes, dtype=float)
    call_arr = np.array([call_oi.get(k, 0.0) for k in strikes], dtype=float)
    put_arr = np.array([put_oi.get(k, 0.0) for k in strikes], dtype=float)
    diff = K[:, None] - K[None, :]                       # S_i - K_j
    call_pay = (np.maximum(diff, 0.0) * call_arr[None, :]).sum(axis=1)
    put_pay = (np.maximum(-diff, 0.0) * put_arr[None, :]).sum(axis=1)
    payout = call_pay + put_pay
    dist = np.abs(K - mid)
    # Lexicographic argmin: primary payout, tiebreak dist-to-mid, then lowest
    # strike (stable order) -- the documented tiebreak min(strikes, key=(payout,
    # abs(S-mid))). NOTE: the vectorized payout regroups the float summation
    # (sum(calls)+sum(puts) vs the old loop's interleaved per-strike +=), so in a
    # near-exact payout tie the two can round to a ~1-ULP-different total and pick
    # a different equidistant strike. The vectorized result applies the documented
    # distance tiebreak faithfully where the old loop's rounding noise sometimes
    # pre-empted it -- so it is numerically equivalent and arguably more correct,
    # NOT bit-identical, on such ties. Enrichment only (a displayed magnet level);
    # max-pain never gates whether an alert fires.
    best = strikes[int(np.lexsort((dist, payout))[0])]
    return best, total_oi, sum(call_oi.values()), sum(put_oi.values())


def _schwab_maxpain(ticker: str):
    """Schwab real-time version of compute_max_pain's `_f`, returning the SAME
    raw dict shape. None -> caller falls back to yfinance. Blocking (executor).

    Fetches the cheap expiration list first to locate the weekly + monthly, then
    bounds the chain fetch to the monthly date so SPY/QQQ (34 daily expirations)
    stay well under the full-chain 502 threshold."""
    from datetime import date, datetime
    try:
        from consensus_engine.scanners import schwab_client
        exp_list = schwab_client.get_expirations(ticker)
    except Exception as ex:
        log.warning("schwab expirations failed for %s: %s", ticker, ex)
        return None
    parsed = []
    for e in exp_list or []:
        try:
            parsed.append((e, datetime.strptime(e, "%Y-%m-%d").date()))
        except ValueError:
            continue
    if not parsed:
        return None
    today = date.today()
    weekly_exp = parsed[0][0]
    monthly_targets = []
    for yr, mo in ((today.year, today.month),
                   (today.year + (today.month == 12), (today.month % 12) + 1)):
        tf = _third_friday(yr, mo)
        if tf >= today:
            monthly_targets.append(tf)
    monthly_exp = None
    if monthly_targets:
        tgt = min(monthly_targets)
        cand = min(parsed, key=lambda p: abs((p[1] - tgt).days))
        if abs((cand[1] - tgt).days) <= 3:
            monthly_exp = cand[0]

    ch = _schwab_chain_obj(ticker, to_date=(monthly_exp or weekly_exp))
    if ch is None or not ch.expirations:
        return None
    spot = ch.underlying_price or 0.0
    want = []
    for e in (weekly_exp, monthly_exp):
        if e and e not in want:
            want.append(e)
    chains = {e: ch.by_expiry(e) for e in want}
    max_pain = {e: _max_pain_for_chain(c) for e, c in chains.items()}
    return {"spot": spot, "weekly_exp": weekly_exp, "monthly_exp": monthly_exp,
            "chains_present": list(chains.keys()), "max_pain": max_pain,
            **_chain_legs(chains, spot)}


# ---------------------------------------------------------------------------
# Stage-3 options-chain legs (k4 GEX + k5 gamma-flip, r10 IV-skew, r16 pinning).
# All computed IN compute_max_pain's executor thread from the ALREADY-FETCHED
# front weekly+monthly chains, BEFORE they are discarded — one fetch, no extra
# round-trip. Every helper is fully guarded (never raises into compute_max_pain)
# and every leg is ADDITIVE (existing max-pain keys stay byte-identical).
# Descriptive, embed-only, each behind a config flag default OFF.
# ---------------------------------------------------------------------------

# Flat annualized risk-free rate for Black-Scholes gamma on the yfinance path
# (yfinance chains carry IV but no greeks). Gamma is nearly insensitive to r, so
# a single constant is adequate; native Schwab gamma is used when present.
_BS_RISK_FREE_RATE = 0.04
# OI-pinning HHI is only an opex phenomenon — only meaningful within ~2 weeks of
# the front expiry (a 30-day-out chain must NOT be labelled "strong pin").
_PINNING_MAX_DTE_DAYS = 10


def _side_rows(df):
    """Extract [(strike, oi, iv, delta, gamma)] from one chain-side DataFrame.

    Mirrors _max_pain_for_chain's row hygiene (itertuples, getattr defaults,
    NaN->0 OI, k>0). iv/delta/gamma are None when the column is absent (yfinance
    has no greeks) or the value is NaN / a Schwab -999 sentinel (already mapped
    to NaN upstream). Returns [] on an empty/None frame."""
    out = []
    if df is None or getattr(df, "empty", True):
        return out
    for row in df.itertuples(index=False):
        k = getattr(row, "strike", None)
        oi = getattr(row, "openInterest", None)
        try:
            k = float(k)
            oi = float(oi) if oi == oi else 0.0  # NaN -> 0
        except (TypeError, ValueError):
            continue
        if k <= 0:
            continue

        def _clean(attr):
            v = getattr(row, attr, None)
            try:
                f = float(v)
            except (TypeError, ValueError):
                return None
            return None if f != f else f  # NaN -> None

        iv = _clean("impliedVolatility")
        if iv is not None and iv <= 0:
            iv = None
        out.append((k, max(0.0, oi), iv, _clean("delta"), _clean("gamma")))
    return out


def _bs_gamma(spot, K, t, iv, r=_BS_RISK_FREE_RATE):
    """Black-Scholes gamma (identical for calls and puts by parity). None on bad
    inputs. `t` is calendar time-to-expiry in YEARS (calendar days / 365 — IV is
    quoted on a calendar-year basis, so t must match)."""
    import math
    try:
        S, Kf, tf, sigma = float(spot), float(K), float(t), float(iv)
    except (TypeError, ValueError):
        return None
    if S <= 0 or Kf <= 0 or tf <= 0 or sigma <= 0:
        return None
    try:
        sqrt_t = math.sqrt(tf)
        d1 = (math.log(S / Kf) + (r + 0.5 * sigma * sigma) * tf) / (sigma * sqrt_t)
        pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
        gamma = pdf / (S * sigma * sqrt_t)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    if gamma != gamma or gamma in (float("inf"), float("-inf")):
        return None
    return gamma


def _sorted_front_exps(chains, nearest):
    """Front `nearest` expiries of the fetched chains, sorted chronologically."""
    from datetime import datetime
    dated = []
    for e in chains:
        try:
            dated.append((datetime.strptime(e, "%Y-%m-%d").date(), e))
        except (ValueError, TypeError):
            continue
    dated.sort()
    return [e for _, e in dated[:max(1, int(nearest))]]


def _gex_for_chain(chains, spot, nearest=2):
    """k4 + k5. Per-strike net dealer GEX over the front `nearest` expiries.

    net_gex(K) = spot^2 * 0.01 * 100 * (call_oi*gamma_call - put_oi*gamma_put)
    (dealers long gamma from calls, short from puts). Gamma is native on the
    Schwab path; Black-Scholes from IV on the yfinance path. k5 gamma_flip is the
    cumulative-net-GEX zero-crossing (linear-interpolated; None if no sign change,
    never extrapolated). Returns a dict or None."""
    from datetime import date, datetime
    if not chains:
        return None
    exps = _sorted_front_exps(chains, nearest)
    if not exps:
        return None
    today = date.today()
    net_by_strike: dict = {}
    native_n = bs_n = 0
    for exp in exps:
        ch = chains.get(exp)
        if ch is None:
            continue
        try:
            exp_d = datetime.strptime(exp, "%Y-%m-%d").date()
            dte = max((exp_d - today).days, 1)
        except (ValueError, TypeError):
            dte = 1
        t = dte / 365.0
        for df, sgn in ((getattr(ch, "calls", None), 1.0),
                        (getattr(ch, "puts", None), -1.0)):
            for (k, oi, iv, _dlt, gma) in _side_rows(df):
                if oi <= 0:
                    continue
                if gma is not None and gma > 0:
                    g = gma
                    native_n += 1
                else:
                    g = _bs_gamma(spot, k, t, iv)
                    if g is not None and g > 0:
                        bs_n += 1
                if g is None or g <= 0:
                    continue
                net_by_strike[k] = net_by_strike.get(k, 0.0) + sgn * oi * g
    if not net_by_strike:
        return None
    # Honest basis label: whichever gamma source dominated (Schwab native greeks
    # vs Black-Scholes-from-IV), noting a mix when both contributed. Illiquid
    # Schwab strikes with a 0/sentinel gamma fall back to BS, so a Schwab chain
    # can legitimately read "schwab-native (+BS fill)".
    if native_n and bs_n:
        basis = "schwab-native (+BS fill)"
    elif native_n:
        basis = "schwab-native"
    else:
        basis = "black-scholes"
    scale = (float(spot) ** 2) * 0.01 * 100.0 if spot and spot > 0 else 1.0
    strikes = sorted(net_by_strike)
    net_list = [{"strike": round(k, 2), "net_gex": net_by_strike[k] * scale}
                for k in strikes]
    total = sum(it["net_gex"] for it in net_list)

    # k5 — cumulative-sum zero-crossing(s); pick the crossing nearest spot.
    crossings = []
    cum = 0.0
    prev_k = prev_cum = None
    for it in net_list:
        cum += it["net_gex"]
        if prev_cum is not None and prev_cum != cum and (
            (prev_cum < 0 <= cum) or (prev_cum > 0 >= cum)
        ):
            frac = (0.0 - prev_cum) / (cum - prev_cum)
            crossings.append(prev_k + frac * (it["strike"] - prev_k))
        prev_k, prev_cum = it["strike"], cum
    flip = None
    if crossings:
        flip = (min(crossings, key=lambda x: abs(x - spot))
                if spot and spot > 0 else crossings[0])

    top = sorted(net_list, key=lambda it: abs(it["net_gex"]), reverse=True)[:3]
    return {
        "net_gex": net_list,
        "top": top,
        "total_net_gex": total,
        "net_sign": "long" if total >= 0 else "short",
        "gamma_flip": round(flip, 2) if flip is not None else None,
        "basis": basis,
        "n_expiries": len(exps),
    }


def _iv_skew_for_chain(chains, spot):
    """r10. put IV minus call IV at comparable deltas on the front expiry.

    Schwab path (native delta): ~25-delta put vs ~25-delta call. yfinance path
    (no delta): ~5%-OTM moneyness-matched put vs call. Basis is labelled honestly
    (never silently mixed). Positive = puts bid over calls = downside demand.
    Skips NaN/sentinel IV; None if no valid pair."""
    if not chains:
        return None
    exps = _sorted_front_exps(chains, 1)
    if not exps:
        return None
    front = exps[0]
    ch = chains.get(front)
    if ch is None:
        return None
    calls = [(k, iv, dlt) for (k, _oi, iv, dlt, _g)
             in _side_rows(getattr(ch, "calls", None)) if iv is not None]
    puts = [(k, iv, dlt) for (k, _oi, iv, dlt, _g)
            in _side_rows(getattr(ch, "puts", None)) if iv is not None]
    if not calls or not puts:
        return None
    has_delta = (any(d is not None for (_, _, d) in calls)
                 and any(d is not None for (_, _, d) in puts))
    if has_delta:
        basis = "25-delta"
        call_pick = min((r for r in calls if r[2] is not None),
                        key=lambda r: abs(abs(r[2]) - 0.25), default=None)
        put_pick = min((r for r in puts if r[2] is not None),
                       key=lambda r: abs(abs(r[2]) - 0.25), default=None)
    else:
        if not spot or spot <= 0:
            return None
        basis = "moneyness-matched"
        call_pick = min(calls, key=lambda r: abs(r[0] - spot * 1.05), default=None)
        put_pick = min(puts, key=lambda r: abs(r[0] - spot * 0.95), default=None)
    if not call_pick or not put_pick:
        return None
    value = put_pick[1] - call_pick[1]
    return {
        "value": round(value, 4),
        "basis": basis,
        "put_iv": round(put_pick[1], 4),
        "call_iv": round(call_pick[1], 4),
        "put_strike": round(put_pick[0], 2),
        "call_strike": round(call_pick[0], 2),
        "expiry": front,
    }


def _pinning_herfindahl(chains, spot, band_pct=0.05):
    """r16. Herfindahl (sum of squared OI shares) of combined call+put OI within
    band_pct of spot on the front expiry. Descriptive concentration, NOT a
    probability. Gated to the front expiry only when it is within
    _PINNING_MAX_DTE_DAYS (opex-only). None when far-out / too thin."""
    from datetime import date, datetime
    if not chains or not spot or spot <= 0:
        return None
    exps = _sorted_front_exps(chains, 1)
    if not exps:
        return None
    front = exps[0]
    try:
        dte = (datetime.strptime(front, "%Y-%m-%d").date() - date.today()).days
    except (ValueError, TypeError):
        return None
    if dte < 0 or dte > _PINNING_MAX_DTE_DAYS:
        return None
    ch = chains.get(front)
    if ch is None:
        return None
    oi_by_strike: dict = {}
    for df in (getattr(ch, "calls", None), getattr(ch, "puts", None)):
        for (k, oi, _iv, _dlt, _g) in _side_rows(df):
            if oi > 0:
                oi_by_strike[k] = oi_by_strike.get(k, 0.0) + oi
    lo, hi = spot * (1 - band_pct), spot * (1 + band_pct)
    in_band = {k: v for k, v in oi_by_strike.items() if lo <= k <= hi and v > 0}
    total = sum(in_band.values())
    if total <= 0 or len(in_band) < 2:
        return None
    hhi = sum((v / total) ** 2 for v in in_band.values())
    dominant = max(in_band, key=in_band.get)
    descriptor = "high" if hhi >= 0.25 else ("moderate" if hhi >= 0.12 else "low")
    return {
        "hhi": round(hhi, 4),
        "descriptor": descriptor,
        "dominant_strike": round(dominant, 2),
        "dte": dte,
        "band_pct": band_pct,
    }


def _chain_legs(chains, spot) -> dict:
    """Compute the additive options-chain legs from the already-fetched front
    chains, in the same executor thread as max-pain. Each leg is gated by its
    config flag (OFF -> not computed, zero added latency) and fully guarded so a
    failure NEVER breaks compute_max_pain. Returns {gex, iv_skew, oi_pinning}."""
    out = {"gex": None, "iv_skew": None, "oi_pinning": None}
    if not chains:
        return out
    if _cfg.get("features.dealer_gamma.enabled", False):
        try:
            nearest = int(_cfg.get("features.dealer_gamma.nearest_expirations", 2) or 2)
        except (TypeError, ValueError):
            nearest = 2
        try:
            out["gex"] = _gex_for_chain(chains, spot, nearest)
        except Exception as ex:
            log.debug("gex compute error: %s", ex)
    if _cfg.get("features.iv_skew.enabled", False):
        try:
            out["iv_skew"] = _iv_skew_for_chain(chains, spot)
        except Exception as ex:
            log.debug("iv_skew compute error: %s", ex)
    if _cfg.get("features.oi_pinning.enabled", False):
        try:
            out["oi_pinning"] = _pinning_herfindahl(chains, spot)
        except Exception as ex:
            log.debug("oi_pinning compute error: %s", ex)
    return out


async def compute_max_pain(ticker: str, executor=None) -> Optional[dict]:
    """Compute max-pain for the nearest weekly + nearest monthly expiry.

    FREE yfinance option-chain data (~15-min delayed). Self-contained single
    fetch (one yf.Ticker, one t.options, only the two target expiries' chains)
    — fewer network round-trips than reusing _fetch_flow_chains + a separate
    monthly call, which matters on the latency-sensitive !all path.

    Returns {"spot", "weekly": {...}|None, "monthly": {...}|None,
    "pc_oi_ratio": float|None} or None. pc_oi_ratio = put-OI/call-OI summed
    over the nearest expiry's chain (2dp; None when call OI is 0).
    Each leg dict: {"strike", "expiry", "total_oi"}. When the nearest expiry
    *is* the monthly (or they coincide within ~5 days), monthly carries it and
    weekly is None to avoid a redundant pair.
    """
    import asyncio
    from datetime import date, datetime

    def _f():
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            exps = list(t.options or [])
            if not exps:
                return None

            spot = 0.0
            fi = getattr(t, "fast_info", None)
            if fi is not None:
                for k in ("lastPrice", "last_price", "regularMarketPrice"):
                    try:
                        v = fi.get(k) if hasattr(fi, "get") else getattr(fi, k, None)
                    except Exception:
                        v = None
                    if v:
                        spot = float(v)
                        break

            today = date.today()
            parsed = []
            for e in exps:
                try:
                    parsed.append((e, datetime.strptime(e, "%Y-%m-%d").date()))
                except ValueError:
                    continue
            if not parsed:
                return None

            weekly_exp = parsed[0][0]

            # nearest monthly = listed expiry closest to a 3rd-Friday >= today
            monthly_targets = []
            for yr, mo in ((today.year, today.month),
                           (today.year + (today.month == 12),
                            (today.month % 12) + 1)):
                tf = _third_friday(yr, mo)
                if tf >= today:
                    monthly_targets.append(tf)
            monthly_exp = None
            if monthly_targets:
                tgt = min(monthly_targets)
                cand = min(parsed, key=lambda p: abs((p[1] - tgt).days))
                if abs((cand[1] - tgt).days) <= 3:
                    monthly_exp = cand[0]

            want = []
            for e in (weekly_exp, monthly_exp):
                if e and e not in want:
                    want.append(e)

            chains = {}
            attempted = failed = 0
            for e in want:
                attempted += 1
                try:
                    chains[e] = t.option_chain(e)
                except Exception:
                    failed += 1
            _note_chain_fetch("compute_max_pain", ticker, attempted, failed)
            # C7: compute max-pain IN this executor thread (not on the event
            # loop after the fetch returns). max_pain[e] = (strike, total_oi,
            # call_oi_sum, put_oi_sum) | None.
            max_pain = {e: _max_pain_for_chain(ch) for e, ch in chains.items()}
            return {"spot": spot, "weekly_exp": weekly_exp,
                    "monthly_exp": monthly_exp, "chains_present": list(chains.keys()),
                    "max_pain": max_pain, **_chain_legs(chains, spot)}
        except Exception as ex:
            log.debug("max-pain fetch error for %s: %s", ticker, ex)
            return None

    loop = asyncio.get_running_loop()
    raw = None
    # #57: Schwab real-time chain PRIMARY for max-pain (!all path).
    if _cfg.get("features.schwab_options.enabled", False):
        try:
            raw = await loop.run_in_executor(executor, _schwab_maxpain, ticker)
        except Exception as ex:
            log.debug("schwab max-pain error for %s: %s", ticker, ex)
            raw = None
    if not raw:
        try:
            async with get_yahoo_semaphore():  # C20
                raw = await loop.run_in_executor(executor, _f)
        except Exception as ex:
            log.debug("max-pain executor error for %s: %s", ticker, ex)
            return None
    if not raw:
        return None

    max_pain = raw["max_pain"]  # C7: precomputed in the executor thread
    spot = raw["spot"]

    def _leg(exp):
        mp = max_pain.get(exp)
        if mp is None:
            return None
        strike, total_oi, _call_oi, _put_oi = mp
        return {"strike": round(strike, 2), "expiry": exp, "total_oi": int(total_oi)}

    weekly_exp = raw["weekly_exp"]
    monthly_exp = raw["monthly_exp"]

    # Put/Call OPEN-INTEREST ratio from the NEAREST expiry (weekly_exp == exps[0]).
    # Same call/put OI sums max-pain already aggregates; >1 = more put OI (bearish
    # positioning), <1 = more call OI. None when the nearest chain has no call OI.
    pc_oi_ratio = None
    call_oi_sum = put_oi_sum = None
    _near = max_pain.get(weekly_exp) if weekly_exp else None
    if _near is not None:
        _, _, _call_oi_sum, _put_oi_sum = _near
        call_oi_sum, put_oi_sum = _call_oi_sum, _put_oi_sum   # #53: for the call/put OI % split
        if _call_oi_sum:
            pc_oi_ratio = round(_put_oi_sum / _call_oi_sum, 2)

    # Dedup: if the monthly is the same listed expiry as the weekly (or within
    # ~5 days), show only the monthly leg to avoid a redundant near-identical pair.
    redundant = False
    if monthly_exp and monthly_exp == weekly_exp:
        redundant = True
    elif monthly_exp:
        try:
            from datetime import datetime as _dt
            dw = _dt.strptime(weekly_exp, "%Y-%m-%d").date()
            dm = _dt.strptime(monthly_exp, "%Y-%m-%d").date()
            if abs((dm - dw).days) <= 5:
                redundant = True
        except ValueError:
            pass

    monthly_leg = _leg(monthly_exp) if monthly_exp else None
    weekly_leg = None if redundant else _leg(weekly_exp)

    if weekly_leg is None and monthly_leg is None:
        return None
    # Existing keys BELOW are byte-unchanged (#6 max-pain + #53 OI-split depend
    # on them). Stage-3 gex/iv_skew/oi_pinning are ADDITIVE, computed in-thread
    # (raw already carries them from _f/_schwab_maxpain); None when their flag is
    # OFF or the leg had no valid data.
    return {"spot": round(spot, 2) if spot else None,
            "weekly": weekly_leg, "monthly": monthly_leg,
            "pc_oi_ratio": pc_oi_ratio,
            "call_oi_sum": call_oi_sum, "put_oi_sum": put_oi_sum,
            "gex": raw.get("gex"), "iv_skew": raw.get("iv_skew"),
            "oi_pinning": raw.get("oi_pinning")}
