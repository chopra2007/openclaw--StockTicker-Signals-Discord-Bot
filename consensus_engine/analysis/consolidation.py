"""A3: Bayesian multi-source consolidation.

Fuses multiple signal_events rows for the same ticker within 15 minutes
into one consolidated_event with cluster-wise effective_n. Replaces the
flat-additive social bonus in cross_reference.py when enabled.
"""
from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field

from consensus_engine import config as cfg
from consensus_engine import db

log = logging.getLogger(__name__)

SOURCE_CLUSTERS: dict[str, set[str]] = {
    "news":     {"brave", "searxng", "finnhub_news", "google_rss"},
    "retail":   {"reddit", "apewisdom", "stocktwits"},
    "analyst":  {"twitter", "ANALYST_CLUSTER"},
    "video":    {"youtube"},
    "official": {"sec_filing"},
}


def _source_to_cluster(source_type: str) -> str | None:
    """Return the cluster name for a source_type string, or None if unknown."""
    for cluster_name, members in SOURCE_CLUSTERS.items():
        if source_type in members:
            return cluster_name
    return None


@dataclass
class ConsolidationResult:
    fired: bool
    consolidated_id: int | None
    effective_n_clusters: int    # 0..3, capped at max_effective_clusters
    combined_log_odds: float
    consensus_boost: int         # int points added to ScoreBreakdown
    sources_seen: list[str]      # list of source_type strings seen
    reason: str                  # "no_other_sources" | "shadow_only" | "consolidated" | "cold_start_passthrough" | "disabled"


async def consolidate_for_ticker(
    ticker: str,
    window_minutes: int = 15,
    shadow_only: bool = True,
) -> ConsolidationResult:
    """Query signal_events for ticker in rolling window, fuse into consolidated_event.

    Query signal_events WHERE ticker=? AND recorded_at >= now - window
    AND consumed_by_cluster_id IS NULL.
    Group by SOURCE_CLUSTERS membership.
    effective_n = min(clusters_hit, max_effective_clusters).
    Per-cluster prior = mean(source_performance.rolling_accuracy of members).
    Cold-start fallback: if any source has no rolling_accuracy row ->
      return fired=False, reason='cold_start_passthrough', consensus_boost=0.
    combined_log_odds = sum of log(prior/(1-prior)) for each cluster.
    consensus_boost = int(effective_n * pts_per_cluster) where
      pts_per_cluster = cfg.get("scoring.multipliers.additional_analyst", 20).
    On INSERT OR IGNORE collision (race), re-SELECT the existing row.
    If shadow_only=True: write consolidated_events but return consensus_boost=0.
    If shadow_only=False: return real consensus_boost.
    """
    max_clusters = cfg.get("features.cross_source_consolidation.max_effective_clusters", 3)
    cfg_window = cfg.get("features.cross_source_consolidation.window_minutes", 15)
    # Caller-supplied window_minutes takes precedence, but config is the default fallback
    if window_minutes == 15:
        window_minutes = cfg_window

    pts_per_cluster = cfg.get("scoring.multipliers.additional_analyst", 20)

    now = time.time()
    cutoff = now - (window_minutes * 60)
    window_start = cutoff
    window_end = now

    conn = await db.get_db()

    # Query signal_events for unconsumed rows in window
    cur = await conn.execute(
        """SELECT id, source_type, recorded_at
           FROM signal_events
           WHERE ticker = ? AND recorded_at >= ? AND consumed_by_cluster_id IS NULL
           ORDER BY recorded_at ASC""",
        (ticker, cutoff),
    )
    rows = await cur.fetchall()

    # Gather all source_type strings seen
    sources_seen: list[str] = [r["source_type"] for r in rows]

    if not sources_seen:
        return ConsolidationResult(
            fired=False,
            consolidated_id=None,
            effective_n_clusters=0,
            combined_log_odds=0.0,
            consensus_boost=0,
            sources_seen=[],
            reason="no_other_sources",
        )

    # Map sources to clusters
    clusters_hit: dict[str, list[str]] = {}  # cluster_name -> [source_types]
    for source_type in sources_seen:
        cluster = _source_to_cluster(source_type)
        if cluster is not None:
            clusters_hit.setdefault(cluster, []).append(source_type)

    if not clusters_hit:
        return ConsolidationResult(
            fired=False,
            consolidated_id=None,
            effective_n_clusters=0,
            combined_log_odds=0.0,
            consensus_boost=0,
            sources_seen=sources_seen,
            reason="no_other_sources",
        )

    # Check cold-start: any source seen without a source_performance row?
    unique_sources = list(set(sources_seen))
    cold_start = False
    source_accuracies: dict[str, float] = {}
    for src in unique_sources:
        perf_cur = await conn.execute(
            "SELECT rolling_accuracy FROM source_performance WHERE entity_id = ? LIMIT 1",
            (src,),
        )
        perf_row = await perf_cur.fetchone()
        if perf_row is None:
            cold_start = True
            source_accuracies[src] = 0.5  # fallback for shadow write
        else:
            source_accuracies[src] = float(perf_row["rolling_accuracy"])

    effective_n = min(len(clusters_hit), max_clusters)

    # Compute per-cluster prior as mean rolling_accuracy of members seen
    combined_log_odds = 0.0
    for cluster_name, cluster_sources in clusters_hit.items():
        accuracies = [source_accuracies.get(s, 0.5) for s in cluster_sources]
        prior = sum(accuracies) / len(accuracies)
        # Clamp to avoid log(0) or log(inf)
        prior = max(0.01, min(0.99, prior))
        combined_log_odds += math.log(prior / (1 - prior))

    if cold_start:
        # Write shadow row but signal cold-start passthrough to caller
        clusters_hit_list = list(clusters_hit.keys())
        _maybe_write_consolidated(
            conn=conn,
            ticker=ticker,
            window_start=window_start,
            window_end=window_end,
            sources_seen=sources_seen,
            clusters_hit=clusters_hit_list,
            effective_n=effective_n,
            combined_log_odds=combined_log_odds,
            consensus_boost=0,
            shadow_only=True,
        )
        return ConsolidationResult(
            fired=False,
            consolidated_id=None,
            effective_n_clusters=effective_n,
            combined_log_odds=combined_log_odds,
            consensus_boost=0,
            sources_seen=sources_seen,
            reason="cold_start_passthrough",
        )

    legacy_boost = round(effective_n * pts_per_cluster)

    # I7: scale consensus_boost by sigmoid(combined_log_odds) when flag is ON
    if cfg.get("features.consensus_logodds.enabled", False):
        count_floor_frac = cfg.get("features.consensus_logodds.count_floor_frac", 0.5)
        sigmoid = 1.0 / (1.0 + math.exp(-combined_log_odds))
        floor_part = count_floor_frac * legacy_boost
        sigmoid_part = (1.0 - count_floor_frac) * legacy_boost * sigmoid
        real_boost = round(floor_part + sigmoid_part)
        log.info(
            "[I7 shadow] $%s consensus_boost scaled=%d legacy=%d (log_odds=%.2f)",
            ticker,
            real_boost,
            legacy_boost,
            combined_log_odds,
        )
    else:
        real_boost = legacy_boost

    consensus_boost = real_boost if not shadow_only else 0

    clusters_hit_list = list(clusters_hit.keys())
    consolidated_id = await _write_consolidated(
        conn=conn,
        ticker=ticker,
        window_start=window_start,
        window_end=window_end,
        sources_seen=sources_seen,
        clusters_hit=clusters_hit_list,
        effective_n=effective_n,
        combined_log_odds=combined_log_odds,
        consensus_boost=real_boost,
        shadow_only=shadow_only,
    )

    reason = "shadow_only" if shadow_only else "consolidated"

    return ConsolidationResult(
        fired=not shadow_only,
        consolidated_id=consolidated_id,
        effective_n_clusters=effective_n,
        combined_log_odds=combined_log_odds,
        consensus_boost=consensus_boost,
        sources_seen=sources_seen,
        reason=reason,
    )


def _maybe_write_consolidated(
    conn,
    ticker: str,
    window_start: float,
    window_end: float,
    sources_seen: list[str],
    clusters_hit: list[str],
    effective_n: int,
    combined_log_odds: float,
    consensus_boost: int,
    shadow_only: bool,
) -> None:
    """Fire-and-forget best-effort shadow write (no await — for cold-start path)."""
    import asyncio
    asyncio.ensure_future(
        _write_consolidated(
            conn=conn,
            ticker=ticker,
            window_start=window_start,
            window_end=window_end,
            sources_seen=sources_seen,
            clusters_hit=clusters_hit,
            effective_n=effective_n,
            combined_log_odds=combined_log_odds,
            consensus_boost=consensus_boost,
            shadow_only=shadow_only,
        )
    )


async def _write_consolidated(
    conn,
    ticker: str,
    window_start: float,
    window_end: float,
    sources_seen: list[str],
    clusters_hit: list[str],
    effective_n: int,
    combined_log_odds: float,
    consensus_boost: int,
    shadow_only: bool,
) -> int | None:
    """INSERT OR IGNORE into consolidated_events; on collision re-SELECT existing row."""
    created_at = time.time()
    try:
        cur = await conn.execute(
            """INSERT OR IGNORE INTO consolidated_events
               (ticker, window_start, window_end, sources_json, clusters_hit_json,
                effective_n_clusters, combined_log_odds, consensus_boost,
                shadow_only, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ticker,
                window_start,
                window_end,
                json.dumps(list(set(sources_seen))),
                json.dumps(clusters_hit),
                effective_n,
                combined_log_odds,
                consensus_boost,
                1 if shadow_only else 0,
                created_at,
            ),
        )
        await conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
        # INSERT OR IGNORE collision — re-SELECT existing
        sel_cur = await conn.execute(
            "SELECT id FROM consolidated_events WHERE ticker = ? AND window_start = ?",
            (ticker, window_start),
        )
        row = await sel_cur.fetchone()
        return row["id"] if row else None
    except Exception as exc:
        log.warning("[A3] Failed to write consolidated_events for $%s: %s", ticker, exc)
        return None
