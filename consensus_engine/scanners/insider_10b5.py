"""r28: Rule 10b5-1 plan adoption/termination tracker — CONTEXT ONLY.

The informative signal is the STRUCTURED 10b5-1 disclosure the 2023 SEC amendments
added to Form 4/5 (the `<aff10b5One>` checkbox), which cross_reference already reads
via `_parse_form4_for_graduation`. This module maintains plan STATE per
(ticker, insider_cik) in the `insider_10b5_plans` table and infers:

    ADOPTION    a previously-tracked insider whose plan flag flips 0 -> 1
    TERMINATION a previously-tracked insider whose plan flag flips 1 -> 0
                (best-effort, LOWER confidence)

The first time an insider is ever seen, the state is SEEDED silently (no event), so a
cold-start empty table emits NOTHING. No LLM, no 10-Q text parsing — structured flag
first, the deterministic `is_10b5_1` footnote matcher as the guaranteed fallback.

Default OFF (`features.insider_10b5_plans.enabled`); shadow-log only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from consensus_engine import db
from consensus_engine.scanners.sec_edgar import check_recent_filings
from consensus_engine.utils.rate_limiter import rate_limiter

log = logging.getLogger(__name__)

_MAX_TICKERS_PER_SCAN = 50
_MAX_FORM4_PER_TICKER = 10


@dataclass
class Plan10b5Event:
    ticker: str
    insider_cik: str
    insider_name: str
    event_type: str        # "adoption" | "termination"
    txn_date: str


def classify_plan_transition(prev_state: Optional[dict], observed_plan: bool) -> Optional[str]:
    """Pure state transition. Returns 'adoption', 'termination', or None.

    prev_state is None on first sight -> None (SEED silently, cold-start safe). An
    unchanged flag returns None. Only an observed flip yields an event.
    """
    if prev_state is None:
        return None
    was_active = bool(prev_state.get("plan_active"))
    if not was_active and observed_plan:
        return "adoption"
    if was_active and not observed_plan:
        return "termination"
    return None


async def scan_10b5_plan_events(hours_back: int = 48) -> list[Plan10b5Event]:
    """Scan recent Form 4s for active tickers; update plan-state; return events.

    A cold-start (empty insider_10b5_plans) run seeds every insider silently and
    returns []. Events fire only on an observed 0->1 / 1->0 flip for an insider we
    were already tracking.
    """
    # Lazy imports (scanner -> cross_reference) mirror the graduation path and keep
    # module import light + cycle-free.
    from consensus_engine.scanners.sec_form4_cluster import _fetch_form4_xml
    from consensus_engine.cross_reference import _parse_form4_for_graduation

    tickers = await db.get_active_tickers(min_signals=1)
    events: list[Plan10b5Event] = []

    for ticker in tickers[:_MAX_TICKERS_PER_SCAN]:
        filings = await check_recent_filings(ticker, hours_back=hours_back)
        form4 = [f for f in filings
                 if isinstance(f, dict) and f.get("form") == "4"][:_MAX_FORM4_PER_TICKER]
        if not form4:
            continue

        # Newest filing per insider wins (check_recent_filings is reverse-chron, so
        # the FIRST parsed filing for a given cik is the most recent).
        seen_ciks: set[str] = set()
        for f in form4:
            try:
                if not await rate_limiter.acquire("sec_edgar"):
                    continue
            except Exception:  # noqa: BLE001 — limiter wobble never voids the rest
                pass
            raw = await _fetch_form4_xml(
                f.get("cik", ""),
                f.get("accession_number", ""),
                f.get("primary_document", ""),
            )
            if not raw:
                continue
            parsed = _parse_form4_for_graduation(raw)
            if not parsed:
                continue
            cik = str(parsed.get("reporter_cik") or "").strip()
            name = str(parsed.get("reporter_name") or "Unknown")
            if not cik or cik in seen_ciks:
                continue
            seen_ciks.add(cik)

            observed_plan = bool(parsed.get("is_10b5_1_structured")) or bool(parsed.get("is_planned"))
            txn_date = str(parsed.get("txn_date") or "")

            try:
                prev = await db.get_insider_10b5_plan(ticker, cik)
                transition = classify_plan_transition(prev, observed_plan)
                terminated_at = None
                if transition == "termination":
                    import time as _t
                    terminated_at = _t.time()
                elif prev is not None and prev.get("terminated_at") is not None and observed_plan:
                    terminated_at = None  # re-adopted: clear the stale termination stamp
                elif prev is not None:
                    terminated_at = prev.get("terminated_at")
                await db.upsert_insider_10b5_plan(
                    ticker=ticker,
                    insider_cik=cik,
                    insider_name=name,
                    plan_active=observed_plan,
                    last_txn_date=txn_date or (prev.get("last_txn_date") if prev else None),
                    terminated_at=terminated_at,
                )
                if transition:
                    events.append(Plan10b5Event(
                        ticker=ticker, insider_cik=cik, insider_name=name,
                        event_type=transition, txn_date=txn_date,
                    ))
                    log.info("[r28] $%s 10b5-1 %s: %s (%s)", ticker, transition, name, txn_date)
            except Exception as e:  # noqa: BLE001 — one insider's DB error never voids the scan
                log.debug("[r28] $%s 10b5 state error for %s: %s", ticker, cik, e)

    return events


def build_10b5_context_line(events: list[Plan10b5Event]) -> Optional[str]:
    """One insider-display context line summarizing plan adoptions/terminations, or None."""
    if not events:
        return None
    adopt = [e for e in events if e.event_type == "adoption"]
    term = [e for e in events if e.event_type == "termination"]
    parts: list[str] = []
    if adopt:
        parts.append(f"{len(adopt)} 10b5-1 plan adoption(s)")
    if term:
        parts.append(f"{len(term)} plan termination(s) (low-confidence)")
    if not parts:
        return None
    return "🗓️ Insider 10b5-1: " + ", ".join(parts)
