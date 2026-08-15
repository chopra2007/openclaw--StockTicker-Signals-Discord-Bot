#!/usr/bin/env python3
"""Read-only Batch 1 measurement gate check."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal
import yaml


PACIFIC = ZoneInfo("America/Los_Angeles")
NYSE = mcal.get_calendar("NYSE")
ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "consensus.yaml"
TERMINAL_OR_CURRENT = (
    "pending", "scored", "suppressed", "rejected_before_send", "timed_out", "failed",
)


def parse_cutoff(value: str) -> float:
    """Parse epoch seconds or an ISO timestamp; naive ISO means Pacific time."""
    try:
        return float(value)
    except ValueError:
        pass
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=PACIFIC)
    return parsed.timestamp()


def _display_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, PACIFIC).isoformat(timespec="seconds")


def _full_regular_sessions_elapsed(since: float, until: float) -> int:
    """Count completed scheduled NYSE sessions, excluding weekends and holidays."""
    start = datetime.fromtimestamp(since, PACIFIC)
    end = datetime.fromtimestamp(until, PACIFIC)
    schedule = NYSE.schedule(start.date(), end.date())
    return sum(
        1
        for _, session in schedule.iterrows()
        if session["market_open"].to_pydatetime() >= start
        and session["market_close"].to_pydatetime() <= end
    )


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple) -> int:
    return int(conn.execute(sql, params).fetchone()[0] or 0)


def evaluate_gate(conn: sqlite3.Connection, since: float, until: float) -> dict:
    """Return only aggregate, privacy-safe gate evidence."""
    window = (since, until)
    candidate_count = _scalar(
        conn,
        "SELECT COUNT(*) FROM measurement_candidates_v1 WHERE created_at>=? AND created_at<?",
        window,
    )
    old_count = _scalar(
        conn,
        "SELECT COUNT(*) FROM alert_history WHERE alerted_at>=? AND alerted_at<?",
        window,
    )
    new_count = _scalar(
        conn,
        """SELECT COUNT(DISTINCT a.legacy_alert_id)
           FROM measurement_alert_events_v1 a
           WHERE a.created_at>=? AND a.created_at<? AND a.legacy_alert_id IS NOT NULL
             AND EXISTS (
                 SELECT 1 FROM measurement_delivery_events_v1 de
                 WHERE de.decision_id=a.decision_id AND de.status='confirmed_delivered'
             )""",
        window,
    )
    missing_direction = _scalar(
        conn,
        """SELECT COUNT(*) FROM measurement_candidates_v1
           WHERE created_at>=? AND created_at<? AND direction NOT IN ('long','short')""",
        window,
    )
    placeholders = ",".join("?" for _ in TERMINAL_OR_CURRENT)
    missing_status = _scalar(
        conn,
        f"""SELECT COUNT(*) FROM measurement_candidates_v1 c
            WHERE c.created_at>=? AND c.created_at<?
              AND NOT EXISTS (
                  SELECT 1 FROM measurement_decision_events_v1 d
                  WHERE d.candidate_id=c.candidate_id
                    AND d.status IN ({placeholders})
              )""",
        (*window, *TERMINAL_OR_CURRENT),
    )
    missing_delivery_link = _scalar(
        conn,
        """SELECT COUNT(*) FROM measurement_delivery_events_v1 de
           WHERE de.created_at>=? AND de.created_at<? AND de.status='confirmed_delivered'
             AND NOT EXISTS (
                 SELECT 1 FROM measurement_decision_events_v1 d
                 WHERE d.decision_id=de.decision_id
             )""",
        window,
    )
    missing_score = _scalar(
        conn,
        """SELECT COUNT(DISTINCT de.decision_id)
           FROM measurement_delivery_events_v1 de
           WHERE de.created_at>=? AND de.created_at<? AND de.status='confirmed_delivered'
             AND EXISTS (
                 SELECT 1 FROM measurement_decision_events_v1 scored
                 WHERE scored.decision_id=de.decision_id AND scored.status='scored'
             )
             AND NOT EXISTS (
                 SELECT 1 FROM measurement_decision_events_v1 d
                 WHERE d.decision_id=de.decision_id
                   AND d.status='scored' AND d.owner_visible_score IS NOT NULL
             )""",
        window,
    )
    missing_displayed_score = _scalar(
        conn,
        """SELECT COUNT(DISTINCT de.decision_id)
           FROM measurement_delivery_events_v1 de
           WHERE de.created_at>=? AND de.created_at<? AND de.status='confirmed_delivered'
             AND EXISTS (
                 SELECT 1 FROM measurement_decision_events_v1 d
                 WHERE d.decision_id=de.decision_id AND d.status='scored'
             )
             AND NOT EXISTS (
                 SELECT 1 FROM measurement_alert_events_v1 a
                 WHERE a.decision_id=de.decision_id AND a.status='scored'
                   AND a.displayed_score IS NOT NULL
             )""",
        window,
    )
    score_mismatch = _scalar(
        conn,
        """SELECT COUNT(DISTINCT de.decision_id)
           FROM measurement_delivery_events_v1 de
           WHERE de.created_at>=? AND de.created_at<? AND de.status='confirmed_delivered'
             AND EXISTS (
                 SELECT 1
                 FROM measurement_decision_events_v1 d
                 JOIN measurement_alert_events_v1 a ON a.decision_id=d.decision_id
                 WHERE d.decision_id=de.decision_id
                   AND d.status='scored' AND a.status='scored'
                   AND d.owner_visible_score IS NOT NULL
                   AND a.displayed_score IS NOT NULL
                   AND d.owner_visible_score<>a.displayed_score
             )""",
        window,
    )
    missing_pending_outcome = _scalar(
        conn,
        """SELECT COUNT(DISTINCT de.decision_id)
           FROM measurement_delivery_events_v1 de
           WHERE de.created_at>=? AND de.created_at<? AND de.status='confirmed_delivered'
             AND NOT EXISTS (
                 SELECT 1 FROM measurement_outcome_events_v1 o
                 WHERE o.decision_id=de.decision_id
                   AND o.status='pending' AND o.horizon='primary'
             )""",
        window,
    )
    sessions = _full_regular_sessions_elapsed(since, until)
    reasons: list[str] = []
    if sessions < 1:
        reasons.append("one full regular market session has not elapsed")
    if candidate_count < 1:
        reasons.append("no trade candidates collected")
    if new_count < 1:
        reasons.append("no confirmed delivered alerts collected")
    if old_count != new_count:
        reasons.append(f"old/new confirmed-delivery count differs ({old_count} vs {new_count})")
    if missing_direction:
        reasons.append(f"{missing_direction} candidate(s) lack long/short direction")
    if missing_status:
        reasons.append(f"{missing_status} candidate(s) lack a current or terminal status")
    if missing_delivery_link:
        reasons.append(f"{missing_delivery_link} confirmed delivery row(s) lack a decision link")
    if missing_score:
        reasons.append(f"{missing_score} confirmed delivery decision(s) lack the stored visible score")
    if missing_displayed_score:
        reasons.append(
            f"{missing_displayed_score} confirmed scored alert(s) lack a displayed score"
        )
    if score_mismatch:
        reasons.append(
            f"{score_mismatch} confirmed scored alert(s) differ from the stored visible score"
        )
    if missing_pending_outcome:
        reasons.append(
            f"{missing_pending_outcome} confirmed delivery decision(s) lack a pending primary outcome"
        )
    return {
        "status": "PASS" if not reasons else "WAIT",
        "since_pacific": _display_time(since),
        "until_pacific": _display_time(until),
        "full_regular_sessions_elapsed": sessions,
        "candidate_count": candidate_count,
        "old_confirmed_delivery_count": old_count,
        "new_confirmed_delivery_count": new_count,
        "count_difference": new_count - old_count,
        "missing_direction": missing_direction,
        "missing_status": missing_status,
        "missing_delivery_link": missing_delivery_link,
        "missing_score": missing_score,
        "missing_displayed_score": missing_displayed_score,
        "score_mismatch": score_mismatch,
        "missing_pending_outcome": missing_pending_outcome,
        "reasons": reasons,
    }


def _database_path() -> Path:
    with CONFIG_PATH.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    return Path(config.get("database", {}).get("path", ROOT / "consensus.db"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, help="Cutover as epoch or ISO time; naive ISO is Pacific")
    parser.add_argument("--until", help="Optional end as epoch or ISO time; defaults to now")
    parser.add_argument("--db", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        since = parse_cutoff(args.since)
        until = parse_cutoff(args.until) if args.until else datetime.now(PACIFIC).timestamp()
        if until <= since:
            raise ValueError("--until must be later than --since")
        db_path = (args.db or _database_path()).resolve()
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            conn.execute("PRAGMA query_only=ON")
            result = evaluate_gate(conn, since, until)
        finally:
            conn.close()
    except (OSError, ValueError, sqlite3.Error) as exc:
        result = {"status": "WAIT", "reasons": [f"gate check could not complete: {exc}"]}
    print(json.dumps(result, sort_keys=True))
    if result["status"] == "PASS":
        print("PASS: Batch 1 measurement gate is satisfied.")
        return 0
    for reason in result["reasons"]:
        print(f"WAIT: {reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
