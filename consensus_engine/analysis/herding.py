"""A2: Analyst herding (cluster) detector.

When >=3 unique analysts post on the same ticker within window_minutes,
and >=2 of them have rolling_accuracy >= min_trusted_accuracy, fires a
ClusterResult. Edits the prior 1-2 Phase-1 messages with swarm context.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.analysis.regime import lookup_regime

log = logging.getLogger(__name__)


@dataclass
class ClusterMember:
    analyst: str
    rolling_accuracy: float     # 0.0 if no data (conservative)
    signal_event_id: int
    posted_at: float            # unix timestamp


@dataclass
class ClusterResult:
    fired: bool
    cluster_id: Optional[int]
    ticker: str
    members: list[ClusterMember]
    effective_size: float        # discounted by pair-correlation
    reason: str                  # "below_threshold" | "trust_floor_failed" | "regime_panic_min_4" | "fired" | "disabled"


@dataclass
class SwarmMemberDetail:
    """The exact stored post represented by one analyst in a swarm alert."""
    analyst: str
    direction: str
    reason: str
    source_link: Optional[str]
    posted_at: float
    reason_kind: str = "none"
    decision_code: str = "missing"
    signal_event_id: Optional[int] = None
    analyst_post_view_id: Optional[int] = None


@dataclass
class SwarmResult:
    """Result of one detect_swarm() evaluation for a single incoming tweet."""
    fired: bool
    reason: str                          # opened | joined | already_counted | below_threshold | disabled
    ticker: str = ""
    analysts: Optional[list] = None      # all analysts in the swarm, ordered by first tweet
    member_times: Optional[dict] = None  # analyst -> first tweet ts (within the open window)
    opened_at: float = 0.0
    now_ts: float = 0.0
    count: int = 0
    member_details: Optional[list[SwarmMemberDetail]] = None


async def _swarm_members(
    conn,
    ticker: str,
    opened_at: float,
    now_ts: float,
    alerted: set,
) -> tuple[list, dict, list[SwarmMemberDetail]]:
    """Return each alerted analyst's exact first stored post in the group window."""
    cur = await conn.execute(
        """SELECT se.id AS signal_event_id, se.source_detail AS analyst,
                  se.recorded_at AS first_at, se.source_link,
                  se.analyst_post_view_id, apv.display_direction,
                  apv.reason_text, apv.reason_kind, apv.decision_code
             FROM signal_events se
             LEFT JOIN analyst_post_views apv
               ON apv.id=se.analyst_post_view_id AND apv.ticker=se.ticker
            WHERE se.source_type='twitter' AND se.ticker=?
              AND se.recorded_at >= ? AND se.recorded_at <= ?
              AND se.source_detail IS NOT NULL
            ORDER BY se.recorded_at, se.id""",
        (ticker, opened_at, now_ts),
    )
    rows = await cur.fetchall()
    first_rows = {}
    for row in rows:
        analyst = row["analyst"]
        if analyst in alerted and analyst not in first_rows:
            first_rows[analyst] = row

    times = {analyst: row["first_at"] for analyst, row in first_rows.items()}
    for a in alerted:
        times.setdefault(a, opened_at)
    members = sorted(alerted, key=lambda a: times.get(a, opened_at))
    details = []
    for analyst in members:
        row = first_rows.get(analyst)
        raw_direction = (row["display_direction"] if row else None) or ""
        direction = raw_direction if raw_direction in {"long", "short"} else "unclear"
        stored_reason = (row["reason_text"] if row else None) or ""
        reason = " ".join(stored_reason.split()) or "reason not stated"
        details.append(SwarmMemberDetail(
            analyst=analyst,
            direction=direction,
            reason=reason,
            source_link=row["source_link"] if row else None,
            posted_at=times[analyst],
            reason_kind=(row["reason_kind"] if row else None) or "none",
            decision_code=(row["decision_code"] if row else None) or "missing",
            signal_event_id=row["signal_event_id"] if row else None,
            analyst_post_view_id=row["analyst_post_view_id"] if row else None,
        ))
    return members, times, details


async def _record_swarm_history(
    conn,
    ticker: str,
    opened_at: float,
    now_ts: float,
    alerted: set,
    details: Optional[list[SwarmMemberDetail]] = None,
) -> None:
    """Append a cluster_events row so the existing `!cluster history` command keeps working.
    Best-effort: never block an alert on a history write."""
    try:
        detail_by_analyst = {detail.analyst: detail for detail in details or []}
        members_json = []
        for analyst in sorted(alerted):
            member = {"analyst": analyst}
            detail = detail_by_analyst.get(analyst)
            if detail:
                member["signal_event_id"] = detail.signal_event_id
                member["analyst_post_view_id"] = detail.analyst_post_view_id
            members_json.append(member)
        await conn.execute(
            """INSERT INTO cluster_events
               (ticker, first_seen_at, last_seen_at, cluster_size, effective_size, members_json, regime_label, fired_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (ticker, opened_at, now_ts, len(alerted), float(len(alerted)),
             json.dumps(members_json), "", now_ts),
        )
        await conn.commit()
    except Exception as e:  # pragma: no cover - defensive
        log.debug("[A2] swarm history write failed for $%s: %s", ticker, e)


async def detect_swarm(ticker: str, analyst: str, now_ts: float) -> SwarmResult:
    """Stateful analyst-swarm detector (TODO #20-area, user spec 2026-06-17).

    A swarm OPENS when >= min_cluster_size distinct analysts tweet the same ticker within
    window_minutes of each other. Once open it stays live for swarm_open_hours (fixed from
    open). Every NEW distinct analyst that tweets the ticker during the open window fires a
    fresh alert (caller pings the user). The same analyst tweeting again does nothing.

    Called once per incoming tweet AFTER the row is in signal_events. Returns a SwarmResult;
    caller sends + pings when .fired is True.
    """
    if not cfg.get("features.analyst_herding.enabled", False):
        return SwarmResult(fired=False, reason="disabled", ticker=ticker, now_ts=now_ts)

    window_min = int(cfg.get("features.analyst_herding.window_minutes", 60))
    open_hours = float(cfg.get("features.analyst_herding.swarm_open_hours", 24))
    min_size = int(cfg.get("features.analyst_herding.min_cluster_size", 2))
    conn = await db.get_db()

    cur = await conn.execute(
        "SELECT opened_at, alerted_analysts FROM swarm_state WHERE ticker=?", (ticker,)
    )
    row = await cur.fetchone()
    is_open = bool(row) and (now_ts - row["opened_at"] < open_hours * 3600)

    if is_open:
        opened_at = row["opened_at"]
        alerted = set(json.loads(row["alerted_analysts"] or "[]"))
        if analyst in alerted:
            return SwarmResult(fired=False, reason="already_counted", ticker=ticker,
                               opened_at=opened_at, now_ts=now_ts, count=len(alerted))
        alerted.add(analyst)
        await conn.execute(
            "UPDATE swarm_state SET alerted_analysts=?, last_alert_at=?, updated_at=? WHERE ticker=?",
            (json.dumps(sorted(alerted)), now_ts, now_ts, ticker),
        )
        await conn.commit()
        members, times, details = await _swarm_members(conn, ticker, opened_at, now_ts, alerted)
        await _record_swarm_history(conn, ticker, opened_at, now_ts, alerted, details)
        log.info("[A2] SWARM joined $%s: %s -> %d analysts", ticker, analyst, len(alerted))
        return SwarmResult(fired=True, reason="joined", ticker=ticker, analysts=members,
                           member_times=times, member_details=details,
                           opened_at=opened_at, now_ts=now_ts, count=len(alerted))

    # No open swarm (new or expired): does the opening condition hold right now?
    cutoff = now_ts - window_min * 60
    cur2 = await conn.execute(
        """SELECT source_detail AS analyst, MIN(recorded_at) AS first_at
           FROM signal_events
           WHERE source_type='twitter' AND ticker=? AND recorded_at >= ? AND recorded_at <= ?
             AND source_detail IS NOT NULL
           GROUP BY source_detail""",
        (ticker, cutoff, now_ts),
    )
    distinct = {r["analyst"]: r["first_at"] for r in await cur2.fetchall()}
    if len(distinct) < min_size:
        return SwarmResult(fired=False, reason="below_threshold", ticker=ticker, now_ts=now_ts,
                           count=len(distinct))

    opened_at = min(distinct.values())
    alerted = set(distinct.keys())
    await conn.execute(
        """INSERT OR REPLACE INTO swarm_state (ticker, opened_at, alerted_analysts, last_alert_at, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (ticker, opened_at, json.dumps(sorted(alerted)), now_ts, now_ts),
    )
    await conn.commit()
    members, times, details = await _swarm_members(conn, ticker, opened_at, now_ts, alerted)
    await _record_swarm_history(conn, ticker, opened_at, now_ts, alerted, details)
    log.info("[A2] SWARM opened $%s: %d analysts in %dm", ticker, len(alerted), window_min)
    return SwarmResult(fired=True, reason="opened", ticker=ticker, analysts=members,
                       member_times=times, member_details=details,
                       opened_at=opened_at, now_ts=now_ts, count=len(alerted))


async def _get_correlation(analyst_a: str, analyst_b: str) -> float:
    """Query analyst_pair_correlations for canonical (a < b) pair. Returns 0.0 if no data."""
    a, b = (analyst_a, analyst_b) if analyst_a < analyst_b else (analyst_b, analyst_a)
    try:
        conn = await db.get_db()
        cur = await conn.execute(
            "SELECT co_post_rate FROM analyst_pair_correlations WHERE analyst_a = ? AND analyst_b = ?",
            (a, b),
        )
        row = await cur.fetchone()
        if row:
            return float(row["co_post_rate"])
    except Exception as e:
        log.debug("[A2] _get_correlation error for (%s, %s): %s", analyst_a, analyst_b, e)
    return 0.0


async def detect_cluster(
    ticker: str,
    new_event_id: int,
    now_utc: datetime,
) -> ClusterResult:
    """
    Query signal_events WHERE source_type='twitter' AND ticker=? AND
    recorded_at >= now - window_minutes AND consumed_by_cluster_id IS NULL.
    Apply trust floor (>=2 of N members with rolling_accuracy >= min_trusted_accuracy).
    Apply regime guard via lookup_regime: if label='panic', require effective_size >= 4.
    Apply correlation discount via _get_correlation(analyst_a, analyst_b).
    On fire:
      - INSERT cluster_events row
      - INSERT signal_events row with source_type='ANALYST_CLUSTER'
      - UPDATE signal_events SET consumed_by_cluster_id = cluster_id for member rows
    Returns ClusterResult.
    """
    if not cfg.get("features.analyst_herding.enabled", False):
        return ClusterResult(
            fired=False,
            cluster_id=None,
            ticker=ticker,
            members=[],
            effective_size=0.0,
            reason="disabled",
        )

    window_minutes: int = cfg.get("features.analyst_herding.window_minutes", 30)
    min_cluster_size: int = cfg.get("features.analyst_herding.min_cluster_size", 3)
    min_trusted_accuracy: float = cfg.get("features.analyst_herding.min_trusted_accuracy", 0.5)
    require_trusted: bool = cfg.get("features.analyst_herding.require_trusted", False)
    panic_min_cluster_size: int = cfg.get("features.analyst_herding.panic_min_cluster_size", 4)
    members_cap: int = cfg.get("features.analyst_herding.members_cap", 20)

    cutoff = now_utc.timestamp() - window_minutes * 60
    conn = await db.get_db()

    # Fetch qualifying signal_events rows for this ticker within window
    cur = await conn.execute(
        """SELECT id, source_detail, recorded_at
           FROM signal_events
           WHERE source_type = 'twitter'
             AND ticker = ?
             AND recorded_at >= ?
             AND (consumed_by_cluster_id IS NULL)
           ORDER BY recorded_at ASC""",
        (ticker, cutoff),
    )
    rows = await cur.fetchall()

    # Deduplicate by analyst (source_detail), keep earliest per analyst
    seen_analysts: dict[str, dict] = {}
    for row in rows:
        analyst = row["source_detail"] or ""
        if analyst and analyst not in seen_analysts:
            seen_analysts[analyst] = {"id": row["id"], "recorded_at": row["recorded_at"]}

    unique_analysts = list(seen_analysts.keys())
    raw_count = len(unique_analysts)

    if raw_count < min_cluster_size:
        return ClusterResult(
            fired=False,
            cluster_id=None,
            ticker=ticker,
            members=[],
            effective_size=float(raw_count),
            reason="below_threshold",
        )

    # Lookup rolling_accuracy for each analyst from source_performance
    members: list[ClusterMember] = []
    for analyst in unique_analysts:
        row_data = seen_analysts[analyst]
        cur2 = await conn.execute(
            "SELECT rolling_accuracy FROM source_performance WHERE entity_id = ? AND horizon = 'short'",
            (analyst,),
        )
        perf_row = await cur2.fetchone()
        accuracy = float(perf_row["rolling_accuracy"]) if perf_row else 0.0
        members.append(ClusterMember(
            analyst=analyst,
            rolling_accuracy=accuracy,
            signal_event_id=row_data["id"],
            posted_at=row_data["recorded_at"],
        ))

    # Trust floor (opt-in via require_trusted, default OFF): at least 2 members must have
    # rolling_accuracy >= min_trusted_accuracy. Kept OFF because distinct-analyst VOLUME is
    # the "breaking news" signal, and source_performance has 0 rows so trusted_count is
    # always 0 — this floor blocked 100% of fires.
    trusted_count = sum(1 for m in members if m.rolling_accuracy >= min_trusted_accuracy)
    if require_trusted and trusted_count < 2:
        return ClusterResult(
            fired=False,
            cluster_id=None,
            ticker=ticker,
            members=members,
            effective_size=float(raw_count),
            reason="trust_floor_failed",
        )

    # Compute correlation discount: effective_size = raw_count - sum(co_post_rate for each pair)
    discount = 0.0
    analyst_list = [m.analyst for m in members]
    for i in range(len(analyst_list)):
        for j in range(i + 1, len(analyst_list)):
            discount += await _get_correlation(analyst_list[i], analyst_list[j])
    effective_size = float(raw_count) - discount

    # Regime guard: panic regime requires effective_size >= panic_min_cluster_size
    regime = await lookup_regime(now_utc)
    if regime.label == "panic" and effective_size < panic_min_cluster_size:
        return ClusterResult(
            fired=False,
            cluster_id=None,
            ticker=ticker,
            members=members,
            effective_size=effective_size,
            reason="regime_panic_min_4",
        )

    # Fire: insert cluster_events, signal_events cluster row, update member consumed_by_cluster_id
    now_ts = now_utc.timestamp()
    first_seen = min(m.posted_at for m in members)
    last_seen = max(m.posted_at for m in members)
    capped_members = members[:members_cap]
    members_json = json.dumps([
        {
            "analyst": m.analyst,
            "rolling_accuracy": m.rolling_accuracy,
            "signal_event_id": m.signal_event_id,
            "posted_at": m.posted_at,
        }
        for m in capped_members
    ])

    cur_ins = await conn.execute(
        """INSERT INTO cluster_events
           (ticker, first_seen_at, last_seen_at, cluster_size, effective_size, members_json, regime_label, fired_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (ticker, first_seen, last_seen, raw_count, effective_size, members_json, regime.label, now_ts),
    )
    cluster_id = cur_ins.lastrowid

    # Insert ANALYST_CLUSTER signal event
    await conn.execute(
        """INSERT INTO signal_events
           (source_type, source_detail, ticker, direction, quality_score, recorded_at)
           VALUES (?, ?, ?, NULL, ?, ?)""",
        ("ANALYST_CLUSTER", f"cluster:{cluster_id}", ticker, float(min(1.0, effective_size / 10.0)), now_ts),
    )

    # Mark member signal_events as consumed
    member_ids = [m.signal_event_id for m in capped_members]
    if member_ids:
        placeholders = ",".join("?" * len(member_ids))
        await conn.execute(
            f"UPDATE signal_events SET consumed_by_cluster_id = ? WHERE id IN ({placeholders})",
            [cluster_id] + member_ids,
        )

    await conn.commit()

    log.info(
        "[A2] Cluster fired for $%s: %d members (effective=%.1f) cluster_id=%s regime=%s",
        ticker, raw_count, effective_size, cluster_id, regime.label,
    )

    return ClusterResult(
        fired=True,
        cluster_id=cluster_id,
        ticker=ticker,
        members=members,
        effective_size=effective_size,
        reason="fired",
    )


async def refresh_correlation_matrix() -> None:
    """Build pair co-posting frequency from last 90d of signal_events.
    Persist to analyst_pair_correlations table.
    Called nightly (or on demand for tests).
    """
    conn = await db.get_db()
    cutoff = time.time() - 90 * 86400

    cur = await conn.execute(
        """SELECT source_detail, recorded_at
           FROM signal_events
           WHERE source_type = 'twitter'
             AND source_detail IS NOT NULL
             AND recorded_at >= ?
           ORDER BY recorded_at ASC""",
        (cutoff,),
    )
    rows = await cur.fetchall()

    # Build per-analyst posting timeline
    analyst_times: dict[str, list[float]] = {}
    for row in rows:
        analyst = row["source_detail"]
        if analyst:
            analyst_times.setdefault(analyst, []).append(row["recorded_at"])

    analysts = sorted(analyst_times.keys())
    pair_counts: dict[tuple, int] = {}
    total_windows: dict[str, int] = {}

    window_sec = 30 * 60  # 30 minutes
    for analyst in analysts:
        times = sorted(analyst_times[analyst])
        total_windows[analyst] = len(times)

    # Count co-posts: for each pair (a < b), count windows where both posted
    for i, a in enumerate(analysts):
        for b in analysts[i + 1:]:
            count = 0
            a_times = sorted(analyst_times[a])
            b_times = sorted(analyst_times[b])
            # Sliding window: for each a-post, check if any b-post within window_sec
            bi = 0
            for at in a_times:
                while bi < len(b_times) and b_times[bi] < at - window_sec:
                    bi += 1
                j = bi
                while j < len(b_times) and b_times[j] <= at + window_sec:
                    count += 1
                    break  # one co-post per a window
                    j += 1  # noqa: unreachable but kept for clarity
            if count > 0:
                pair_counts[(a, b)] = count

    now_ts = time.time()
    for (a, b), cnt in pair_counts.items():
        total = max(total_windows.get(a, 1), total_windows.get(b, 1))
        co_post_rate = cnt / total if total > 0 else 0.0
        await conn.execute(
            """INSERT OR REPLACE INTO analyst_pair_correlations
               (analyst_a, analyst_b, co_post_rate, sample_count, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (a, b, co_post_rate, cnt, now_ts),
        )

    await conn.commit()
    log.info("[A2] Correlation matrix refreshed: %d pairs updated", len(pair_counts))
