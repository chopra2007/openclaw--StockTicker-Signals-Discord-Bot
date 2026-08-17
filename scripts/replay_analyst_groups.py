#!/usr/bin/env python3
"""Rebuild and audit the saved analyst-group alert history for TODO #83/#84.

The public script contains no saved post text or account IDs. Raw source text and
row-level results are written only to the requested private `.omx/evidence` folder.
The database is opened read-only and this script never changes live alert data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from consensus_engine.analysis import benchmark_grading as bg  # noqa: E402
from grade_options_flow import fetch_daily_closes  # noqa: E402

PACIFIC = ZoneInfo("America/Los_Angeles")
DEFAULT_DB = ROOT / "consensus.db"
DEFAULT_OUTPUT = ROOT / ".omx" / "evidence" / "todo-83-84"
REVIEW_BATCH_SIZE = 20
EXACT_POST_EPSILON_SECONDS = 0.000001
EXACT_ALERT_MAX_DELAY_SECONDS = 5.0
MIN_RATE_SAMPLE = 10


@dataclass
class Reconstruction:
    recoverable: list[dict]
    unrecoverable: list[dict]


def _row_dicts(rows: Iterable) -> list[dict]:
    return [dict(row) for row in rows]


def _direction(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "long":
        return "bullish"
    if normalized == "short":
        return "bearish"
    return "unclear"


def _group_direction(members: Sequence[dict]) -> str:
    directions = {member["proposed_direction"] for member in members}
    if "bullish" in directions and "bearish" in directions:
        return "mixed"
    if directions == {"bullish"}:
        return "bullish"
    if directions == {"bearish"}:
        return "bearish"
    return "unclear"


def _post_key(ticker: str, analyst: str, timestamp: float) -> tuple[str, str, float]:
    return ticker, analyst, round(float(timestamp), 6)


def _members(group: dict) -> list[str]:
    try:
        payload = json.loads(group.get("members_json") or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item["analyst"]) for item in payload if item.get("analyst")]


def _review_id(event: dict, post: dict) -> str:
    raw = "|".join(
        (
            str(event["id"]),
            str(event["ticker"]),
            f"{float(event['recorded_at']):.6f}",
            str(post.get("raw_text") or ""),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def reconstruct_groups(
    group_rows: Sequence[dict], signal_rows: Sequence[dict], post_rows: Sequence[dict]
) -> Reconstruction:
    """Join each actual group-alert ledger row to its exact first member posts.

    `cluster_events` is the alert ledger. Each repeated row for the same ticker and
    `first_seen_at` is retained, so later analyst joins remain separate alert events.
    A row is recoverable only when every listed analyst has both the exact signal
    event inside `first_seen_at..fired_at` and the ticker_signals post at the same
    timestamp.
    """
    events_by_member: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for event in signal_rows:
        events_by_member[(event["ticker"], event["source_detail"])].append(event)
    for events in events_by_member.values():
        events.sort(key=lambda row: (float(row["recorded_at"]), int(row["id"])))

    posts_by_key: dict[tuple[str, str, float], list[dict]] = defaultdict(list)
    for post in post_rows:
        posts_by_key[
            _post_key(post["ticker"], post["source_detail"], post["detected_at"])
        ].append(post)
    for posts in posts_by_key.values():
        posts.sort(key=lambda row: int(row["id"]))

    chain_counts: Counter = Counter()
    recoverable: list[dict] = []
    unrecoverable: list[dict] = []

    for group in sorted(group_rows, key=lambda row: (float(row["fired_at"]), int(row["id"]))):
        analysts = _members(group)
        chain_key = (group["ticker"], float(group["first_seen_at"]))
        chain_counts[chain_key] += 1
        matched_members: list[dict] = []
        missing_members: list[str] = []
        missing_reasons: Counter = Counter()

        for analyst in analysts:
            candidates = [
                event
                for event in events_by_member[(group["ticker"], analyst)]
                if float(group["first_seen_at"]) - EXACT_POST_EPSILON_SECONDS
                <= float(event["recorded_at"])
                <= float(group["fired_at"]) + EXACT_POST_EPSILON_SECONDS
            ]
            if not candidates:
                missing_members.append(analyst)
                missing_reasons["missing_signal_event_in_group_window"] += 1
                continue
            event = candidates[0]
            exact_posts = posts_by_key.get(
                _post_key(event["ticker"], event["source_detail"], event["recorded_at"]), []
            )
            if not exact_posts:
                missing_members.append(analyst)
                missing_reasons["source_post_expired_or_missing"] += 1
                continue
            post = exact_posts[0]
            source_text = str(post.get("raw_text") or "")
            proposed_reason = " ".join(source_text.split()) or "reason not stated"
            matched_members.append(
                {
                    "analyst": analyst,
                    "signal_event_id": int(event["id"]),
                    "post_id": int(post["id"]),
                    "posted_at": float(event["recorded_at"]),
                    "source_link": event.get("source_link"),
                    "source_text": source_text,
                    "proposed_direction": _direction(event.get("direction")),
                    "proposed_reason": proposed_reason,
                    "reason_kind": "none",
                    "decision_code": "legacy_missing_view",
                    "review_id": _review_id(event, post),
                }
            )

        if missing_members:
            unrecoverable.append(
                {
                    "group_event_id": int(group["id"]),
                    "ticker": group["ticker"],
                    "fired_at": float(group["fired_at"]),
                    "listed_member_count": len(analysts),
                    "recovered_member_count": len(matched_members),
                    "missing_members": missing_members,
                    "missing_reasons": dict(missing_reasons),
                }
            )
            continue

        matched_members.sort(key=lambda row: (row["posted_at"], row["signal_event_id"]))
        recoverable.append(
            {
                "group_event_id": int(group["id"]),
                "ticker": group["ticker"],
                "first_seen_at": float(group["first_seen_at"]),
                "fired_at": float(group["fired_at"]),
                "event_kind": "opened" if chain_counts[chain_key] == 1 else "joined",
                "chain_event_number": chain_counts[chain_key],
                "member_count": len(matched_members),
                "group_direction": _group_direction(matched_members),
                "members": matched_members,
            }
        )

    return Reconstruction(recoverable=recoverable, unrecoverable=unrecoverable)


_DISCORD_ID = re.compile(r"<@!?\d{15,22}>|(?<!\d)\d{17,22}(?!\d)")
_SECRET_SHAPE = re.compile(
    r"(?i)\b(api[_ -]?key|token|secret|password)\b\s*[:=]\s*\S+"
)


def _redact_review_text(text: str) -> tuple[str, int]:
    redactions = 0

    def replace_id(match):
        nonlocal redactions
        redactions += 1
        return "[redacted-id]"

    def replace_secret(match):
        nonlocal redactions
        redactions += 1
        return f"{match.group(1)}=[redacted]"

    return _SECRET_SHAPE.sub(replace_secret, _DISCORD_ID.sub(replace_id, text)), redactions


def build_blind_review_rows(groups: Sequence[dict], batch_size: int = REVIEW_BATCH_SIZE) -> list[dict]:
    """One blind, de-duplicated review row per contributing post.

    Proposed labels, analyst handles, source links, and database IDs are excluded.
    This lets another Codex session read the post before seeing the bot's answer.
    """
    unique: dict[str, dict] = {}
    group_ids: dict[str, list[int]] = defaultdict(list)
    for group in groups:
        for member in group["members"]:
            review_id = member["review_id"]
            unique.setdefault(review_id, member)
            group_ids[review_id].append(int(group["group_event_id"]))

    rows = []
    for index, review_id in enumerate(sorted(unique), start=1):
        member = unique[review_id]
        source_text, redactions = _redact_review_text(member["source_text"])
        rows.append(
            {
                "review_id": review_id,
                "batch_number": (index - 1) // batch_size + 1,
                "ticker": next(
                    group["ticker"]
                    for group in groups
                    if any(item["review_id"] == review_id for item in group["members"])
                ),
                "posted_at_pacific": datetime.fromtimestamp(
                    member["posted_at"], tz=timezone.utc
                ).astimezone(PACIFIC).isoformat(),
                "source_text": source_text,
                "redaction_count": redactions,
                "contributing_group_event_ids": sorted(set(group_ids[review_id])),
                "review_request": {
                    "direction": "bullish, bearish, neutral, mixed, or unclear",
                    "catalyst_or_setup": "explicit reason or 'not stated'",
                    "support_phrase": "short phrase from the post",
                    "event_verification": "verified or unverified from supplied material",
                },
            }
        )
    return rows


def _field(embed: dict, name: str) -> str | None:
    for item in embed.get("fields", []):
        if item.get("name") == name:
            return item.get("value")
    return None


def compare_card_facts(legacy: dict, new: dict, *, ticker: str, count: int, span: str) -> dict:
    """Check facts that must survive the requested title/detail rewrite."""
    legacy_text = json.dumps(legacy, sort_keys=True)
    new_text = json.dumps(new, sort_keys=True)
    missing = []
    for label, expected in (
        ("ticker", f"${ticker}"),
        ("analyst count", str(count)),
        ("elapsed span", span),
    ):
        if expected not in legacy_text or expected not in new_text:
            missing.append(label)
    if legacy.get("color") != new.get("color"):
        missing.append("alert color")
    if _field(legacy, "Price") != _field(new, "Price"):
        missing.append("price")

    legacy_analysts = _field(legacy, "Analysts") or ""
    for linked_or_plain_handle in [part.strip() for part in legacy_analysts.split(",") if part.strip()]:
        if linked_or_plain_handle not in new_text:
            missing.append(f"analyst link or handle: {linked_or_plain_handle}")

    return {
        "unchanged_facts_pass": not missing,
        "missing_facts": missing,
        "requested_changes_present": {
            "swarm_removed_from_title": "SWARM" not in str(new.get("title", "")),
            "swarm_removed_from_footer": "swarm" not in str(new.get("footer", {})).lower(),
            "old_clock_window_removed": _field(new, "Window") is None,
            "group_bias_added": _field(new, "Group bias") is not None,
        },
    }


def _legacy_card(group: dict, price: float, links: dict[str, str]) -> dict:
    from consensus_engine.alerts.discord import _human_span

    count = len(group["members"])
    span = _human_span(group["fired_at"] - group["first_seen_at"])
    handles = ", ".join(
        f"[@{member['analyst']}]({links[member['analyst']]})"
        if links.get(member["analyst"])
        else f"@{member['analyst']}"
        for member in group["members"][:20]
    )
    fields = [{"name": "Analysts", "value": handles or "—", "inline": False}]
    posted = sorted(member["posted_at"] for member in group["members"])
    if posted:
        first = datetime.fromtimestamp(posted[0], tz=timezone.utc).strftime("%H:%M")
        last = datetime.fromtimestamp(posted[-1], tz=timezone.utc).strftime("%H:%M")
        fields.append(
            {"name": "Window", "value": f"{count} posts, {first}–{last} UTC", "inline": False}
        )
    if price > 0:
        fields.append({"name": "Price", "value": f"${price:.2f}", "inline": True})
    return {
        "title": f"🚨 SWARM: ${group['ticker']} — {count} analysts tweeting in {span}",
        "color": 0xED4245,
        "fields": fields,
        "footer": {"text": "OpenClaw Signal Engine | analyst swarm"},
    }


def _new_card(group: dict, price: float) -> dict:
    from consensus_engine.alerts.discord import format_swarm_alert
    from consensus_engine.analysis.herding import SwarmMemberDetail, SwarmResult

    details = [
        SwarmMemberDetail(
            analyst=member["analyst"],
            direction=(
                "long"
                if member["proposed_direction"] == "bullish"
                else "short"
                if member["proposed_direction"] == "bearish"
                else "unclear"
            ),
            reason=member["proposed_reason"],
            source_link=member.get("source_link"),
            posted_at=member["posted_at"],
            reason_kind=member.get("reason_kind", "none"),
            decision_code=member.get("decision_code", "missing"),
        )
        for member in group["members"]
    ]
    swarm = SwarmResult(
        fired=True,
        reason=group["event_kind"],
        ticker=group["ticker"],
        analysts=[member["analyst"] for member in group["members"]],
        member_times={member["analyst"]: member["posted_at"] for member in group["members"]},
        member_details=details,
        opened_at=group["first_seen_at"],
        now_ts=group["fired_at"],
        count=len(details),
    )
    return format_swarm_alert(swarm, price)


def _exact_alert(group: dict, alerts_by_ticker: dict[str, list[dict]]) -> dict | None:
    first_at = min(member["posted_at"] for member in group["members"])
    candidates = [
        alert
        for alert in alerts_by_ticker[group["ticker"]]
        if 0.0 <= float(alert["alerted_at"]) - first_at <= EXACT_ALERT_MAX_DELAY_SECONDS
        and float(alert.get("price_at_alert") or 0.0) > 0.0
    ]
    return candidates[0] if len(candidates) == 1 else None


def _daily_window(bars: dict[str, float], market_date: str, sessions: int) -> list[float]:
    days = sorted(bars)
    try:
        start = next(index for index, day in enumerate(days) if day >= market_date)
    except StopIteration:
        return []
    return [bars[day] for day in days[start : start + sessions + 1]]


def _return(entry: float | None, exit_price: float | None) -> float | None:
    if not entry or not exit_price or entry <= 0 or exit_price <= 0:
        return None
    return exit_price / entry - 1.0


def _worked(direction: str, move: float | None) -> bool | None:
    if move is None or direction not in {"bullish", "bearish"}:
        return None
    return move > 0 if direction == "bullish" else move < 0


def attach_outcomes(
    groups: list[dict], alert_rows: Sequence[dict], bars: dict[str, dict[str, float]]
) -> None:
    alerts_by_ticker: dict[str, list[dict]] = defaultdict(list)
    for alert in alert_rows:
        alerts_by_ticker[alert["ticker"]].append(alert)

    for group in groups:
        first_at = min(member["posted_at"] for member in group["members"])
        market_date = datetime.fromtimestamp(first_at, tz=timezone.utc).astimezone(PACIFIC).date().isoformat()
        ticker = group["ticker"]
        benchmark = bg.resolve_benchmark(ticker)
        stock_bars = bars.get(ticker, {})
        benchmark_bars = bars.get(benchmark, {}) if benchmark else {}
        stock_entry = bg.close_n_trading_days_later(stock_bars, market_date, 0)
        stock_1d = bg.close_n_trading_days_later(stock_bars, market_date, 1)
        stock_5d = bg.close_n_trading_days_later(stock_bars, market_date, 5)
        stock_21d = bg.close_n_trading_days_later(stock_bars, market_date, 21)
        window = _daily_window(stock_bars, market_date, 21)
        daily_1d = _return(stock_entry, stock_1d)
        daily_5d = _return(stock_entry, stock_5d)
        daily_21d = _return(stock_entry, stock_21d)
        exact = _exact_alert(group, alerts_by_ticker)

        group["price_anchor"] = {
            "kind": "exact_intraday" if exact else "daily_price_approximation",
            "price": float(exact["price_at_alert"]) if exact else stock_entry,
            "tweet_to_price_seconds": (
                float(exact["alerted_at"]) - first_at if exact else None
            ),
            "first_tweet_at": first_at,
            "market_date_pacific": market_date,
        }
        group["exact_intraday_outcomes"] = {
            "available": bool(exact),
            "entry_price": float(exact["price_at_alert"]) if exact else None,
            "return_24h": (
                _return(exact["price_at_alert"], exact.get("price_24h_later")) if exact else None
            ),
            "return_5d": (
                _return(exact["price_at_alert"], exact.get("price_5d_later")) if exact else None
            ),
        }
        group["daily_price_approximation"] = {
            "entry_close": stock_entry,
            "return_1_session": daily_1d,
            "return_5_sessions": daily_5d,
            "return_21_sessions": daily_21d,
            "best_move_21_sessions": (
                max((_return(stock_entry, price) for price in window), default=None)
                if stock_entry
                else None
            ),
            "worst_move_21_sessions": (
                min((_return(stock_entry, price) for price in window), default=None)
                if stock_entry
                else None
            ),
            "benchmark": benchmark,
            "benchmark_adjusted_5_sessions": (
                bg.buy_and_hold_abnormal_return(stock_bars, benchmark_bars, market_date, 5)
                if benchmark_bars
                else None
            ),
            "benchmark_adjusted_21_sessions": (
                bg.buy_and_hold_abnormal_return(stock_bars, benchmark_bars, market_date, 21)
                if benchmark_bars
                else None
            ),
        }
        group["direction_later_worked"] = {
            "exact_24h": _worked(
                group["group_direction"], group["exact_intraday_outcomes"]["return_24h"]
            ),
            "exact_5d": _worked(
                group["group_direction"], group["exact_intraday_outcomes"]["return_5d"]
            ),
            "daily_21_sessions": _worked(group["group_direction"], daily_21d),
        }


def attach_card_comparisons(groups: list[dict]) -> None:
    from consensus_engine.alerts.discord import _clip, _human_span

    for group in groups:
        for member in group["members"]:
            url = member.get("source_link")
            handle = (
                f"[@{member['analyst']}]({url})" if url and len(url) <= 180 else f"@{member['analyst']}"
            )
            label = {
                "bullish": "🟢 Bullish",
                "bearish": "🔴 Bearish",
                "unclear": "⚪ Unclear",
            }[member["proposed_direction"]]
            prefix = f"{handle} — {label} — "
            if len(prefix) > 220:
                prefix = f"@{member['analyst']} — {label} — "
            reason = " ".join((member["proposed_reason"] or "").split()) or "reason not stated"
            if member.get("reason_kind") == "event_claim" and reason != "reason not stated":
                reason = f"Analyst says: {reason}"
            member["displayed_reason"] = _clip(reason, max(20, 250 - len(prefix)))
        links = {
            member["analyst"]: member["source_link"]
            for member in group["members"]
            if member.get("source_link")
        }
        price = float(group.get("price_anchor", {}).get("price") or 0.0)
        legacy = _legacy_card(group, price, links)
        new = _new_card(group, price)
        group["card_comparison"] = compare_card_facts(
            legacy,
            new,
            ticker=group["ticker"],
            count=len(group["members"]),
            span=_human_span(group["fired_at"] - group["first_seen_at"]),
        )


def _rate(values: Sequence[bool | None]) -> tuple[float | None, str]:
    resolved = [value for value in values if value is not None]
    if len(resolved) < MIN_RATE_SAMPLE:
        return None, f"{len(resolved)} resolved cases; rate withheld below {MIN_RATE_SAMPLE}"
    return sum(bool(value) for value in resolved) / len(resolved), f"{len(resolved)} resolved cases"


def summarize_counts(
    *,
    total_group_events: int,
    recoverable_groups: Sequence[dict],
    unresolved_group_count: int,
    exact_anchor_count: int,
    daily_anchor_count: int,
    direction_results: Sequence[bool | None],
) -> dict:
    unique_tweets = {
        member["review_id"] for group in recoverable_groups for member in group["members"]
    }
    rate, rate_note = _rate(direction_results)
    return {
        "counts": {
            "actual_group_events": total_group_events,
            "recoverable_group_events": len(recoverable_groups),
            "unrecoverable_group_events": unresolved_group_count,
            "opened_events": sum(group["event_kind"] == "opened" for group in recoverable_groups),
            "repeated_join_events": sum(
                group["event_kind"] == "joined" for group in recoverable_groups
            ),
            "member_appearances": sum(len(group["members"]) for group in recoverable_groups),
            "unique_contributing_tweets": len(unique_tweets),
            "exact_intraday_anchors": exact_anchor_count,
            "daily_price_approximation_anchors": daily_anchor_count,
        },
        "rates": {
            "direction_later_worked": rate,
            "direction_later_worked_note": rate_note,
        },
    }


def summarize_outcomes(groups: Sequence[dict]) -> dict:
    exact_24h = [group["direction_later_worked"]["exact_24h"] for group in groups]
    exact_5d = [group["direction_later_worked"]["exact_5d"] for group in groups]
    daily_21 = [group["direction_later_worked"]["daily_21_sessions"] for group in groups]
    rate_24h, note_24h = _rate(exact_24h)
    rate_5d, note_5d = _rate(exact_5d)
    rate_21d, note_21d = _rate(daily_21)

    def resolved(values):
        return [value for value in values if value is not None]

    return {
        "counts": {
            "group_bias": dict(Counter(group["group_direction"] for group in groups)),
            "exact_24h_direction_resolved": len(resolved(exact_24h)),
            "exact_24h_direction_worked": sum(resolved(exact_24h)),
            "exact_5d_direction_resolved": len(resolved(exact_5d)),
            "exact_5d_direction_worked": sum(resolved(exact_5d)),
            "daily_21_session_direction_resolved": len(resolved(daily_21)),
            "daily_21_session_direction_worked": sum(resolved(daily_21)),
            "daily_1_session_raw_moves": sum(
                group["daily_price_approximation"]["return_1_session"] is not None
                for group in groups
            ),
            "daily_5_session_raw_moves": sum(
                group["daily_price_approximation"]["return_5_sessions"] is not None
                for group in groups
            ),
            "daily_21_session_raw_moves": sum(
                group["daily_price_approximation"]["return_21_sessions"] is not None
                for group in groups
            ),
            "benchmark_adjusted_5_session_moves": sum(
                group["daily_price_approximation"]["benchmark_adjusted_5_sessions"] is not None
                for group in groups
            ),
            "benchmark_adjusted_21_session_moves": sum(
                group["daily_price_approximation"]["benchmark_adjusted_21_sessions"] is not None
                for group in groups
            ),
        },
        "rates": {
            "exact_24h_direction_worked": rate_24h,
            "exact_24h_note": note_24h,
            "exact_5d_direction_worked": rate_5d,
            "exact_5d_note": note_5d,
            "daily_21_session_direction_worked": rate_21d,
            "daily_21_session_note": note_21d,
        },
    }


def _read_database(path: Path) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        groups = _row_dicts(
            connection.execute(
                "SELECT * FROM cluster_events WHERE regime_label='' ORDER BY fired_at, id"
            )
        )
        signals = _row_dicts(
            connection.execute(
                """SELECT id, ticker, source_detail, direction, recorded_at, source_link
                   FROM signal_events
                   WHERE source_type='twitter' AND source_detail IS NOT NULL
                   ORDER BY recorded_at, id"""
            )
        )
        posts = _row_dicts(
            connection.execute(
                """SELECT id, ticker, source_detail, raw_text, sentiment, detected_at
                   FROM ticker_signals
                   WHERE source_type='twitter' AND source_detail IS NOT NULL"""
            )
        )
        alerts = _row_dicts(
            connection.execute(
                """SELECT id, ticker, alerted_at, price_at_alert,
                          price_24h_later, price_5d_later
                   FROM alert_history ORDER BY alerted_at, id"""
            )
        )
        return groups, signals, posts, alerts
    finally:
        connection.close()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path: Path, rows: Sequence[dict]) -> None:
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _write_review_package(output_dir: Path, rows: Sequence[dict]) -> None:
    package_dir = output_dir / "blind-review-batches"
    package_dir.mkdir(parents=True, exist_ok=True)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["reviews"],
        "properties": {
            "reviews": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "review_id",
                        "direction",
                        "catalyst_or_setup",
                        "support_phrase",
                        "event_verification",
                    ],
                    "properties": {
                        "review_id": {"type": "string"},
                        "direction": {
                            "type": "string",
                            "enum": ["bullish", "bearish", "neutral", "mixed", "unclear"],
                        },
                        "catalyst_or_setup": {"type": "string"},
                        "support_phrase": {"type": "string"},
                        "event_verification": {
                            "type": "string",
                            "enum": ["verified", "unverified"],
                        },
                    },
                },
            }
        },
    }
    _write_json(package_dir / "review-output-schema.json", schema)
    by_batch: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_batch[int(row["batch_number"])].append(row)
    for batch_number, batch_rows in sorted(by_batch.items()):
        _write_json(package_dir / f"batch-{batch_number:03d}.json", batch_rows)


def _write_root_cause_package(output_dir: Path, groups: Sequence[dict]) -> int:
    package_dir = output_dir / "root-cause-batches"
    package_dir.mkdir(parents=True, exist_ok=True)
    unique: dict[str, dict] = {}
    ticker_by_review: dict[str, str] = {}
    for group in groups:
        for member in group["members"]:
            if not member.get("direction_agreement", True) or not member.get("reason_supported", True):
                unique.setdefault(member["review_id"], member)
                ticker_by_review.setdefault(member["review_id"], group["ticker"])

    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["reviews"],
        "properties": {
            "reviews": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "review_id", "primary_cause", "source_direction_verdict",
                        "independent_review_verdict", "displayed_reason_verdict",
                        "recommended_rule", "short_explanation",
                    ],
                    "properties": {
                        "review_id": {"type": "string"},
                        "primary_cause": {
                            "type": "string",
                            "enum": [
                                "source_signal_direction_wrong",
                                "independent_review_wrong_or_uncorroborated",
                                "multi_ticker_attribution_wrong",
                                "generic_or_neutral_post_mislabeled",
                                "excerpt_selection_wrong",
                            ],
                        },
                        "source_direction_verdict": {
                            "type": "string",
                            "enum": ["bullish", "bearish", "neutral", "mixed", "unclear"],
                        },
                        "independent_review_verdict": {
                            "type": "string",
                            "enum": ["correct", "wrong", "ambiguous"],
                        },
                        "displayed_reason_verdict": {
                            "type": "string",
                            "enum": ["supported", "unsupported", "truncated_wrong_clause"],
                        },
                        "recommended_rule": {
                            "type": "string",
                            "enum": [
                                "use_stored_parsed_direction_and_summary",
                                "force_unclear_for_generic_activity",
                                "extract_ticker_specific_clause",
                                "retain_full_ticker_clause_before_clipping",
                                "no_production_change_review_error",
                            ],
                        },
                        "short_explanation": {"type": "string"},
                    },
                },
            }
        },
    }
    _write_json(package_dir / "root-cause-output-schema.json", schema)
    rows = []
    for index, review_id in enumerate(sorted(unique), start=1):
        member = unique[review_id]
        rows.append(
            {
                "review_id": review_id,
                "batch_number": (index - 1) // REVIEW_BATCH_SIZE + 1,
                "ticker": ticker_by_review[review_id],
                "source_text": member["source_text"],
                "stored_direction": member["proposed_direction"],
                "displayed_reason": member.get("displayed_reason"),
                "blind_review": member.get("independent_review"),
                "direction_disagreement": not member.get("direction_agreement", True),
                "bullish_bearish_reversal": bool(member.get("direction_reversal")),
                "unsupported_reason": not member.get("reason_supported", True),
            }
        )
    by_batch: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_batch[row["batch_number"]].append(row)
    for batch_number, batch_rows in sorted(by_batch.items()):
        _write_json(package_dir / f"batch-{batch_number:03d}.json", batch_rows)
    return len(rows)


def _write_adjudication_package(output_dir: Path) -> int:
    source_dir = output_dir / "root-cause-batches"
    package_dir = output_dir / "adjudication-batches"
    package_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(source_dir.glob("batch-*.json")):
        rows.extend(json.loads(path.read_text()))
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["reviews"],
        "properties": {
            "reviews": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "review_id", "final_direction", "final_catalyst_or_setup",
                        "final_support_phrase", "corroboration_status", "root_cause",
                        "recommended_rule", "short_explanation",
                    ],
                    "properties": {
                        "review_id": {"type": "string"},
                        "final_direction": {
                            "type": "string",
                            "enum": ["bullish", "bearish", "neutral", "mixed", "unclear"],
                        },
                        "final_catalyst_or_setup": {"type": "string"},
                        "final_support_phrase": {"type": "string"},
                        "corroboration_status": {
                            "type": "string",
                            "enum": ["verified", "unverified", "not_applicable"],
                        },
                        "root_cause": {
                            "type": "string",
                            "enum": [
                                "source_signal_direction_wrong",
                                "independent_review_wrong_or_uncorroborated",
                                "multi_ticker_attribution_wrong",
                                "generic_or_neutral_post_mislabeled",
                                "excerpt_selection_wrong",
                            ],
                        },
                        "recommended_rule": {"type": "string"},
                        "short_explanation": {"type": "string"},
                    },
                },
            }
        },
    }
    _write_json(package_dir / "adjudication-output-schema.json", schema)
    by_batch: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_batch[int(row["batch_number"])].append(row)
    for batch_number, batch_rows in sorted(by_batch.items()):
        _write_json(package_dir / f"batch-{batch_number:03d}.json", batch_rows)
    return len(rows)


def _write_pending_rows(
    output_dir: Path, source_subdir: str, completed: dict[str, dict], filename: str
) -> int:
    rows = []
    for path in sorted((output_dir / source_subdir).glob("batch-*.json")):
        rows.extend(json.loads(path.read_text()))
    pending = [row for row in rows if row["review_id"] not in completed]
    _write_json(output_dir / filename, pending)
    return len(pending)


def load_review_results(results_dir: Path | None) -> dict[str, dict]:
    if results_dir is None or not results_dir.exists():
        return {}
    results: dict[str, dict] = {}
    for path in sorted(results_dir.glob("batch-*.json")):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for review in payload.get("reviews", []):
            review_id = str(review.get("review_id") or "")
            if review_id:
                results[review_id] = review
    return results


def summarize_root_causes(groups: Sequence[dict], results_dir: Path | None) -> dict:
    results = load_review_results(results_dir)
    mismatches: dict[str, dict] = {}
    for group in groups:
        for member in group["members"]:
            if not member.get("direction_agreement", True) or not member.get("reason_supported", True):
                mismatches.setdefault(member["review_id"], member)
    category_counts = Counter()
    direction_category_counts = Counter()
    reversal_category_counts = Counter()
    reason_category_counts = Counter()
    recommended_rule_counts = Counter()
    representative_ids: dict[str, list[str]] = defaultdict(list)
    for review_id, member in mismatches.items():
        result = results.get(review_id)
        if not result:
            continue
        category = result.get("primary_cause", "")
        category_counts[category] += 1
        recommended_rule_counts[result.get("recommended_rule", "")] += 1
        if not member.get("direction_agreement", True):
            direction_category_counts[category] += 1
        if member.get("direction_reversal"):
            reversal_category_counts[category] += 1
        if not member.get("reason_supported", True):
            reason_category_counts[category] += 1
        if len(representative_ids[category]) < 5:
            representative_ids[category].append(review_id)
        member["root_cause_review"] = result
    return {
        "counts": {
            "unique_mismatch_posts": len(mismatches),
            "categorized": sum(category_counts.values()),
            "missing": len(mismatches) - sum(category_counts.values()),
            "all_mismatches_by_primary_cause": dict(category_counts),
            "direction_disagreements_by_primary_cause": dict(direction_category_counts),
            "reversals_by_primary_cause": dict(reversal_category_counts),
            "unsupported_reasons_by_primary_cause": dict(reason_category_counts),
            "recommended_rule_counts": dict(recommended_rule_counts),
        },
        "representative_review_ids": dict(representative_ids),
    }


def _normalized_review_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.lower().split()).strip(" \t\r\n.\"'“”‘’…")


def _not_stated(value: object) -> bool:
    normalized = _normalized_review_text(value)
    return normalized in {
        "",
        "not stated",
        "reason not stated",
        "none",
        "no catalyst stated",
        "no setup stated",
    }


def _support_phrase_present(phrase: object, proposed_reason: object) -> bool:
    normalized_phrase = _normalized_review_text(phrase)
    normalized_reason = _normalized_review_text(proposed_reason)
    return bool(normalized_phrase) and normalized_phrase in normalized_reason


def attach_review_results(groups: Sequence[dict], results: dict[str, dict]) -> dict:
    unique_members: dict[str, dict] = {}
    for group in groups:
        for member in group["members"]:
            unique_members.setdefault(member["review_id"], member)

    counts = Counter()
    for review_id, member in unique_members.items():
        review = results.get(review_id)
        if not review:
            continue
        independent = str(review.get("direction") or "unclear").lower()
        proposed = member["proposed_direction"]
        independent_for_compare = "unclear" if independent == "neutral" else independent
        reversal = (proposed, independent_for_compare) in {
            ("bullish", "bearish"),
            ("bearish", "bullish"),
        }
        direction_agreement = proposed == independent_for_compare
        displayed_reason = member.get("displayed_reason", member.get("proposed_reason"))
        proposed_reason_missing = _not_stated(displayed_reason)
        independent_catalyst_missing = _not_stated(review.get("catalyst_or_setup"))
        support_present = _support_phrase_present(
            review.get("support_phrase"), displayed_reason
        )
        catalyst_agreement = (
            proposed_reason_missing and independent_catalyst_missing
        ) or (
            not proposed_reason_missing and not independent_catalyst_missing and support_present
        )
        unsupported_reason = not catalyst_agreement
        member["independent_review"] = review
        member["tweet_read_accurate"] = direction_agreement and catalyst_agreement
        member["direction_reversal"] = reversal
        member["direction_agreement"] = direction_agreement
        member["catalyst_agreement"] = catalyst_agreement
        member["support_phrase_present_in_displayed_reason"] = support_present
        member["reason_supported"] = not unsupported_reason
        counts["reviewed"] += 1
        counts["direction_agreements"] += int(direction_agreement)
        counts["direction_disagreements"] += int(not direction_agreement)
        counts["catalyst_agreements"] += int(catalyst_agreement)
        counts["unsupported_reasons"] += int(unsupported_reason)
        counts["support_phrase_not_found"] += int(
            not independent_catalyst_missing and not support_present
        )
        counts["reversals"] += int(reversal)
        counts["unverified_events"] += int(review.get("event_verification") == "unverified")
    counts["missing"] = len(unique_members) - counts["reviewed"]
    counts["gate_pass"] = (
        counts["missing"] == 0
        and counts["reversals"] == 0
        and counts["unsupported_reasons"] == 0
    )
    return dict(counts)


def apply_adjudication_results(groups: Sequence[dict], results: dict[str, dict]) -> dict:
    unique_members: dict[str, dict] = {}
    for group in groups:
        for member in group["members"]:
            unique_members.setdefault(member["review_id"], member)
    required = {
        review_id
        for review_id, member in unique_members.items()
        if not member.get("direction_agreement", True) or not member.get("reason_supported", True)
    }
    for review_id in required:
        member = unique_members[review_id]
        result = results.get(review_id)
        if not result:
            continue
        final_direction = str(result.get("final_direction") or "unclear").lower()
        final_for_compare = "unclear" if final_direction == "neutral" else final_direction
        displayed_reason = member.get("displayed_reason", member.get("proposed_reason"))
        catalyst_missing = _not_stated(result.get("final_catalyst_or_setup"))
        displayed_missing = _not_stated(displayed_reason)
        support_present = _support_phrase_present(result.get("final_support_phrase"), displayed_reason)
        catalyst_agreement = (displayed_missing and catalyst_missing) or (
            not displayed_missing and not catalyst_missing and support_present
        )
        direction_agreement = member["proposed_direction"] == final_for_compare
        reversal = (member["proposed_direction"], final_for_compare) in {
            ("bullish", "bearish"),
            ("bearish", "bullish"),
        }
        member["adjudication_override"] = result
        member["direction_agreement"] = direction_agreement
        member["catalyst_agreement"] = catalyst_agreement
        member["reason_supported"] = catalyst_agreement
        member["direction_reversal"] = reversal
        member["tweet_read_accurate"] = direction_agreement and catalyst_agreement

    reviewed = [member for member in unique_members.values() if member.get("independent_review")]
    missing_adjudications = len(required - set(results))
    counts = {
        "reviewed": len(reviewed),
        "adjudication_required": len(required),
        "adjudicated": len(required & set(results)),
        "missing_adjudications": missing_adjudications,
        "direction_agreements": sum(member.get("direction_agreement", False) for member in reviewed),
        "direction_disagreements": sum(not member.get("direction_agreement", False) for member in reviewed),
        "reversals": sum(member.get("direction_reversal", False) for member in reviewed),
        "catalyst_agreements": sum(member.get("reason_supported", False) for member in reviewed),
        "unsupported_reasons": sum(not member.get("reason_supported", False) for member in reviewed),
    }
    counts["gate_pass"] = (
        len(reviewed) == len(unique_members)
        and missing_adjudications == 0
        and counts["reversals"] == 0
        and counts["unsupported_reasons"] == 0
    )
    return counts


def _exact_support_phrase(source_text: str, phrase: object) -> str | None:
    wanted = str(phrase or "").strip()
    if not wanted or _not_stated(wanted):
        return None
    direct = source_text.find(wanted)
    if direct >= 0:
        return source_text[direct : direct + len(wanted)]
    words = wanted.split()
    if not words:
        return None
    match = re.search(r"\s+".join(re.escape(word) for word in words), source_text, re.IGNORECASE)
    return match.group(0) if match else None


def apply_final_review_views(
    groups: Sequence[dict], blind_results: dict[str, dict], adjudications: dict[str, dict]
) -> dict:
    """Build private historical analyst-view-v1 values from the final reviewed truth.

    This does not write the live database. It exercises the same fail-closed direction,
    exact reason span, event attribution, and card rendering rules for saved history.
    """
    applied = 0
    missing = 0
    invalid_support = 0
    for group in groups:
        for member in group["members"]:
            review_id = member["review_id"]
            override = adjudications.get(review_id)
            blind = blind_results.get(review_id)
            truth = override or blind
            if not truth:
                missing += 1
                continue
            raw_direction = (
                truth.get("final_direction") if override else truth.get("direction")
            )
            direction = str(raw_direction or "unclear").lower()
            member["proposed_direction"] = (
                direction if direction in {"bullish", "bearish"} else "unclear"
            )
            catalyst = (
                truth.get("final_catalyst_or_setup")
                if override
                else truth.get("catalyst_or_setup")
            )
            phrase = (
                truth.get("final_support_phrase") if override else truth.get("support_phrase")
            )
            exact_phrase = None if _not_stated(catalyst) else _exact_support_phrase(
                member["source_text"], phrase
            )
            if _not_stated(catalyst):
                member["proposed_reason"] = "reason not stated"
                member["reason_kind"] = "none"
                member["decision_code"] = "reviewed_no_explicit_clause"
            elif exact_phrase:
                member["proposed_reason"] = exact_phrase
                corroboration = (
                    truth.get("corroboration_status")
                    if override
                    else truth.get("event_verification")
                )
                member["reason_kind"] = (
                    "event_claim" if corroboration in {"verified", "unverified"} else "setup"
                )
                member["decision_code"] = "explicit_clause"
            else:
                member["proposed_reason"] = "reason not stated"
                member["reason_kind"] = "none"
                member["decision_code"] = "invalid_span"
                invalid_support += 1
            member["synthetic_view_source"] = "adjudication" if override else "accepted_blind_review"
            applied += 1
        group["group_direction"] = _group_direction(group["members"])
        if group.get("direction_later_worked"):
            group["direction_later_worked"]["exact_24h"] = _worked(
                group["group_direction"], group["exact_intraday_outcomes"]["return_24h"]
            )
            group["direction_later_worked"]["exact_5d"] = _worked(
                group["group_direction"], group["exact_intraday_outcomes"]["return_5d"]
            )
            group["direction_later_worked"]["daily_21_sessions"] = _worked(
                group["group_direction"],
                group["daily_price_approximation"]["return_21_sessions"],
            )
    return {"applied": applied, "missing": missing, "invalid_support_phrases": invalid_support}


def final_review_views(groups: Sequence[dict]) -> dict[str, dict]:
    views: dict[str, dict] = {}
    for group in groups:
        for member in group["members"]:
            review_id = member["review_id"]
            if review_id in views:
                continue
            reason = member["proposed_reason"]
            start = member["source_text"].find(reason) if reason != "reason not stated" else -1
            views[review_id] = {
                "review_id": review_id,
                "ticker": group["ticker"],
                "display_direction": (
                    "long"
                    if member["proposed_direction"] == "bullish"
                    else "short"
                    if member["proposed_direction"] == "bearish"
                    else "unclear"
                ),
                "reason_text": None if reason == "reason not stated" else reason,
                "reason_start": None if start < 0 else start,
                "reason_end": None if start < 0 else start + len(reason),
                "reason_kind": member.get("reason_kind", "none"),
                "decision_code": member.get("decision_code", "missing"),
                "parser_version": "analyst-view-v1-audit",
                "review_source": member.get("synthetic_view_source"),
            }
    return views


def _write_unsupported_reason_rows(output_dir: Path, groups: Sequence[dict]) -> int:
    rows = []
    seen = set()
    for group in groups:
        for member in group["members"]:
            if member["review_id"] in seen or member.get("reason_supported", True):
                continue
            seen.add(member["review_id"])
            rows.append(
                {
                    "review_id": member["review_id"],
                    "ticker": group["ticker"],
                    "source_text": member["source_text"],
                    "current_adjudication": member.get("adjudication_override"),
                    "display_reason_character_budget": max(
                        20, len(member.get("displayed_reason", "")) - len("Analyst says: ")
                    ),
                }
            )
    _write_json(output_dir / "pending-unsupported-reasons-private.json", rows)
    return len(rows)


def _report(summary: dict, unavailable: Sequence[dict], card_failures: int) -> str:
    counts = summary["counts"]
    missing_reason_counts = Counter()
    for row in unavailable:
        missing_reason_counts.update(row["missing_reasons"])
    lines = [
        "# TODO #83/#84 analyst-group replay",
        "",
        "## Recovery counts",
        "",
        f"- Actual saved group-alert events: {counts['actual_group_events']}",
        f"- Fully recoverable events: {counts['recoverable_group_events']}",
        f"- Unrecoverable events: {counts['unrecoverable_group_events']}",
        f"- Opening events recovered: {counts['opened_events']}",
        f"- Repeated join events recovered: {counts['repeated_join_events']}",
        f"- Member appearances: {counts['member_appearances']}",
        f"- Unique contributing posts: {counts['unique_contributing_tweets']}",
        "",
        "## Missing-history counts",
        "",
    ]
    lines.extend(
        f"- {reason.replace('_', ' ')}: {count} member rows"
        for reason, count in sorted(missing_reason_counts.items())
    )
    lines.extend(
        [
            "",
            "## Price evidence counts",
            "",
            f"- Exact intraday anchors: {counts['exact_intraday_anchors']}",
            f"- Daily-price approximation anchors: {counts['daily_price_approximation_anchors']}",
            "- Exact intraday and daily approximations are stored in separate fields.",
            f"- Exact 24-hour direction results: {summary['outcomes']['counts']['exact_24h_direction_worked']} worked out of {summary['outcomes']['counts']['exact_24h_direction_resolved']} resolved.",
            f"- Exact 5-day direction results: {summary['outcomes']['counts']['exact_5d_direction_worked']} worked out of {summary['outcomes']['counts']['exact_5d_direction_resolved']} resolved.",
            f"- Daily 21-session direction results: {summary['outcomes']['counts']['daily_21_session_direction_worked']} worked out of {summary['outcomes']['counts']['daily_21_session_direction_resolved']} resolved.",
            "",
            "## Card comparison",
            "",
            f"- Card fact comparison failures: {card_failures}",
            "- Historical card prices were not stored. Replays use the first-tweet audit anchor in both versions.",
            "",
            "## Independent review",
            "",
            f"- Blind review rows prepared: {counts['unique_contributing_tweets']}",
            "- Proposed labels and analyst names are absent from the blind input.",
            f"- Final review status: {summary['review']['status']}.",
            f"- Adjudications supplied: {summary['review']['counts']['adjudicated']} of {summary['review']['counts']['adjudication_required']} required.",
            f"- Final bullish/bearish reversals: {summary['review']['counts']['reversals']}.",
            f"- Final unsupported displayed reasons: {summary['review']['counts']['unsupported_reasons']}.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(
    db_path: Path,
    output_dir: Path,
    *,
    skip_prices: bool = False,
    review_results_dir: Path | None = None,
    root_cause_results_dir: Path | None = None,
    adjudication_results_dir: Path | None = None,
    use_review_views: bool = False,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    groups, signals, posts, alerts = _read_database(db_path)
    reconstruction = reconstruct_groups(groups, signals, posts)
    recovered = reconstruction.recoverable

    bars: dict[str, dict[str, float]] = {}
    if recovered and not skip_prices:
        tickers = {group["ticker"] for group in recovered}
        benchmarks = {bg.resolve_benchmark(ticker) for ticker in tickers}
        requested = sorted(tickers | {ticker for ticker in benchmarks if ticker})
        first_date = min(
            datetime.fromtimestamp(
                min(member["posted_at"] for member in group["members"]), tz=timezone.utc
            ).astimezone(PACIFIC).date()
            for group in recovered
        )
        bars = fetch_daily_closes(
            requested,
            start=first_date - timedelta(days=7),
            end=datetime.now(PACIFIC).date(),
            use_cache=False,
        )
        _write_json(output_dir / "daily-price-bars.json", bars)

    attach_outcomes(recovered, alerts, bars)
    attach_card_comparisons(recovered)
    review_rows = build_blind_review_rows(recovered)
    _write_review_package(output_dir, review_rows)
    blind_results = load_review_results(review_results_dir)
    pending_blind_reviews = _write_pending_rows(
        output_dir,
        "blind-review-batches",
        blind_results,
        "pending-blind-review-private.json",
    )
    first_pass_review_counts = attach_review_results(recovered, blind_results)
    root_cause_input_count = _write_root_cause_package(output_dir, recovered)
    adjudication_input_count = _write_adjudication_package(output_dir)
    root_cause_summary = summarize_root_causes(recovered, root_cause_results_dir)
    adjudication_results = load_review_results(adjudication_results_dir)
    pending_root_causes = _write_pending_rows(
        output_dir,
        "root-cause-batches",
        load_review_results(root_cause_results_dir),
        "pending-root-cause-private.json",
    )
    pending_adjudications = _write_pending_rows(
        output_dir,
        "adjudication-batches",
        adjudication_results,
        "pending-adjudication-private.json",
    )
    review_view_counts = {"applied": 0, "missing": 0, "invalid_support_phrases": 0}
    if use_review_views:
        review_view_counts = apply_final_review_views(
            recovered, blind_results, adjudication_results
        )
        attach_card_comparisons(recovered)
    adjudication_counts = apply_adjudication_results(recovered, adjudication_results)
    pending_unsupported_reasons = _write_unsupported_reason_rows(output_dir, recovered)
    direction_results = [
        group["direction_later_worked"]["daily_21_sessions"] for group in recovered
    ]
    exact_count = sum(
        group["price_anchor"]["kind"] == "exact_intraday" for group in recovered
    )
    daily_count = sum(
        group["price_anchor"]["kind"] == "daily_price_approximation" for group in recovered
    )
    summary = summarize_counts(
        total_group_events=len(groups),
        recoverable_groups=recovered,
        unresolved_group_count=len(reconstruction.unrecoverable),
        exact_anchor_count=exact_count,
        daily_anchor_count=daily_count,
        direction_results=direction_results,
    )
    summary["unrecoverable_reason_counts"] = dict(
        sum((Counter(row["missing_reasons"]) for row in reconstruction.unrecoverable), Counter())
    )
    summary["outcomes"] = summarize_outcomes(recovered)
    summary["card_comparison_failure_count"] = sum(
        not group["card_comparison"]["unchanged_facts_pass"]
        or not all(group["card_comparison"]["requested_changes_present"].values())
        for group in recovered
    )
    summary["review"] = {
        "blind_rows": len(review_rows),
        "batch_count": max((row["batch_number"] for row in review_rows), default=0),
        "results_supplied": first_pass_review_counts.get("reviewed", 0),
        "pending_blind_review_rows": pending_blind_reviews,
        "first_pass_counts": first_pass_review_counts,
        "adjudication_input_rows": adjudication_input_count,
        "review_view_counts": review_view_counts,
        "pending_root_cause_rows": pending_root_causes,
        "pending_adjudication_rows": pending_adjudications,
        "pending_unsupported_reason_rows": pending_unsupported_reasons,
        "counts": adjudication_counts,
        "status": (
            "pass"
            if adjudication_counts.get("gate_pass")
            else "failed_accuracy_gate"
            if adjudication_counts.get("reviewed", 0) == len(review_rows)
            and adjudication_counts.get("missing_adjudications", 0) == 0
            else "pending_independent_codex_review"
        ),
    }
    summary["root_cause_review"] = {
        "input_rows": root_cause_input_count,
        **root_cause_summary,
    }

    _write_jsonl(output_dir / "group-audit-private.jsonl", recovered)
    _write_jsonl(output_dir / "unrecoverable-groups-private.jsonl", reconstruction.unrecoverable)
    _write_jsonl(output_dir / "codex-blind-review-input-private.jsonl", review_rows)
    _write_review_package(output_dir, review_rows)
    _write_json(output_dir / "summary.json", summary)
    _write_json(output_dir / "root-cause-summary.json", root_cause_summary)
    _write_json(output_dir / "adjudication-overrides-private.json", adjudication_results)
    _write_json(output_dir / "final-reviewed-views-private.json", final_review_views(recovered))
    (output_dir / "report.md").write_text(
        _report(summary, reconstruction.unrecoverable, summary["card_comparison_failure_count"])
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--skip-prices",
        action="store_true",
        help="Reconstruct rows and cards without downloading daily price bars.",
    )
    parser.add_argument(
        "--use-review-views",
        action="store_true",
        help="Replay private final reviewed analyst-view-v1 values in memory; never writes the database.",
    )
    parser.add_argument(
        "--root-cause-results-dir",
        type=Path,
        help="Directory containing root-cause batch-*.json results.",
    )
    parser.add_argument(
        "--review-results-dir",
        type=Path,
        help="Directory containing independent batch-*.json review results.",
    )
    parser.add_argument(
        "--adjudication-results-dir",
        type=Path,
        help="Directory containing final adjudication batch-*.json overrides.",
    )
    args = parser.parse_args()
    summary = run(
        args.db,
        args.output_dir,
        skip_prices=args.skip_prices,
        review_results_dir=args.review_results_dir,
        root_cause_results_dir=args.root_cause_results_dir,
        adjudication_results_dir=args.adjudication_results_dir,
        use_review_views=args.use_review_views,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
