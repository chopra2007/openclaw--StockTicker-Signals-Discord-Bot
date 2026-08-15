#!/usr/bin/env python3
"""Read-only Batch 2 exact-trade gate check."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from consensus_engine import trade_tracking
from scripts.check_batch1_measurement_gate import (
    PACIFIC,
    _full_regular_sessions_elapsed,
    parse_cutoff,
)


CONFIG_PATH = ROOT / "config" / "consensus.yaml"
TABLES = (
    "measurement_trade_rule_sets_v1",
    "measurement_trade_plan_events_v1",
    "measurement_contract_selection_events_v1",
    "measurement_market_observations_v1",
    "measurement_trade_result_events_v1",
)


def _display_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, PACIFIC).isoformat(timespec="seconds")


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0] or 0)


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _latest_plan_cte() -> str:
    return """WITH latest_plan AS (
        SELECT p.* FROM measurement_trade_plan_events_v1 p
        WHERE p.rowid=(
            SELECT p2.rowid FROM measurement_trade_plan_events_v1 p2
            WHERE p2.trade_id=p.trade_id
            ORDER BY p2.rowid DESC LIMIT 1
        )
    )"""


def _reproduction_failures(
    conn: sqlite3.Connection, since: float, until: float, instrument: str,
) -> int:
    rows = conn.execute(
        _latest_plan_cte()
        + """
        SELECT r.result_json, r.gross_micros, r.net_micros,
               r.contract_fees_micros
        FROM measurement_trade_result_events_v1 r
        JOIN latest_plan p ON p.trade_id=r.trade_id
        WHERE p.confirmed_delivery_at>=? AND p.confirmed_delivery_at<?
          AND p.instrument_type=?
          AND r.status='resolved' AND r.is_primary=1
        """,
        (since, until, instrument),
    ).fetchall()
    failures = 0
    for row in rows:
        try:
            stored = json.loads(row[0])
            if instrument == "option":
                rebuilt = trade_tracking.reproduce_option_result(stored)
                expected = {
                    "gross_micros": trade_tracking.dollars_to_micros(
                        rebuilt["gross_dollars"]
                    ),
                    "net_micros": trade_tracking.dollars_to_micros(
                        rebuilt["net_dollars"]
                    ),
                    "contract_fees_micros": trade_tracking.dollars_to_micros(
                        rebuilt["contract_fees_total"]
                    ),
                }
            else:
                rebuilt = trade_tracking.reproduce_share_result(stored)
                expected = {
                    "gross_micros": trade_tracking.dollars_to_micros(
                        rebuilt["gross_dollars"]
                    ),
                    "net_micros": trade_tracking.dollars_to_micros(
                        rebuilt["net_dollars"]
                    ),
                    "contract_fees_micros": row[3],
                }
            actual = {
                "gross_micros": row[1],
                "net_micros": row[2],
                "contract_fees_micros": row[3],
            }
            if expected != actual:
                failures += 1
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            failures += 1
    return failures


def evaluate_gate(conn: sqlite3.Connection, since: float, until: float) -> dict:
    """Return aggregate evidence only; no ticker, analyst, or message text."""
    missing_tables = sorted(set(TABLES) - _table_names(conn))
    if missing_tables:
        return {
            "status": "WAIT",
            "since_pacific": _display_time(since),
            "until_pacific": _display_time(until),
            "missing_table_count": len(missing_tables),
            "reasons": ["Batch 2 database tables are not deployed"],
        }

    window = (since, until)
    sessions = _full_regular_sessions_elapsed(since, until)
    confirmed_decisions = _scalar(
        conn,
        """SELECT COUNT(DISTINCT decision_id)
           FROM measurement_delivery_events_v1
           WHERE status='confirmed_delivered' AND confirmed_at>=? AND confirmed_at<?""",
        window,
    )
    plan_count = _scalar(
        conn,
        """SELECT COUNT(DISTINCT trade_id)
           FROM measurement_trade_plan_events_v1
           WHERE confirmed_delivery_at>=? AND confirmed_delivery_at<?""",
        window,
    )
    missing_plan = _scalar(
        conn,
        """WITH first_delivery AS (
               SELECT d.* FROM measurement_delivery_events_v1 d
               WHERE d.status='confirmed_delivered'
                 AND d.rowid=(
                     SELECT d2.rowid FROM measurement_delivery_events_v1 d2
                     WHERE d2.decision_id=d.decision_id
                       AND d2.status='confirmed_delivered'
                     ORDER BY d2.confirmed_at, d2.rowid LIMIT 1
                 )
           )
           SELECT COUNT(*) FROM first_delivery d
           WHERE d.confirmed_at>=? AND d.confirmed_at<?
             AND NOT EXISTS (
                 SELECT 1 FROM measurement_trade_plan_events_v1 p
                 WHERE p.delivery_id=d.delivery_id
                   AND p.decision_id=d.decision_id
                   AND p.confirmed_delivery_at=d.confirmed_at
             )""",
        window,
    )
    broken_links = _scalar(
        conn,
        """SELECT COUNT(*) FROM measurement_trade_plan_events_v1 p
           WHERE p.confirmed_delivery_at>=? AND p.confirmed_delivery_at<?
             AND (
                 NOT EXISTS (SELECT 1 FROM measurement_candidates_v1 c
                             WHERE c.candidate_id=p.candidate_id)
              OR NOT EXISTS (SELECT 1 FROM measurement_decision_events_v1 d
                             WHERE d.decision_id=p.decision_id
                               AND d.candidate_id=p.candidate_id)
              OR NOT EXISTS (SELECT 1 FROM measurement_outcome_events_v1 o
                             WHERE o.outcome_id=p.outcome_id
                               AND o.decision_id=p.decision_id)
              OR NOT EXISTS (SELECT 1 FROM measurement_delivery_events_v1 de
                             WHERE de.delivery_id=p.delivery_id
                               AND de.decision_id=p.decision_id
                               AND de.status='confirmed_delivered'
                               AND de.confirmed_at=p.confirmed_delivery_at)
              OR NOT EXISTS (SELECT 1 FROM measurement_trade_rule_sets_v1 r
                             WHERE r.rule_set_id=p.rule_set_id)
             )""",
        window,
    )
    bad_rule_fee = _scalar(
        conn,
        """SELECT COUNT(*) FROM measurement_trade_rule_sets_v1
           WHERE fee_per_contract_transaction_micros<>450000""",
    )
    latest = _latest_plan_cte()
    missing_contract = _scalar(
        conn,
        latest
        + """
        SELECT COUNT(*) FROM latest_plan p
        WHERE p.confirmed_delivery_at>=? AND p.confirmed_delivery_at<?
          AND p.instrument_type='option'
          AND (
              (p.status='eligible' AND NOT EXISTS (
                  SELECT 1 FROM measurement_contract_selection_events_v1 c
                  WHERE c.trade_id=p.trade_id
                    AND c.contract_symbol<>'' AND c.option_type IN ('call','put')
                    AND c.action='buy_to_open' AND c.strike_micros>0
                    AND c.expiration<>'' AND c.multiplier>0
                    AND c.quote_source='schwab'
                    AND json_extract(c.contract_json, '$.capture_origin')
                        ='live_schwab_api'
              ))
              OR EXISTS (
                  SELECT 1 FROM measurement_trade_result_events_v1 x
                  WHERE x.trade_id=p.trade_id AND NOT EXISTS (
                      SELECT 1 FROM measurement_contract_selection_events_v1 c
                      WHERE c.trade_id=x.trade_id
                        AND c.selection_id=x.contract_selection_id
                        AND c.contract_symbol<>''
                        AND c.option_type IN ('call','put')
                        AND c.action='buy_to_open' AND c.strike_micros>0
                        AND c.expiration<>'' AND c.multiplier>0
                        AND c.quote_source='schwab'
                        AND json_extract(c.contract_json, '$.capture_origin')
                            ='live_schwab_api'
                  )
              )
          )""",
        window,
    )
    bad_entry_timing = _scalar(
        conn,
        latest
        + """
        SELECT COUNT(*)
        FROM measurement_market_observations_v1 o
        JOIN latest_plan p ON p.trade_id=o.trade_id
        JOIN measurement_trade_rule_sets_v1 r ON r.rule_set_id=p.rule_set_id
        WHERE p.confirmed_delivery_at>=? AND p.confirmed_delivery_at<?
          AND o.purpose='entry' AND o.usable=1
          AND (o.provider_timestamp>o.received_timestamp
               OR o.provider_timestamp<p.confirmed_delivery_at
               OR o.received_timestamp<p.confirmed_delivery_at
               OR o.received_timestamp>p.confirmed_delivery_at
                                        + r.max_delivery_entry_delay_seconds
               OR o.delivery_to_quote_seconds IS NULL
               OR ABS(o.delivery_to_quote_seconds
                      - (o.received_timestamp-p.confirmed_delivery_at))>0.001)""",
        window,
    )
    expired_pending = _scalar(
        conn,
        latest
        + """
        SELECT COUNT(*) FROM latest_plan p
        JOIN measurement_trade_rule_sets_v1 r ON r.rule_set_id=p.rule_set_id
        WHERE p.confirmed_delivery_at>=? AND p.confirmed_delivery_at<?
          AND p.status='pending'
          AND p.confirmed_delivery_at+r.max_delivery_entry_delay_seconds<?""",
        (*window, until),
    )

    def cohort_count(instrument: str, resolved: bool) -> int:
        condition = (
            "EXISTS (SELECT 1 FROM measurement_trade_result_events_v1 x "
            "JOIN measurement_market_observations_v1 xo "
            "ON xo.observation_id=x.exit_observation_id AND xo.trade_id=x.trade_id "
            "WHERE x.trade_id=p.trade_id AND x.status='resolved' AND x.is_primary=1 "
            "AND xo.purpose='exit' AND xo.status='observed' "
            "AND xo.provider_timestamp IS NOT NULL AND xo.received_timestamp IS NOT NULL "
            "AND xo.provider_timestamp<=xo.received_timestamp "
            "AND xo.quote_source='schwab' "
            "AND json_extract(xo.observation_json,'$.capture_origin')='live_schwab_api' "
            "AND (xo.usable=1 OR json_extract(xo.observation_json,'$.result_treatment')='zero_value'))"
            if resolved
            else "EXISTS (SELECT 1 FROM measurement_market_observations_v1 o "
                 "WHERE o.trade_id=p.trade_id AND o.purpose='entry' AND o.usable=1 "
                 "AND o.provider_timestamp<=o.received_timestamp "
                 "AND o.quote_source='schwab' "
                 "AND json_extract(o.observation_json,'$.capture_origin')='live_schwab_api')"
        )
        return _scalar(
            conn,
            latest
            + f"""
            SELECT COUNT(*) FROM latest_plan p
            WHERE p.confirmed_delivery_at>=? AND p.confirmed_delivery_at<?
              AND p.instrument_type=? AND p.status='eligible' AND {condition}""",
            (*window, instrument),
        )

    option_entries = cohort_count("option", False)
    share_entries = cohort_count("share", False)
    resolved_options = cohort_count("option", True)
    resolved_shares = cohort_count("share", True)
    result_link_errors = _scalar(
        conn,
        latest
        + """
        SELECT COUNT(*) FROM measurement_trade_result_events_v1 r
        JOIN latest_plan p ON p.trade_id=r.trade_id
        WHERE p.confirmed_delivery_at>=? AND p.confirmed_delivery_at<?
          AND r.outcome_id<>p.outcome_id""",
        window,
    )
    option_fee_errors = _scalar(
        conn,
        latest
        + """
        SELECT COUNT(*) FROM measurement_trade_result_events_v1 r
        JOIN latest_plan p ON p.trade_id=r.trade_id
        WHERE p.confirmed_delivery_at>=? AND p.confirmed_delivery_at<?
          AND p.instrument_type='option' AND r.status='resolved' AND r.is_primary=1
          AND r.contract_fees_micros<>(900000*COALESCE(p.contract_count,1))""",
        window,
    )
    reproduction_failures = _reproduction_failures(conn, since, until, "option")
    share_reproduction_failures = _reproduction_failures(
        conn, since, until, "share"
    )
    missing_usable_exit = _scalar(
        conn,
        latest
        + """
        SELECT COUNT(*) FROM measurement_trade_result_events_v1 r
        JOIN latest_plan p ON p.trade_id=r.trade_id
        WHERE p.confirmed_delivery_at>=? AND p.confirmed_delivery_at<?
          AND r.status='resolved' AND r.is_primary=1
          AND NOT EXISTS (
              SELECT 1 FROM measurement_market_observations_v1 o
              WHERE o.observation_id=r.exit_observation_id
                AND o.trade_id=r.trade_id AND o.purpose='exit'
                AND o.status='observed'
                AND o.provider_timestamp IS NOT NULL
                AND o.received_timestamp IS NOT NULL
                AND o.provider_timestamp<=o.received_timestamp
                AND o.quote_source='schwab'
                AND json_extract(o.observation_json, '$.capture_origin')
                    ='live_schwab_api'
                AND (o.usable=1 OR json_extract(
                    o.observation_json, '$.result_treatment'
                )='zero_value')
          )""",
        window,
    )
    result_observation_errors = _scalar(
        conn,
        latest
        + """
        SELECT COUNT(*) FROM measurement_trade_result_events_v1 r
        JOIN latest_plan p ON p.trade_id=r.trade_id
        WHERE p.confirmed_delivery_at>=? AND p.confirmed_delivery_at<?
          AND r.status='resolved' AND r.is_primary=1
          AND (
              NOT EXISTS (
                  SELECT 1 FROM measurement_market_observations_v1 e
                  WHERE e.observation_id=r.entry_observation_id
                    AND e.trade_id=r.trade_id AND e.purpose='entry' AND e.usable=1
                    AND e.observation_id=(
                        SELECT e2.observation_id
                        FROM measurement_market_observations_v1 e2
                        WHERE e2.trade_id=r.trade_id
                          AND e2.purpose='entry' AND e2.usable=1
                        ORDER BY e2.observed_at, e2.observation_id LIMIT 1
                    )
              )
              OR EXISTS (
                  SELECT 1
                  FROM measurement_market_observations_v1 e
                  JOIN measurement_market_observations_v1 x
                    ON x.observation_id=r.exit_observation_id
                   AND x.trade_id=r.trade_id
                  WHERE e.observation_id=r.entry_observation_id
                    AND e.trade_id=r.trade_id
                    AND (
                        r.resolved_at IS NULL
                        OR e.received_timestamp IS NULL
                        OR x.received_timestamp IS NULL
                        OR e.provider_timestamp>e.received_timestamp
                        OR x.provider_timestamp>x.received_timestamp
                        OR e.quote_source<>'schwab'
                        OR x.quote_source<>'schwab'
                        OR json_extract(e.observation_json, '$.capture_origin')
                            IS NOT 'live_schwab_api'
                        OR json_extract(x.observation_json, '$.capture_origin')
                            IS NOT 'live_schwab_api'
                        OR r.resolved_at < e.received_timestamp
                        OR ABS(r.resolved_at-x.received_timestamp)>0.001
                        OR
                        (p.instrument_type='option' AND (
                            r.contract_selection_id IS NULL
                            OR e.contract_selection_id<>r.contract_selection_id
                            OR x.contract_selection_id<>r.contract_selection_id
                            OR CAST(ROUND(json_extract(r.result_json, '$.entry_ask')*1000000) AS INTEGER)
                                <> e.ask_micros
                            OR CAST(ROUND(json_extract(r.result_json, '$.exit_bid')*1000000) AS INTEGER)
                                <> x.bid_micros
                        ))
                        OR (p.instrument_type='share' AND (
                            CAST(ROUND(json_extract(r.result_json, '$.entry_price')*1000000) AS INTEGER)
                                <> e.executable_price_micros
                            OR CAST(ROUND(json_extract(r.result_json, '$.exit_price')*1000000) AS INTEGER)
                                <> x.executable_price_micros
                        ))
                    )
              )
          )""",
        window,
    )
    overdue_unresolved = _scalar(
        conn,
        latest
        + """
        SELECT COUNT(*) FROM latest_plan p
        WHERE p.confirmed_delivery_at>=? AND p.confirmed_delivery_at<?
          AND p.status='eligible'
          AND COALESCE(json_extract(p.plan_json, '$.exit_due_at'), 0)<?
          AND NOT EXISTS (
              SELECT 1 FROM measurement_trade_result_events_v1 r
              WHERE r.trade_id=p.trade_id AND r.is_primary=1
                AND r.status IN (
                    'resolved', 'adjusted_contract', 'expired',
                    'early_assignment_risk', 'halted', 'gap', 'cannot_close'
                )
          )""",
        (*window, until),
    )
    missing_or_unusable_observations = _scalar(
        conn,
        latest
        + """
        SELECT COUNT(*) FROM measurement_market_observations_v1 o
        JOIN latest_plan p ON p.trade_id=o.trade_id
        WHERE p.confirmed_delivery_at>=? AND p.confirmed_delivery_at<?
          AND (o.status='missing_data' OR o.usable=0)""",
        window,
    )
    special_outcome_count = _scalar(
        conn,
        latest
        + """
        SELECT COUNT(*) FROM measurement_trade_result_events_v1 r
        JOIN latest_plan p ON p.trade_id=r.trade_id
        WHERE p.confirmed_delivery_at>=? AND p.confirmed_delivery_at<?
          AND r.status IN (
              'adjusted_contract', 'expired', 'early_assignment_risk',
              'halted', 'gap', 'cannot_close'
          )""",
        window,
    )
    invalid_special_outcomes = _scalar(
        conn,
        latest
        + """
        SELECT COUNT(*) FROM measurement_trade_result_events_v1 r
        JOIN latest_plan p ON p.trade_id=r.trade_id
        WHERE p.confirmed_delivery_at>=? AND p.confirmed_delivery_at<?
          AND r.status IN (
              'adjusted_contract', 'expired', 'early_assignment_risk',
              'halted', 'gap', 'cannot_close'
          )
          AND (
              r.result_rule_version=''
              OR r.resolved_at IS NULL
              OR COALESCE(json_extract(r.result_json, '$.reason'), '')=''
              OR (p.instrument_type='option' AND NOT EXISTS (
                  SELECT 1 FROM measurement_contract_selection_events_v1 c
                  WHERE c.trade_id=r.trade_id
                    AND c.selection_id=r.contract_selection_id
                    AND c.quote_source='schwab'
                    AND json_extract(c.contract_json, '$.capture_origin')
                        ='live_schwab_api'
              ))
              OR (r.status IN ('adjusted_contract','halted','gap') AND NOT EXISTS (
                  SELECT 1 FROM measurement_market_observations_v1 o
                  WHERE o.trade_id=r.trade_id
                    AND o.observation_id IN (
                        r.entry_observation_id, r.exit_observation_id
                    )
                    AND o.provider_timestamp<=o.received_timestamp
                    AND o.quote_source='schwab'
                    AND json_extract(o.observation_json, '$.capture_origin')
                        ='live_schwab_api'
                    AND (p.instrument_type<>'option'
                         OR o.contract_selection_id=r.contract_selection_id)
              ))
              OR (r.status='cannot_close' AND NOT EXISTS (
                  SELECT 1 FROM measurement_market_observations_v1 o
                  WHERE o.trade_id=r.trade_id
                    AND o.observation_id=r.exit_observation_id
                    AND o.status='missing_data'
              ))
          )""",
        window,
    )
    status_counts = {
        row[0]: int(row[1])
        for row in conn.execute(
            latest
            + """
            SELECT p.status, COUNT(*) FROM latest_plan p
            WHERE p.confirmed_delivery_at>=? AND p.confirmed_delivery_at<?
            GROUP BY p.status""",
            window,
        ).fetchall()
    }

    reasons: list[str] = []
    if sessions < 1:
        reasons.append("one completed market session has not elapsed")
    if confirmed_decisions < 1:
        reasons.append("no confirmed delivered decisions were collected")
    if missing_plan:
        reasons.append(f"{missing_plan} confirmed decision(s) lack a Batch 2 trade record")
    if broken_links:
        reasons.append(f"{broken_links} trade record(s) have a broken Batch 1 link")
    if bad_rule_fee:
        reasons.append(f"{bad_rule_fee} frozen rule set(s) do not use the $0.45 fee")
    if missing_contract:
        reasons.append(f"{missing_contract} eligible option trade(s) lack an exact contract")
    if bad_entry_timing:
        reasons.append(f"{bad_entry_timing} usable entry quote(s) violate delivery timing")
    if expired_pending:
        reasons.append(f"{expired_pending} trade(s) stayed pending after the entry window")
    if result_link_errors:
        reasons.append(f"{result_link_errors} result(s) use the wrong Batch 1 outcome")
    if option_fee_errors:
        reasons.append(f"{option_fee_errors} option result(s) use the wrong contract fee")
    if reproduction_failures:
        reasons.append(f"{reproduction_failures} option result(s) do not reproduce")
    if share_reproduction_failures:
        reasons.append(
            f"{share_reproduction_failures} share result(s) do not reproduce"
        )
    if missing_usable_exit:
        reasons.append(
            f"{missing_usable_exit} resolved result(s) lack a linked usable exit"
        )
    if result_observation_errors:
        reasons.append(
            f"{result_observation_errors} result(s) do not match their linked quotes"
        )
    if overdue_unresolved:
        reasons.append(
            f"{overdue_unresolved} eligible trade(s) lack a required final result"
        )
    if invalid_special_outcomes:
        reasons.append(
            f"{invalid_special_outcomes} special outcome(s) lack a version or reason"
        )
    if option_entries < 1:
        reasons.append("no eligible option has a real post-delivery entry")
    if share_entries < 1:
        reasons.append("no eligible share idea has a real post-delivery entry")
    if resolved_options < 1:
        reasons.append("no eligible option has a required real exit")
    if resolved_shares < 1:
        reasons.append("no eligible share idea has a required real exit")

    return {
        "status": "PASS" if not reasons else "WAIT",
        "since_pacific": _display_time(since),
        "until_pacific": _display_time(until),
        "full_sessions_elapsed": sessions,
        "confirmed_decision_count": confirmed_decisions,
        "trade_count": plan_count,
        "latest_status_counts": status_counts,
        "option_entry_count": option_entries,
        "share_entry_count": share_entries,
        "resolved_option_count": resolved_options,
        "resolved_share_count": resolved_shares,
        "missing_or_unusable_observation_count": missing_or_unusable_observations,
        "missing_plan": missing_plan,
        "broken_links": broken_links,
        "bad_rule_fee": bad_rule_fee,
        "missing_exact_contract": missing_contract,
        "bad_entry_timing": bad_entry_timing,
        "expired_pending": expired_pending,
        "result_link_errors": result_link_errors,
        "option_fee_errors": option_fee_errors,
        "reproduction_failures": reproduction_failures,
        "share_reproduction_failures": share_reproduction_failures,
        "missing_usable_exit": missing_usable_exit,
        "result_observation_errors": result_observation_errors,
        "overdue_unresolved": overdue_unresolved,
        "special_outcome_count": special_outcome_count,
        "invalid_special_outcomes": invalid_special_outcomes,
        "reasons": reasons,
    }


def _database_path() -> Path:
    with CONFIG_PATH.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    return Path(config.get("database", {}).get("path", ROOT / "consensus.db"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True)
    parser.add_argument("--until")
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
        print("PASS: Batch 2 exact-trade gate is satisfied.")
        return 0
    for reason in result["reasons"]:
        print(f"WAIT: {reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
