"""M9.1AZ/M9.1BZ: finite decision moments for playbooks #1-4 over retained batches.

Version `M91AZ_DECISION_MOMENTS_V1` is fixed before any result is seen. For every
session batch built by `retained_history_batches`, the moments are every 5 minutes
from open+5 minutes through close-5 minutes (09:35-15:55 New York on a full day),
matching the five-minute decision-time bands of M0.3I. The same grid applies to
`HOD_COMP_RS`, `OR_FAILURE_REV` and `FIRST_PULLBACK_VWAP`; each playbook's own
rules decide whether anything is eligible at a moment. Nothing here sets an entry,
`atr_1m` (left unset, D-104), a trade or a result, and no data is read. M9.1BZ
adds `CRVOL_ORB5` to the same already-frozen grid; it does not change the grid.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from .retained_history_batches import RetainedHistoryBatches, SessionHistory
from .trade_alerts_models import RecordError
from .utils.time_context import session_bounds

DECISION_MOMENTS_VERSION = "M91BZ_DECISION_MOMENTS_V2"
PLAYBOOKS = ("CRVOL_ORB5", "HOD_COMP_RS", "OR_FAILURE_REV", "FIRST_PULLBACK_VWAP")
STEP = timedelta(minutes=5)
EDGE = timedelta(minutes=5)


@dataclass(frozen=True)
class DecisionPlanItem:
    playbook: str
    ticker: str
    session: str
    moments: tuple[datetime, ...]  # UTC
    history: SessionHistory
    atr_1m: None = None


def decision_moments(session: str) -> tuple[datetime, ...]:
    try:
        bounds = session_bounds(date.fromisoformat(session))
    except ValueError as exc:
        raise RecordError(f"bad session {session!r}") from exc
    if bounds is None:
        raise RecordError(f"{session} is not a trading session")
    opened, closed = bounds
    moments = []
    moment = opened + EDGE
    while moment <= closed - EDGE:
        moments.append(moment.astimezone(timezone.utc))
        moment += STEP
    return tuple(moments)


def plan_decision_moments(
    batches: RetainedHistoryBatches, *, playbooks: tuple[str, ...] = PLAYBOOKS,
) -> tuple[DecisionPlanItem, ...]:
    if not playbooks or len(set(playbooks)) != len(playbooks) or not set(playbooks) <= set(PLAYBOOKS):
        raise RecordError("playbooks must be a non-empty unique subset of the frozen list")
    return tuple(
        DecisionPlanItem(pb, h.ticker, h.session, decision_moments(h.session), h)
        for h in batches.histories for pb in playbooks)


__all__ = ["DECISION_MOMENTS_VERSION", "DecisionPlanItem", "PLAYBOOKS", "decision_moments",
           "plan_decision_moments"]
