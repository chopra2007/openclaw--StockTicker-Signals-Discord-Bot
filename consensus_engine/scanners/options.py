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


def _is_sweep(vol: float, oi: float, min_ratio: float = 5.0, min_notional: float = 0) -> bool:
    """Check if volume/OI ratio qualifies as a sweep."""
    if oi == 0:
        return False
    return (vol / oi) >= min_ratio


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
            log.debug("yfinance options fetch error for %s: %s", ticker, e)
            return None

    loop = asyncio.get_running_loop()
    try:
        # C20: bound concurrent Yahoo hits process-wide (released the instant
        # the fetch returns; never held across an alert decision).
        async with get_yahoo_semaphore():
            chains = await loop.run_in_executor(executor, _fetch)
    except Exception as e:
        log.debug("run_in_executor error for %s: %s", ticker, e)
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
            hits.append(FlowHit(
                ticker=ticker, side=side,
                strike=float(getattr(row, "strike", 0) or 0), expiry=expiry,
                volume=int(vol), open_interest=int(oi),
                vol_oi_ratio=round(ratio, 2), premium_usd=round(premium, 2),
                last_trade_ts=lt, spot=spot,
                contract_symbol=str(getattr(row, "contractSymbol", "")),
                staleness_unverified=staleness_unverified,
            ))
    return hits


async def _fetch_flow_chains(ticker: str, executor, nearest: int):
    """Fetch spot + the nearest `nearest` expirations' chains (blocking yf in executor)."""
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
    out: list = []
    for tk in tickers:
        try:
            spot, chains = await _fetch_flow_chains(tk, executor, nearest_expirations)
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
    """Render a FlowHit as an instant-trigger Discord alert (Alert Philosophy)."""
    direction = "🟢 BULLISH" if hit.side == "CALL" else "🔴 BEARISH"
    prem_m = hit.premium_usd / 1_000_000.0
    spot_txt = f" | spot ${hit.spot:,.2f}" if hit.spot else ""
    # C12: be honest when we couldn't verify the contract's last-trade freshness.
    stale_txt = " _[staleness unverified]_" if getattr(hit, "staleness_unverified", False) else ""
    return (
        f"⚡ **UNUSUAL OPTIONS FLOW** — `${hit.ticker}` {direction}\n"
        f"**{hit.side}** {hit.expiry} ${hit.strike:g} strike{spot_txt}\n"
        f"Volume **{hit.volume:,}** vs OI {hit.open_interest:,} "
        f"(**{hit.vol_oi_ratio:.1f}x** — fresh positioning) | "
        f"premium **${prem_m:.2f}M**{stale_txt}\n"
        f"_Free ~15-min-delayed chain data; unusual-flow instant trigger._"
    )


def format_options_sweep_digest(sweeps: list[dict]) -> str:
    """Format sweep results as Discord message."""
    if not sweeps:
        return "No unusual options sweeps detected."
    lines = ["**Options Sweep Scanner**"]
    for s in sweeps[:10]:
        lines.append(
            f"`${s['ticker']}` **{s['direction']}** sweep -- "
            f"{s['max_ratio']:.1f}x vol/OI | P/C: {s['put_call_ratio']:.2f}"
        )
    return "\n".join(lines)


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
    # above is preserved verbatim so OI aggregation (dup strikes, NaN->0, k>0,
    # max(0,oi)) is byte-identical to the prior loop.
    K = np.array(strikes, dtype=float)
    call_arr = np.array([call_oi.get(k, 0.0) for k in strikes], dtype=float)
    put_arr = np.array([put_oi.get(k, 0.0) for k in strikes], dtype=float)
    diff = K[:, None] - K[None, :]                       # S_i - K_j
    call_pay = (np.maximum(diff, 0.0) * call_arr[None, :]).sum(axis=1)
    put_pay = (np.maximum(-diff, 0.0) * put_arr[None, :]).sum(axis=1)
    payout = call_pay + put_pay
    dist = np.abs(K - mid)
    # Lexicographic argmin (primary payout, tiebreak dist, then lowest strike via
    # stable order) — matches min(strikes, key=(payout, abs(S-mid))).
    best = strikes[int(np.lexsort((dist, payout))[0])]
    return best, total_oi, sum(call_oi.values()), sum(put_oi.values())


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
                    "max_pain": max_pain}
        except Exception as ex:
            log.debug("max-pain fetch error for %s: %s", ticker, ex)
            return None

    loop = asyncio.get_running_loop()
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
    return {"spot": round(spot, 2) if spot else None,
            "weekly": weekly_leg, "monthly": monthly_leg,
            "pc_oi_ratio": pc_oi_ratio,
            "call_oi_sum": call_oi_sum, "put_oi_sum": put_oi_sum}
