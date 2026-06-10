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

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.models import (
    ParsedTweet, CrossReferenceResult, ScoreBreakdown,
    CatalystResult, TechnicalResult, OptionsResult, YouTubeContext,
)
from consensus_engine.scanners.news import news_cascade
from consensus_engine.analysis.technical import verify_technical
from consensus_engine.analysis.llm_scorer import score_confidence


@dataclass
class ScoreTickerResult:
    """Tweetless scoring result wrapping the parallel-gather + ScoreBreakdown.

    Returned by `score_ticker()`; `cross_reference()` decorates this into a
    `CrossReferenceResult` with tweet-specific fields.
    """
    ticker: str
    breakdown: ScoreBreakdown
    catalyst: Optional[CatalystResult] = None
    technical: Optional[TechnicalResult] = None
    options: Optional[OptionsResult] = None
    youtube: Optional[YouTubeContext] = None
    social_data: dict = field(default_factory=dict)
    sec_hit: bool = False
    sec_summary: str = ""
    other_analysts: list = field(default_factory=list)
    llm_reasoning: str = ""
    consolidation_result: Optional[object] = None
    metrics: dict = field(default_factory=dict)
    # I3 producer (signal-features-2026-06-09): 0=unanimous, 1=perfectly split.
    # Computed in score_ticker; 0.0 until features.contradiction_index_live.enabled.
    contradiction_index: float = 0.0

    @property
    def final_score(self) -> int:
        return self.breakdown.total

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
    """Compute score from technical filters. +2 per passing filter, max 12."""
    if not technical or not technical.filters:
        return 0
    per_filter = cfg.get("scoring.multipliers.technical_per_filter", 2)
    max_pts = cfg.get("scoring.multipliers.technical_max", 12)
    return min(technical.passed_count * per_filter, max_pts)


def compute_social_score(social_data: dict[str, int]) -> int:
    """Compute social cross-reference score from platform signal counts."""
    score = 0
    m = cfg.get("scoring.multipliers", {})
    if social_data.get("apewisdom", 0) >= 1:
        score += m.get("social_apewisdom", 10)
    if social_data.get("stocktwits", 0) >= 1:
        score += m.get("social_stocktwits", 10)
    if social_data.get("reddit", 0) >= 2:
        score += m.get("social_reddit", 10)
    if social_data.get("google_trends", 0) >= 1:
        score += m.get("google_trends", 5)
    return score


def _compute_social_breakdown(social_data: dict[str, int]) -> dict[str, int]:
    """Return per-source social points for the ScoreBreakdown."""
    m = cfg.get("scoring.multipliers", {})
    return {
        "social_apewisdom": m.get("social_apewisdom", 10) if social_data.get("apewisdom", 0) >= 1 else 0,
        "social_stocktwits": m.get("social_stocktwits", 10) if social_data.get("stocktwits", 0) >= 1 else 0,
        "social_reddit": m.get("social_reddit", 10) if social_data.get("reddit", 0) >= 2 else 0,
        "google_trends": m.get("google_trends", 5) if social_data.get("google_trends", 0) >= 1 else 0,
    }


def _get_catalyst_score(catalyst_type: str) -> int:
    """Look up tiered score for a catalyst type. Defaults to medium (15)."""
    tiers = cfg.get("scoring.catalyst_tiers", {})
    for tier_data in tiers.values():
        if catalyst_type in tier_data.get("types", []):
            return tier_data.get("score", 15)
    return tiers.get("medium", {}).get("score", 15)


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
    """Render named-insider lines for the SEC summary, reusing the
    `commands._sec_and_reply` emoji house style (🟢/🔴 + role + buy/sell + size).

    `fetched` is a list of transaction lists (one per Form-4 filing). Open-market
    purchases/sales are shown per insider, top-N by dollar value, CEO/CFO
    highlighted; routine awards / option exercises / tax withholding are
    collapsed to a count. The whole block is capped under one embed field.
    Returns "" when there is nothing to show.
    """
    from consensus_engine.scanners.sec_edgar import _OPEN_MARKET_TX_TYPES
    from consensus_engine.alerts.commands import _fmt_insider_name

    all_txs = [t for txs in fetched for t in (txs or [])]
    if not all_txs:
        return ""
    open_market = [t for t in all_txs
                   if t.get("transaction_type") in _OPEN_MARKET_TX_TYPES]
    routine_count = len(all_txs) - len(open_market)
    if not open_market:
        return f"Form 4 detail: {routine_count} routine award/exercise(s) only."

    def _dollar(t) -> float:
        try:
            return float(t.get("shares") or 0) * float(t.get("price") or 0)
        except (TypeError, ValueError):
            return 0.0

    ranked = sorted(open_market, key=_dollar, reverse=True)
    header = "Form 4 insiders:"
    lines: list[str] = []
    shown = 0
    for t in ranked:
        name = _fmt_insider_name(str(t.get("reporter_name") or "Unknown"))
        title = str(t.get("title") or "Insider")
        direction = t.get("direction")
        verb = "bought" if direction == "Buy" else "sold" if direction == "Sell" else "traded"
        icon = "🟢" if direction == "Buy" else "🔴" if direction == "Sell" else "⚪"
        try:
            shares = float(t.get("shares") or 0)
        except (TypeError, ValueError):
            shares = 0.0
        value = _dollar(t)
        star = "⭐ " if any(r in title.upper() for r in ("CEO", "CFO")) else ""
        dollar_str = f" (~${value:,.0f})" if value else ""
        line = (f"{icon} {star}{name} ({title}) {verb} "
                f"{shares:,.0f} sh{dollar_str}")
        tail_more = len(ranked) - shown - 1
        tail = (f"\n  plus {tail_more} more insider(s)") if tail_more > 0 else ""
        candidate = header + "\n" + "\n".join(lines + [line]) + tail
        if len(candidate) > _NAMED_INSIDER_FIELD_CAP and lines:
            break
        lines.append(line)
        shown += 1

    block = header + "\n" + "\n".join(lines)
    remaining = len(open_market) - shown
    if remaining > 0:
        block += f"\n  plus {remaining} more insider(s)"
    if routine_count:
        block += f"\n  (+{routine_count} routine award/exercise(s))"
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
        log.debug("SEC check error for %s: %s", ticker, e)
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


@dataclass
class _SecGraduation:
    """Parsed Form-4 facts the I5 graduation tier needs. Defaults = no signal."""
    has_form4: bool = False
    max_buy_dollars: float = 0.0      # largest single-insider open-market BUY ($)
    reporter_role: str = "other"      # canonicalized role of the top buyer
    is_planned: bool = False          # 10b5-1 / pre-arranged plan footnote present
    plan_flag_seen: bool = False      # a footnote was parseable for the top buy
    txn_date: str = ""                # transaction date of the top buy (YYYY-MM-DD)
    net_selling: bool = False         # open-market sells present with no qualifying buy


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
    """True if the transaction date is within recency_days of now (UTC).

    SEC Form-4 transactionDate is always `YYYY-MM-DD`. An empty or unparseable
    date counts as NOT recent (stale -> no graduation), so an already-priced old
    buy can't inflate a fresh alert.
    """
    if not txn_date:
        return False
    from datetime import datetime, timezone, timedelta
    try:
        dt = datetime.strptime(txn_date[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - dt) <= timedelta(days=recency_days)


def _graduate_sec_pts(grad: _SecGraduation, flat_pts: int) -> int:
    """Compute the I5 graduated SEC points from parsed Form-4 facts.

    Tiers (all additive, never negative):
      +base_pts (8)  any Form-4 present (the floor)
      +large_buy_pts (15)  open-market BUY > _MIN_PURCHASE_DOLLARS ($250k)
      +csuite_pts (20)  the same large buy by a canonical C-suite role

    Safeguards:
      - plan flag ABSENT (footnote not parseable) -> cap at +8 (no +20 tier).
      - 10b5-1 / planned buy -> cap at +8 (a pre-arranged trade is not a signal).
      - net selling -> withhold the buy credit (stays at +8), NEVER subtract.
      - stale transaction date (recency gate applied by caller) -> already
        downgraded to a non-large grad before this call.
      - unknown role -> 'other' -> +15 max, never +20.
    """
    if not grad.has_form4:
        return 0
    base = int(cfg.get("features.sec_graduated_scoring.base_pts", 8))
    large = int(cfg.get("features.sec_graduated_scoring.large_buy_pts", 15))
    csuite = int(cfg.get("features.sec_graduated_scoring.csuite_pts", 20))

    from consensus_engine.scanners.sec_form4_cluster import _MIN_PURCHASE_DOLLARS

    qualifying_buy = (
        grad.max_buy_dollars > _MIN_PURCHASE_DOLLARS
        and not grad.net_selling
    )
    # Plan-flag safeguard: a planned (10b5-1) buy, OR a buy whose footnote we
    # could not parse at all, cannot earn above the +8 floor.
    plan_clean = grad.plan_flag_seen and not grad.is_planned
    if not qualifying_buy or not plan_clean:
        return base
    if grad.reporter_role == "csuite":
        return csuite
    return large


def _earnings_magnitude_bonus(catalyst: "CatalystResult") -> int:
    """I12: magnitude bonus added ON TOP of the base catalyst tier.

    A +40% blowout beat and an in-line print currently score the same catalyst
    tier. This adds `+per_10pct (5) per 10% surprise, capped at cap (+15)` when
    the catalyst is a FRESH earnings print carrying a numeric surprise %.

    Safeguards (all mandatory, additive only — never subtracts):
      - absolute-$ surprise floor: |eps_surprise_pct| must exceed `min_abs_eps`
        (default 0.02 => 2%). A near-zero surprise earns 0.
      - sane-denominator guard: `eps_estimate` must be a non-trivial denominator
        (>= min_abs_eps in absolute terms). A $0.01 beat on a $0.001 estimate
        cannot manufacture a +900%-style bonus.
      - cap: the bonus is clamped to `cap` (default +15).
      - freshness gate: the recap's quarter `eps_period` must be within
        `recency_days` (default 5) of now; a stale recap earns 0 so an
        already-priced old print can't inflate a fresh alert.
      - missing/None surprise % -> 0 (base tier only).
    """
    if not catalyst:
        return 0
    surprise = catalyst.eps_surprise_pct
    estimate = catalyst.eps_estimate
    if surprise is None:
        return 0
    min_abs_eps = float(cfg.get("features.earnings_magnitude.min_abs_eps", 0.02))
    # sane-denominator guard: need a real estimate to trust the % surprise.
    if estimate is None or abs(estimate) < min_abs_eps:
        return 0
    # absolute-magnitude floor: a near-zero surprise % earns nothing.
    if abs(surprise) <= min_abs_eps:
        return 0
    # freshness gate: only a recent post-print recap may add the bonus.
    recency_days = int(cfg.get("features.earnings_magnitude.recency_days", 5))
    if not _is_txn_recent(catalyst.eps_period, recency_days):
        return 0
    per_10pct = int(cfg.get("features.earnings_magnitude.per_10pct", 5))
    cap = int(cfg.get("features.earnings_magnitude.cap", 15))
    bonus = int(abs(surprise) / 10.0 * per_10pct)
    return min(bonus, cap)


def _graduate_options_pts(options: "OptionsResult", direction: str) -> int:
    """I6: graduate options_pts by premium ALIGNED with the tweet direction.

    Returns (SAME-DIRECTION confluence only):
      +10  a >$250k single-strike dominant-side premium ALIGNED with `direction`
           (long<->call, short<->put)
      +6   aligned dominant side but premium <= $250k (the small-flow nudge)
      0    opposing OR ambiguous dominant side, OR a stale snapshot

    Safeguards (E4 — all mandatory):
      - the opposing/negative branch is DROPPED entirely: an OPPOSING dominant
        side (e.g. a put-wall on a long) contributes 0, NEVER a negative sign —
        public single-leg side inference is the refuted Pan-Poteshman fallacy.
      - an AMBIGUOUS dominant side ("" — call/put premium tie or no unusual
        contract) contributes 0, never a sign.
      - stale / after-hours snapshot (dominant last trade older than the #18
        watcher's max_staleness_min, or no timestamp) -> 0.
      - magnitude-capped low: the return is at most aligned_pts (default +10);
        this term is a confluence nudge, never solo-STRONG.
    """
    unusual = int(cfg.get("features.options_graduated_scoring.unusual_pts", 6))
    aligned = int(cfg.get("features.options_graduated_scoring.aligned_pts", 10))
    large_premium = float(cfg.get("options_flow.min_premium_usd", 250_000.0))
    max_staleness_min = int(cfg.get("options_flow.max_staleness_min", 60))

    # Staleness gate: reuse the #18 watcher cap. A snapshot whose dominant
    # contract last traded outside the window (e.g. a prior-session / after-hours
    # print) contributes 0. No timestamp at all -> treat as stale -> 0.
    if max_staleness_min:
        ts = options.dominant_last_trade_ts
        if not ts or (time.time() - ts) > max_staleness_min * 60:
            return 0

    # Alignment: long pairs with call flow, short pairs with put flow. An
    # opposing or ambiguous ("") dominant side is NOT a confluence signal -> 0.
    aligned_side = "call" if direction == "long" else "put" if direction == "short" else ""
    if aligned_side == "" or options.dominant_side != aligned_side:
        return 0
    pts = aligned if options.premium_notional > large_premium else unusual
    return min(pts, aligned)  # magnitude cap (never above the aligned ceiling)


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
    """Cheap normalised word-set for Jaccard similarity (no LLM)."""
    return frozenset(re.sub(r"[^a-z0-9$#]", " ", text.lower()).split())


def _jaccard(a: frozenset, b: frozenset) -> float:
    """Jaccard similarity of two word-sets."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union > 0 else 0.0


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


@dataclass
class _BurstAnalysis:
    """Result of E6 manufactured-agreement scan over analyst signal texts."""
    burst_detected: bool = False
    burst_actor_ids: frozenset = field(default_factory=frozenset)
    has_independent_corroboration: bool = False
    # True when burst detected AND no independent corroboration yet.
    boost_gated: bool = False


def _analyse_burst(
    signal_rows: list[dict],
    *,
    similarity_threshold: float = _E6_SIMILARITY_DEFAULT,
    burst_window_sec: float = _E6_BURST_WINDOW_SEC_DEFAULT,
    min_accounts: int = _E6_MIN_ACCOUNTS_DEFAULT,
) -> tuple[bool, frozenset]:
    """Scan signal_rows for a near-simultaneous near-duplicate wording burst.

    Algorithm (cheap — no LLM):
      1. Filter rows with usable text + timestamp + account id.
      2. Sort by detected_at.
      3. For every pair within burst_window_sec, compute word-set Jaccard.
      4. Collect involved accounts into a burst cluster.
      5. A burst requires >= min_accounts distinct accounts.

    Returns (burst_detected, frozenset_of_burst_account_ids).
    """
    if len(signal_rows) < min_accounts:
        return False, frozenset()

    valid = [
        r for r in signal_rows
        if r.get("raw_text") and r.get("detected_at") and r.get("source_detail")
    ]
    if len(valid) < min_accounts:
        return False, frozenset()

    valid.sort(key=lambda r: float(r["detected_at"]))
    word_sets = [_word_set(str(r["raw_text"])) for r in valid]

    burst_accounts: set[str] = set()
    n = len(valid)
    for i in range(n):
        for j in range(i + 1, n):
            if float(valid[j]["detected_at"]) - float(valid[i]["detected_at"]) > burst_window_sec:
                break  # sorted: all further j are outside the window
            if _jaccard(word_sets[i], word_sets[j]) >= similarity_threshold:
                burst_accounts.add(str(valid[i]["source_detail"]))
                burst_accounts.add(str(valid[j]["source_detail"]))

    if len(burst_accounts) < min_accounts:
        return False, frozenset()
    return True, frozenset(burst_accounts)


def _check_e6_corroboration(
    burst_detected: bool,
    *,
    sec_hit: bool,
    catalyst_passed: bool,
    options_has_activity: bool,
) -> bool:
    """True when an independent non-burst source corroborates.

    Independent sources: SEC filing, hard news catalyst, or options activity.
    Any one of these lifts the E6 gate (they are actor-independent from the
    Twitter/analyst channel).
    """
    if not burst_detected:
        return True  # no gate needed
    return sec_hit or catalyst_passed or options_has_activity


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
    """Compute contradiction_index in [0,1] from SIGNED sources only.

    Logic: index = min(opposing_weight, supporting_weight) / total_weight

    Signed sources (only when they carry a clear direction):
      - analyst cluster (tweet trigger + other_analysts): always SUPPORTING
        (they cited the same ticker; analyst_pts > 0 means they contributed)
      - youtube consensus_dir: SUPPORTING when matches tweet_direction,
        OPPOSING when opposite; NEUTRAL -> no sign -> no contribution
      - options dominant_side: SUPPORTING (call=long, put=short match) or
        OPPOSING; ambiguous ("") -> no contribution (I6 safeguard preserved)
      - SEC: SUPPORTING when sec_pts > 0 + tweet is long (a buy confirms
        bullish); OPPOSING when tweet is short + sec is a buy signal

    Actor-identity (I3 safeguard — distinct independent actors):
      - analyst cluster = ONE actor ("analyst")
      - youtube = ONE actor ("youtube")
      - options = ONE actor ("options")
      - SEC = ONE actor ("sec")

    E6 reconciliation: burst accounts already collapsed to one actor by the
    time I3 runs (E6 runs first and burst_analysis carries the collapsed set).

    Safeguards:
      - <2 fresh signed legs -> index 0 (no fabricated split)
      - NaN/empty -> 0; abs-magnitude math; clamp [0,1]
      - stale legs excluded via recency_window filter_fresh
      - 0-pts contribution is unsigned -> no leg added
    """
    from consensus_engine.analysis.recency_window import SourceLeg, filter_fresh
    import datetime as _dt

    now = _dt.datetime.now(_dt.timezone.utc)
    tweet_dir = tweet_direction.lower()
    supporting_options_side = "call" if tweet_dir == "long" else "put" if tweet_dir == "short" else ""

    legs: list[SourceLeg] = []

    # Analyst cluster: always supporting (they corroborate the alert direction)
    if analyst_pts > 0:
        legs.append(SourceLeg(
            source="tweet",
            as_of=now,
            weight=float(analyst_pts),
            direction="supporting",
            actor="analyst",
        ))

    # YouTube: only contributes a sign when direction is not neutral
    if youtube is not None and youtube_pts != 0:
        yt_dir = youtube.direction.value if hasattr(youtube.direction, "value") else str(youtube.direction)
        if yt_dir != "neutral" and yt_dir != "":
            yt_sign = "supporting" if yt_dir == tweet_dir else "opposing"
            legs.append(SourceLeg(
                source="youtube",
                as_of=now,
                weight=float(abs(youtube_pts)),
                direction=yt_sign,
                actor="youtube",
            ))

    # Options: only when dominant_side is unambiguous (I6 / E4 safeguard)
    if options is not None and options_pts != 0 and supporting_options_side != "":
        dominant = options.dominant_side
        if dominant in ("call", "put"):
            opt_sign = "supporting" if dominant == supporting_options_side else "opposing"
            legs.append(SourceLeg(
                source="options",
                as_of=now,
                weight=float(abs(options_pts)),
                direction=opt_sign,
                actor="options",
            ))

    # SEC: sec_pts > 0 = a buy signal; supporting on long, opposing on short
    if sec_hit and sec_pts > 0 and tweet_dir in ("long", "short"):
        sec_sign = "supporting" if tweet_dir == "long" else "opposing"
        legs.append(SourceLeg(
            source="sec",
            as_of=now,
            weight=float(sec_pts),
            direction=sec_sign,
            actor="sec",
        ))

    # Recency filter: drop any leg outside its source's freshness cap
    fresh_legs = filter_fresh(legs, now=now)

    # Require >= 2 signed sources to compute a meaningful index
    if len(fresh_legs) < 2:
        return 0.0

    supporting_weight = sum(leg.weight for leg in fresh_legs if leg.direction == "supporting")
    opposing_weight = sum(leg.weight for leg in fresh_legs if leg.direction == "opposing")
    total_weight = supporting_weight + opposing_weight

    if total_weight <= 0.0:
        return 0.0

    raw_index = min(opposing_weight, supporting_weight) / total_weight
    return max(0.0, min(1.0, raw_index))


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
    """Count DISTINCT opposing actors (for the I3 downgrade-gate check).

    An index >= downgrade_threshold requires >= min_actors distinct opposing
    actors. A single injected source should not solo-trigger a downgrade.
    Burst accounts (E6) already collapsed to one actor.
    """
    tweet_dir = tweet_direction.lower()
    supporting_options_side = "call" if tweet_dir == "long" else "put" if tweet_dir == "short" else ""
    opposing_actors: set[str] = set()

    if youtube is not None and youtube_pts != 0:
        yt_dir = youtube.direction.value if hasattr(youtube.direction, "value") else str(youtube.direction)
        if yt_dir not in ("neutral", "", tweet_dir):
            opposing_actors.add("youtube")

    if options is not None and options_pts != 0 and supporting_options_side != "":
        if options.dominant_side in ("call", "put") and options.dominant_side != supporting_options_side:
            opposing_actors.add("options")

    # SEC buy on a short-direction tweet = opposing actor
    if sec_hit and sec_pts > 0 and tweet_dir == "short":
        opposing_actors.add("sec")

    return len(opposing_actors)


async def _run_social_check(ticker: str) -> dict[str, int]:
    """Get social signal counts for a ticker from the database."""
    counts = await db.get_signal_counts_by_source(ticker)
    return {
        "apewisdom": counts.get("apewisdom", 0),
        "stocktwits": counts.get("stocktwits", 0),
        "reddit": counts.get("reddit", 0),
        "google_trends": counts.get("google_trends", 0),
    }


async def _run_technical(ticker: str, direction: str = "long") -> Optional[TechnicalResult]:
    return await verify_technical(ticker, direction=direction)


async def _run_other_analysts(ticker: str, exclude_analyst: str = "") -> list[str]:
    """Get other analysts who recently mentioned this ticker."""
    analysts = await db.get_recent_analysts_for_ticker(ticker, window_seconds=3600)
    return [a for a in analysts if a != exclude_analyst]


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
    catalyst, (sec_hit, sec_summary), social_data, technical, other_analysts, options, youtube = \
        await asyncio.gather(
            _with_timeout(_timed(_run_news_cascade(ticker), metrics, "news_cascade_ms"), 15.0, None, "news", sem=_sem_news),
            _with_timeout(_timed(_run_sec_check(ticker), metrics, "sec_check_ms"), 10.0, (False, ""), "sec", sem=_sem_news),
            _with_timeout(_timed(_run_social_check(ticker), metrics, "social_ms"), 5.0, {}, "social", sem=_sem_social),
            _with_timeout(_timed(_run_technical(ticker, direction=direction), metrics, "technical_ms"), 20.0, None, "technical", sem=_sem_technical),
            _with_timeout(_timed(_run_other_analysts(ticker, exclude_analyst=exclude_analyst), metrics, "analyst_check_ms"), 5.0, [], "analysts"),
            _with_timeout(_timed(_run_options_check(ticker, executor), metrics, "options_check_ms"), 15.0, None, "options", sem=_sem_technical),
            _with_timeout(_timed(_get_youtube_context(ticker), metrics, "youtube_ms"), 8.0, None, "youtube"),
        )

    # Cheap subtotals (no LLM) are computed BEFORE the LLM guard so the
    # flag-gated skip below can decide whether the LLM call could ever change
    # the alert outcome. (Reorder for #16 — math is unchanged.)
    max_analysts = cfg.get("scoring.multipliers.max_additional_analysts", 3)
    per_analyst = m.get("additional_analyst", 20)
    flat_analyst_pts = min(len(other_analysts), max_analysts) * per_analyst
    analyst_pts = flat_analyst_pts
    # I2 (signal-features-2026-06-09, flag OFF default): weight each contributing
    # analyst by track record. Flag OFF -> analyst_pts stays the flat
    # min(len,3)*20 above (byte-identical). With the flag on, sum 20*weight per
    # analyst where weight = clamp(2 * wilson_lb, discount_floor, weight_cap):
    # a Wilson lower-bound of 0.5 -> weight 1.0 (neutral 20); sample_count<min_n
    # (10) -> precision None -> neutral 20; a chronic loser floors at 0.5x.
    if cfg.get("features.analyst_accuracy_weight.enabled", False) and other_analysts:
        min_n = int(cfg.get("features.analyst_accuracy_weight.min_n", 10))
        discount_floor = float(cfg.get("features.analyst_accuracy_weight.discount_floor", 0.5))
        weight_cap = float(cfg.get("features.analyst_accuracy_weight.weight_cap", 1.5))
        weighted = 0.0
        for analyst in other_analysts[:max_analysts]:
            lb = await db.get_analyst_precision_lb(analyst, horizon="1h", min_n=min_n)
            if lb is None:
                weight = 1.0  # thin/absent record -> neutral 20
            else:
                weight = max(discount_floor, min(weight_cap, 2.0 * lb))
            weighted += per_analyst * weight
        # Per-call notional cap: banked accuracy can't be fully spent on one pump.
        # Cap the uplift above the flat baseline so a stack of high-track-record
        # analysts can't run away (default cap = one extra analyst-unit, 20).
        uplift_cap = float(cfg.get("features.analyst_accuracy_weight.uplift_cap", per_analyst))
        analyst_pts = int(round(min(weighted, flat_analyst_pts + uplift_cap)))
        log.info(
            "[I2 shadow] $%s analyst_pts weighted=%d flat=%d (n_analysts=%d)",
            ticker, analyst_pts, flat_analyst_pts, len(other_analysts),
        )
    news_pts = _get_catalyst_score(catalyst.catalyst_type) if (catalyst and catalyst.passed) else 0
    # I12 (signal-features-2026-06-09, flag OFF default): add a magnitude bonus
    # on TOP of the base catalyst tier for a FRESH earnings print carrying a
    # numeric surprise %. Flag OFF -> news_pts stays the base tier above
    # (byte-identical; this block never runs). With the flag on: +5 per 10%
    # surprise, cap +15, behind an absolute-$/denominator floor and a freshness
    # gate (a near-zero or $0.01/$0.001 beat, or a stale recap, adds 0).
    if (
        cfg.get("features.earnings_magnitude.enabled", False)
        and catalyst and catalyst.passed
        and catalyst.catalyst_type in ("Earnings Report", "Earnings Beat")
    ):
        magnitude_bonus = _earnings_magnitude_bonus(catalyst)
        if magnitude_bonus:
            news_pts += magnitude_bonus
            log.info(
                "[I12 shadow] $%s news_pts=%d (+%d magnitude on %s, surprise=%.1f%% est=%s period=%s)",
                ticker, news_pts, magnitude_bonus, catalyst.catalyst_type,
                catalyst.eps_surprise_pct, catalyst.eps_estimate, catalyst.eps_period,
            )
    sec_pts = m.get("sec_filing", 15) if sec_hit else 0
    # I5 (signal-features-2026-06-09, flag OFF default): graduate sec_pts by
    # insider role + open-market BUY $ instead of the flat +15. Flag OFF -> the
    # flat `m.get("sec_filing",15) if sec_hit else 0` above is byte-identical
    # (this block never runs). With the flag on: +8 any Form-4, +15 a >$250k
    # open-market buy, +20 a C-suite buy; plan-flag absent or 10b5-1 caps at +8;
    # net selling withholds the buy credit (never subtracts); a stale
    # transaction date (older than recency_days) is demoted to the +8 floor.
    if cfg.get("features.sec_graduated_scoring.enabled", False) and sec_hit:
        grad = await _run_sec_graduation(ticker)
        recency_days = int(cfg.get("features.sec_graduated_scoring.recency_days", 5))
        if grad.max_buy_dollars > 0 and not _is_txn_recent(grad.txn_date, recency_days):
            # Stale buy -> drop the large/csuite eligibility, keep the Form-4 floor.
            grad.max_buy_dollars = 0.0
        sec_pts = _graduate_sec_pts(grad, sec_pts)
        log.info(
            "[I5 shadow] $%s sec_pts graduated=%d (role=%s buy$=%.0f planned=%s "
            "plan_seen=%s net_sell=%s date=%s)",
            ticker, sec_pts, grad.reporter_role, grad.max_buy_dollars,
            grad.is_planned, grad.plan_flag_seen, grad.net_selling, grad.txn_date,
        )
    tech_pts = compute_technical_score(technical)
    social_breakdown = _compute_social_breakdown(social_data)

    llm_max = m.get("llm_boost_max", 15)

    options_pts = m.get("options_flow", 10) if (options and options.has_unusual_activity) else 0
    # I6 (signal-features-2026-06-09, flag OFF default): graduate options_pts by
    # premium ALIGNED with the tweet direction instead of the flat +10. Flag OFF
    # -> the flat `m.get("options_flow",10) if has_unusual else 0` above is
    # byte-identical (this block never runs). With the flag on:
    #   +6  any unusual activity (the confluence-nudge floor)
    #   +10 a >$250k single-strike premium whose dominant side is ALIGNED with
    #       the tweet direction (long<->call, short<->put)
    # SAFEGUARDS (E4): the opposing/negative branch is DROPPED entirely — an
    # ambiguous or opposing dominant side contributes 0, NEVER a negative sign
    # (public single-leg side inference is the refuted Pan-Poteshman fallacy);
    # the term is magnitude-capped low (max +10, a confluence nudge never a
    # solo-STRONG driver); a stale/after-hours snapshot (dominant last trade
    # older than the #18 watcher's max_staleness_min) contributes 0. The
    # contribution carries the intraday/1-2d horizon attribute (options.horizon).
    if (cfg.get("features.options_graduated_scoring.enabled", False)
            and options and options.has_unusual_activity):
        options_pts = _graduate_options_pts(options, direction)
        options.horizon = cfg.get("features.options_graduated_scoring.horizon", "1-2d")
        log.info(
            "[I6 shadow] $%s options_pts graduated=%d (dir=%s side=%s prem$=%.0f "
            "stale_ts=%.0f horizon=%s)",
            ticker, options_pts, direction, options.dominant_side,
            options.premium_notional, options.dominant_last_trade_ts, options.horizon,
        )

    youtube_pts = youtube.score_boost if youtube else 0

    # #12 level-confluence (flag features.youtube_score.level_confluence, default
    # OFF): award a small capped bonus to youtube_pts when a YouTube-cited level
    # price sits within confluence_band_pct of the technical price ±1 ATR band.
    # Signed to MATCH the boost direction (bearish YouTube boost is negative when
    # #9 is also on) so confluence never flips a bear into a bull. Flag OFF -> no
    # bonus -> byte-identical. Inside score_ticker the only technical anchor is
    # technical.price ± atr14 (no S/R list here) — an ATR-band proximity proxy.
    if cfg.get("features.youtube_score.level_confluence", False) and youtube and youtube_pts and technical:
        tech_price = getattr(technical, "price", 0.0) or 0.0
        atr = getattr(technical, "atr14", None)
        if tech_price > 0 and atr:
            band_pct = float(cfg.get("features.youtube_score.confluence_band_pct", 0.015))
            bonus_unit = int(cfg.get("features.youtube_score.confluence_bonus", 3))
            cap = int(cfg.get("features.youtube_score.confluence_cap", 6))
            tol = max(tech_price * band_pct, float(atr))
            hits = 0
            for lvl in (youtube.levels or []):
                lvl_price = lvl.get("price")
                if lvl_price is None:
                    continue
                if abs(float(lvl_price) - tech_price) <= tol:
                    hits += 1
            if hits:
                raw_bonus = min(hits * bonus_unit, cap)
                sign = 1 if youtube_pts >= 0 else -1
                youtube_pts += sign * raw_bonus

    llm_score, llm_reasoning = 0.0, ""
    # Decision-safe LLM skip (#16, flag-gated, default OFF): if even the maximum
    # possible LLM boost cannot push base + cheap subtotals up to the alert line
    # (medium_confidence), the LLM call cannot change the WATCHLIST/IGNORE
    # outcome, so skip it. Flag OFF → this is always False → byte-identical.
    skip_llm = False
    if cfg.get("scoring.skip_llm_below_threshold", False):
        cheap_subtotal = analyst_pts + news_pts + sec_pts + tech_pts + youtube_pts + options_pts
        medium_confidence = cfg.get("precision_engine.thresholds.medium_confidence", 65)
        if base_score + cheap_subtotal + llm_max < medium_confidence:
            skip_llm = True
            log.info("skipped LLM scorer (cannot reach threshold) for $%s", ticker)

    if (technical or catalyst) and not skip_llm:
        t0 = time.perf_counter()
        try:
            async with _sem_llm:
                llm_score, llm_reasoning = await asyncio.wait_for(
                    _run_llm_score(ticker, catalyst, technical, sec_summary), timeout=15.0
                )
        except asyncio.TimeoutError:
            log.warning("LLM scorer timed out after 15s for $%s", ticker)
        metrics["llm_score_ms"] = int((time.perf_counter() - t0) * 1000)

    llm_pts = int(llm_score / 100 * llm_max)

    # A3: Bayesian multi-source consolidation (always runs for shadow data)
    from consensus_engine.analysis.consolidation import consolidate_for_ticker
    shadow_only = not cfg.get("features.cross_source_consolidation.enabled", False)
    try:
        cons_result = await consolidate_for_ticker(ticker, window_minutes=15, shadow_only=shadow_only)
        consensus_boost = cons_result.consensus_boost if not shadow_only else 0
    except Exception as _cons_exc:
        log.warning("[A3] consolidate_for_ticker failed for $%s: %s", ticker, _cons_exc)
        from consensus_engine.analysis.consolidation import ConsolidationResult
        cons_result = ConsolidationResult(
            fired=False, consolidated_id=None, effective_n_clusters=0,
            combined_log_odds=0.0, consensus_boost=0, sources_seen=[], reason="disabled",
        )
        consensus_boost = 0

    breakdown = ScoreBreakdown(
        base=base_score,
        additional_analysts=analyst_pts,
        news_catalyst=news_pts,
        sec_filing=sec_pts,
        technical=tech_pts,
        llm_boost=llm_pts,
        options_flow=options_pts,
        consensus_boost=consensus_boost,
        **social_breakdown,
    )
    # YouTube boost as its own breakdown term (visible as `yt=N` in the footer).
    # Kept inside the total so the numeric score is unchanged vs. the old
    # llm_boost merge; see _BULLISH_BIASED_FIELDS for the direction-sum parity.
    breakdown.youtube = youtube_pts

    # -----------------------------------------------------------------
    # E6 — manufactured-agreement gate (signal-features-2026-06-09)
    # flag: features.manufactured_agreement_gate.enabled (default OFF)
    #
    # A near-duplicate analyst burst cannot ADD confluence points until
    # >= 1 independent non-burst source corroborates. Flag OFF -> byte-
    # identical (consensus_boost unchanged, burst_analysis stays None).
    # E6 runs BEFORE I3 so burst accounts collapse to one actor in I3.
    # -----------------------------------------------------------------
    burst_analysis: Optional[_BurstAnalysis] = None
    if cfg.get("features.manufactured_agreement_gate.enabled", False) and consensus_boost > 0:
        e6_window = int(cfg.get(
            "features.manufactured_agreement_gate.burst_window_sec",
            _E6_BURST_WINDOW_SEC_DEFAULT,
        ))
        e6_thresh = float(cfg.get(
            "features.manufactured_agreement_gate.similarity_threshold",
            _E6_SIMILARITY_DEFAULT,
        ))
        e6_min_accts = int(cfg.get(
            "features.manufactured_agreement_gate.min_accounts",
            _E6_MIN_ACCOUNTS_DEFAULT,
        ))
        signal_rows = await _fetch_analyst_signals_for_burst(ticker, window_sec=e6_window)
        burst_detected, burst_accounts = _analyse_burst(
            signal_rows,
            similarity_threshold=e6_thresh,
            burst_window_sec=float(e6_window),
            min_accounts=e6_min_accts,
        )
        has_corroboration = _check_e6_corroboration(
            burst_detected,
            sec_hit=sec_hit,
            catalyst_passed=bool(catalyst and catalyst.passed),
            options_has_activity=bool(options and options.has_unusual_activity),
        )
        boost_gated = burst_detected and not has_corroboration
        burst_analysis = _BurstAnalysis(
            burst_detected=burst_detected,
            burst_actor_ids=burst_accounts,
            has_independent_corroboration=has_corroboration,
            boost_gated=boost_gated,
        )
        if boost_gated:
            # Gate the crowd-agreement credit. Signals are NOT dropped.
            consensus_boost = 0
            breakdown.consensus_boost = 0
            log.info(
                "[E6] $%s burst detected (accounts=%d), consensus_boost gated "
                "(no independent corroboration)",
                ticker, len(burst_accounts),
            )
        elif burst_detected:
            log.info(
                "[E6] $%s burst detected (accounts=%d), boost KEPT "
                "(independent corroboration present)",
                ticker, len(burst_accounts),
            )

    # -----------------------------------------------------------------
    # I3 — contradiction_index PRODUCER (signal-features-2026-06-09)
    # flag: features.contradiction_index_live.enabled (default OFF)
    #
    # Computes the index from SIGNED sources already gathered above.
    # Always computes for the shadow log; writes onto result ONLY when
    # flag is ON (flag OFF -> result.contradiction_index stays 0.0 ->
    # consumer is a verbatim no-op -> existing tests unchanged).
    # E6 reconciliation: burst_analysis passed so burst accounts count
    # as one actor in the opposing-actor tally.
    # -----------------------------------------------------------------
    computed_ci = _compute_contradiction_index(
        tweet_direction=direction,
        analyst_pts=analyst_pts,
        other_analysts=other_analysts,
        options=options,
        options_pts=options_pts,
        youtube=youtube,
        youtube_pts=youtube_pts,
        sec_hit=sec_hit,
        sec_pts=sec_pts,
        burst_analysis=burst_analysis,
    )
    n_opposing = _count_opposing_actors(
        tweet_direction=direction,
        options=options,
        options_pts=options_pts,
        youtube=youtube,
        youtube_pts=youtube_pts,
        sec_hit=sec_hit,
        sec_pts=sec_pts,
        burst_analysis=burst_analysis,
    )
    # Count signed legs (rough proxy for shadow log)
    yt_dir_val = ""
    if youtube is not None:
        yt_dir_val = youtube.direction.value if hasattr(youtube.direction, "value") else str(youtube.direction)
    n_signed = sum([
        1 if analyst_pts > 0 else 0,
        1 if (youtube is not None and youtube_pts != 0 and yt_dir_val != "neutral") else 0,
        1 if (options is not None and options_pts != 0 and options.dominant_side in ("call", "put")) else 0,
        1 if (sec_hit and sec_pts > 0) else 0,
    ])

    if computed_ci > 0:
        log.info(
            "[I3 shadow] $%s contradiction_index=%.2f (opposing_actors=%d signed_sources=%d)",
            ticker, computed_ci, n_opposing, n_signed,
        )

    result_ci = computed_ci if cfg.get("features.contradiction_index_live.enabled", False) else 0.0

    return ScoreTickerResult(
        ticker=ticker,
        breakdown=breakdown,
        catalyst=catalyst,
        technical=technical,
        options=options,
        youtube=youtube,
        social_data=social_data,
        sec_hit=sec_hit,
        sec_summary=sec_summary,
        other_analysts=other_analysts,
        llm_reasoning=llm_reasoning,
        consolidation_result=cons_result,
        metrics=metrics,
        contradiction_index=result_ci,
    )


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

    # Check xref cache (prevents redundant API calls for same ticker within 5 min)
    cached = await get_cached_xref(ticker)
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
    )

    log.info("Cross-reference for $%s: score=%d (base=%d + xref=%d, youtube=%d)",
             ticker, result.final_score, tweet.base_score,
             result.final_score - tweet.base_score, youtube_pts)

    await cache_xref(ticker, result)

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
