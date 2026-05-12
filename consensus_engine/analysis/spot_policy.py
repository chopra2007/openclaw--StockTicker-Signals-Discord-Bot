"""Global `spot is None` policy for distance-reasoning code paths.

Multiple call sites used to scatter `if spot is None: …` checks with
different defaults. This module is the single source of truth: callers
ask `resolve_spot(price)` and get a `SpotPolicy` decision back.

Default action is `DEMOTE_FOR_REPLAY`, matching CEF-9: rather than
hard-rejecting (which is terminal under today's schema), we mark rows
as suppressed with `suppression_reason='no_live_price'` and emit a
log line `pending_retry_candidate=1` so a future reconciliation cron
can revisit. v1.1 will replace the log marker with an explicit
`pending` enum state on `suppressed`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger("consensus_engine.analysis.spot_policy")


class SpotAction(str, Enum):
    OK = "ok"
    HARD_REJECT = "hard_reject"
    DEMOTE_FOR_REPLAY = "demote_for_replay"


@dataclass(frozen=True)
class SpotPolicy:
    action: SpotAction
    reason: str

    @property
    def is_ok(self) -> bool:
        return self.action == SpotAction.OK


def resolve_spot(price: float | None) -> SpotPolicy:
    """Translate a possibly-missing spot price into a downstream action.

    Use cases:
      * Anchor distance penalty (C-C1) requires `current_price > 0`.
        Calling without a real spot would divide by zero or partition
        all anchors as "resistance above 0" (CEF-11).
      * Aggregator early-abort: if `resolve_spot(quote).action != OK`,
        skip the trade plan entirely and surface a user-visible
        "live quote unavailable" footer instead of fabricating one.

    The default for unusable spot values is DEMOTE_FOR_REPLAY:
      * Rows being inserted should set `suppressed=1,
        suppression_reason='no_live_price'`.
      * The structured log line should include `pending_retry_candidate=1`
        so the v1.1 reconciliation cron can find them.

    Returning HARD_REJECT is reserved for paths that cannot defer the
    operation (e.g. user-blocking real-time alert path that has nothing
    to retry against). Callers must opt in explicitly.
    """
    if price is None:
        return SpotPolicy(SpotAction.DEMOTE_FOR_REPLAY, "spot_is_none")
    if not isinstance(price, (int, float)):
        return SpotPolicy(SpotAction.DEMOTE_FOR_REPLAY, "spot_not_numeric")
    if price <= 0:
        return SpotPolicy(SpotAction.DEMOTE_FOR_REPLAY, "spot_non_positive")
    return SpotPolicy(SpotAction.OK, "ok")
