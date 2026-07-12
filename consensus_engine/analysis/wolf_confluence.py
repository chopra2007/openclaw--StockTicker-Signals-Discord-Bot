"""Cross-source confluence for the Wolf macro-brain (TODO #20, phase 2 / Type-2).

Pure scoring logic: given a live Wolf thesis (macro_theses) and recent directional
stances from the OTHER sources the user follows — Twitter, YouTube, options flow,
SEC insider BUYS — decide how many INDEPENDENT sources agree / disagree with Wolf,
rolled up to the thesis scope (stock / sector / market / asset), and what conviction
tier that earns:

    surface  = Wolf alone, or a level-less thesis (no @-ping)
    high     = Wolf + >=1 corroborating source (thesis must carry levels)
    critical = Wolf + >=2 corroborating sources (thesis must carry levels) -> @-ping

Design notes (all verified against the live DB + real code in pass 0/3, gated by an
opus critic + Gemini):
- Each SOURCE TYPE casts ONE net vote (majority of its bull-vs-bear rows by `min_dominance`),
  so one chatty source can't crowd the score and a source that's internally split (e.g.
  Twitter both long & short on NVDA) doesn't double as both agree and disagree.
- SEC counts BUYS ONLY (insider sells are routine pay events -> 19503 sells vs 799 buys in
  21d; equal-weighting them would auto-confirm every bear thesis). Sells are dropped upstream
  in the gather query; this module also skips non-bull SEC just in case.
- Inverse ETFs are flipped (SOXS long = SMH bear) via wolf_scope.is_inverse_proxy.
- VIX-family vehicles are excluded in v1 (sign of a long-vol position vs equities is ambiguous).
- Roll-up uses ONE map per scope_key: broad SPDR sectors -> sector_map.yaml; sub-industry ETFs
  (SMH/IGV/ITA) -> peer_groups.yaml members; market -> index proxies; asset -> direct proxies only.

I15 (wolf.confluence.weighted_votes_enabled):
- Each row may carry optional `as_of` (epoch float or ISO str) and `size` (raw numeric,
  source-specific: SEC insider $, options premium, YouTube n_channels; absent -> 1.0).
- Age-decay: weight = max(DECAY_FLOOR, exp(-DECAY_RATE * age_hours)). Legs with no usable
  timestamp or older than the confluence window itself (wolf.confluence.window_days) are
  excluded entirely; in-window staleness is handled by the smooth decay, NOT the global
  minutes-scale recency_window caps (those are for the per-tweet scoring lane).
- Size: normalised per-source to [0, 1] via a percentile cap (SIZE_CAP_PCT) so one giant
  options print can't dominate channel counts. Final vote weight = decay * (1 + size_norm).
- Actor controllability: only SEC filings are non-actor-controllable. Escalation to critical
  requires >= 1 non-actor-controllable agreeing source when require_nonactor_for_critical is
  true (default). SEC rows with is_planned=True are excluded from that count.
- With the flag OFF, score_confluence and net_vote behave byte-identically to legacy.

This module does NO database or network I/O — callers pass already-windowed rows in, so every
function here is deterministic and unit-testable. The DB gather + the loop live elsewhere.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import yaml

from consensus_engine import config as cfg
from consensus_engine.analysis.wolf_scope import (
    resolve_scope, is_inverse_proxy, stock_sector_etf,
)

# raw source direction -> common stance vocab
_NORM_DIR = {
    "long": "BULL", "bull": "BULL", "bullish": "BULL", "call": "BULL", "buy": "BULL",
    "short": "BEAR", "bear": "BEAR", "bearish": "BEAR", "put": "BEAR", "sell": "BEAR",
}
# Wolf thesis direction -> common stance vocab
_THESIS_DIR = {"bull": "BULL", "bear": "BEAR"}

# VIX / long-vol vehicles: excluded from voting in v1 (a long-vol position is bearish
# *equities*, but these tickers resolve to ('market','VIX') or ('stock',..), so their
# written direction can't be cleanly mapped to a market/sector stance yet).
_VOL_EXCLUDE = {"VIX", "VXX", "UVXY", "UVIX", "SVXY", "VIXY"}

# The 11 broad SPDR sectors: for a Wolf thesis on one of these, roll up stocks via
# sector_map.yaml (rich: ~28 names for XLK), NOT peer_groups (sparse for SPDRs).
_BROAD_SPDR = {
    "XLK", "XLF", "XLV", "XLY", "XLP", "XLC", "XLE", "XLI", "XLU", "XLRE", "XLB",
}

_PEER_GROUPS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "peer_groups.yaml")
_peer_members_cache: dict[str, set[str]] | None = None

# Source types we read, in display order. SEC last (weakest / buys-only).
SOURCE_TYPES = ("twitter", "youtube", "options", "sec")
_SOURCE_LABEL = {"twitter": "Twitter", "youtube": "YouTube", "options": "Options", "sec": "SEC buys"}

# ── #20 timing: independence buckets ─────────────────────────────────────────
# "Four sources agree" is worthless if two of them are the same crowd wearing different
# hats. Options flow and the Schwab chain snapshot read the SAME order book; an SEC Form 4
# and an insider cluster-buy are the SAME filings. So every source is tagged with an
# INDEPENDENCE BUCKET and each bucket casts at most ONE net vote, no matter how many rows
# or sources it holds. Agreement is counted in buckets, never in rows.
_BUCKET_OF = {
    "twitter": "twitter",
    "youtube": "youtube",
    "options": "options",          # unusual flow
    "schwab_options": "options",   # ...and the chain snapshot: same order book, one vote
    "sec": "insider",              # Form 4 buys
    "form4": "insider",            # ...and cluster buys: same filings, one vote
    "sector_rs": "macro",          # the market's own verdict on the sector
}
TIMING_BUCKETS = ("twitter", "youtube", "options", "insider", "macro")

# FAST buckets move within hours/days; SLOW ones take days/weeks to show up. A thesis that
# only slow sources agree with may be right but is not yet a TRADE — the timing gate needs
# at least one fast mover to say "now", which is the whole point of #20.
_FAST_BUCKETS = frozenset({"twitter", "options"})

# The gate: at least this many INDEPENDENT buckets agreeing, at least one of them fast.
_TIMING_MIN_BUCKETS = 2
_TIMING_MIN_FAST = 1

# I15: actor-controllable sources cannot solo-push a critical @-ping (single actor
# can flood twitter, post a YT video, or print an options order).
# Non-actor-controllable = SEC filing (a regulated Form-4 event, not freely manufacturable).
_ACTOR_CONTROLLABLE = frozenset({"twitter", "youtube", "options"})

# I15: age-decay parameters — decay toward DECAY_FLOOR, never to zero.
# rate chosen so a 7-day-old row retains ~50% weight (ln2/168h ≈ 0.00413/h).
_DECAY_RATE: float = 0.00413   # per hour
_DECAY_FLOOR: float = 0.20     # stale but not dead — a 21-day-old row keeps 20%

# I15: per-source size percentile cap (95th pct proxy): any size value above this
# multiplier of the median is clipped so one outlier can't dominate.
# Size is normalised -> [0, 1] within each source's own rows before weighting.
_SIZE_CAP_PCT: float = 0.95    # top 5% clipped to 1.0


def _coerce_as_of(v) -> Optional[datetime]:
    """Best-effort UTC datetime from epoch float, ISO str, or datetime. None on failure."""
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v
    elif isinstance(v, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(v), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _age_decay(as_of_val, now: datetime) -> float:
    """Compute exp-decay weight in [DECAY_FLOOR, 1.0] from a row's as_of field.

    If as_of is None/unparseable the row was already excluded by the window
    freshness check upstream, so this DECAY_FLOOR return is a safety net only.
    """
    dt = _coerce_as_of(as_of_val)
    if dt is None:
        return _DECAY_FLOOR
    age_hours = max(0.0, (now - dt).total_seconds() / 3600.0)
    return max(_DECAY_FLOOR, math.exp(-_DECAY_RATE * age_hours))


def _size_norm(sizes: list[float]) -> list[float]:
    """Normalise a list of raw size values to [0, 1] with a percentile cap.

    Values above the SIZE_CAP_PCT quantile are clipped to 1.0; others scaled linearly
    against that cap. A single row or all-zero list -> all 0.0 (size adds nothing).
    """
    if not sizes or all(s <= 0 for s in sizes):
        return [0.0] * len(sizes)
    sorted_s = sorted(sizes)
    idx = max(0, int(len(sorted_s) * _SIZE_CAP_PCT) - 1)
    cap = sorted_s[idx]
    if cap <= 0:
        return [0.0] * len(sizes)
    return [min(1.0, s / cap) for s in sizes]


def _peer_members() -> dict[str, set[str]]:
    """benchmark_etf -> {member tickers} from peer_groups.yaml (cached). Used only for
    sub-industry roll-up (SMH/IGV/ITA), where sector_map.yaml can't emit the bucket."""
    global _peer_members_cache
    if _peer_members_cache is None:
        out: dict[str, set[str]] = {}
        try:
            with open(_PEER_GROUPS_PATH) as f:
                groups = (yaml.safe_load(f) or {}).get("groups", {})
            for spec in groups.values():
                etf = (spec or {}).get("benchmark_etf")
                if not etf:
                    continue
                members = {str(m).upper() for m in (spec.get("members") or []) if isinstance(m, str)}
                out.setdefault(etf.upper(), set()).update(members)
        except Exception:
            out = {}
        _peer_members_cache = out
    return _peer_members_cache


def normalize_source_stance(ticker: str, raw_dir: str) -> tuple[str, str, str] | None:
    """Map a source row (ticker, raw direction) -> (scope_type, scope_key, stance).

    Returns None to SKIP the row: neutral/unknown direction, or a VIX-family vehicle.
    Inverse ETFs (SOXS/SQQQ) have their stance flipped so they reinforce the base
    instrument's direction (SOXS long -> SMH BEAR; SQQQ long -> NDX BEAR).
    """
    if not ticker:
        return None
    d = _NORM_DIR.get((raw_dir or "").strip().lower())
    if d is None:
        return None
    up = ticker.strip().upper()
    if up in _VOL_EXCLUDE:
        return None
    scope_type, scope_key = resolve_scope(up)
    if is_inverse_proxy(up):
        d = "BEAR" if d == "BULL" else "BULL"
    return (scope_type, scope_key, d)


def scope_matches(thesis_type: str, thesis_key: str,
                  src_type: str, src_key: str, src_ticker: str) -> bool:
    """True if a source stance at (src_type, src_key) is ABOUT the same thing the Wolf
    thesis (thesis_type, thesis_key) is about, after roll-up. One map per scope_key:

      stock  : exact ticker match.
      market : source resolves to the same index (QQQ->NDX matches an NDX thesis).
      asset  : source resolves to the same asset proxy (USO->OIL matches an OIL thesis); no two-hop.
      sector : direct ETF match, OR a stock rolls up — broad SPDR via sector_map, sub-industry
               (SMH/IGV/ITA) via peer_groups members. No double-count: each thesis_key picks ONE map.
    """
    tkey = (thesis_key or "").upper()
    skey = (src_key or "").upper()
    sticker = (src_ticker or "").upper()

    if thesis_type == "stock":
        return src_type == "stock" and skey == tkey
    if thesis_type == "market":
        return src_type == "market" and skey == tkey
    if thesis_type == "asset":
        return src_type == "asset" and skey == tkey
    if thesis_type == "sector":
        # direct: the source IS this sector ETF (or resolves to it, e.g. SOXX->SMH).
        if src_type == "sector" and skey == tkey:
            return True
        if sticker == tkey:
            return True
        # stock roll-up (one map per scope_key)
        if src_type == "stock":
            if tkey in _BROAD_SPDR:
                return stock_sector_etf(sticker) == tkey
            # sub-industry ETF bucket (SMH/IGV/ITA): use curated peer members
            return sticker in _peer_members().get(tkey, set())
        return False
    return False


def net_vote(stances: list[str], min_dominance: float = 0.6) -> str | None:
    """Collapse one source's matching stances into a single net vote.

    Returns 'BULL'/'BEAR' only when one side has >= min_dominance share; otherwise None
    (no directional rows, or too split to call). This caps each source to ONE vote and
    drops internally-mixed sources.

    When I15 weighted_votes_enabled is ON, callers use net_vote_weighted instead; this
    function is kept for the flag-OFF legacy path and external callers.
    """
    bull = sum(1 for s in stances if s == "BULL")
    bear = sum(1 for s in stances if s == "BEAR")
    total = bull + bear
    if total == 0:
        return None
    share = bull / total
    if share >= min_dominance:
        return "BULL"
    if share <= 1.0 - min_dominance:
        return "BEAR"
    return None


def net_vote_weighted(
    stances_weights: list[tuple[str, float]],
    min_dominance: float = 0.6,
) -> str | None:
    """I15: weighted net vote — same dominance rule but uses per-row vote weights.

    `stances_weights` is [(stance, weight), ...] where weight = decay * (1 + size_norm).
    Returns 'BULL'/'BEAR' or None (split/empty). Dominance threshold is by weight share,
    not row count, so a high-weight fresh row outweighs many stale low-weight ones.
    """
    bull_w = sum(w for s, w in stances_weights if s == "BULL")
    bear_w = sum(w for s, w in stances_weights if s == "BEAR")
    total_w = bull_w + bear_w
    if total_w <= 0:
        return None
    share = bull_w / total_w
    if share >= min_dominance:
        return "BULL"
    if share <= 1.0 - min_dominance:
        return "BEAR"
    return None


@dataclass
class SourceVote:
    source_type: str
    net_dir: str                      # BULL | BEAR
    n_rows: int                       # matching directional rows
    n_channels: int = 0               # distinct YouTube channels (display only; 0 for others)
    sample_tickers: list[str] = field(default_factory=list)  # up to 3, for the alert
    sample_video_ids: list[str] = field(default_factory=list)  # raw YouTube ids, up to 3 (no URLs)
    sample_links: list[str] = field(default_factory=list)  # item E: TweetShift links, up to 3 (twitter)


@dataclass
class BucketVote:
    """One independence bucket's single net vote (however many sources fed it)."""
    bucket: str
    net_dir: str                      # BULL | BEAR
    fast: bool
    n_rows: int
    sources: list[str] = field(default_factory=list)


@dataclass
class ConfluenceResult:
    tier: str                         # surface | high | critical (confluence component)
    agree_count: int
    disagree_count: int
    agree: list[SourceVote] = field(default_factory=list)
    disagree: list[SourceVote] = field(default_factory=list)
    divided: bool = False
    # #20 timing (SHADOW unless wolf.confluence.timing.enabled): independent-bucket view.
    timing_verdict: str = "none"      # act | wait | none
    timing_bucket_agree: int = 0      # how many INDEPENDENT buckets agree
    timing_fast_agree: int = 0        # ...of which are fast movers
    timing_buckets: list[BucketVote] = field(default_factory=list)


_TIER_RANK = {"surface": 0, "high": 1, "critical": 2}


def combined_tier(phase1_tier: str, confluence_tier: str) -> str:
    """max of the two on surface<high<critical — confluence can only push a thesis UP."""
    a = _TIER_RANK.get(phase1_tier, 0)
    b = _TIER_RANK.get(confluence_tier, 0)
    for name, rank in _TIER_RANK.items():
        if rank == max(a, b):
            return name
    return "surface"


def score_timing(thesis: dict, rows_by_source: dict[str, list[dict]],
                 min_dominance: float = 0.6) -> tuple[str, int, int, list[BucketVote]]:
    """#20: is the thesis's moment NOW? Returns (verdict, bucket_agree, fast_agree, buckets).

    Counts agreement in INDEPENDENT buckets, not rows and not sources. Four bullish
    options rows plus two bullish Schwab snapshots are ONE options vote — the same order
    book cannot corroborate itself. Then:

      act  — at least 2 independent buckets agree AND at least 1 of them is a fast mover
             (twitter / options). Slow-only agreement is a thesis, not a trade.
      wait — someone agrees, but not enough independent families, or nobody fast.
      none — no bucket agrees at all.

    Pure function of the rows handed in; it writes nothing and, on its own, alerts nothing.
    """
    t_type = thesis["scope_type"]
    t_key = thesis["scope_key"]
    t_stance = _THESIS_DIR.get(thesis.get("direction"), "")

    # Collect every matching row per bucket, remembering which source fed it.
    per_bucket: dict[str, list[tuple[str, str]]] = {}   # bucket -> [(stance, source_key)]
    for skey, rows in rows_by_source.items():
        bucket = _BUCKET_OF.get(skey)
        if not bucket:
            continue
        for row in rows or []:
            norm = normalize_source_stance(row.get("ticker", ""), row.get("dir", ""))
            if norm is None:
                continue
            s_type, s_key, stance = norm
            if scope_matches(t_type, t_key, s_type, s_key, row.get("ticker", "")):
                per_bucket.setdefault(bucket, []).append((stance, skey))

    buckets: list[BucketVote] = []
    for bucket, entries in per_bucket.items():
        nv = net_vote([s for s, _ in entries], min_dominance)   # ONE net vote per bucket
        if nv is None:
            continue                                            # internally mixed -> abstains
        buckets.append(BucketVote(
            bucket=bucket, net_dir=nv, fast=bucket in _FAST_BUCKETS,
            n_rows=len(entries), sources=sorted({k for _, k in entries}),
        ))

    agreeing = [b for b in buckets if b.net_dir == t_stance]
    fast_agree = sum(1 for b in agreeing if b.fast)
    if not agreeing:
        verdict = "none"
    elif len(agreeing) >= _TIMING_MIN_BUCKETS and fast_agree >= _TIMING_MIN_FAST:
        verdict = "act"
    else:
        verdict = "wait"
    return verdict, len(agreeing), fast_agree, buckets


def score_confluence(thesis: dict, rows_by_source: dict[str, list[dict]],
                     min_dominance: float = 0.6) -> ConfluenceResult:
    """Score one thesis against already-windowed source rows.

    `thesis`: dict with scope_type, scope_key, direction ('bull'/'bear'), has_levels (0/1).
    `rows_by_source`: {source_type: [{'ticker':.., 'dir':.., 'channel':..(opt)}, ...]} — the
    caller (DB gather) is responsible for the 21-day window + SEC buys-only filter.

    I15 (wolf.confluence.weighted_votes_enabled): each row may additionally carry:
      'as_of'    — epoch float or ISO str; used for age-decay weight.
      'size'     — raw numeric (SEC insider $, options premium, YT n_channels); optional.
      'is_planned' — bool; SEC 10b5-1 rows excluded from non-actor-controllable count.
    With the flag OFF, these extra fields are silently ignored and behavior is byte-identical.
    """
    weighted = cfg.get("wolf.confluence.weighted_votes_enabled", False)

    t_type = thesis["scope_type"]
    t_key = thesis["scope_key"]
    t_stance = _THESIS_DIR.get(thesis.get("direction"), "")
    has_levels = int(thesis.get("has_levels", 0) or 0)

    now = datetime.now(timezone.utc)

    votes: list[SourceVote] = []
    # I15: track agreeing sources that are non-actor-controllable (SEC non-planned buys).
    nonactor_agree_count = 0

    for stype in SOURCE_TYPES:
        raw_rows = rows_by_source.get(stype, [])

        if weighted:
            # Freshness cap = the confluence WINDOW itself (21 days by default),
            # not the global per-tweet recency_window caps (sec=2h, tweet=2h...).
            # Wolf confluence is deliberately an over-time feature: rows are
            # gathered over window_days and age-DECAY (above) weights them down
            # smoothly. Running them through the minutes-scale global caps
            # deleted every vote in the first live test (2026-06-10). A leg only
            # hard-drops when it has no usable timestamp or exceeds the window.
            window_days = float(cfg.get("wolf.confluence.window_days", 21))
            cap_min = window_days * 1440.0
            fresh_rows = []
            for r in raw_rows:
                dt = _coerce_as_of(r.get("as_of"))
                if dt is None:
                    continue  # null/unparseable timestamp -> stale (I1 rule)
                age_min = (now - dt).total_seconds() / 60.0
                if -60.0 <= age_min <= cap_min:
                    fresh_rows.append(r)
        else:
            fresh_rows = raw_rows

        matched: list[tuple[str, dict]] = []
        for row in fresh_rows:
            norm = normalize_source_stance(row.get("ticker", ""), row.get("dir", ""))
            if norm is None:
                continue
            s_type, s_key, stance = norm
            if scope_matches(t_type, t_key, s_type, s_key, row.get("ticker", "")):
                matched.append((stance, row))
        if not matched:
            continue

        if weighted:
            # Compute age-decay weights per row.
            decays = [_age_decay(r.get("as_of"), now) for _, r in matched]
            # Compute size-normalised weights per row.
            raw_sizes = [float(r.get("size") or 0.0) for _, r in matched]
            size_norms = _size_norm(raw_sizes)
            # Final weight = decay * (1 + size_norm); size adds up to 1x bonus at most.
            weights = [d * (1.0 + sn) for d, sn in zip(decays, size_norms)]
            stances_weights = [(s, w) for (s, _), w in zip(matched, weights)]
            nv = net_vote_weighted(stances_weights, min_dominance)
        else:
            nv = net_vote([s for s, _ in matched], min_dominance)

        if nv is None:
            continue

        # Only the rows on the winning side describe this vote.
        winners = [r for s, r in matched if s == nv]
        is_yt = stype == "youtube"
        n_channels = (len({(r.get("channel") or "") for r in winners if r.get("channel")})
                      if is_yt else 0)
        # Dedupe by ticker, capturing a representative video_id (YouTube) / source_link
        # (Twitter) for each sampled ticker so the link label and URL describe the SAME
        # ticker. winners preserves the DB order — twitter is newest-first, so the first
        # winning row per ticker is the NEWEST winning-direction tweet (item E, MED-E4).
        is_tw = stype == "twitter"
        sample, sample_vids, sample_links, seen = [], [], [], set()
        for r in winners:
            tk = (r.get("ticker") or "").upper()
            if tk and tk not in seen:
                seen.add(tk)
                sample.append(tk)
                if is_yt:
                    sample_vids.append(r.get("video_id") or "")
                if is_tw:
                    sample_links.append(r.get("link") or "")
            if len(sample) >= 3:
                break
        votes.append(SourceVote(stype, nv, len(matched), n_channels, sample, sample_vids, sample_links))

        # I15: count non-actor-controllable agreeing sources for the critical-ping guard.
        if weighted and nv == t_stance and stype not in _ACTOR_CONTROLLABLE:
            # SEC 10b5-1 / pre-arranged buys don't qualify — a planned trade isn't a signal.
            has_unplanned = any(not r.get("is_planned", False) for r in winners)
            if has_unplanned:
                nonactor_agree_count += 1

    agree = [v for v in votes if v.net_dir == t_stance]
    disagree = [v for v in votes if v.net_dir and v.net_dir != t_stance]
    agree_count = len(agree)
    disagree_count = len(disagree)

    if has_levels and agree_count >= 2:
        tier = "critical"
    elif has_levels and agree_count >= 1:
        tier = "high"
    else:
        tier = "surface"
    divided = disagree_count >= 1 and disagree_count >= agree_count
    # A genuinely contested call must not @-ping as "critical high-conviction" — cap it to
    # a loud 'high' that still surfaces the split. (Spec: disagreement is its own signal.)
    if divided and tier == "critical":
        tier = "high"

    # I15: critical-ping safeguard — escalation to critical requires >= 1 non-actor-
    # controllable agreeing source when require_nonactor_for_critical is true (default).
    # This prevents a single public options print or a coordinated tweet campaign from
    # solo-pushing an @-ping. The gate only activates inside the weighted_votes_enabled
    # path so flag-OFF behavior is byte-identical.
    if (weighted
            and tier == "critical"
            and cfg.get("wolf.confluence.require_nonactor_for_critical", True)
            and nonactor_agree_count < 1):
        tier = "high"

    # ── #20 timing verdict ───────────────────────────────────────────────────
    # Two independent flags, on purpose:
    #   timing.collect — compute + store the verdict (SHADOW). Changes nothing a user sees.
    #   timing.enabled — let an 'act' verdict actually push the alert tier UP.
    # With collect ON and enabled OFF (the shipped default) every field below is recorded
    # but `tier` is untouched, so the live @-ping behaviour is byte-identical to today's.
    verdict, bucket_agree, fast_agree, buckets = "none", 0, 0, []
    if cfg.get("wolf.confluence.timing.collect", False):
        verdict, bucket_agree, fast_agree, buckets = score_timing(
            thesis, rows_by_source, min_dominance)
        if cfg.get("wolf.confluence.timing.enabled", False) and verdict == "act":
            # An 'act' moment escalates ONE notch; it can never skip straight to critical
            # from nothing, and main.py's alerted_tier hysteresis still gates the post.
            tier = {"surface": "high", "high": "critical"}.get(tier, tier)

    return ConfluenceResult(tier, agree_count, disagree_count, agree, disagree, divided,
                            timing_verdict=verdict, timing_bucket_agree=bucket_agree,
                            timing_fast_agree=fast_agree, timing_buckets=buckets)
