"""Cross-Reference Engine — orchestrates all multiplier sources.

Runs in parallel after the instant Discord ping. Computes a final
score from news, social, technical, other analysts, and LLM confidence.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from consensus_engine.utils.xref_cache import get_cached_xref, cache_xref
from consensus_engine.measurement import build_score_cache_key, classify_analyst_alignment

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.models import (
    ParsedTweet, CrossReferenceResult, ScoreBreakdown,
    CatalystResult, TechnicalResult, OptionsResult, YouTubeContext,
)
from consensus_engine.scanners.news import news_cascade
from consensus_engine.analysis.technical import verify_technical
from consensus_engine.analysis.llm_scorer import score_confidence
from consensus_engine.analysis import research_compute as _research
from consensus_engine.analysis.research_contracts import ScoreTickerResult, _SecGraduation, _BurstAnalysis



log = logging.getLogger("consensus_engine.cross_reference")

_sem_news = asyncio.Semaphore(3)
_sem_social = asyncio.Semaphore(5)
_sem_technical = asyncio.Semaphore(3)
_sem_llm = asyncio.Semaphore(2)


def _resolve_catalyst_type(news_catalyst_type: str, sec_hit: bool) -> str:
    """Pick the catalyst_type for downstream M6 exemption.

    News-classified catalysts win. When the only signal is from the SEC
    watcher, fall back to 'sec_filing' so engine.py:304's
    `is_sec_catalyst = catalyst_type.startswith("sec_")` check fires.
    """
    if news_catalyst_type:
        return news_catalyst_type
    if sec_hit:
        return "sec_filing"
    return ""


def compute_technical_score(technical: Optional[TechnicalResult]) -> int:
    return _research.compute_technical_score(technical, settings=cfg, now=time.time())


def _compute_apewisdom_zscore_pts(
    social_data: dict,
    *,
    sec_hit: bool,
    catalyst_passed: bool,
    technical_pts: int,
) -> int:
    return _research._compute_apewisdom_zscore_pts(social_data, sec_hit=sec_hit, catalyst_passed=catalyst_passed, technical_pts=technical_pts, settings=cfg, now=time.time())


def compute_social_score(social_data: dict[str, int]) -> int:
    return _research.compute_social_score(social_data, settings=cfg, now=time.time())


def _compute_social_breakdown(
    social_data: dict,
    *,
    sec_hit: bool = False,
    catalyst_passed: bool = False,
    technical_pts: int = 0,
) -> dict[str, int]:
    return _research._compute_social_breakdown(social_data, sec_hit=sec_hit, catalyst_passed=catalyst_passed, technical_pts=technical_pts, settings=cfg, now=time.time())


def _compute_finra_short_volume_pts(
    short_pct: float,
    baseline: dict,
    finra_published_at: float | None,
    *,
    direction: str = "long",
) -> int:
    return _research._compute_finra_short_volume_pts(short_pct, baseline, finra_published_at, direction=direction, settings=cfg, now=time.time())


def _compute_days_to_cover_pts(
    si_row: dict,
    *,
    direction: str = "long",
) -> int:
    return _research._compute_days_to_cover_pts(si_row, direction=direction, settings=cfg, now=time.time())


def _compute_pead_pts(
    pead_result: Optional[dict],
    *,
    direction: str = "long",
) -> int:
    return _research._compute_pead_pts(pead_result, direction=direction, settings=cfg, now=time.time())


def _get_catalyst_score(catalyst_type: str) -> int:
    return _research._get_catalyst_score(catalyst_type, settings=cfg, now=time.time())


async def _run_news_cascade(ticker: str) -> Optional[CatalystResult]:
    return await news_cascade(ticker)


# #8 — named-insider enrichment of the SEC summary. Bounded so the existing
# 10s _with_timeout around _run_sec_check never trips: at most this many
# Form-4 filings are fetched (mirrors aggregator._FORM4_ENRICH_LIMIT), and the
# whole enrichment fetch is time-boxed below that wrapper.
_NAMED_INSIDER_FETCH_LIMIT = 5
_NAMED_INSIDER_FETCH_TIMEOUT = 7.0
_NAMED_INSIDER_FIELD_CAP = 1024  # keep the appended block under one embed field


def _format_named_insiders(fetched: list) -> str:
    """Render the named-insider block for the SEC summary via the shared
    insider renderer (one code-block card per insider, per date, per side).

    `fetched` is a list of transaction lists (one per Form-4 filing). Open-market
    purchases/sales are aggregated per insider; routine awards / option exercises
    / tax withholding are collapsed to a count. The block is trimmed to stay
    under one embed field. Returns "" when there is nothing to show.
    """
    from consensus_engine.alerts.insider_display import (
        aggregate_insiders, render_cards,
    )

    all_txs = [t for txs in fetched for t in (txs or [])]
    if not all_txs:
        return ""
    summaries, routine_count = aggregate_insiders(all_txs)
    if not summaries:
        if routine_count:
            return f"Form 4 detail: {routine_count} routine award/exercise(s) only."
        return ""

    shown = list(summaries)
    block = render_cards(shown, routine_count)
    while len(block) > _NAMED_INSIDER_FIELD_CAP and len(shown) > 1:
        shown = shown[:-1]
        note = f"+{len(summaries) - len(shown)} more insiders"
        block = render_cards(shown, routine_count, note=note)
    return block


async def _fetch_named_insiders(ticker: str, filings: list) -> str:
    """Fetch Form-4 detail for up to _NAMED_INSIDER_FETCH_LIMIT filings and
    render the named-insider block. Time-boxed; returns "" on no detail."""
    from consensus_engine.scanners.sec_edgar import fetch_form4_details
    from consensus_engine.utils.rate_limiter import rate_limiter

    form4 = [f for f in filings
             if isinstance(f, dict) and f.get("form") == "4"][:_NAMED_INSIDER_FETCH_LIMIT]
    if not form4:
        return ""

    async def _one(f: dict) -> list:
        try:
            if not await rate_limiter.acquire("sec_edgar"):
                return []
            txs = await fetch_form4_details(
                f.get("cik", ""),
                f.get("accession_number", ""),
                f.get("primary_document", ""),
            )
            return list(txs or [])
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — one bad filing never voids the rest
            log.debug("named-insider fetch error: %s", exc)
            return []

    tasks = [asyncio.create_task(_one(f)) for f in form4]
    fetched: list = []
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=_NAMED_INSIDER_FETCH_TIMEOUT)
    except asyncio.TimeoutError:
        pass
    for t in tasks:
        if t.done() and not t.cancelled() and t.exception() is None:
            fetched.append(t.result())
        else:
            t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    return _format_named_insiders(fetched)


async def _run_sec_check(ticker: str) -> tuple[bool, str]:
    """Check SEC EDGAR for recent filings. Returns (has_filing, summary)."""
    try:
        from consensus_engine.scanners.sec_edgar import check_recent_filings, classify_filing_significance
        filings = await check_recent_filings(ticker, hours_back=48)
        has_filing, summary = classify_filing_significance(filings)
        # #8 — expand "Form 4 x{n}" to named insiders (flag-gated, default OFF).
        if cfg.get("sec_watcher.named_insiders_in_alert", False) and \
                any(isinstance(f, dict) and f.get("form") == "4" for f in filings):
            block = await _fetch_named_insiders(ticker, filings)
            if block:
                summary = f"{summary}\n{block}" if summary else block
        return has_filing, summary
    except Exception as e:
        log.warning("SEC check error for %s: %s", ticker, e)
        return False, ""


# ── I5 (signal-features-2026-06-09) — graduate SEC by role + open-market $ ──
# All of this is dark until `features.sec_graduated_scoring.enabled` is ON. The
# 2-tuple `_run_sec_check` contract above is LOAD-BEARING (every existing caller
# and mock unpacks `(has_filing, summary)` or returns `(False, "")`), so the
# graduation data is computed by this SEPARATE helper rather than widening that
# tuple — adding fields to `_run_sec_check`'s return would break those mocks.
# Flag OFF -> this helper is never called and `sec_pts` stays the flat +15.

# Canonical C-suite roles eligible for the +20 tier. The keys are matched as
# whole UPPER tokens / substrings against the Form-4 officerTitle string.
_CSUITE_ROLE_PATTERNS = (
    "CHIEF EXECUTIVE", "CEO", "PEO",            # principal executive
    "CHIEF FINANCIAL", "CFO", "PFO",            # principal financial
    "CHIEF OPERATING", "COO",
    "PRESIDENT",
)


def _canonicalize_sec_role(title: str) -> str:
    """Map a raw Form-4 officer title to 'csuite' or 'other'.

    CEO/CFO/COO/President and the SEC principal-officer codes PEO/PFO map to
    'csuite' (the only role tier that can earn +20). Anything else (Director,
    10% Owner, VP, unknown) maps to 'other' -> +8 baseline, never +20.
    """
    up = (title or "").upper()
    # "Vice President" must NOT match the PRESIDENT C-suite tier.
    if "VICE PRESIDENT" in up or up.strip().startswith("VP") or " VP " in f" {up} ":
        return "other"
    for pat in _CSUITE_ROLE_PATTERNS:
        if pat in up:
            return "csuite"
    return "other"




def _parse_form4_for_graduation(raw_xml: str) -> Optional[dict]:
    """Extract I5 graduation fields from one Form-4 XML.

    Returns {role, is_planned, plan_flag_seen, buy_dollars, buy_date, has_sell}
    or None on parse failure. Reuses the cluster module's role/footnote parser
    shape but keeps BOTH buys (code 'P') and open-market sells (code 'S') so the
    net-selling withhold can fire. Plan flag = 10b5-1 footnote detection.
    """
    import xml.etree.ElementTree as ET
    from consensus_engine.scanners.sec_form4_cluster import is_10b5_1

    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError:
        return None

    def _val(node, tag):
        el = node.find(f".//{tag}/value")
        if el is None:
            el = node.find(f".//{tag}")
        return (el.text or "").strip() if el is not None else ""

    officer_title = _val(root, "officerTitle")
    is_director = _val(root, "isDirector") == "1"
    is_officer = _val(root, "isOfficer") == "1"
    is_ten_pct = _val(root, "isTenPercentOwner") == "1"
    if officer_title:
        title = officer_title
    elif is_director and is_officer:
        title = "Director & Officer"
    elif is_director:
        title = "Director"
    elif is_ten_pct:
        title = "10% Owner"
    else:
        title = "Insider"

    footnote_nodes = root.findall(".//footnote")
    footnote_text = " ".join((fn.text or "") for fn in footnote_nodes)
    # plan_flag_seen distinguishes "footnote absent" (cannot rule out a plan ->
    # cap at +8) from "footnote present and clean". Any footnote node = parseable.
    plan_flag_seen = bool(footnote_nodes)
    is_planned = bool(footnote_text) and is_10b5_1(footnote_text)

    # r28: the STRUCTURED 10b5-1 checkbox the 2023 amendments added to Form 4/5.
    # <aff10b5One>1</aff10b5One> (a top-level flag; value "1" = the transaction was
    # made under a Rule 10b5-1(c) plan). Pinned live against NVDA Form 4s. This is
    # more reliable than the footnote matcher, which stays the guaranteed fallback.
    aff_node = root.find(".//aff10b5One")
    structured_plan_flag_seen = aff_node is not None
    is_10b5_1_structured = structured_plan_flag_seen and (aff_node.text or "").strip() == "1"
    reporter_cik = _val(root, "rptOwnerCik")
    reporter_name = _val(root, "rptOwnerName") or "Unknown"

    buy_dollars = 0.0
    buy_date = ""
    has_sell = False
    for tx in root.findall(".//nonDerivativeTransaction"):
        code = _val(tx, "transactionCode")  # P=open-market buy, S=open-market sale
        if code not in ("P", "S"):
            continue
        try:
            shares = float(_val(tx, "transactionShares") or 0)
            price = float(_val(tx, "transactionPricePerShare") or 0)
        except ValueError:
            continue
        dollars = shares * price
        if code == "P" and dollars > 0:
            if dollars > buy_dollars:
                buy_dollars = dollars
                buy_date = _val(tx, "transactionDate")
        elif code == "S" and dollars > 0:
            has_sell = True

    return {
        "role": _canonicalize_sec_role(title),
        "is_planned": is_planned,
        "plan_flag_seen": plan_flag_seen,
        "buy_dollars": buy_dollars,
        "buy_date": buy_date,
        "has_sell": has_sell,
        # r28 additive fields (existing I5 consumers ignore them; the 2-tuple
        # _run_sec_check contract and _SecGraduation are untouched):
        "is_10b5_1_structured": is_10b5_1_structured,
        "structured_plan_flag_seen": structured_plan_flag_seen,
        "reporter_cik": reporter_cik,
        "reporter_name": reporter_name,
        "txn_date": buy_date or "",
    }


async def _run_sec_graduation(ticker: str) -> _SecGraduation:
    """Fetch recent Form-4 filings and aggregate the I5 graduation facts.

    Only called when `features.sec_graduated_scoring.enabled` is ON. Picks the
    SINGLE largest open-market BUY across all parsed Form-4s; its role/date/plan
    flag drive the tier. If no qualifying buy exists but an open-market sell did,
    `net_selling` is set so the caller WITHHOLDS the buy credit (never subtracts).
    Returns the all-default _SecGraduation on any error (graceful -> +8 if Form-4
    present, else 0).
    """
    grad = _SecGraduation()
    try:
        from consensus_engine.scanners.sec_edgar import check_recent_filings
        from consensus_engine.scanners.sec_form4_cluster import _fetch_form4_xml
        from consensus_engine.utils.rate_limiter import rate_limiter

        filings = await check_recent_filings(ticker, hours_back=48)
        form4 = [f for f in filings
                 if isinstance(f, dict) and f.get("form") == "4"][:_NAMED_INSIDER_FETCH_LIMIT]
        if not form4:
            return grad
        grad.has_form4 = True

        any_sell = False
        for f in form4:
            try:
                if not await rate_limiter.acquire("sec_edgar"):
                    continue
            except Exception:  # noqa: BLE001 — rate limiter wobble never voids the rest
                pass
            raw = await _fetch_form4_xml(
                f.get("cik", ""),
                f.get("accession_number", ""),
                f.get("primary_document", ""),
            )
            if not raw:
                continue
            parsed = _parse_form4_for_graduation(raw)
            if not parsed:
                continue
            if parsed["has_sell"]:
                any_sell = True
            if parsed["buy_dollars"] > grad.max_buy_dollars:
                grad.max_buy_dollars = parsed["buy_dollars"]
                grad.reporter_role = parsed["role"]
                grad.is_planned = parsed["is_planned"]
                grad.plan_flag_seen = parsed["plan_flag_seen"]
                grad.txn_date = parsed["buy_date"]

        # Net selling: open-market sells present but no qualifying open-market buy.
        grad.net_selling = any_sell and grad.max_buy_dollars <= 0.0
        return grad
    except Exception as e:  # noqa: BLE001 — graduation is best-effort; fall back to +8/0
        log.debug("SEC graduation error for %s: %s", ticker, e)
        return grad


def _is_txn_recent(txn_date: str, recency_days: int) -> bool:
    return _research._is_txn_recent(txn_date, recency_days, settings=cfg, now=time.time())


def _graduate_sec_pts(grad: _SecGraduation, flat_pts: int) -> int:
    from consensus_engine.scanners.sec_form4_cluster import _MIN_PURCHASE_DOLLARS
    return _research._graduate_sec_pts(grad, flat_pts, min_purchase_dollars=_MIN_PURCHASE_DOLLARS, settings=cfg, now=time.time())


def _earnings_magnitude_bonus(catalyst: "CatalystResult") -> int:
    return _research._earnings_magnitude_bonus(catalyst, settings=cfg, now=time.time())


def _graduate_options_pts(options: "OptionsResult", direction: str) -> int:
    return _research._graduate_options_pts(options, direction, settings=cfg, now=time.time())


# ---------------------------------------------------------------------------
# E6 — manufactured-agreement gate (signal-features-2026-06-09)
# ---------------------------------------------------------------------------
# Detects a near-duplicate analyst burst (near-simultaneous timing +
# templated/near-duplicate wording + low distinct-account count). A burst does
# NOT suppress any signal; it only gates the crowd-agreement bonus
# (consensus_boost) until an independent non-burst source corroborates.
# E6 runs BEFORE I3 so burst accounts collapse to ONE actor in I3's math.
# Flag: features.manufactured_agreement_gate.enabled (default OFF).
# Flag OFF -> byte-identical (consensus_boost unchanged, burst unused by I3).
# ---------------------------------------------------------------------------

# Config-key defaults (can be overridden via config/consensus.yaml)
_E6_SIMILARITY_DEFAULT = 0.6    # Jaccard threshold for "same wording"
_E6_BURST_WINDOW_SEC_DEFAULT = 300   # 5-minute window for near-simultaneous
_E6_MIN_ACCOUNTS_DEFAULT = 2    # minimum distinct accounts to flag a burst


def _word_set(text: str) -> frozenset:
    return _research._word_set(text, settings=cfg, now=time.time())


def _jaccard(a: frozenset, b: frozenset) -> float:
    return _research._jaccard(a, b, settings=cfg, now=time.time())


async def _fetch_analyst_signals_for_burst(ticker: str, window_sec: int) -> list[dict]:
    """Fetch recent Twitter/analyst signal rows for E6 burst detection.

    Returns rows with keys: source_detail (handle), raw_text, detected_at.
    Bounded to the given window. Returns [] on any error (graceful degradation).
    """
    try:
        return await db.get_twitter_signals(ticker, window_seconds=window_sec)
    except Exception as exc:
        log.debug("E6 burst fetch error for $%s: %s", ticker, exc)
        return []




def _analyse_burst(
    signal_rows: list[dict],
    *,
    similarity_threshold: float = _E6_SIMILARITY_DEFAULT,
    burst_window_sec: float = _E6_BURST_WINDOW_SEC_DEFAULT,
    min_accounts: int = _E6_MIN_ACCOUNTS_DEFAULT,
) -> tuple[bool, frozenset]:
    return _research._analyse_burst(signal_rows, similarity_threshold=similarity_threshold, burst_window_sec=burst_window_sec, min_accounts=min_accounts, settings=cfg, now=time.time())


def _check_e6_corroboration(
    burst_detected: bool,
    *,
    sec_hit: bool,
    catalyst_passed: bool,
    options_has_activity: bool,
) -> bool:
    return _research._check_e6_corroboration(burst_detected, sec_hit=sec_hit, catalyst_passed=catalyst_passed, options_has_activity=options_has_activity, settings=cfg, now=time.time())


# ---------------------------------------------------------------------------
# I3 — live contradiction_index PRODUCER (signal-features-2026-06-09)
# ---------------------------------------------------------------------------
# The consumer is ALREADY LIVE: engine._classify (penalty :267-268) and
# main.py:1276-1290 (A1 post-process). This producer sets the value on
# ScoreTickerResult so the consumer has a non-zero index to act on.
# Flag: features.contradiction_index_live.enabled (default OFF).
# Flag OFF -> ScoreTickerResult.contradiction_index stays 0.0 -> consumer
# is a verbatim no-op -> existing tests unchanged.
# ---------------------------------------------------------------------------

def _compute_contradiction_index(
    *,
    tweet_direction: str,
    analyst_pts: int,
    other_analysts: list,
    options: Optional["OptionsResult"],
    options_pts: int,
    youtube: Optional["YouTubeContext"],
    youtube_pts: int,
    sec_hit: bool,
    sec_pts: int,
    burst_analysis: Optional["_BurstAnalysis"] = None,
) -> float:
    return _research._compute_contradiction_index(tweet_direction=tweet_direction, analyst_pts=analyst_pts, other_analysts=other_analysts, options=options, options_pts=options_pts, youtube=youtube, youtube_pts=youtube_pts, sec_hit=sec_hit, sec_pts=sec_pts, burst_analysis=burst_analysis, settings=cfg, now=time.time())


def _count_opposing_actors(
    *,
    tweet_direction: str,
    options: Optional["OptionsResult"],
    options_pts: int,
    youtube: Optional["YouTubeContext"],
    youtube_pts: int,
    sec_hit: bool,
    sec_pts: int,
    burst_analysis: Optional["_BurstAnalysis"] = None,
) -> int:
    return _research._count_opposing_actors(tweet_direction=tweet_direction, options=options, options_pts=options_pts, youtube=youtube, youtube_pts=youtube_pts, sec_hit=sec_hit, sec_pts=sec_pts, burst_analysis=burst_analysis, settings=cfg, now=time.time())


async def _run_social_check(ticker: str) -> dict:
    """Get social signal counts for a ticker from the database.

    I13 (signal-features-2026-06-09): also fetches the per-ticker ApeWisdom
    mention count + baseline from the new apewisdom_mentions series so the
    scorer can compute a z-score.  Extra keys are only populated when the
    flag is ON to keep the fast path cheap (flag OFF -> baseline fetch skipped).

    Extra keys added when flag is ON:
      "apewisdom_mentions"   (int)  — latest mention count from the series
      "apewisdom_baseline"   (dict) — {"mean", "std", "sample_days"}
      "apewisdom_captured_at" (float|None) — timestamp of the latest row
    """
    counts = await db.get_signal_counts_by_source(ticker)
    result: dict = {
        "apewisdom": counts.get("apewisdom", 0),
        "stocktwits": counts.get("stocktwits", 0),
        "reddit": counts.get("reddit", 0),
        "google_trends": counts.get("google_trends", 0),
    }

    if cfg.get("features.apewisdom_zscore.enabled", False):
        baseline = await db.get_apewisdom_baseline(ticker)
        latest = await db.get_latest_apewisdom_mentions(ticker)
        result["apewisdom_baseline"] = baseline
        result["apewisdom_mentions"] = latest.get("mentions", 0) if latest else 0
        result["apewisdom_captured_at"] = latest.get("captured_at") if latest else None

    return result


async def _run_technical(ticker: str, direction: str = "long") -> Optional[TechnicalResult]:
    return await verify_technical(ticker, direction=direction)


async def _run_other_analysts(
    ticker: str, direction: str, exclude_analyst: str = "",
) -> dict[str, list[str]]:
    """Split recent analysts into same-direction and opposing groups."""
    rows = await db.get_recent_analyst_signals_for_ticker(ticker, window_seconds=3600)
    latest: dict[str, tuple[float | None, set[str]]] = {}
    for row in rows:
        analyst = row["analyst"]
        if analyst == exclude_analyst:
            continue
        detected_at = row.get("detected_at")
        state = latest.get(analyst)
        if state is None or (detected_at is not None and
                             (state[0] is None or detected_at > state[0])):
            latest[analyst] = (detected_at, {str(row.get("direction", "")).lower()})
        elif detected_at == state[0]:
            state[1].add(str(row.get("direction", "")).lower())
    aligned: list[str] = []
    opposing: list[str] = []
    for analyst, (_, directions) in latest.items():
        if len(directions) != 1 or "ambiguous" in directions:
            opposing.append(analyst)
            continue
        alignment = classify_analyst_alignment(direction, next(iter(directions)))
        if alignment == "agreement":
            aligned.append(analyst)
        elif alignment == "disagreement":
            opposing.append(analyst)
    return {"aligned": aligned, "opposing": opposing}


async def _run_llm_score(ticker: str, catalyst: Optional[CatalystResult],
                          technical: Optional[TechnicalResult], sec_summary: str = "") -> tuple[float, str]:
    """Get LLM confidence score with SEC/EDGAR data for thesis generation."""
    return await score_confidence(ticker, None, None, catalyst, technical, sec_summary)


async def _timed(coro, metrics: dict, key: str) -> Any:
    """Await a coroutine and record its elapsed time in milliseconds to metrics."""
    t0 = time.perf_counter()
    result = await coro
    metrics[key] = int((time.perf_counter() - t0) * 1000)
    return result


async def _with_timeout(coro, timeout: float, default: Any, label: str,
                        sem: Optional[asyncio.Semaphore] = None) -> Any:
    """Run a coroutine with a timeout, returning default on timeout or error."""
    async def _run():
        if sem is None:
            return await coro
        async with sem:
            return await coro

    try:
        return await asyncio.wait_for(_run(), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("Cross-reference source timed out after %.0fs: %s", timeout, label)
        await db.record_metric(f"xref_{label}_timeout", 1)
        return default
    except Exception as e:
        log.warning("Cross-reference source error (%s): %s", label, e)
        await db.record_metric(f"xref_{label}_error", 1)
        return default


async def _run_options_check(ticker: str, executor) -> Optional[OptionsResult]:
    """Check for unusual options activity."""
    if executor is None:
        return None
    try:
        from consensus_engine.scanners.options import check_unusual_options
        return await check_unusual_options(ticker, executor)
    except Exception as e:
        log.debug("Options check error for %s: %s", ticker, e)
        return None


def _count_trusted_channels(mentions: list[dict], min_graded_n: int) -> int:
    """I1 — count DISTINCT channels that may count toward the bearish floor.

    A channel's trust counts ONLY if it has BOTH (a) channel age (a non-null
    `channel_age_days`, i.e. the channel is registered/known long enough to have
    a track record) AND (b) at least `min_graded_n` graded outcomes
    (`graded_n`). Either field absent -> the channel does NOT count. In
    production the per-mention rows do not yet carry these fields, so this
    returns 0 -> the bearish subtraction floor is never met -> a bearish
    consensus contributes 0, never a positive add (the I1 wrong-sign-bug fix).
    The dedicated I1 test injects `channel_age_days` + `graded_n` to exercise
    the trusted-multi-channel path.
    """
    trusted: set[str] = set()
    for m in mentions:
        name = m.get("channel_name")
        if not name:
            continue
        age = m.get("channel_age_days")
        graded = m.get("graded_n")
        if age is None or graded is None:
            continue
        try:
            if float(age) > 0 and int(graded) >= min_graded_n:
                trusted.add(name)
        except (TypeError, ValueError):
            continue
    return len(trusted)


async def _get_youtube_context(ticker: str):
    """Query YouTube signals for ticker (8th source for cross-reference)."""
    try:
        from consensus_engine.models import YouTubeContext, Direction, Conviction
        mentions = await db.get_youtube_signals_for_ticker(ticker, days=7)
        if not mentions:
            return None

        # Filter to signals with primary coverage (evidence spans >= threshold)
        threshold = int(cfg.get("all_command.youtube_links.min_evidence_spans", 1))
        primary_mentions = [m for m in mentions if (m.get("evidence_spans_for_ticker") or 0) >= threshold]
        if not primary_mentions:
            return None

        # Aggregate mentions
        direction_votes = {"long": 0, "short": 0, "neutral": 0}
        conviction_scores = {"high": 3, "medium": 2, "low": 1}
        max_conviction_score = 0
        top_conviction = "medium"

        for mention in primary_mentions:
            direction = mention.get("direction", "neutral")
            conviction = mention.get("conviction", "medium")
            direction_votes[direction] = direction_votes.get(direction, 0) + 1
            conv_score = conviction_scores.get(conviction, 1)
            if conv_score > max_conviction_score:
                max_conviction_score = conv_score
                top_conviction = conviction

        # Consensus direction
        consensus_dir = max(direction_votes, key=direction_votes.get)

        # Get canonical evidence: setups first, then unabsorbed raw levels
        evidence = await db.get_youtube_evidence_for_ticker(ticker, days=7)
        level_data = []
        for ev in evidence:
            if ev.get("evidence_type") == "setup":
                price = ev.get("entry_low") or ev.get("entry_high")
                level_type = f"setup:{ev.get('setup_type', 'unknown')}"
                conf = 0.85
            else:
                price = ev.get("price")
                level_type = ev.get("level_type")
                conf = ev.get("confidence", 0.8)
            if price is not None:
                level_data.append({"type": level_type, "price": price, "confidence": conf})

        # Determine score boost
        conv_map = {"high": 15, "medium": 10, "low": 5}
        score_boost = conv_map.get(top_conviction, 10)

        # --- Wave 4 flag-gated YouTube-score smarts (all default OFF) ---
        # The unsigned, undecayed, unscaled `score_boost` above is today's
        # behavior. Each block below is a multiplier/sign applied ONLY when its
        # flag is ON, so with every flag OFF `score_boost` is byte-identical.

        # Capture the unsigned legacy boost for the I1 signed-vs-unsigned shadow
        # log (always positive here; the flag blocks below may sign/scale it).
        unsigned_boost = score_boost

        # #9 direction-aware (flag features.youtube_score.direction_aware):
        # sign the boost by the 7-day consensus direction so a bearish YouTube
        # consensus lowers the score instead of raising it. short -> negative,
        # long -> positive, neutral -> KEEP today's positive (do NOT zero —
        # zeroing could silently suppress range-bound-ticker alerts).
        #
        # I1 Pass-3 safeguards (apply ONLY on the bearish/short branch):
        #   (1) min-2-trusted-channel FLOOR before any bearish subtraction —
        #       below the floor the boost becomes 0, NEVER a positive add (do
        #       NOT re-introduce the wrong-sign bug);
        #   (2) a channel's trust counts toward the floor only if it has
        #       channel-age AND >= min_channel_graded_n graded outcomes
        #       (_count_trusted_channels);
        #   (3) cap the bearish (negative) magnitude at bearish_cap (-8) while
        #       bullish stays up to +15.
        if cfg.get("features.youtube_score.direction_aware", False):
            if consensus_dir == "short":
                min_trusted = int(cfg.get("features.youtube_score.min_trusted_channels", 2))
                min_graded_n = int(cfg.get("features.youtube_score.min_channel_graded_n", 10))
                bearish_cap = int(cfg.get("features.youtube_score.bearish_cap", 8))
                n_trusted = _count_trusted_channels(primary_mentions, min_graded_n)
                if n_trusted < min_trusted:
                    # Below the floor: NO bearish subtraction (would be unsafe),
                    # and NEVER the legacy positive add (would be the bug). 0.
                    score_boost = 0
                else:
                    # Bearish subtraction allowed; cap the negative magnitude
                    # below the bullish ceiling (+15).
                    score_boost = -min(abs(score_boost), bearish_cap)

        # #10 recency decay (flag features.youtube_score.recency_decay):
        # multiply by 0.5 ** (age_days / half_life) off the FRESHEST contributing
        # mention, floored at recency_floor. Older consensus = smaller boost.
        #
        # I1 safeguard (4): a null/missing `extracted_at` is treated as STALE —
        # never fresh. If ANY contributing mention lacks a timestamp, or if NO
        # mention carries one at all, the freshness is unknown, so the boost is
        # down-weighted to the stale floor (`recency_floor`) instead of being
        # left at full strength. The `half_life > 0` check guards the divide.
        if cfg.get("features.youtube_score.recency_decay", False):
            half_life = float(cfg.get("features.youtube_score.recency_half_life_days", 3))
            floor = float(cfg.get("features.youtube_score.recency_floor", 0.3))
            extracted_times = [m.get("extracted_at") for m in primary_mentions if m.get("extracted_at") is not None]
            any_missing = any(m.get("extracted_at") is None for m in primary_mentions)
            if half_life > 0:
                if not extracted_times:
                    # No timestamps at all -> stale -> down-weight to the floor.
                    score_boost = score_boost * floor
                else:
                    freshest = max(extracted_times)
                    age_days = max(0.0, (time.time() - float(freshest)) / 86400.0)
                    decay = max(floor, 0.5 ** (age_days / half_life))
                    if any_missing:
                        # At least one stale (null-timestamp) leg -> cannot treat
                        # the consensus as fresh; never exceed the stale floor.
                        decay = min(decay, floor)
                    score_boost = score_boost * decay

        # #11 channel-reliability (flag features.youtube_score.channel_reliability):
        # scale by the MAX trust_score among contributing mentions, clamped to
        # [trust_floor, 1.0]. NULL trust (unregistered channel) bootstraps to 0.5
        # (mirrors levels.py:210). All 14 registered channels are trust=1.0 today,
        # so this is a no-op multiplier on current data.
        if cfg.get("features.youtube_score.channel_reliability", False):
            trust_floor = float(cfg.get("features.youtube_score.trust_floor", 0.3))
            trust_values = [
                (float(m["trust_score"]) if m.get("trust_score") is not None else 0.5)
                for m in primary_mentions
            ]
            if trust_values:
                trust = max(min(max(trust_values), 1.0), trust_floor)
                score_boost = score_boost * trust

        # Build deduplicated video list (order from query: extracted_at DESC)
        max_videos = cfg.get("all_command.youtube_links.max_videos", 3)
        seen_video_ids: set[str] = set()
        videos: list[dict] = []
        for m in primary_mentions:
            vid = m.get("video_id")
            if vid and vid not in seen_video_ids:
                seen_video_ids.add(vid)
                videos.append({
                    "video_id": vid,
                    "title": m.get("video_title"),
                    "channel_name": m.get("channel_name"),
                })
                if len(videos) >= max_videos:
                    break

        # score_boost is `int` on YouTubeContext and feeds breakdown.youtube (int).
        # When all Wave 4 flags are OFF it is still the original int (no block ran),
        # so int(round(...)) is byte-identical; when a flag is ON it collapses the
        # decay/trust float back to an int so total math has no float drift.
        score_boost = int(round(score_boost))

        # I1 shadow log — signed-vs-unsigned youtube_pts. Only emitted when the
        # signing flag is ON (off -> signed == unsigned, nothing to compare).
        if cfg.get("features.youtube_score.direction_aware", False):
            log.info(
                "[I1 shadow] $%s youtube_pts signed=%d unsigned=%d (dir=%s)",
                ticker, score_boost, int(round(unsigned_boost)), consensus_dir,
            )

        return YouTubeContext(
            mention_count=len(primary_mentions),
            direction=Direction(consensus_dir),
            top_conviction=Conviction(top_conviction),
            channels=list(set(m.get("channel_name") for m in primary_mentions if m.get("channel_name"))),
            levels=level_data,
            score_boost=score_boost,
            videos=videos,
        )
    except Exception as e:
        log.debug("YouTube context error for $%s: %s", ticker, e)
        return None


async def score_ticker(
    ticker: str,
    *,
    base_score: int = 0,
    direction: str = "long",
    exclude_analyst: str = "",
    executor=None,
) -> ScoreTickerResult:
    """Run the parallel-gather + ScoreBreakdown assembly for a ticker.

    Tweetless pure scorer — does NOT consult the xref cache. Callers
    (`cross_reference()`, `!all` command) decide their own caching strategy.
    """
    log.info("Starting score_ticker for $%s (base=%d)", ticker, base_score)
    m = cfg.get("scoring.multipliers", {})

    metrics: dict[str, int] = {}
    catalyst, (sec_hit, sec_summary), social_data, technical, analyst_groups, options, youtube = \
        await asyncio.gather(
            _with_timeout(_timed(_run_news_cascade(ticker), metrics, "news_cascade_ms"), 15.0, None, "news", sem=_sem_news),
            _with_timeout(_timed(_run_sec_check(ticker), metrics, "sec_check_ms"), 10.0, (False, ""), "sec", sem=_sem_news),
            _with_timeout(_timed(_run_social_check(ticker), metrics, "social_ms"), 5.0, {}, "social", sem=_sem_social),
            _with_timeout(_timed(_run_technical(ticker, direction=direction), metrics, "technical_ms"), 20.0, None, "technical", sem=_sem_technical),
            _with_timeout(_timed(_run_other_analysts(ticker, direction, exclude_analyst=exclude_analyst), metrics, "analyst_check_ms"), 5.0, {"aligned": [], "opposing": []}, "analysts"),
            _with_timeout(_timed(_run_options_check(ticker, executor), metrics, "options_check_ms"), 15.0, None, "options", sem=_sem_technical),
            _with_timeout(_timed(_get_youtube_context(ticker), metrics, "youtube_ms"), 8.0, None, "youtube"),
        )

    from types import SimpleNamespace
    inputs = SimpleNamespace(catalyst=catalyst, sec_hit=sec_hit, sec_summary=sec_summary,
                             social_data=social_data, technical=technical,
                             analyst_groups=analyst_groups, options=options, youtube=youtube)
    calculation = _research.score_calculation(
        ticker, inputs, base_score=base_score, direction=direction,
        settings=cfg, now=time.time(),
    )
    response = None
    pending_error = None
    while True:
        try:
            request = calculation.throw(pending_error) if pending_error else calculation.send(response)
        except StopIteration as finished:
            result = finished.value
            result.metrics = metrics
            return result
        pending_error = None
        try:
            response = await _collect_score_request(
                request, ticker, catalyst, technical, sec_summary, metrics, executor)
        except Exception as exc:
            # Preserve the generator's original local FINRA/PEAD exception gates.
            pending_error = exc


async def _collect_score_request(request, ticker, catalyst, technical, sec_summary, metrics, executor):
    if request.kind == "precision":
        return await db.get_analyst_precision_lb(request.arguments[0], min_n=request.arguments[1])
    if request.kind == "sec_graduation":
        from consensus_engine.scanners.sec_form4_cluster import _MIN_PURCHASE_DOLLARS
        return await _run_sec_graduation(ticker), _MIN_PURCHASE_DOLLARS
    if request.kind == "llm_score":
        t0 = time.perf_counter()
        response = (0.0, "")
        try:
            async with _sem_llm:
                response = await asyncio.wait_for(
                    _run_llm_score(ticker, catalyst, technical, sec_summary), timeout=15.0)
        except asyncio.TimeoutError:
            log.warning("LLM scorer timed out after 15s for $%s", ticker)
        metrics["llm_score_ms"] = int((time.perf_counter() - t0) * 1000)
        return response
    if request.kind == "consolidation":
        from consensus_engine.analysis.consolidation import consolidate_for_ticker, ConsolidationResult
        try:
            return await consolidate_for_ticker(ticker, window_minutes=15, shadow_only=request.arguments[0])
        except Exception as exc:
            log.warning("[A3] consolidate_for_ticker failed for $%s: %s", ticker, exc)
            return ConsolidationResult(False, None, 0, 0.0, 0, [], "disabled")
    if request.kind == "burst":
        return await _fetch_analyst_signals_for_burst(ticker, window_sec=request.arguments[0])
    if request.kind == "finra_volume":
        return await db.get_latest_finra_short_volume(ticker)
    if request.kind == "finra_baseline":
        return await db.get_finra_short_volume_baseline(ticker)
    if request.kind == "short_interest":
        return await db.get_latest_finra_short_interest(ticker)
    if request.kind == "pead":
        from consensus_engine.analysis import pead
        return await pead.compute_pead(
            ticker,
            min_days_after=int(cfg.get("features.pead.min_days_after", 5)),
            max_days_after=int(cfg.get("features.pead.max_days_after", 45)),
            min_surprise_pct=float(cfg.get("features.pead.min_surprise_pct", 2.0)),
            faded_threshold_pct=float(cfg.get("features.pead.faded_threshold_pct", 2.0)),
            executor=executor)
    raise ValueError("Unknown score data request")


def _build_social_summary(social_data: dict, youtube: Optional[YouTubeContext]) -> str:
    """Build the human-readable social + youtube summary string."""
    from consensus_engine.alerts._markdown import _escape_md_link_text

    social_parts = []
    if social_data.get("apewisdom", 0) >= 1:
        social_parts.append(f"ApeWisdom ({social_data['apewisdom']} mentions)")
    if social_data.get("stocktwits", 0) >= 1:
        social_parts.append("StockTwits trending")
    if social_data.get("reddit", 0) >= 2:
        social_parts.append(f"Reddit ({social_data['reddit']} mentions)")
    if social_data.get("google_trends", 0) >= 1:
        social_parts.append("Google Trends spike")

    youtube_parts = []
    if youtube:
        youtube_parts.append(f"YouTube ({youtube.mention_count} videos, {youtube.direction.value})")
        if youtube.levels:
            youtube_parts.append(f"Levels: {len(youtube.levels)} S/R zones")

    all_sources = social_parts + youtube_parts
    summary = ", ".join(all_sources) if all_sources else ""

    # Append clickable video links beneath the YouTube one-liner (Section 2P).
    if youtube and youtube.videos and cfg.get("all_command.youtube_links.enabled", True):
        title_max = cfg.get("all_command.youtube_links.title_max_chars", 80)
        max_videos = cfg.get("all_command.youtube_links.max_videos", 3)
        link_lines = []
        for v in youtube.videos[:max_videos]:
            url = f"https://www.youtube.com/watch?v={v['video_id']}"
            raw_title = v.get("title")
            if raw_title:
                escaped = _escape_md_link_text(raw_title)
                if len(escaped) > title_max:
                    escaped = escaped[:title_max] + "…"
                link_text = escaped
            else:
                channel = v.get("channel_name") or "Unknown"
                link_text = f"Video by {_escape_md_link_text(channel)}"
            link_lines.append(f"• [{link_text}]({url})")
        if link_lines:
            summary = summary + "\n" + "\n".join(link_lines)

    return summary


async def cross_reference(ticker: str, tweet: ParsedTweet, executor=None) -> CrossReferenceResult:
    """Run all cross-reference sources in parallel and compute final score.

    Thin wrapper over `score_ticker()` that adds tweet-specific decoration
    (catalyst URLs, social summary, resolved catalyst_type) and the xref
    cache layer.
    """
    direction = tweet.direction.value if hasattr(tweet.direction, 'value') else "long"

    bucket_seconds = int(cfg.get("measurement.batch1.score_cache_bucket_seconds", 300))
    # `!scan`/`!sweep` build a NEUTRAL fake tweet on purpose (the real direction is
    # decided later from the score breakdown) — build_score_cache_key's validator only
    # accepts long/short, so NEUTRAL crashed cross_reference() outright. The cache key
    # is a dedup key, not a real trade record, so any non-long/short direction is safe
    # to normalize to "long" here; `direction` itself (passed to score_ticker below)
    # is untouched, so real scoring behavior for NEUTRAL callers doesn't change.
    cache_key_direction = direction if direction in ("long", "short") else "long"
    cache_key = build_score_cache_key(
        ticker=ticker,
        direction=cache_key_direction,
        analyst=tweet.analyst,
        source="twitter",
        catalyst=getattr(tweet.tweet_type, "value", str(tweet.tweet_type)),
        base_score=tweet.base_score,
        rule_version=cfg.get("measurement.batch1.rule_version", "batch1-v1"),
        time_bucket=int(time.time() // bucket_seconds),
        input_fingerprint=getattr(tweet, "tweet_url", ""),
    )
    # A final score is reusable only for the exact same signed input situation.
    cached = await get_cached_xref(ticker, key_prefix=cache_key)
    if cached is not None:
        log.info("Cross-reference cache HIT for $%s", ticker)
        return cached

    score_result = await score_ticker(
        ticker,
        base_score=tweet.base_score,
        direction=direction,
        exclude_analyst=tweet.analyst,
        executor=executor,
    )

    catalyst = score_result.catalyst
    youtube = score_result.youtube
    youtube_pts = youtube.score_boost if youtube else 0

    sources_summary = _build_social_summary(score_result.social_data, youtube)

    resolved_catalyst_type = _resolve_catalyst_type(
        catalyst.catalyst_type if catalyst else "",
        sec_hit=score_result.sec_hit,
    )

    result = CrossReferenceResult(
        ticker=ticker,
        breakdown=score_result.breakdown,
        catalyst_summary=catalyst.catalyst_summary if catalyst else "",
        catalyst_type=resolved_catalyst_type,
        catalyst_sources=catalyst.news_sources if catalyst else [],
        catalyst_urls=catalyst.source_urls if catalyst else [],
        catalyst_body=catalyst.catalyst_body if catalyst else "",
        technical=score_result.technical,
        other_analysts=score_result.other_analysts,
        social_summary=sources_summary,  # Include YouTube in summary
        sec_summary=score_result.sec_summary,
        llm_reasoning=score_result.llm_reasoning,
        options=score_result.options,
        consolidation_result=score_result.consolidation_result,
        # I3: propagate the produced contradiction_index to the consumer
        # (engine._classify penalty + main.py A1 post-process use this field)
        contradiction_index=score_result.contradiction_index,
        n_opposing=score_result.n_opposing,
    )

    log.info("Cross-reference for $%s: score=%d (base=%d + xref=%d, youtube=%d)",
             ticker, result.final_score, tweet.base_score,
             result.final_score - tweet.base_score, youtube_pts)

    await cache_xref(ticker, result, key_prefix=cache_key)

    # Record per-component latency metrics
    for metric_key, ms_value in score_result.metrics.items():
        await db.record_metric(f"xref_{metric_key}", ms_value)

    # Always-on signal_events read so tweet rows (routed via insert_signal) reach a consumer.
    try:
        signal_events = await db.get_signal_events_for_ticker(ticker, window_seconds=3600)
        log.debug("cross_reference $%s: signal_events in 1h window=%d", ticker, len(signal_events))
    except Exception as exc:  # pragma: no cover - defensive; DB read must never block scoring
        log.warning("cross_reference: signal_events read failed for $%s: %s", ticker, exc)

    return result
