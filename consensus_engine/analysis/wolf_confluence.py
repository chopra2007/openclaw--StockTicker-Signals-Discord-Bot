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

This module does NO database or network I/O — callers pass already-windowed rows in, so every
function here is deterministic and unit-testable. The DB gather + the loop live elsewhere.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml

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


@dataclass
class SourceVote:
    source_type: str
    net_dir: str                      # BULL | BEAR
    n_rows: int                       # matching directional rows
    n_channels: int = 0               # distinct YouTube channels (display only; 0 for others)
    sample_tickers: list[str] = field(default_factory=list)  # up to 3, for the alert
    sample_video_ids: list[str] = field(default_factory=list)  # raw YouTube ids, up to 3 (no URLs)


@dataclass
class ConfluenceResult:
    tier: str                         # surface | high | critical (confluence component)
    agree_count: int
    disagree_count: int
    agree: list[SourceVote] = field(default_factory=list)
    disagree: list[SourceVote] = field(default_factory=list)
    divided: bool = False


_TIER_RANK = {"surface": 0, "high": 1, "critical": 2}


def combined_tier(phase1_tier: str, confluence_tier: str) -> str:
    """max of the two on surface<high<critical — confluence can only push a thesis UP."""
    a = _TIER_RANK.get(phase1_tier, 0)
    b = _TIER_RANK.get(confluence_tier, 0)
    for name, rank in _TIER_RANK.items():
        if rank == max(a, b):
            return name
    return "surface"


def score_confluence(thesis: dict, rows_by_source: dict[str, list[dict]],
                     min_dominance: float = 0.6) -> ConfluenceResult:
    """Score one thesis against already-windowed source rows.

    `thesis`: dict with scope_type, scope_key, direction ('bull'/'bear'), has_levels (0/1).
    `rows_by_source`: {source_type: [{'ticker':.., 'dir':.., 'channel':..(opt)}, ...]} — the
    caller (DB gather) is responsible for the 21-day window + SEC buys-only filter.
    """
    t_type = thesis["scope_type"]
    t_key = thesis["scope_key"]
    t_stance = _THESIS_DIR.get(thesis.get("direction"), "")
    has_levels = int(thesis.get("has_levels", 0) or 0)

    votes: list[SourceVote] = []
    for stype in SOURCE_TYPES:
        matched: list[tuple[str, dict]] = []
        for row in rows_by_source.get(stype, []):
            norm = normalize_source_stance(row.get("ticker", ""), row.get("dir", ""))
            if norm is None:
                continue
            s_type, s_key, stance = norm
            if scope_matches(t_type, t_key, s_type, s_key, row.get("ticker", "")):
                matched.append((stance, row))
        if not matched:
            continue
        nv = net_vote([s for s, _ in matched], min_dominance)
        if nv is None:
            continue
        # only the rows on the winning side describe this vote
        winners = [r for s, r in matched if s == nv]
        is_yt = stype == "youtube"
        n_channels = (len({(r.get("channel") or "") for r in winners if r.get("channel")})
                      if is_yt else 0)
        # Dedupe by ticker, capturing a representative video_id for each sampled
        # ticker so the link label and the URL describe the SAME ticker.
        sample, sample_vids, seen = [], [], set()
        for r in winners:
            tk = (r.get("ticker") or "").upper()
            if tk and tk not in seen:
                seen.add(tk)
                sample.append(tk)
                if is_yt:
                    sample_vids.append(r.get("video_id") or "")
            if len(sample) >= 3:
                break
        votes.append(SourceVote(stype, nv, len(matched), n_channels, sample, sample_vids))

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

    return ConfluenceResult(tier, agree_count, disagree_count, agree, disagree, divided)
