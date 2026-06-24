"""Precision scoring engine — budget-aware, multi-adapter signal analysis.

Classifies signals into STRONG_ALERT / WATCHLIST / IGNORE using an
escalation pipeline: cheap sources first (Finnhub, Brave), expensive
sources only if the score is promising (Exa, SerpApi, Firecrawl).
"""

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from consensus_engine import config as cfg, db
from consensus_engine.analysis.contradiction import evaluate_contradiction, ContradictionVerdict
from consensus_engine.analysis.regime import lookup_regime, RegimeContext, _COLD_START
from consensus_engine.adapter_protocols import (
    FinnhubContext,
    FirecrawlPage,
    SearchHit,
)
from consensus_engine.api_adapters import (
    BraveAdapter,
    ExaAdapter,
    FinnhubAdapter,
    FirecrawlAdapter,
    SerpApiAdapter,
)
from consensus_engine.utils.http import get_session

log = logging.getLogger("consensus_engine.engine")

_TRUSTED_DOMAINS = {
    "reuters.com", "cnbc.com", "bloomberg.com", "wsj.com", "marketwatch.com",
    "finance.yahoo.com", "sec.gov", "fda.gov", "prnewswire.com",
    "businesswire.com", "seekingalpha.com", "benzinga.com", "barrons.com",
    "investors.com", "ft.com",
}

_MAINSTREAM = {"reuters.com", "cnbc.com", "bloomberg.com", "wsj.com", "ft.com"}


class SignalClass(str, Enum):
    STRONG_ALERT = "STRONG_ALERT"
    WATCHLIST = "WATCHLIST"
    IGNORE = "IGNORE"


# ---------------------------------------------------------------------------
# Budget Manager — async SQLite daily usage tracking
# ---------------------------------------------------------------------------

class BudgetManager:
    """Tracks daily API consumption in the api_usage_daily table."""

    _COLUMNS = (
        "finnhub_calls", "brave_queries", "exa_queries",
        "serpapi_queries", "firecrawl_credits",
        "gemini_input_tokens", "gemini_output_tokens", "gemini_video_calls",
        "wolf_vision_calls",
    )

    def __init__(self):
        # I4-display / I10 prerequisite: per-run set of source columns whose fetch
        # was skipped because budget ran out (vs fetched-and-empty). Surfaced on the
        # analyze_signal result so downstream can render "confidence degraded: budget".
        self.skipped_sources: set[str] = set()

    async def _today_key(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    async def _ensure_row(self, conn, day: str):
        cursor = await conn.execute(
            "SELECT 1 FROM api_usage_daily WHERE day_utc = ?", (day,)
        )
        row = await cursor.fetchone()
        if not row:
            await conn.execute(
                "INSERT OR IGNORE INTO api_usage_daily (day_utc) VALUES (?)", (day,)
            )
            await conn.commit()

    async def consume(self, adapter_col: str, amount: int = 1) -> bool:
        """Atomically increment usage if within budget. Returns False if over or column invalid."""
        if adapter_col not in self._COLUMNS:
            return False
        budget_key = f"precision_engine.budget.{adapter_col}"
        limit = cfg.get(budget_key, 9999)

        conn = await db.get_db()
        day = await self._today_key()
        await self._ensure_row(conn, day)

        cursor = await conn.execute(
            f"""UPDATE api_usage_daily
                SET {adapter_col} = {adapter_col} + ?, updated_at = datetime('now')
                WHERE day_utc = ? AND {adapter_col} + ? <= ?""",
            (amount, day, amount, limit),
        )
        await conn.commit()
        if cursor.rowcount == 0:
            log.warning("Budget exceeded for %s (limit=%d)", adapter_col, limit)
            self.skipped_sources.add(adapter_col)
            return False
        return True

    async def can_consume(self, adapter_col: str, amount: int = 1) -> bool:
        """Check if budget allows without consuming."""
        if adapter_col not in self._COLUMNS:
            return False
        budget_key = f"precision_engine.budget.{adapter_col}"
        limit = cfg.get(budget_key, 9999)

        conn = await db.get_db()
        day = await self._today_key()
        await self._ensure_row(conn, day)

        cursor = await conn.execute(
            f"SELECT {adapter_col} FROM api_usage_daily WHERE day_utc = ?", (day,)
        )
        row = await cursor.fetchone()
        current = row[adapter_col] if row else 0
        allowed = current + amount <= limit
        if not allowed:
            self.skipped_sources.add(adapter_col)
        return allowed

    async def pct_used(self, adapter_col: str) -> float:
        """Return percentage of daily budget used (0-100)."""
        if adapter_col not in self._COLUMNS:
            return 0.0
        budget_key = f"precision_engine.budget.{adapter_col}"
        limit = cfg.get(budget_key, 1)

        conn = await db.get_db()
        day = await self._today_key()
        await self._ensure_row(conn, day)

        cursor = await conn.execute(
            f"SELECT {adapter_col} FROM api_usage_daily WHERE day_utc = ?", (day,)
        )
        row = await cursor.fetchone()
        current = row[adapter_col] if row else 0
        return (current / limit) * 100 if limit > 0 else 0.0

    async def can_consume_gemini(self, estimated_tokens: int = 50000) -> bool:
        """Peek if a Gemini call with `estimated_tokens` input fits under all caps.
        Returns True if every Gemini budget (input_tokens, output_tokens, calls)
        still has headroom; False otherwise.
        """
        if not await self.can_consume("gemini_input_tokens", estimated_tokens):
            return False
        if not await self.can_consume("gemini_video_calls", 1):
            return False
        return True

    async def consume_gemini(self, input_tokens: int, output_tokens: int) -> bool:
        """Atomically bump input_tokens, output_tokens, and video_calls by 1.
        Returns True only if all three increments stayed under their caps.
        Any single cap breach returns False (still logs per-column warning).
        """
        ok_in = await self.consume("gemini_input_tokens", max(0, int(input_tokens)))
        ok_out = await self.consume("gemini_output_tokens", max(0, int(output_tokens)))
        ok_calls = await self.consume("gemini_video_calls", 1)
        return ok_in and ok_out and ok_calls


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _score_finnhub(ctx: FinnhubContext) -> int:
    """Score from Finnhub market data: 0-30 points."""
    score = 0
    pct = abs(ctx.change_pct)
    if pct >= 5.0:
        score += 20
    elif pct >= 2.0:
        score += 12
    elif pct >= 0.5:
        score += 5

    if ctx.rvol >= 3.0:
        score += 8
    elif ctx.rvol >= 2.0:
        score += 5
    elif ctx.rvol >= 1.5:
        score += 2

    if ctx.news_headlines:
        score += min(len(ctx.news_headlines), 3) * 2
    return min(score, 30)


def _score_hits(hits: list[SearchHit]) -> tuple[int, bool]:
    """Score from search results. Returns (points, has_mainstream)."""
    if not hits:
        return 0, False

    score = 0
    has_mainstream = False
    seen_domains = set()

    for hit in hits:
        domain = hit.source.lower().lstrip("www.")
        if domain in seen_domains:
            continue
        seen_domains.add(domain)

        if domain in _TRUSTED_DOMAINS:
            score += 5
        else:
            score += 2

        if domain in _MAINSTREAM:
            has_mainstream = True

    return min(score, 25), has_mainstream


def _score_firecrawl(pages: list[FirecrawlPage], ticker: str) -> int:
    """Score from deep content extraction: 0-15 points."""
    if not pages:
        return 0
    score = 0
    ticker_lower = ticker.lower()
    for page in pages:
        if not page.success:
            continue
        text_lower = page.text.lower()
        if ticker_lower in text_lower or f"${ticker_lower}" in text_lower:
            score += 5
            word_count = len(page.text.split())
            if word_count >= 200:
                score += 3
    return min(score, 15)


def _classify(
    total_score: int,
    has_mainstream: bool,
    market_ok: bool,
    bypass_market_confirmation: bool = False,
    contradiction_index: float = 0.0,
    regime=None,
    breakdown=None,
    technical_filter_count: int = 0,
    analyst_lb: Optional[float] = None,
    budget_skipped_sources: Optional[set] = None,
    ticker: str = "",
    e2_multiplier: float = 1.0,
) -> tuple["SignalClass", "ContradictionVerdict"]:
    """Map total score + quality flags to a signal classification.

    Returns (SignalClass, ContradictionVerdict). ContradictionVerdict is always
    computed for shadow-mode writes even when the feature is disabled.

    ``bypass_market_confirmation`` is set by HIGH-conviction or SEC-catalyst
    callers; it lets them surface a WATCHLIST even when the flat-market gate
    would normally route them to IGNORE.

    I10 optional args (all default to None/0/empty — existing callers unaffected):
    - breakdown: ScoreBreakdown instance with per-source point totals.
    - technical_filter_count: number of technical filters that passed this run.
    - analyst_lb: Wilson lower-bound precision for the primary analyst (from
      db.get_analyst_precision_lb); None when unavailable or below min_n=10.
    - budget_skipped_sources: set of source column names whose fetch was skipped
      for budget this run (vs fetched-and-empty); populated by BudgetManager.

    I10 hard-evidence rule (flag features.strong_requires_hard_evidence.enabled):
    STRONG requires score >= high AND at least one hard-evidence component:
      news_catalyst > 0  OR  sec_filing > 0  OR  options_flow > 0  OR
      technical_filter_count >= min_technical_filters (config, default 2)  OR
      analyst Wilson-LB >= analyst_lb_threshold (config, default 0.65).
    Before-mainstream carve-out: a high-track-record analyst (lb >= threshold)
    counts as hard evidence — a genuine early call is not demoted.
    Absent-vs-unfetched safeguard: if a confirming source column appears in
    budget_skipped_sources its absence does NOT count against hard evidence.
    Shadow line is emitted on every STRONG-threshold eval regardless of flag.

    E2 + I14-widening combined cutoff adjustment (reconciled into ONE formula):
    ``effective_high = clamp(base_high * e2_multiplier + regime_shift,
                             base_high - 10, cutoff_ceiling=90)``
    - regime_shift is the graduated shift from regime.py (I14-widening) —
      except for high-conviction bypass callers (see I14 handoff item below).
    - e2_multiplier scales base_high before adding the additive shift, so the
      two adjustments never independently stack beyond the ceiling or below the
      floor.  Flag OFF on either feature leaves that term at its neutral value
      (e2_multiplier=1.0, regime_shift=0) making the formula a no-op.
    - The clamp guarantees: veto can never raise the cutoff above ceiling (90)
      nor can a confirm lower it below base_high - 10.

    I14 handoff — high-conviction bypass exemption:
    When bypass_market_confirmation=True AND features.regime_widening_graduated
    is enabled, the regime_shift applied to this caller's high cutoff is capped
    at the STATIC map value (features.regime_classifier.regime_shifts[label]),
    NOT the graduated extra.  This prevents high-conviction calls (and
    SEC-catalyst callers) from facing the extra graduated widening.
    Gate: only when features.regime_widening_graduated.enabled is True; OFF ->
    bypass callers see the full (already-static in that case) threshold_shift.
    """
    base_high = cfg.get("precision_engine.thresholds.high_confidence", 80)
    med = cfg.get("precision_engine.thresholds.medium_confidence", 65)
    cutoff_ceiling = cfg.get("features.regime_widening_graduated.cutoff_ceiling", 90)

    # Determine regime shift, applying I14 bypass exemption when applicable.
    regime_shift: int = 0
    if regime is not None and cfg.get("features.regime_classifier.enabled", False):
        if (
            bypass_market_confirmation
            and cfg.get("features.regime_widening_graduated.enabled", False)
        ):
            # I14 handoff: high-conviction callers exempt from graduated EXTRA
            # widening — cap at the static map value for this label.
            shifts = cfg.get(
                "features.regime_classifier.regime_shifts",
                {"calm": -5, "elevated": 5, "panic": 10},
            )
            regime_shift = shifts.get(regime.label, 0)
        else:
            regime_shift = regime.threshold_shift

    # E2 + I14 reconciliation: ONE bounded cutoff adjustment.
    # Flag OFF on either feature -> neutral value -> formula is a no-op.
    if cfg.get("features.cross_asset.enabled", False) and e2_multiplier != 1.0:
        raw_high = base_high * e2_multiplier + regime_shift
    else:
        raw_high = base_high + regime_shift

    high = int(max(base_high - 10, min(cutoff_ceiling, raw_high)))
    require_mainstream = cfg.get("precision_engine.thresholds.require_mainstream_for_strong", True)
    require_market = cfg.get(
        "precision_engine.thresholds.require_market_confirmation_for_low_conviction", True
    )
    effective_market_ok = market_ok or bypass_market_confirmation

    # Always compute contradiction verdict for shadow-mode writes
    from datetime import datetime as _dt
    _now = _dt.utcnow()
    contradiction_verdict = evaluate_contradiction(contradiction_index, _now)

    # I10: compute hard-evidence verdict whenever score reaches the STRONG threshold.
    # The shadow log fires even when the flag is OFF (compute, don't act).
    _i10_would_demote = False
    if total_score >= high and breakdown is not None:
        min_tech = int(cfg.get("features.strong_requires_hard_evidence.min_technical_filters", 2))
        lb_threshold = float(cfg.get("features.strong_requires_hard_evidence.analyst_lb_threshold", 0.65))
        skipped = budget_skipped_sources or set()

        # Absent-vs-unfetched safeguard: if ANY confirming paid source was budget-skipped
        # this run, we can't rule out evidence we didn't fetch → do NOT demote.
        # Confirming paid source columns: exa, serpapi, firecrawl.
        confirming_paid_cols = {"exa_queries", "serpapi_queries", "firecrawl_credits"}
        any_confirming_skipped = bool(skipped & confirming_paid_cols)

        has_hard_evidence = (
            (breakdown.news_catalyst > 0)
            or (breakdown.sec_filing > 0)
            or (technical_filter_count >= min_tech)
            or (breakdown.options_flow > 0)
            or (analyst_lb is not None and analyst_lb >= lb_threshold)
            or any_confirming_skipped  # skipped paid source → indeterminate, don't demote
        )
        _i10_would_demote = not has_hard_evidence

        log.info(
            "[I10 shadow] $%s would_demote=%s (catalyst=%d sec=%d tech_filters=%d"
            " options=%d analyst_lb=%s budget_skipped=%s)",
            ticker or "?",
            _i10_would_demote,
            breakdown.news_catalyst,
            breakdown.sec_filing,
            technical_filter_count,
            breakdown.options_flow,
            f"{analyst_lb:.3f}" if analyst_lb is not None else "None",
            sorted(skipped) if skipped else "[]",
        )

    if total_score >= high:
        if require_mainstream and not has_mainstream:
            return SignalClass.WATCHLIST, contradiction_verdict
        if require_market and not effective_market_ok:
            return SignalClass.WATCHLIST, contradiction_verdict
        # A1 (last gate before STRONG): contradiction penalty
        if contradiction_verdict.apply_penalty:
            return SignalClass.WATCHLIST, contradiction_verdict
        # I10: crowd-only STRONG cap (flag must be ON to act; shadow fires above)
        if (
            _i10_would_demote
            and breakdown is not None
            and cfg.get("features.strong_requires_hard_evidence.enabled", False)
        ):
            log.info("[I10] $%s capped at WATCHLIST — no hard evidence", ticker or "?")
            return SignalClass.WATCHLIST, contradiction_verdict
        return SignalClass.STRONG_ALERT, contradiction_verdict

    if total_score >= med:
        return SignalClass.WATCHLIST, contradiction_verdict

    if bypass_market_confirmation:
        return SignalClass.WATCHLIST, contradiction_verdict

    return SignalClass.IGNORE, contradiction_verdict


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def analyze_signal(
    ticker: str,
    base_score: int = 0,
    budget: Optional[BudgetManager] = None,
    catalyst_type: str = "",
    contradiction_index: float = 0.0,
    direction: str = "",
    breakdown=None,
    technical_filter_count: int = 0,
    analyst: str = "",
    analyst_lb: Optional[float] = None,
) -> dict:
    """Run the precision scoring pipeline for a ticker.

    Returns a dict with keys:
        ticker, classification, total_score, finnhub_score, search_score,
        firecrawl_score, has_mainstream, market_ok, finnhub_ctx,
        search_hits, firecrawl_pages
    """
    if not cfg.get("precision_engine.enabled", False):
        return {
            "ticker": ticker,
            "classification": SignalClass.IGNORE,
            "total_score": base_score,
            "skipped": True,
            "contradiction_verdict": ContradictionVerdict(apply_penalty=False, reason="disabled"),
            "regime": _COLD_START,
            "skipped_sources": [],
        }

    budget = budget or BudgetManager()
    session = await get_session()

    # A5: lookup current regime for threshold shifting
    regime = await lookup_regime()

    score = base_score
    has_mainstream = False
    market_ok = False
    finnhub_ctx = FinnhubContext()
    all_hits: list[SearchHit] = []
    fc_pages: list[FirecrawlPage] = []

    # KILL 4 / M6-lite: exemption flags computed once, used at both the early
    # gate and _classify so HIGH-conviction + SEC-catalyst signals don't get
    # buried by a flat-market read.
    high_conv_threshold = cfg.get("precision_engine.thresholds.high_conviction_threshold", 30)
    sec_exempt = cfg.get("precision_engine.thresholds.sec_catalyst_exempt", True)
    is_high_conviction = base_score >= high_conv_threshold
    is_sec_catalyst = (catalyst_type or "").lower().startswith("sec_")
    skip_market_gate = is_high_conviction or (sec_exempt and is_sec_catalyst)

    # --- Phase 1: Finnhub (cheap, 2 calls) ---
    if await budget.consume("finnhub_calls", 2):
        adapter = FinnhubAdapter(session)
        finnhub_ctx = await adapter.get_context(ticker)
        fh_score = _score_finnhub(finnhub_ctx)
        score += fh_score
        market_ok = finnhub_ctx.market_ok
        log.info("$%s Finnhub: +%d pts (change=%.1f%%, rvol=%.1f, news=%d)",
                 ticker, fh_score, finnhub_ctx.change_pct, finnhub_ctx.rvol,
                 len(finnhub_ctx.news_headlines))

        require_market = cfg.get(
            "precision_engine.thresholds.require_market_confirmation_for_low_conviction", True
        )
        if not market_ok and require_market and not skip_market_gate:
            log.info("$%s early exit: market not confirming (change=%.1f%%)", ticker, finnhub_ctx.change_pct)
            return {
                "ticker": ticker,
                "classification": SignalClass.IGNORE,
                "total_score": score,
                "finnhub_score": _score_finnhub(finnhub_ctx),
                "search_score": 0,
                "firecrawl_score": 0,
                "has_mainstream": False,
                "market_ok": False,
                "finnhub_ctx": finnhub_ctx,
                "search_hits": [],
                "firecrawl_pages": [],
                "contradiction_verdict": ContradictionVerdict(apply_penalty=False, reason="disabled"),
                "regime": _COLD_START,
                "skipped_sources": sorted(budget.skipped_sources),
            }

    # --- Phase 2: Brave Search (cheap) ---
    query = f"{ticker} stock news today"
    if await budget.consume("brave_queries"):
        brave = BraveAdapter(session)
        brave_hits = await brave.search(query)
        all_hits.extend(brave_hits)

    search_score, has_mainstream = _score_hits(all_hits)
    score += search_score

    # --- Phase 3: Exa (medium cost, only if score < high threshold) ---
    high_thresh = cfg.get("precision_engine.thresholds.high_confidence", 80)
    if score < high_thresh and await budget.can_consume("exa_queries"):
        await budget.consume("exa_queries")
        exa = ExaAdapter(session)
        exa_hits = await exa.search(f"{ticker} stock catalyst breaking news")
        all_hits.extend(exa_hits)
        search_score, has_mainstream = _score_hits(all_hits)
        score = base_score + _score_finnhub(finnhub_ctx) + search_score

    # --- Phase 4: SerpApi (expensive, only if score >= threshold) ---
    serpapi_thresh = cfg.get("precision_engine.thresholds.min_score_for_serpapi", 60)
    if cfg.get("precision_engine.serpapi_enabled", True) and score >= serpapi_thresh and await budget.can_consume("serpapi_queries"):
        await budget.consume("serpapi_queries")
        serpapi = SerpApiAdapter(session)
        serp_hits = await serpapi.search(f"{ticker} stock news")
        all_hits.extend(serp_hits)
        search_score, has_mainstream = _score_hits(all_hits)
        score = base_score + _score_finnhub(finnhub_ctx) + search_score

    # --- Phase 5: Firecrawl (most expensive, only if score >= threshold) ---
    fc_thresh = cfg.get("precision_engine.thresholds.min_score_for_firecrawl", 65)
    max_fc_urls = cfg.get("precision_engine.thresholds.max_firecrawl_urls", 2)
    if score >= fc_thresh and all_hits:
        urls_to_scrape = [h.url for h in all_hits if h.url][:max_fc_urls]
        credits_needed = len(urls_to_scrape)
        if credits_needed > 0 and await budget.can_consume("firecrawl_credits", credits_needed):
            await budget.consume("firecrawl_credits", credits_needed)
            fc = FirecrawlAdapter(session)
            fc_pages = await fc.extract(urls_to_scrape)
            fc_score = _score_firecrawl(fc_pages, ticker)
            score += fc_score

    # A4: sector ETF peer-confirmation gate
    from consensus_engine.analysis.sector_confirmation import check_sector_alignment
    sector_verdict = await check_sector_alignment(
        ticker, direction or "long", catalyst_type, datetime.utcnow(),
    )
    bypass_due_to_a4 = (
        cfg.get("features.sector_confirmation.enabled", False)
        and (sector_verdict.aligned or sector_verdict.bypass_due_to_catalyst
             or sector_verdict.bypass_due_to_unknown or sector_verdict.bypass_due_to_premarket
             or sector_verdict.bypass_due_to_unmapped)
    )
    skip_market_gate = skip_market_gate or bypass_due_to_a4

    # --- I10: resolve analyst LB for hard-evidence carve-out ---
    # Only look up the DB when an analyst handle is provided AND the flag is ON
    # (or the score is already at the STRONG threshold, where the shadow log fires).
    # If analyst_lb was pre-computed by the caller, use that directly.
    _resolved_analyst_lb = analyst_lb
    if _resolved_analyst_lb is None and analyst:
        high_check = cfg.get("precision_engine.thresholds.high_confidence", 80)
        if score >= high_check or cfg.get("features.strong_requires_hard_evidence.enabled", False):
            try:
                _resolved_analyst_lb = await db.get_analyst_precision_lb(analyst, horizon="1h", min_n=10)
            except Exception as _lb_exc:
                log.debug("[I10] analyst LB lookup failed for %s: %s", analyst, _lb_exc)

    # --- E2: cross-asset regime multiplier ---
    # Runs when enabled=True (apply) OR when shadow=True and enabled=False (log-only).
    # get_multiplier returns 1.0 in shadow-only mode so the live score is unaffected.
    _e2_multiplier: float = 1.0
    _e2_enabled = cfg.get("features.cross_asset.enabled", False)
    _e2_shadow = cfg.get("features.cross_asset.shadow", True)
    if _e2_enabled or _e2_shadow:
        try:
            from consensus_engine.analysis.cross_asset import get_multiplier as _get_e2
            _e2_multiplier = await _get_e2()
        except Exception as _e2_exc:
            log.debug("[E2] multiplier fetch failed — using 1.0: %s", _e2_exc)

    # --- Classify ---
    classification, contradiction_verdict = _classify(
        score, has_mainstream, market_ok,
        bypass_market_confirmation=skip_market_gate,
        contradiction_index=contradiction_index,
        regime=regime,
        breakdown=breakdown,
        technical_filter_count=technical_filter_count,
        analyst_lb=_resolved_analyst_lb,
        budget_skipped_sources=budget.skipped_sources,
        ticker=ticker,
        e2_multiplier=_e2_multiplier,
    )
    log.info("[A1] $%s contradiction=%.2f → %s", ticker, contradiction_index, contradiction_verdict.reason)
    log.info("$%s precision result: %s (score=%d, mainstream=%s, market_ok=%s)",
             ticker, classification.value, score, has_mainstream, market_ok)

    return {
        "ticker": ticker,
        "classification": classification,
        "total_score": score,
        "finnhub_score": _score_finnhub(finnhub_ctx),
        "search_score": search_score,
        "firecrawl_score": _score_firecrawl(fc_pages, ticker) if fc_pages else 0,
        "has_mainstream": has_mainstream,
        "market_ok": market_ok,
        "finnhub_ctx": finnhub_ctx,
        "search_hits": all_hits,
        "firecrawl_pages": fc_pages,
        "contradiction_verdict": contradiction_verdict,
        "regime": regime,
        "sector_verdict": sector_verdict,
        "skipped_sources": sorted(budget.skipped_sources),
    }
