"""Wolf phase-4 #2: infer ranked beneficiary LONG stocks for a macro/sector thesis.

Pure ranking logic + reuse of existing READ-ONLY signals (relative strength, news
catalyst, options flow, confluence). Writes nothing itself — the caller (the precompute
cycle in main.py) persists the result to the wolf_beneficiaries table.

Design (see .claude/discover/wolf-phase4/final-plan.md §2e):
  - RS-leadership spine: peer-relative N-day relative strength is the ranking signal.
    An ABSOLUTE outperformance floor gates eligibility, so a weak bucket yields NO picks
    (never a manufactured winner — Codex C2).
  - The macro_universe map already encodes WHO benefits (the long bucket per scope+direction),
    so we always rank by BULLISH RS — no thesis-direction sign-flip (Codex C1).
  - Catalyst + options flow are CONFIRMATION that LIFT confidence when aligned; absent =>
    neutral, never penalized. Confluence is a thesis-level confidence multiplier (constant
    across candidates — it has no per-candidate discrimination).
  - Tiers: a pure-RS name caps at 🟡; 🟢 needs confidence >= 0.65 AND >= 2 aligned signals.

Isolation: reads options_flow / RS / confluence / news only; never writes any table.
"""
import json
import logging
import os
import time
from typing import Optional

import yaml

from consensus_engine import config as cfg, db
from consensus_engine.analysis.peer_comparison import compute_relative_strength
from consensus_engine.scanners.news import news_cascade

log = logging.getLogger(__name__)

_MAP_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "macro_universe.yaml")
_PEER_GROUPS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "peer_groups.yaml")
_map_cache: Optional[dict] = None
_peer_etf_index: Optional[dict] = None

# Direction of a catalyst type for confirming a LONG (Codex C3). Only clearly directional
# types count; ambiguous ones (M&A, IPO, Stock Split, Dividend, SEC Filing, Patent,
# Guidance Update, Breaking News) are neutral => no confidence boost.
_CATALYST_DIRECTION = {
    "Short Squeeze": "bullish", "Analyst Upgrade": "bullish", "Earnings Beat": "bullish",
    "FDA Approval": "bullish", "Government Contract": "bullish", "Partnership": "bullish",
    "Insider Buying": "bullish", "Product Launch": "bullish",
    "Analyst Downgrade": "bearish", "Earnings Miss": "bearish", "FDA Rejection": "bearish",
    "Insider Selling": "bearish",
}


class BeneficiaryComputeError(Exception):
    """Raised when RS data fails for too many candidates — caller skips the thesis and
    keeps the prior rows (never writes a thin/empty result)."""


def _load_map() -> dict:
    global _map_cache
    if _map_cache is None:
        try:
            with open(_MAP_PATH) as f:
                _map_cache = (yaml.safe_load(f) or {}).get("universes", {})
        except Exception as e:  # noqa: BLE001
            log.error("wolf_beneficiaries: failed to load macro_universe.yaml: %s", e)
            _map_cache = {}
    return _map_cache


def _peer_etf_members() -> dict:
    """benchmark_etf -> unioned member list, reverse-indexed from peer_groups.yaml."""
    global _peer_etf_index
    if _peer_etf_index is None:
        idx: dict[str, list[str]] = {}
        try:
            with open(_PEER_GROUPS_PATH) as f:
                groups = (yaml.safe_load(f) or {}).get("groups", {})
            for g in groups.values():
                etf = (g.get("benchmark_etf") or "").upper()
                if not etf:
                    continue
                bucket = idx.setdefault(etf, [])
                for m in g.get("members", []):
                    if m not in bucket:
                        bucket.append(m)
        except Exception as e:  # noqa: BLE001
            log.error("wolf_beneficiaries: failed to index peer_groups.yaml: %s", e)
        _peer_etf_index = idx
    return _peer_etf_index


def resolve_candidate_universe(scope_type: str, scope_key: str, direction: str) -> list[str]:
    """The candidate LONG universe for a thesis. Returns [] => omit (single-stock or unmapped).

    macro/index/asset -> curated macro_universe.yaml beneficiary_longs for (scope_key, direction);
    sector            -> union of peer_groups.yaml members whose benchmark_etf == scope_key.
    """
    if scope_type == "stock":
        return []
    key = (scope_key or "").upper()
    dirn = (direction or "").lower()
    umap = _load_map().get(key)
    if umap:
        bucket = umap.get(dirn) or {}
        return list(bucket.get("beneficiary_longs", []))
    if scope_type == "sector" and dirn == "bull":
        # Derived sector universe = the ETF's members, ranked as LONG leaders. Only valid for
        # a BULL thesis. A BEAR sector call has no long beneficiary in longs-only v1 (it would
        # be shorting the laggards — the gated short side), so omit rather than contradict the
        # thesis by surfacing the strongest names as longs.
        return list(_peer_etf_members().get(key, []))
    return []


def _quantile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation quantile of an already-sorted list."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    frac = pos - lo
    if lo + 1 >= len(sorted_vals):
        return sorted_vals[-1]
    return sorted_vals[lo] + frac * (sorted_vals[lo + 1] - sorted_vals[lo])


def _winsorized_percentiles(deltas: list[float]) -> list[float]:
    """Map each delta to a (0,1) percentile rank, winsorizing at 10th/90th when n>=5
    (robust at small n; z-scores are unstable and min-max is outlier-pinned)."""
    n = len(deltas)
    vals = list(deltas)
    if n >= 5:
        s = sorted(vals)
        lo, hi = _quantile(s, 0.10), _quantile(s, 0.90)
        vals = [min(max(v, lo), hi) for v in vals]
    order = sorted(range(n), key=lambda i: vals[i])
    pct = [0.0] * n
    for rank, i in enumerate(order, start=1):
        pct[i] = rank / (n + 1)
    return pct


def _confluence_mult(confl: Optional[dict]) -> float:
    """Thesis-level confidence multiplier from FRESH confluence only (stale/absent => 1.0)."""
    if not confl:
        return 1.0
    max_age = float(cfg.get("wolf.beneficiaries.confluence_max_age_sec", 86400))
    if (time.time() - float(confl.get("checked_at", 0) or 0)) > max_age:
        return 1.0
    tier = confl.get("combined_tier") or confl.get("tier")
    return {"critical": 1.10, "high": 1.05}.get(tier, 1.0)


async def _aligned_catalyst(ticker: str) -> tuple[Optional[str], Optional[str]]:
    """(direction, catalyst_type) for the ticker's first news catalyst, or (None, None)."""
    if not cfg.get("wolf.beneficiaries.use_catalyst", True):
        return (None, None)
    try:
        res = await news_cascade(ticker)
    except Exception as e:  # noqa: BLE001
        log.debug("wolf_beneficiaries: catalyst lookup failed for %s: %s", ticker, e)
        return (None, None)
    if not res:
        return (None, None)
    ctype = getattr(res, "catalyst_type", None)
    return (_CATALYST_DIRECTION.get(ctype), ctype)


async def _bullish_flow(ticker: str) -> bool:
    """True if recent unusual options flow leans bullish by CALL-vs-PUT premium dominance."""
    if not cfg.get("wolf.beneficiaries.use_flow", True):
        return False
    try:
        rows = await db.get_options_flow_for_ticker(ticker)
    except Exception as e:  # noqa: BLE001
        log.debug("wolf_beneficiaries: flow lookup failed for %s: %s", ticker, e)
        return False
    if not rows:
        return False
    call_prem = sum((r.get("premium_usd") or 0) for r in rows if r.get("side") == "CALL")
    put_prem = sum((r.get("premium_usd") or 0) for r in rows if r.get("side") == "PUT")
    return call_prem > put_prem and call_prem > 0


def _reason(delta: float, cat_dir: Optional[str], cat_type: Optional[str],
            flow_bull: bool, signal_count: int) -> str:
    """A terse (<=8 word) honest justification line."""
    if signal_count == 1:
        return "leads peers; unconfirmed"
    parts = [f"leads peers +{delta:.1f}%"]
    if cat_dir == "bullish" and cat_type:
        parts.append(cat_type.lower())
    if flow_bull:
        parts.append("bullish flow")
    return ", ".join(parts)


async def rank_beneficiaries(thesis: dict) -> list[dict]:
    """Rank the beneficiary LONGs for one thesis. Returns up to top_k rows (or [] to omit).

    Raises BeneficiaryComputeError if RS fails for >60% of candidates (caller keeps prior rows).
    """
    scope_type, scope_key, direction = thesis["scope_type"], thesis["scope_key"], thesis["direction"]
    candidates = resolve_candidate_universe(scope_type, scope_key, direction)
    if not candidates:
        return []

    window = int(cfg.get("wolf.beneficiaries.rs_window_days", 21))
    floor = float(cfg.get("wolf.beneficiaries.abs_rs_floor", 0.5))
    top_k = int(cfg.get("wolf.beneficiaries.top_k", 3))
    conf_floor = float(cfg.get("wolf.beneficiaries.conf_floor", 0.40))

    # 1. RS per candidate; keep only those clearing the absolute outperformance floor.
    eligible: list[dict] = []
    failed = 0
    rs_cache: dict[str, Optional[dict]] = {}
    for t in candidates:
        if t not in rs_cache:
            rs_cache[t] = await compute_relative_strength(t, window_days=window)
        rs = rs_cache[t]
        if rs is None:
            failed += 1
            continue
        if rs["delta"] > floor:
            eligible.append({"ticker": t, "delta": rs["delta"], "mode": rs["mode"]})

    total = len(candidates)
    if total and failed / total > 0.60:
        raise BeneficiaryComputeError(f"RS failed for {failed}/{total} candidates of {scope_key}")
    if not eligible:
        return []

    # 2. winsorized-percentile rank_score on eligible deltas
    for e, p in zip(eligible, _winsorized_percentiles([e["delta"] for e in eligible])):
        e["rank_score"] = p

    # 3-8. confirmation + confidence + tier per candidate
    confl = await db.get_confluence_check(thesis["id"]) if thesis.get("id") is not None else None
    confl_mult = _confluence_mult(confl)
    rows: list[dict] = []
    for e in eligible:
        t = e["ticker"]
        cat_dir, cat_type = await _aligned_catalyst(t)
        flow_bull = await _bullish_flow(t)
        data_quality = 1.0 if e["mode"] == "peers" else 0.85   # ETF-mode self-inclusion penalty
        lift = 1.0 + (0.08 if cat_dir == "bullish" else 0.0) + (0.07 if flow_bull else 0.0)
        lift = min(lift, 1.15)
        confidence = max(0.15, min(0.95, e["rank_score"] * data_quality * confl_mult * lift))
        signal_count = 1 + (1 if cat_dir == "bullish" else 0) + (1 if flow_bull else 0)
        if confidence >= 0.65 and signal_count >= 2:
            tier = "green"
        elif confidence >= conf_floor:
            tier = "yellow"
        else:
            continue   # below floor -> drop
        rows.append({
            "ticker": t, "side": "long", "score": round(e["rank_score"], 4),
            "confidence": round(confidence, 4), "tier": tier,
            "reason": _reason(e["delta"], cat_dir, cat_type, flow_bull, signal_count),
            "signals_json": json.dumps({
                "rs_delta": e["delta"], "rs_mode": e["mode"],
                "catalyst": cat_type if cat_dir == "bullish" else None,
                "flow_bullish": flow_bull, "confluence_mult": confl_mult,
                "signal_count": signal_count,
            }),
        })
    rows.sort(key=lambda r: r["confidence"], reverse=True)
    return rows[:top_k]


async def run_cycle() -> int:
    """Precompute beneficiaries for every active macro/sector thesis; persist to
    wolf_beneficiaries. Returns the number of theses written. Throttled per thesis by
    computed_at age. Each thesis is computed FULLY in memory, then written in one
    all-or-nothing transaction (a thin/failed compute keeps the prior rows)."""
    throttle = float(cfg.get("wolf.beneficiaries.per_thesis_throttle_sec", 3600))
    now = time.time()
    theses = await db.get_active_theses()
    written = 0
    for th in theses:
        if th.get("scope_type") == "stock":
            continue
        if not resolve_candidate_universe(th["scope_type"], th["scope_key"], th["direction"]):
            continue
        # per-thesis throttle: skip if the existing rows are still fresh
        existing = await db.get_beneficiaries(th["id"])
        if existing and (now - float(existing[0].get("computed_at", 0) or 0)) < throttle:
            continue
        try:
            rows = await rank_beneficiaries(th)
        except BeneficiaryComputeError as e:
            log.info("wolf_beneficiaries: skip thesis %s (keep prior rows): %s", th["id"], e)
            continue
        except Exception as e:  # noqa: BLE001
            log.error("wolf_beneficiaries: rank error for thesis %s: %s", th["id"], e, exc_info=True)
            continue
        if not rows:
            # nothing clears the floor -> clear any stale rows so the digest omits the section
            await db.replace_beneficiaries(th["id"], [])
            continue
        await db.replace_beneficiaries(th["id"], [
            {**r, "thesis_id": th["id"], "scope_type": th["scope_type"],
             "scope_key": th["scope_key"], "direction": th["direction"], "computed_at": now}
            for r in rows
        ])
        written += 1
    return written
