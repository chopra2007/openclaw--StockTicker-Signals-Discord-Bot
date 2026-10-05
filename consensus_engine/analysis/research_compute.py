"""Reusable market calculations. No collection, credentials, database or delivery.

The score generator requests a closed set of value records. The bot fulfils those
requests at the original boundaries; restricted callers supply already collected
records. The arithmetic has a single implementation for both callers.
"""
from __future__ import annotations

import dataclasses
import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional
from types import SimpleNamespace

from consensus_engine.models import (ScoreBreakdown, CatalystResult, TechnicalResult,
                                    OptionsResult, YouTubeContext)
from consensus_engine.analysis.research_contracts import (ScoreRequest, ScoreTickerResult,
                                                          _SecGraduation, _BurstAnalysis)

log = logging.getLogger("consensus_engine.cross_reference")
_E6_SIMILARITY_DEFAULT = 0.6
_E6_BURST_WINDOW_SEC_DEFAULT = 300
_E6_MIN_ACCOUNTS_DEFAULT = 2


def compute_technical_score(technical: Optional[TechnicalResult], *, settings, now, min_purchase_dollars=250_000.0,) -> int:
    """Compute score from technical filters. +2 per passing filter, max 12."""
    if not technical or not technical.filters:
        return 0
    per_filter = settings.get("scoring.multipliers.technical_per_filter", 2)
    max_pts = settings.get("scoring.multipliers.technical_max", 12)
    return min(technical.passed_count * per_filter, max_pts)



def _compute_apewisdom_zscore_pts(
    social_data: dict,
    *,
    sec_hit: bool,
    catalyst_passed: bool,
    technical_pts: int, settings, now, min_purchase_dollars=250_000.0,) -> int:
    """I13: z-score gate for the social_apewisdom term.

    Called only when ``features.apewisdom_zscore.enabled`` is True.

    Gate conditions (ALL must pass for +10):
      1. Ticker has >= min_baseline_days distinct calendar days of baseline.
      2. Current mentions > z_threshold sigma above the baseline mean.
      3. At least one actor-independent hard corroborator agrees:
           - SEC buy (sec_hit=True)
           - hard news catalyst (catalyst_passed=True)
           - technical breakout (technical_pts >= 2 filters, per I10 definition)
      4. Mention data is fresh (recency_window "apewisdom" cap, 1440 min by default).
         Freshness is checked against apewisdom_captured_at in social_data.
         If not present / None -> stale -> 0.

    Returns 0 when any gate fails. Never subtracts.
    """
    min_days = int(settings.get("features.apewisdom_zscore.min_baseline_days", 14))
    z_threshold = float(settings.get("features.apewisdom_zscore.z_threshold", 2.0))
    m = settings.get("scoring.multipliers", {})
    pts = m.get("social_apewisdom", 10)

    # Gate 1: baseline must be mature enough to be trustworthy.
    baseline = social_data.get("apewisdom_baseline") or {}
    sample_days = int(baseline.get("sample_days", 0))
    if sample_days < min_days:
        log.debug(
            "[I13] thin baseline (sample_days=%d < %d) -> 0", sample_days, min_days
        )
        return 0

    # Gate 2: z-score must exceed threshold.
    current_mentions = int(social_data.get("apewisdom_mentions", 0))
    baseline_mean = float(baseline.get("mean", 0.0))
    baseline_std = float(baseline.get("std", 0.0))
    if baseline_std <= 0:
        # Zero-variance baseline -> divide-by-zero guard -> use raw count as floor.
        # With zero std the ticker has been perfectly flat; any positive count is
        # "infinite sigma" — new-ticker hole: treat as stale/insufficient.
        log.debug("[I13] zero-std baseline -> 0")
        return 0
    z_score = (current_mentions - baseline_mean) / baseline_std
    if z_score <= z_threshold:
        log.debug(
            "[I13] z_score=%.2f <= threshold=%.2f -> 0", z_score, z_threshold
        )
        return 0

    # Gate 3: actor-independent hard corroborator required.
    min_tech_filters = int(settings.get("features.strong_requires_hard_evidence.min_technical_filters", 2))
    has_corroborator = (
        sec_hit
        or catalyst_passed
        or technical_pts >= min_tech_filters
    )
    if not has_corroborator:
        log.debug(
            "[I13] z_score=%.2f but NO hard corroborator (sec=%s catalyst=%s tech_pts=%d) -> 0",
            z_score, sec_hit, catalyst_passed, technical_pts,
        )
        return 0

    # Gate 4: freshness check via recency_window.
    from consensus_engine.analysis.recency_window import is_fresh  # local import: avoids circular
    captured_at = social_data.get("apewisdom_captured_at")
    if not is_fresh("apewisdom", captured_at, settings=settings, now=datetime.fromtimestamp(now, timezone.utc)):
        log.debug("[I13] stale apewisdom data (captured_at=%s) -> 0", captured_at)
        return 0

    log.info(
        "[I13] z_score=%.2f (mentions=%d mean=%.1f std=%.1f days=%d) + "
        "corroborator(sec=%s cat=%s tech=%d) -> +%d",
        z_score, current_mentions, baseline_mean, baseline_std,
        sample_days, sec_hit, catalyst_passed, technical_pts, pts,
    )
    return pts



def compute_social_score(social_data: dict[str, int], *, settings, now, min_purchase_dollars=250_000.0,) -> int:
    """Compute social cross-reference score from platform signal counts."""
    score = 0
    m = settings.get("scoring.multipliers", {})
    if social_data.get("apewisdom", 0) >= 1:
        score += m.get("social_apewisdom", 10)
    if social_data.get("stocktwits", 0) >= 1:
        score += m.get("social_stocktwits", 10)
    if social_data.get("reddit", 0) >= 2:
        score += m.get("social_reddit", 10)
    if social_data.get("google_trends", 0) >= 1:
        score += m.get("google_trends", 5)
    return score



def _compute_social_breakdown(
    social_data: dict,
    *,
    sec_hit: bool = False,
    catalyst_passed: bool = False,
    technical_pts: int = 0, settings, now, min_purchase_dollars=250_000.0,) -> dict[str, int]:
    """Return per-source social points for the ScoreBreakdown.

    I13 (signal-features-2026-06-09, flag OFF default): when
    ``features.apewisdom_zscore.enabled`` is True, the ``social_apewisdom``
    term is replaced with a z-score gate that awards +10 ONLY when:
      (a) the ticker has >= min_baseline_days (14) distinct calendar days
          of baseline data in apewisdom_mentions,
      (b) today's mention count is > z_threshold (2.0) sigma above the
          per-ticker baseline mean,
      (c) at least ONE actor-independent hard source already agrees on
          direction: SEC buy (sec_hit), hard news catalyst (catalyst_passed),
          or technical breakout (technical_pts >= 2 filters).
    A pure Reddit/ApeWisdom spike with no hard corroborator earns 0.
    Below min_baseline_days -> 0 (NOT the old presence +10).
    Stale mention data (recency_window apewisdom cap, 1440 min) -> 0.
    Flag OFF -> byte-identical (presence-only +10).
    """
    m = settings.get("scoring.multipliers", {})
    aw_pts = m.get("social_apewisdom", 10) if social_data.get("apewisdom", 0) >= 1 else 0

    # I13 z-score gate — runs ONLY when the flag is ON.
    if settings.get("features.apewisdom_zscore.enabled", False):
        aw_pts = _compute_apewisdom_zscore_pts(
            social_data,
            sec_hit=sec_hit,
            catalyst_passed=catalyst_passed,
            technical_pts=technical_pts,
         settings=settings, now=now, min_purchase_dollars=min_purchase_dollars)

    breakdown = {
        "social_apewisdom": aw_pts,
        "social_stocktwits": m.get("social_stocktwits", 10) if social_data.get("stocktwits", 0) >= 1 else 0,
        "social_reddit": m.get("social_reddit", 10) if social_data.get("reddit", 0) >= 2 else 0,
        "google_trends": m.get("google_trends", 5) if social_data.get("google_trends", 0) >= 1 else 0,
    }

    # #65 Fix 2 (social-family de-dup, flag OFF default): ApeWisdom, StockTwits and
    # Reddit are the SAME retail crowd, so counting all three inflates "independent"
    # agreement. When the flag is ON, each source family collapses to ONE vote — keep
    # the single highest-scoring member of a family, zero the rest. Demotion-only: it
    # can never create an alert, only shrink an over-counted one. Flag OFF -> byte-identical.
    if settings.get("features.social_family_dedup.enabled", False):
        families = settings.get("features.social_family_dedup.families", {
            "social_apewisdom": "retail_crowd",
            "social_stocktwits": "retail_crowd",
            "social_reddit": "retail_crowd",
            "google_trends": "search",
        })
        # For each family, keep the single highest-scoring member; zero the rest.
        best_in_family: dict[str, tuple[str, int]] = {}  # fam -> (key, score)
        for key, fam in families.items():
            score = breakdown.get(key, 0)
            if fam not in best_in_family or score > best_in_family[fam][1]:
                best_in_family[fam] = (key, score)
        winners = {k for (k, _s) in best_in_family.values()}
        for key in families:
            if key not in winners:
                breakdown[key] = 0

    return breakdown



def _compute_finra_short_volume_pts(
    short_pct: float,
    baseline: dict,
    finra_published_at: float | None,
    *,
    direction: str = "long", settings, now, min_purchase_dollars=250_000.0,) -> int:
    """E1: z-score confluence term for FINRA daily short-volume.

    Returns a small positive term (cap from config, default +5) ONLY when:
      1. The ticker's latest short_pct is >2 sigma above its own 30-day baseline.
      2. The row is fresh (recency_window "finra_short_volume" cap, 1440 min default).
      3. The direction is direction-compatible (spec: confluence-only, not standalone).
         Short-volume spike is ambiguous w.r.t. direction — it can mean bearish
         institutional flow OR MM hedging.  We add the term ONLY on the bullish
         path (high short-pct can precede a short-squeeze on long signals); on a
         short-signal it would be directionally redundant so we skip it.
      4. baseline has >= 30 sample days (30-day baseline requirement from spec).

    Flag OFF -> returns 0 without reading the DB (the DB read is skipped entirely
    on the hot path; this function is never called when flag is OFF).

    Provenance label (hard render rule, never mutate):
        ``FINRA_SHORT_VOL_PROVENANCE = "short-volume %, MM-hedging-inflated proxy"``
    """
    # Freshness check via recency_window
    from consensus_engine.analysis.recency_window import is_fresh
    if not is_fresh("finra_short_volume", finra_published_at, settings=settings, now=datetime.fromtimestamp(now, timezone.utc)):
        log.debug("[E1] stale finra row (published_at=%s) -> 0", finra_published_at)
        return 0

    # sample_days counts TRADING days (one row per trade_date). The 45-calendar-
    # day baseline window holds ~31 trading days; require >=20 so the gate can
    # open after a 30-trading-day backfill (a 30 floor on a 30-calendar-day
    # window could never fire — ~21 trading days max).
    sample_days = int(baseline.get("sample_days", 0))
    min_days = int(settings.get("features.finra_short_volume.min_baseline_days", 20))
    if sample_days < min_days:
        log.debug("[E1] thin baseline (%d days < %d) -> 0", sample_days, min_days)
        return 0

    mean = float(baseline.get("mean", 0.0))
    std = float(baseline.get("std", 0.0))
    if std <= 0.0:
        log.debug("[E1] zero std baseline -> 0 (new-ticker guard)")
        return 0

    z = (short_pct - mean) / std
    z_threshold = float(settings.get("features.finra_short_volume.z_threshold", 2.0))
    if z <= z_threshold:
        log.debug("[E1] z=%.2f <= %.2f threshold -> 0", z, z_threshold)
        return 0

    # Direction-compatibility: only add on long signals (short-vol spike can
    # indicate MM hedging / short-squeeze setup; on short it's redundant).
    if direction.lower() != "long":
        log.debug("[E1] non-long direction (%s) -> 0 (confluence-only)", direction)
        return 0

    cap = int(settings.get("features.finra_short_volume.term_cap", 5))
    log.info(
        "[E1] $%s short_pct=%.3f z=%.2f (mean=%.3f std=%.3f sample_days=%d) -> +%d "
        "provenance='%s'",
        "",  # ticker logged by caller
        short_pct, z, mean, std, sample_days, cap,
        "short-volume %, MM-hedging-inflated proxy",
    )
    return cap



def _compute_days_to_cover_pts(
    si_row: dict,
    *,
    direction: str = "long", settings, now, min_purchase_dollars=250_000.0,) -> int:
    """r12: settlement short-interest days-to-cover confluence term.

    Returns a small capped positive term (config, default +3) ONLY when:
      1. The row is fresh (recency_window "short_interest" cap).
      2. days_to_cover >= min_days_to_cover (real squeeze fuel, default 3.0).
      3. Short interest is RISING vs the prior settlement (pct_change > 0) when
         require_rising is set — a growing crowded short is the squeeze setup.
      4. The direction is long (confluence-only; on a short signal a crowded short
         is directionally redundant, so we skip it — mirrors the E1 short-vol leg).

    Flag OFF -> this function is never called (no DB read on the hot path).
    Distinct from snapshot.py's single yfinance short-interest point: this keys off
    the official FINRA settlement series + its bi-monthly change.
    """
    from consensus_engine.analysis.recency_window import is_fresh
    if not is_fresh("short_interest", si_row.get("published_at"), settings=settings, now=datetime.fromtimestamp(now, timezone.utc)):
        return 0
    dtc = si_row.get("days_to_cover")
    if dtc is None:
        return 0
    min_dtc = float(settings.get("features.short_interest.min_days_to_cover", 3.0))
    if float(dtc) < min_dtc:
        return 0
    if settings.get("features.short_interest.require_rising", True):
        pct = si_row.get("pct_change")
        if pct is None or float(pct) <= 0.0:
            return 0
    if direction.lower() != "long":
        return 0
    return int(settings.get("features.short_interest.term_cap", 3))



def _compute_pead_pts(
    pead_result: Optional[dict],
    *,
    direction: str = "long", settings, now, min_purchase_dollars=250_000.0,) -> int:
    """r17: post-earnings-drift confluence term.

    Returns a small capped positive term (config, default +3) ONLY when the PEAD
    read is drift-CONSISTENT (post-print continuation) AND its continuation
    direction matches the signal direction. Faded/reversed drift -> 0. Confluence
    LIFT only on an already-triggered signal — never a standalone trigger.

    pead_result is computed only AFTER earnings_magnitude's 5-day window (enforced
    in pead.classify_pead), so this leg can never double-count that bonus.
    """
    if not pead_result:
        return 0
    if pead_result.get("classification") != "drift-consistent":
        return 0
    if (pead_result.get("direction") or "").lower() != direction.lower():
        return 0
    return int(settings.get("features.pead.term_cap", 3))



def _get_catalyst_score(catalyst_type: str, *, settings, now, min_purchase_dollars=250_000.0,) -> int:
    """Look up tiered score for a catalyst type. Defaults to medium (15)."""
    tiers = settings.get("scoring.catalyst_tiers", {})
    for tier_data in tiers.values():
        if catalyst_type in tier_data.get("types", []):
            return tier_data.get("score", 15)
    return tiers.get("medium", {}).get("score", 15)



def _is_txn_recent(txn_date: str, recency_days: int, *, settings, now, min_purchase_dollars=250_000.0,) -> bool:
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
    return (datetime.fromtimestamp(now, timezone.utc) - dt) <= timedelta(days=recency_days)



def _graduate_sec_pts(grad: _SecGraduation, flat_pts: int, *, settings, now, min_purchase_dollars=250_000.0,) -> int:
    """Compute the I5 graduated SEC points from parsed Form-4 facts.

    Tiers (all additive, never negative):
      +base_pts (8)  any Form-4 present (the floor)
      +large_buy_pts (15)  open-market BUY > min_purchase_dollars ($250k)
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
    base = int(settings.get("features.sec_graduated_scoring.base_pts", 8))
    large = int(settings.get("features.sec_graduated_scoring.large_buy_pts", 15))
    csuite = int(settings.get("features.sec_graduated_scoring.csuite_pts", 20))


    qualifying_buy = (
        grad.max_buy_dollars > min_purchase_dollars
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



def _earnings_magnitude_bonus(catalyst: "CatalystResult", *, settings, now, min_purchase_dollars=250_000.0,) -> int:
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
    min_abs_eps = float(settings.get("features.earnings_magnitude.min_abs_eps", 0.02))
    # sane-denominator guard: need a real estimate to trust the % surprise.
    if estimate is None or abs(estimate) < min_abs_eps:
        return 0
    # absolute-magnitude floor: a near-zero surprise % earns nothing.
    if abs(surprise) <= min_abs_eps:
        return 0
    # freshness gate: only a recent post-print recap may add the bonus.
    recency_days = int(settings.get("features.earnings_magnitude.recency_days", 5))
    if not _is_txn_recent(catalyst.eps_period, recency_days, settings=settings, now=now, min_purchase_dollars=min_purchase_dollars):
        return 0
    per_10pct = int(settings.get("features.earnings_magnitude.per_10pct", 5))
    cap = int(settings.get("features.earnings_magnitude.cap", 15))
    bonus = int(abs(surprise) / 10.0 * per_10pct)
    return min(bonus, cap)



def _graduate_options_pts(options: "OptionsResult", direction: str, *, settings, now, min_purchase_dollars=250_000.0,) -> int:
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
    unusual = int(settings.get("features.options_graduated_scoring.unusual_pts", 6))
    aligned = int(settings.get("features.options_graduated_scoring.aligned_pts", 10))
    large_premium = float(settings.get("options_flow.min_premium_usd", 250_000.0))
    max_staleness_min = int(settings.get("options_flow.max_staleness_min", 60))

    # Staleness gate: reuse the #18 watcher cap. A snapshot whose dominant
    # contract last traded outside the window (e.g. a prior-session / after-hours
    # print) contributes 0. No timestamp at all -> treat as stale -> 0.
    if max_staleness_min:
        ts = options.dominant_last_trade_ts
        if not ts or (now - ts) > max_staleness_min * 60:
            return 0

    # Alignment: long pairs with call flow, short pairs with put flow. An
    # opposing or ambiguous ("") dominant side is NOT a confluence signal -> 0.
    aligned_side = "call" if direction == "long" else "put" if direction == "short" else ""
    if aligned_side == "" or options.dominant_side != aligned_side:
        return 0
    pts = aligned if options.premium_notional > large_premium else unusual
    return min(pts, aligned)  # magnitude cap (never above the aligned ceiling)



def _word_set(text: str, *, settings, now, min_purchase_dollars=250_000.0,) -> frozenset:
    """Cheap normalised word-set for Jaccard similarity (no LLM)."""
    return frozenset(re.sub(r"[^a-z0-9$#]", " ", text.lower()).split())



def _jaccard(a: frozenset, b: frozenset, *, settings, now, min_purchase_dollars=250_000.0,) -> float:
    """Jaccard similarity of two word-sets."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union > 0 else 0.0



def _analyse_burst(
    signal_rows: list[dict],
    *,
    similarity_threshold: float = _E6_SIMILARITY_DEFAULT,
    burst_window_sec: float = _E6_BURST_WINDOW_SEC_DEFAULT,
    min_accounts: int = _E6_MIN_ACCOUNTS_DEFAULT, settings, now, min_purchase_dollars=250_000.0,) -> tuple[bool, frozenset]:
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
    word_sets = [_word_set(str(r["raw_text"]), settings=settings, now=now, min_purchase_dollars=min_purchase_dollars) for r in valid]

    burst_accounts: set[str] = set()
    n = len(valid)
    for i in range(n):
        for j in range(i + 1, n):
            if float(valid[j]["detected_at"]) - float(valid[i]["detected_at"]) > burst_window_sec:
                break  # sorted: all further j are outside the window
            if _jaccard(word_sets[i], word_sets[j], settings=settings, now=now, min_purchase_dollars=min_purchase_dollars) >= similarity_threshold:
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
    options_has_activity: bool, settings, now, min_purchase_dollars=250_000.0,) -> bool:
    """True when an independent non-burst source corroborates.

    Independent sources: SEC filing, hard news catalyst, or options activity.
    Any one of these lifts the E6 gate (they are actor-independent from the
    Twitter/analyst channel).
    """
    if not burst_detected:
        return True  # no gate needed
    return sec_hit or catalyst_passed or options_has_activity



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
    burst_analysis: Optional["_BurstAnalysis"] = None, settings, now, min_purchase_dollars=250_000.0,) -> float:
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

    instant = _dt.datetime.fromtimestamp(now, _dt.timezone.utc)
    tweet_dir = tweet_direction.lower()
    supporting_options_side = "call" if tweet_dir == "long" else "put" if tweet_dir == "short" else ""

    legs: list[SourceLeg] = []

    # Analyst cluster: always supporting (they corroborate the alert direction)
    if analyst_pts > 0:
        legs.append(SourceLeg(
            source="tweet",
            as_of=instant,
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
                as_of=instant,
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
                as_of=instant,
                weight=float(abs(options_pts)),
                direction=opt_sign,
                actor="options",
            ))

    # SEC: sec_pts > 0 = a buy signal; supporting on long, opposing on short
    if sec_hit and sec_pts > 0 and tweet_dir in ("long", "short"):
        sec_sign = "supporting" if tweet_dir == "long" else "opposing"
        legs.append(SourceLeg(
            source="sec",
            as_of=instant,
            weight=float(sec_pts),
            direction=sec_sign,
            actor="sec",
        ))

    # Recency filter: drop any leg outside its source's freshness cap
    fresh_legs = filter_fresh(legs, now=instant, settings=settings)

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
    burst_analysis: Optional["_BurstAnalysis"] = None, settings, now, min_purchase_dollars=250_000.0,) -> int:
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



def score_calculation(ticker, inputs, *, base_score=0, direction="long", settings, now, min_purchase_dollars=250_000.0,):
    catalyst = inputs.catalyst
    sec_hit, sec_summary = inputs.sec_hit, inputs.sec_summary
    social_data, technical = inputs.social_data, inputs.technical
    analyst_groups, options, youtube = inputs.analyst_groups, inputs.options, inputs.youtube
    metrics = {}
    m = settings.get("scoring.multipliers", {})
    # Cheap subtotals (no LLM) are computed BEFORE the LLM guard so the
    # flag-gated skip below can decide whether the LLM call could ever change
    # the alert outcome. (Reorder for #16 — math is unchanged.)
    if isinstance(analyst_groups, dict):
        opposing_analysts = list(dict.fromkeys(analyst_groups.get("opposing", [])))
        opposing_set = set(opposing_analysts)
        other_analysts = [
            analyst for analyst in dict.fromkeys(analyst_groups.get("aligned", []))
            if analyst not in opposing_set
        ]
    else:
        # Identity-only rows carry no direction and cannot count as agreement.
        other_analysts = []
        opposing_analysts = []
    max_analysts = settings.get("scoring.multipliers.max_additional_analysts", 3)
    per_analyst = m.get("additional_analyst", 20)
    flat_analyst_pts = min(len(other_analysts), max_analysts) * per_analyst
    analyst_pts = flat_analyst_pts
    # I2 (signal-features-2026-06-09, flag OFF default): weight each contributing
    # analyst by track record. Flag OFF -> analyst_pts stays the flat
    # min(len,3)*20 above (byte-identical). With the flag on, sum 20*weight per
    # analyst where weight = clamp(2 * wilson_lb, discount_floor, weight_cap):
    # a Wilson lower-bound of 0.5 -> weight 1.0 (neutral 20); sample_count<min_n
    # (10) -> precision None -> neutral 20; a chronic loser floors at 0.5x.
    if settings.get("features.analyst_accuracy_weight.enabled", False) and other_analysts:
        min_n = int(settings.get("features.analyst_accuracy_weight.min_n", 10))
        discount_floor = float(settings.get("features.analyst_accuracy_weight.discount_floor", 0.5))
        weight_cap = float(settings.get("features.analyst_accuracy_weight.weight_cap", 1.5))
        weighted = 0.0
        for analyst in other_analysts[:max_analysts]:
            # #62: horizon resolves via db.analyst_horizon() — '1h' (no rows, so
            # neutral) until scoring.analyst_accuracy_weight.enabled flips it to 24h.
            lb = yield ScoreRequest("precision", (analyst, min_n))
            if lb is None:
                weight = 1.0  # thin/absent record -> neutral 20
            else:
                weight = max(discount_floor, min(weight_cap, 2.0 * lb))
            weighted += per_analyst * weight
        # Per-call notional cap: banked accuracy can't be fully spent on one pump.
        # Cap the uplift above the flat baseline so a stack of high-track-record
        # analysts can't run away (default cap = one extra analyst-unit, 20).
        uplift_cap = float(settings.get("features.analyst_accuracy_weight.uplift_cap", per_analyst))
        analyst_pts = int(round(min(weighted, flat_analyst_pts + uplift_cap)))
        log.info(
            "[I2 shadow] $%s analyst_pts weighted=%d flat=%d (n_analysts=%d)",
            ticker, analyst_pts, flat_analyst_pts, len(other_analysts),
        )
    # Opposing signed calls are disagreement, never agreement. Apply the same
    # per-analyst magnitude as a subtraction, capped by the existing analyst cap.
    analyst_pts -= min(len(opposing_analysts), max_analysts) * per_analyst
    news_pts = _get_catalyst_score(catalyst.catalyst_type, settings=settings, now=now, min_purchase_dollars=min_purchase_dollars) if (catalyst and catalyst.passed) else 0
    # I12 (signal-features-2026-06-09, flag OFF default): add a magnitude bonus
    # on TOP of the base catalyst tier for a FRESH earnings print carrying a
    # numeric surprise %. Flag OFF -> news_pts stays the base tier above
    # (byte-identical; this block never runs). With the flag on: +5 per 10%
    # surprise, cap +15, behind an absolute-$/denominator floor and a freshness
    # gate (a near-zero or $0.01/$0.001 beat, or a stale recap, adds 0).
    if (
        settings.get("features.earnings_magnitude.enabled", False)
        and catalyst and catalyst.passed
        and catalyst.catalyst_type in ("Earnings Report", "Earnings Beat")
    ):
        magnitude_bonus = _earnings_magnitude_bonus(catalyst, settings=settings, now=now, min_purchase_dollars=min_purchase_dollars)
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
    if settings.get("features.sec_graduated_scoring.enabled", False) and sec_hit:
        grad, min_purchase_dollars = yield ScoreRequest("sec_graduation")
        recency_days = int(settings.get("features.sec_graduated_scoring.recency_days", 5))
        if grad.max_buy_dollars > 0 and not _is_txn_recent(grad.txn_date, recency_days, settings=settings, now=now, min_purchase_dollars=min_purchase_dollars):
            # Stale buy -> drop the large/csuite eligibility, keep the Form-4 floor.
            grad.max_buy_dollars = 0.0
        sec_pts = _graduate_sec_pts(grad, sec_pts, settings=settings, now=now, min_purchase_dollars=min_purchase_dollars)
        log.info(
            "[I5 shadow] $%s sec_pts graduated=%d (role=%s buy$=%.0f planned=%s "
            "plan_seen=%s net_sell=%s date=%s)",
            ticker, sec_pts, grad.reporter_role, grad.max_buy_dollars,
            grad.is_planned, grad.plan_flag_seen, grad.net_selling, grad.txn_date,
        )
    tech_pts = compute_technical_score(technical, settings=settings, now=now, min_purchase_dollars=min_purchase_dollars)
    # I13 (signal-features-2026-06-09): thread corroborators into the social
    # breakdown so the z-score gate can require a hard independent source.
    # Flag OFF -> extra kwargs are default (False/0) -> byte-identical path.
    social_breakdown = _compute_social_breakdown(
        social_data,
        sec_hit=sec_hit,
        catalyst_passed=bool(catalyst and catalyst.passed),
        technical_pts=tech_pts,
     settings=settings, now=now, min_purchase_dollars=min_purchase_dollars)

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
    if (settings.get("features.options_graduated_scoring.enabled", False)
            and options and options.has_unusual_activity):
        options_pts = _graduate_options_pts(options, direction, settings=settings, now=now, min_purchase_dollars=min_purchase_dollars)
        options.horizon = settings.get("features.options_graduated_scoring.horizon", "1-2d")
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
    if settings.get("features.youtube_score.level_confluence", False) and youtube and youtube_pts and technical:
        tech_price = getattr(technical, "price", 0.0) or 0.0
        atr = getattr(technical, "atr14", None)
        if tech_price > 0 and atr:
            band_pct = float(settings.get("features.youtube_score.confluence_band_pct", 0.015))
            bonus_unit = int(settings.get("features.youtube_score.confluence_bonus", 3))
            cap = int(settings.get("features.youtube_score.confluence_cap", 6))
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
    if settings.get("scoring.skip_llm_below_threshold", False):
        cheap_subtotal = analyst_pts + news_pts + sec_pts + tech_pts + youtube_pts + options_pts
        medium_confidence = settings.get("precision_engine.thresholds.medium_confidence", 65)
        if base_score + cheap_subtotal + llm_max < medium_confidence:
            skip_llm = True
            log.info("skipped LLM scorer (cannot reach threshold) for $%s", ticker)

    if (technical or catalyst) and not skip_llm:
        llm_score, llm_reasoning = yield ScoreRequest("llm_score")

    llm_pts = int(llm_score / 100 * llm_max)

    # A3: Bayesian multi-source consolidation (always runs for shadow data)
    shadow_only = not settings.get("features.cross_source_consolidation.enabled", False)
    cons_result = yield ScoreRequest("consolidation", (shadow_only,))
    consensus_boost = cons_result.consensus_boost if not shadow_only else 0

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
    if settings.get("features.manufactured_agreement_gate.enabled", False) and consensus_boost > 0:
        e6_window = int(settings.get(
            "features.manufactured_agreement_gate.burst_window_sec",
            _E6_BURST_WINDOW_SEC_DEFAULT,
        ))
        e6_thresh = float(settings.get(
            "features.manufactured_agreement_gate.similarity_threshold",
            _E6_SIMILARITY_DEFAULT,
        ))
        e6_min_accts = int(settings.get(
            "features.manufactured_agreement_gate.min_accounts",
            _E6_MIN_ACCOUNTS_DEFAULT,
        ))
        signal_rows = yield ScoreRequest("burst", (e6_window,))
        burst_detected, burst_accounts = _analyse_burst(
            signal_rows,
            similarity_threshold=e6_thresh,
            burst_window_sec=float(e6_window),
            min_accounts=e6_min_accts,
         settings=settings, now=now, min_purchase_dollars=min_purchase_dollars)
        has_corroboration = _check_e6_corroboration(
            burst_detected,
            sec_hit=sec_hit,
            catalyst_passed=bool(catalyst and catalyst.passed),
            options_has_activity=bool(options and options.has_unusual_activity),
         settings=settings, now=now, min_purchase_dollars=min_purchase_dollars)
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
     settings=settings, now=now, min_purchase_dollars=min_purchase_dollars)
    n_opposing = _count_opposing_actors(
        tweet_direction=direction,
        options=options,
        options_pts=options_pts,
        youtube=youtube,
        youtube_pts=youtube_pts,
        sec_hit=sec_hit,
        sec_pts=sec_pts,
        burst_analysis=burst_analysis,
     settings=settings, now=now, min_purchase_dollars=min_purchase_dollars)
    if opposing_analysts:
        n_opposing += 1
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

    # I3 downgrade safeguard: require >= min_actors DISTINCT opposing sources before a
    # non-zero contradiction_index reaches the consumer, so one lone opposing source can
    # never sink a thinly-supported STRONG. n_opposing < min -> result_ci=0.0 makes both
    # downgrade sites no-op (engine verdict on 0.0 = below_threshold; main.py A1 skips).
    _min_opp = int(settings.get("features.contradiction_index_live.min_actors", 2))
    result_ci = (
        computed_ci
        if (settings.get("features.contradiction_index_live.enabled", False) and n_opposing >= _min_opp)
        else 0.0
    )

    # -----------------------------------------------------------------
    # E1 — FINRA daily short-volume confluence term (signal-features-2026-06-09)
    # flag: features.finra_short_volume.enabled (default OFF)
    #
    # Adds a small capped term (+5 max) when the ticker's latest short_pct is
    # >2 sigma above its own 30-day baseline AND the row is EOD-fresh (recency_window
    # "finra_short_volume" cap, 1440 min).  Flag OFF -> ZERO DB reads on the hot
    # path; the term contributes 0 and breakdown is byte-identical.
    #
    # Provenance label (hard render rule, never change):
    #   "short-volume %, MM-hedging-inflated proxy"
    # -----------------------------------------------------------------
    finra_pts = 0
    if settings.get("features.finra_short_volume.enabled", False):
        try:
            latest_finra = yield ScoreRequest("finra_volume")
            if latest_finra is not None:
                baseline_finra = yield ScoreRequest("finra_baseline")
                finra_pts = _compute_finra_short_volume_pts(
                    short_pct=latest_finra["short_pct"],
                    baseline=baseline_finra,
                    finra_published_at=latest_finra["finra_published_at"],
                    direction=direction,
                 settings=settings, now=now, min_purchase_dollars=min_purchase_dollars)
                if finra_pts:
                    log.info(
                        "[E1] $%s short_pct=%.3f finra_pts=%d "
                        "(provenance='short-volume %%, MM-hedging-inflated proxy')",
                        ticker, latest_finra["short_pct"], finra_pts,
                    )
        except Exception as _e1_exc:
            log.warning("[E1] DB lookup failed for $%s: %s", ticker, _e1_exc)
            finra_pts = 0
    breakdown.finra_short_volume = finra_pts

    # -----------------------------------------------------------------
    # r12 — FINRA settlement short-interest days-to-cover confluence leg
    # flag: features.short_interest.enabled (default OFF)
    #
    # Adds a small capped term (+3 max) when the ticker's latest FINRA settlement
    # shows elevated days-to-cover AND a rising crowded short, on a LONG signal
    # (squeeze-fuel confluence). Flag OFF -> ZERO DB reads on the hot path; the
    # term is 0 and the breakdown is byte-identical. Confluence-only, never a trigger.
    # -----------------------------------------------------------------
    dtc_pts = 0
    if settings.get("features.short_interest.enabled", False):
        try:
            latest_si = yield ScoreRequest("short_interest")
            if latest_si is not None:
                dtc_pts = _compute_days_to_cover_pts(latest_si, direction=direction, settings=settings, now=now, min_purchase_dollars=min_purchase_dollars)
                if dtc_pts:
                    log.info(
                        "[r12] $%s days_to_cover=%.2f pct_change=%s -> +%d "
                        "(settlement short interest, %s)",
                        ticker, latest_si.get("days_to_cover") or 0.0,
                        latest_si.get("pct_change"), dtc_pts, latest_si.get("settlement_date"),
                    )
        except Exception as _r12_exc:
            log.warning("[r12] DB lookup failed for $%s: %s", ticker, _r12_exc)
            dtc_pts = 0
    breakdown.days_to_cover = dtc_pts

    # -----------------------------------------------------------------
    # r17 — post-earnings-announcement drift (PEAD) confluence leg
    # flag: features.pead.enabled (default OFF)
    #
    # Adds a small capped term (+3 max) when realized post-print drift is
    # drift-CONSISTENT and its continuation direction matches the signal, ONLY after
    # earnings_magnitude's 5-day window (no double-count). Flag OFF -> no earnings/
    # price fetch on the hot path; term 0; breakdown byte-identical.
    # -----------------------------------------------------------------
    pead_pts = 0
    if settings.get("features.pead.enabled", False):
        try:
            pead_res = yield ScoreRequest("pead")
            pead_pts = _compute_pead_pts(pead_res, direction=direction, settings=settings, now=now, min_purchase_dollars=min_purchase_dollars)
            if pead_pts:
                log.info(
                    "[r17] $%s pead=%s drift=%.2f%% days_since=%d -> +%d",
                    ticker, pead_res.get("classification"), pead_res.get("drift_pct"),
                    pead_res.get("days_since"), pead_pts,
                )
        except Exception as _r17_exc:
            log.warning("[r17] PEAD compute failed for $%s: %s", ticker, _r17_exc)
            pead_pts = 0
    breakdown.pead = pead_pts

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
        n_opposing=n_opposing,
    )



from consensus_engine.alerts.all_command import levels, structured_fields
from consensus_engine.analysis import indicators
from consensus_engine.analysis.research_contracts import ResearchRequest

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



def research_calculation(ticker, data, *, settings, epoch, today, start, remaining, telemetry):
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
    # Level-sanity guard (item C extension, 2026-06-10): drop wild levels (>=2x or <=0.5x
    # live price) BEFORE they become TP anchors.  Matches the always-on gate in alfred.py
    # and wolf_news.py.  A mis-attributed stored level (NVDA 700 from a QQQ/SPY video) can
    # still reach !all as an unsuppressed row before the DB sweep runs; this gate is the
    # last line of defense before TP1/2/3 are emitted.
    yt_levels = yield ResearchRequest("sane_levels", yt_levels)
    swing_candles = _swing_candles(data["technical_long"])
    yt_anchors = levels.extract_anchors_from_youtube_levels(yt_levels, settings=settings)
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
    yield ResearchRequest("direction_parity", {
        "event_id": f"{ticker}:{int(start)}", "ticker": ticker,
        "legacy_direction": _legacy_direction,
        "structured_direction": _structured_direction,
        "agree": _legacy_normalized == _structured_normalized, "ts": epoch,
    })
    _direction_source = settings.get("all_command.direction_source", "legacy")
    if _direction_source == "structured":
        direction_str = _structured_direction
    else:
        direction_str = _legacy_direction
    gap_deadline = epoch + min(20.0, remaining())
    # Feature E — sector label for the macro-risk query disambiguation. The
    # peer_strength result's "group" is a human-readable sector/industry name
    # ("Semiconductors", "Technology"); far better in a search query than the
    # ETF symbol from sector_map.yaml. Empty string when unavailable.
    _peer_strength = data.get("peer_strength")
    _macro_sector = ""
    if isinstance(_peer_strength, dict):
        _macro_sector = str(_peer_strength.get("group") or "")
    try:
        gap_fill_result = yield ResearchRequest("gap_fill", dict(
            ticker=ticker,
            anchors_count=len(initial_anchors),
            sec_filings=sec_filings_list,
            has_event_date=bool(earnings_iso_str),
            direction=direction_str,
            deadline=gap_deadline,
            company_name=data.get("company_name") or "",
            sector=_macro_sector,
        ))
    except Exception as exc:  # noqa: BLE001
        log.warning("aggregator: gap_fill failed: %s", exc)
        gap_fill_result = {
            "harvested_anchors_snippets": [],
            "eight_k_summary_snippets": [],
            "event_date_snippets": [],
            "catalyst_research_snippets": [],
            "macro_risk_snippets": [],
        }

    yield ResearchRequest("stage", "gap_fill")
    web_anchor_snippets = list(gap_fill_result.get("harvested_anchors_snippets", []))
    web_anchors = levels.extract_anchors_from_search_snippets(
        web_anchor_snippets,
        current_price=_current_price(data["technical_long"]) or 0.0,
    )

    all_anchors = levels.cluster_anchors(initial_anchors + web_anchors, 0.005)
    current_price = _current_price(data["technical_long"]) or 0.0
    supports, resistances = levels.rank_anchors(all_anchors, current_price, ticker=ticker, settings=settings, telemetry=telemetry, now=epoch)
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
            _d = (_ed - today).days
            if _d >= 0:
                _earnings_days_for_plan = _d
        except (ValueError, TypeError):
            pass

    # Smart technical-levels engine (full-audit Wave 2). Flag-gated; default OFF
    # → this whole block is skipped and behavior is byte-identical to today.
    _engine_live = False
    if settings.get("all_command.levels.technical_engine_enabled", False):
        # The whole engine (shadow OR live) must NEVER break !all — wrap it, and
        # read daily_candles defensively (.get) since a fetch failure can omit it.
        try:
            _candles = data.get("daily_candles") if isinstance(data.get("daily_candles"), list) else []
            _eng_atr = _atr14_for_plan
            if (_eng_atr is None or _eng_atr <= 0) and _candles:
                _eng_atr = indicators.atr(
                    [c["high"] for c in _candles], [c["low"] for c in _candles],
                    [c["close"] for c in _candles], 14)
            # 52wk boundaries: `data["snapshot"]` defaults to None, so `or {}` (NOT
            # .get("snapshot", {})) — and read the raw wk52_high/wk52_low keys added
            # to snapshot.py in Wave 0. Clamp to spot when snapshot is None/missing.
            _snap = data.get("snapshot") or {}
            tech_anchors = levels.build_technical_anchors(
                _candles, current_price, _eng_atr or 0.0,
                wk52_high=_snap.get("wk52_high") or current_price,
                wk52_low=_snap.get("wk52_low") or current_price, settings=settings,
            )
            if settings.get("all_command.levels.technical_engine_shadow_mode", True):
                # Shadow: compute the parallel plan, log it, DON'T change the posted plan.
                _baseline_plan = levels.select_trade_plan(
                    supports, resistances, spot=current_price,
                    atr14=_atr14_for_plan, direction=_direction_for_plan,
                    earnings_days=_earnings_days_for_plan, engine_on=False, settings=settings, telemetry=telemetry, now=epoch)
                _shadow_supports, _shadow_resist = levels.rank_anchors(
                    levels.cluster_anchors(all_anchors + tech_anchors, 0.005),
                    current_price, ticker=ticker, settings=settings, telemetry=telemetry, now=epoch)
                _shadow_plan = levels.select_trade_plan(
                    _shadow_supports, _shadow_resist,
                    spot=current_price, atr14=_eng_atr,
                    direction=_direction_for_plan,
                    earnings_days=_earnings_days_for_plan, engine_on=True, settings=settings, telemetry=telemetry, now=epoch)
                yield ResearchRequest("smart_shadow", dict(
                    ticker=ticker, spot=current_price, atr14=_eng_atr,
                    crowd_anchor_count=len(supports) + len(resistances),
                    tech_anchor_count=len(_shadow_supports) + len(_shadow_resist),
                    baseline_plan=_baseline_plan, shadow_plan=_shadow_plan))
            else:
                # Live: merge tech anchors into the pool before rank.
                all_anchors = levels.cluster_anchors(all_anchors + tech_anchors, 0.005)
                supports, resistances = levels.rank_anchors(
                    all_anchors, current_price, ticker=ticker, settings=settings, telemetry=telemetry, now=epoch)
                _engine_live = True
        except Exception as exc:  # noqa: BLE001 — smart-levels must never break !all
            log.warning("aggregator: smart-levels engine failed: %s", exc)
            _engine_live = False

    trade_plan = levels.select_trade_plan(
        supports, resistances,
        spot=current_price,
        atr14=_atr14_for_plan,
        direction=_direction_for_plan,
        earnings_days=_earnings_days_for_plan,
        engine_on=_engine_live, settings=settings, telemetry=telemetry, now=epoch,
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
    confidence = structured_fields.compute_confidence_label(final_score, threshold=settings.get("precision_engine.thresholds.high_confidence", 80))
    earnings_iso = _earnings_iso(data["decision_snapshots"]) or data.get("next_earnings_iso")
    timeframe = structured_fields.compute_breakout_timeframe(
        ticker, earnings_iso, data["options_unusual"], today=today,
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
    nasdaq_events = yield ResearchRequest("nasdaq")
    next_catalyst_days, next_catalyst_kind, next_catalyst_mechanism = (
        structured_fields.compute_next_catalyst(
            earnings_iso, data["options_unusual"], extra_events=nasdaq_events, today=today,
        )
    )
    # #25 (full-audit-2026-06-06) — realized close-to-close daily move, blended
    # into the swing-horizon denominator when the flag is on. None (the
    # default) keeps the ATR-only horizon.
    _realized_daily_move = structured_fields.compute_realized_daily_move(
        data.get("daily_candles") if isinstance(data.get("daily_candles"), list) else []
    )
    swing_horizon_days, swing_horizon_band, _swing_note = (
        structured_fields.compute_swing_horizon(
            current_price, tp1, atr14, earnings_iso,
            realized_daily_move=_realized_daily_move, today=today,
            horizon_realized_vol=settings.get("all_command.horizon_realized_vol", False),
        )
    )
    expected_move_typical, expected_move_high_vol, magnitude_band_label = (
        structured_fields.compute_magnitude_band(
            atr14, swing_horizon_days, current_price, atr_90d_high_pct=None,
        )
    )

    # Stage-3 — the options-chain legs ride along on compute_max_pain's dict
    # (gex/iv_skew/oi_pinning as ADDITIVE keys); split them onto their own
    # StructuredFields attrs here. Existing max_pain consumers are unaffected.
    _mp_dict = data.get("max_pain") if isinstance(data.get("max_pain"), dict) else {}

    # Stage-4 vol-context (k7 IV-vs-RV tag, r9 squeeze) — descriptive-only, each
    # gated behind its flag so the OFF path is byte-identical (no field, and for
    # k7 no compute_em fetch upstream). Both reuse already-gathered data; never
    # touch score_breakdown / confidence / direction / any trigger.
    _candles_for_vol = (
        data.get("daily_candles") if isinstance(data.get("daily_candles"), list) else []
    )
    _iv_rv_tag = None
    if settings.get("features.iv_rv_tag.enabled", False):
        _iv_rv_tag = structured_fields.compute_iv_rv_tag(
            data.get("iv_rv_atm_iv"),
            _candles_for_vol,
            rich_threshold=settings.get("features.iv_rv_tag.rich_threshold", 1.25),
            cheap_threshold=settings.get("features.iv_rv_tag.cheap_threshold", 0.85),
        )
    _squeeze_state = None
    if settings.get("features.vol_squeeze.enabled", False):
        from consensus_engine.analysis import patterns as _patterns
        _squeeze_state = _patterns.compute_squeeze(
            _candles_for_vol,
            period=settings.get("features.vol_squeeze.period", 20),
            bb_mult=settings.get("features.vol_squeeze.bb_mult", 2.0),
            kc_mult=settings.get("features.vol_squeeze.kc_mult", 1.5),
        )
    # r17 PEAD — descriptive post-earnings-drift read (embed-only, NOT narrator).
    # Reuses the already-fetched earnings recap; fetches its own dated price series
    # (daily_candles carry no dates). Gated OFF -> no compute/fetch, field absent.
    _pead = None
    if settings.get("features.pead.enabled", False):
        _pead = yield ResearchRequest("pead")

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
        gex=_mp_dict.get("gex"),
        iv_skew=_mp_dict.get("iv_skew"),
        oi_pinning=_mp_dict.get("oi_pinning"),
        skew_index=data.get("skew_index"),
        iv_rv_tag=_iv_rv_tag,
        squeeze_state=_squeeze_state,
        pead=_pead,
        peer_strength=data.get("peer_strength"),
        snapshot=data.get("snapshot"),
        earnings_move=data.get("earnings_move"),
        tweets_today=data.get("tweets_today"),
        stocktwits=data.get("stocktwits"),
        risk_reward=risk_reward,
        relative_volume=structured_fields.compute_relative_volume(
            data.get("daily_candles") if isinstance(data.get("daily_candles"), list) else []
        ),
    )

    return {
        "structured": structured, "score_breakdown": score_breakdown,
        "trade_plan": trade_plan, "supports": supports, "resistances": resistances,
        "all_anchors": all_anchors, "gap_fill_result": gap_fill_result,
    }


from consensus_engine.alerts.all_command import output_filter


async def synthesize_with_gates(*, ticker, messages, structured, deadline_seconds,
                                invoke, telemetry, epoch, risk_gate_strict,
                                contradiction_system):
    """Original narrator retry/adoption gates with explicit effect boundaries."""
    from consensus_engine.alerts.all_command import quality_bar as _qb

    telemetry({"ts": epoch(), "event": "narrator_cache_miss", "ticker": ticker})
    raw = await invoke(messages, deadline_seconds)
    telemetry({"ts": epoch(), "event": "synth_initial", "ticker": ticker})
    if not raw:
        return "", "fallback_data_only"

    # If the narrator dropped one of the required sections
    # (TL;DR / ## Risk Considerations), retry once with a hardened
    # prompt that lists the missing tokens explicitly. After one retry, we
    # accept whatever comes back and let output_filter handle contradictions.
    if not _qb.has_required_sections(raw):
        missing = _qb.missing_required_sections(raw)
        log.warning(
            "narrator: missing required sections %s — re-prompting once", missing,
        )
        telemetry({
            "ts": epoch(), "event": "synth_retry",
            "reason": "missing_sections", "ticker": ticker, "missing": missing,
        })
        hardened_sections = list(messages)
        hardened_sections[-1] = dict(hardened_sections[-1])
        hardened_sections[-1]["content"] = (
            hardened_sections[-1].get("content", "")
            + "\n\nMISSING SECTIONS — your previous draft dropped: "
            + ", ".join(missing)
            + ". Re-emit the FULL narrative with EVERY required section "
              "header present verbatim."
        )
        retried = await invoke(
            hardened_sections, max(1.0, deadline_seconds * 0.5),
        )
        if retried:
            raw = retried

    # all-risk-section (Feature B) — hard gate behind the prompt's "no price
    # levels in Risk Considerations" rule. Prompt-only bans proved unreliable on
    # the free-model chain (live NVDA restated the stop 6×), so re-prompt once if
    # the stop-loss price literal leaks into the merged risk section.
    _stop_price = getattr(structured, "sl", None)
    # #24 strict price gate (flag all_command.risk_price_gate_strict, default
    # off). When on, the gate also catches leaked entry/target/buy-zone prices,
    # not just the stop literal. Flag off → byte-identical to the stop-only check.
    _risk_gate_strict = risk_gate_strict
    _current_price = getattr(structured, "current_price", None)
    _price_levels = [
        v for v in (
            _stop_price,
            getattr(structured, "tp1", None),
            getattr(structured, "tp2", None),
            getattr(structured, "tp3", None),
            getattr(structured, "buy_zone_low", None),
            getattr(structured, "buy_zone_high", None),
            _current_price,
        )
        if v is not None
    ]
    _risk_violations = _qb.risk_section_violations(
        raw, _stop_price,
        price_levels=_price_levels,
        current_price=_current_price,
        strict=_risk_gate_strict,
    )
    if _risk_violations:
        log.warning(
            "narrator: risk-section violations %s — re-prompting once",
            _risk_violations,
        )
        telemetry({
            "ts": epoch(), "event": "synth_retry",
            "reason": "risk_violation", "ticker": ticker,
        })
        hardened_risk = list(messages)
        hardened_risk[-1] = dict(hardened_risk[-1])
        hardened_risk[-1]["content"] = (
            hardened_risk[-1].get("content", "")
            + "\n\nRISK SECTION FIX — your previous draft violated: "
            + "; ".join(_risk_violations)
            + ". Re-emit the FULL narrative. In `## Risk Considerations` do NOT "
              "mention the stop-loss or ANY price level — the trader already "
              "sees the stop in the Trade Plan. Replace every such line with a "
              "specific, evidence-cited business / macro / positioning risk."
        )
        retried_risk = await invoke(
            hardened_risk, max(1.0, deadline_seconds * 0.5),
        )
        # all-risk-section v2 Fix #3 — re-validate the retry before adopting it.
        # A stubborn free-tier model can leak the stop price twice; adopting an
        # unchecked retry let a still-bad output through. Keep the ORIGINAL raw
        # if the retry still violates (or is empty).
        if retried_risk and not _qb.risk_section_violations(
            retried_risk, _stop_price,
            price_levels=_price_levels,
            current_price=_current_price,
            strict=_risk_gate_strict,
        ):
            raw = retried_risk
        else:
            log.warning(
                "narrator: risk-section retry still violated (or empty) — keeping original",
            )

    # Retry-once with hardened prompt if output_filter detects contradiction.
    async def _retry_fn() -> str:
        telemetry({
            "ts": epoch(), "event": "synth_retry",
            "reason": "contradiction", "ticker": ticker,
        })
        hardened = list(messages)
        hardened[0] = dict(hardened[0])
        hardened[0]["content"] = (
            contradiction_system()
        )
        retry_deadline = max(1.0, deadline_seconds * 0.5)
        return await invoke(hardened, retry_deadline)

    sanitized, status = await output_filter.sanitize_or_retry(
        raw, structured, retry_fn=_retry_fn,
    )
    return sanitized, status


def compute_score(ticker, inputs, settings, clock, *, base_score=0, direction='long'):
    """Drive the shared score using supplied value records only.

    A missing optional source is explicit unavailable data, never a collection
    fallback. In particular consolidation is not re-entered through the bot.
    """
    from consensus_engine.analysis.research_contracts import ScoreInputs, thaw_value
    if type(inputs) is not ScoreInputs:
        raise TypeError('compute_score requires immutable ScoreInputs')
    prepared = SimpleNamespace(
        catalyst=inputs.catalyst.model() if inputs.catalyst else None,
        technical=inputs.technical.model() if inputs.technical else None,
        options=inputs.options.model() if inputs.options else None,
        youtube=inputs.youtube.model() if inputs.youtube else None,
        sec_hit=inputs.sec_hit, sec_summary=inputs.sec_summary,
        analyst_groups={'aligned': list(inputs.aligned_analysts), 'opposing': list(inputs.opposing_analysts)},
        social_data=thaw_value(inputs.social_data),
    )
    calculation = score_calculation(
        ticker, prepared, settings=settings, now=clock.epoch,
        min_purchase_dollars=settings.min_purchase_dollars,
        base_score=base_score, direction=direction,
    )
    response = None
    while True:
        try:
            request = calculation.send(response)
        except StopIteration as finished:
            return finished.value
        if request.kind == 'precision':
            # Absent precision has exactly the legacy thin-record weight.
            response = inputs.precision.get(request.arguments[0])
        elif request.kind == 'sec_graduation':
            response = (_SecGraduation(**thaw_value(inputs.sec_graduation or {})),
                        settings.min_purchase_dollars)
        elif request.kind == 'llm_score':
            response = inputs.llm_score
        elif request.kind == 'consolidation':
            response = inputs.consolidation
        elif request.kind == 'burst':
            response = thaw_value(inputs.burst_rows)
        elif request.kind == 'finra_volume':
            response = thaw_value(inputs.finra_volume)
        elif request.kind == 'finra_baseline':
            if inputs.finra_baseline is None:
                raise ValueError('A completed FINRA row requires an explicit baseline result')
            response = thaw_value(inputs.finra_baseline)
        elif request.kind == 'short_interest':
            response = thaw_value(inputs.short_interest)
        elif request.kind == 'pead':
            response = thaw_value(inputs.pead)
        else:
            raise ValueError('Unknown score data request')


async def compute_research(ticker, inputs, services):
    """Compute restricted public research without any bot collection or delivery."""
    from consensus_engine.analysis.research_contracts import (
        ResearchInputs, ResearchServices, ResearchOutput, GapFillRequest, GapFillResult,
        SynthesisRequest, SourceStatus, thaw_value,
    )
    from consensus_engine.analysis.level_display_sanity import classify_level_from_quote, LevelVerdict
    if type(inputs) is not ResearchInputs or type(services) is not ResearchServices:
        raise TypeError('Explicit typed research inputs and services are required')
    if not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,9}', ticker):
        raise ValueError('Invalid research ticker')
    loop = asyncio.get_running_loop()
    deadline = loop.time() + services.deadline_seconds
    remaining = lambda: max(0.0, deadline - loop.time())
    evidence = list(inputs.evidence)
    statuses = list(inputs.source_statuses)
    score = compute_score(ticker, inputs.score, services.settings, services.clock)
    surfaced = [status.source_id for status in inputs.source_statuses if status.status == 'completed']
    data = {
        'score': score,
        'technical_long': inputs.technical_long.model() if inputs.technical_long else None,
        'technical_short': inputs.technical_short.model() if inputs.technical_short else None,
        'news_catalyst': inputs.news_catalyst.model() if inputs.news_catalyst else None,
        'options_unusual': inputs.options_unusual.model() if inputs.options_unusual else None,
        'yt_levels': thaw_value(inputs.youtube_levels),
        'daily_candles': thaw_value(inputs.daily_candles),
        'decision_snapshots': [], 'next_earnings_iso': inputs.earnings_date,
        'sec_filings': [], 'company_name': inputs.company_name,
    }
    calculation = research_calculation(
        ticker, data, settings=services.settings, epoch=services.clock.epoch,
        today=services.clock.pacific_date, start=services.clock.monotonic,
        remaining=remaining, telemetry=services.telemetry,
    )
    response = None
    while True:
        try:
            request = calculation.send(response)
        except StopIteration as finished:
            computed = finished.value
            break
        if request.kind == 'sane_levels':
            response = [row for row in request.value if classify_level_from_quote(
                ticker, row['price'], inputs.sanity_quote) is not LevelVerdict.DROP]
        elif request.kind == 'gap_fill':
            value = request.value
            public_request = GapFillRequest(**{key: value[key] for key in (
                'ticker', 'anchors_count', 'has_event_date', 'direction', 'deadline', 'company_name', 'sector')})
            try:
                result = await asyncio.wait_for(services.gap_fill(public_request),
                                                timeout=min(20.0, remaining()))
            except Exception:
                response = dataclasses.asdict(GapFillResult())
                statuses.append(SourceStatus('gap_fill', 'shared-research-v1', 'failed', None,
                                             'Public gap fill is unavailable'))
            else:
                if type(result) is not GapFillResult:
                    raise TypeError('Gap fill must return typed public results')
                evidence.extend(result.evidence)
                statuses.extend(result.source_statuses)
                response = {key: list(val) for key, val in dataclasses.asdict(result).items()}
        elif request.kind in {'direction_parity', 'smart_shadow'}:
            services.telemetry({'event': request.kind, 'ticker': ticker, 'data': request.value})
            response = None
        elif request.kind == 'stage':
            response = None
        elif request.kind == 'nasdaq':
            # No provider is enabled by this computation boundary. Task 6 supplies
            # separately authorized calendar records before making this live.
            response = []
        elif request.kind == 'pead':
            response = thaw_value(inputs.score.pead)
        else:
            raise ValueError('Unknown research data request')
    structured = computed['structured']
    gap_result = computed['gap_fill_result']
    news = _build_news_snippets(data['news_catalyst'], gap_result)
    catalyst_news = []
    for snippet in (gap_result.get('catalyst_research_snippets') or [])[:6]:
        if isinstance(snippet, str) and snippet.strip():
            if snippet.startswith('[cat_') and '] ' in snippet:
                snippet = snippet.split('] ', 1)[1]
            catalyst_news.append(snippet)
    macro_news = [snippet for snippet in (gap_result.get('macro_risk_snippets') or [])[:5]
                  if isinstance(snippet, str) and snippet.strip()]
    # External prose remains evidence, never instruction. The synthesis service
    # receives bounded strings and explicit typed provenance, no private context.
    public_request = SynthesisRequest(
        ticker=ticker, structured_json=json.dumps(dataclasses.asdict(structured)),
        score_json=json.dumps(dataclasses.asdict(score.breakdown)),
        news=tuple((macro_news + catalyst_news + news)[:20]), sec=(),
        evidence=tuple(evidence), deadline_seconds=remaining(),
    )
    initial_messages = [{'role': 'system', 'content': 'Use only the supplied evidence and computed signal.'},
                        {'role': 'user', 'content': 'Write the public research narrative.'}]
    calls = 0

    async def invoke(messages, deadline):
        nonlocal calls
        calls += 1
        if calls > 4:
            return ''
        request = dataclasses.replace(public_request, deadline_seconds=min(deadline, remaining()),
                                      retry_instruction=(messages[0]['content'] + '\n' + messages[-1]['content'])
                                      if calls > 1 else '')
        try:
            result = await asyncio.wait_for(services.synthesis(request), timeout=request.deadline_seconds)
        except Exception:
            return ''
        if not isinstance(result, str):
            raise TypeError('Synthesis must return narrative text')
        return result[:services.max_output_chars]

    if remaining() < 10.0:
        narrative, status = '', 'skipped_low_budget'
    else:
        narrative, status = await synthesize_with_gates(
            ticker=ticker, messages=initial_messages, structured=structured,
            deadline_seconds=remaining(), invoke=invoke,
            telemetry=services.telemetry, epoch=lambda: services.clock.epoch,
            risk_gate_strict=bool(services.settings.get('all_command.risk_price_gate_strict', False)),
            contradiction_system=lambda: 'Do not contradict the computed signal or invent price levels.',
        )
    if status != 'ok':
        narrative = output_filter.render_data_only_fallback(structured, score.breakdown, surfaced)
    conflicts = (f'Opposing source groups: {score.n_opposing}',) if score.n_opposing else ()
    return ResearchOutput(
        narrative=narrative, structured=structured, score_breakdown=score.breakdown,
        evidence=tuple(evidence), conflicts=conflicts, source_statuses=tuple(statuses),
        analysis_version='shared-research-v1', narrative_status=status,
        anchors=tuple(computed['supports'][:6] + computed['resistances'][:6]),
        trade_plan=computed['trade_plan'],
    )


class MemberResearchProvider:
    """Compute from explicitly supplied public records; no live provider fallback.

    Source authorization and provider collection belong to the dashboard adapter.
    This class intentionally cannot discover bot configuration or credentials.
    """
    def __init__(self, records, services):
        from consensus_engine.analysis.research_contracts import ResearchInputs
        if any(type(value) is not ResearchInputs for value in records.values()):
            raise TypeError('Only typed public research records may be assembled')
        self._records = dict(records)
        self._services = services

    async def compute(self, ticker):
        if ticker not in self._records:
            raise ValueError('No approved public records for this ticker')
        return await compute_research(ticker, self._records[ticker], self._services)
