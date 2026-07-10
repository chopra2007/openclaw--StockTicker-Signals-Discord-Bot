"""#71: notice when the Schwab real-time feed is unreachable, and say so.

Schwab failing is the quietest bad thing that happens to this bot. Every call site
catches the error, shrugs, and falls back to free 15-minute-delayed prices — at
`log.debug`. The options numbers keep printing. They are just stale, and nobody is
told.

This module classifies a Schwab failure into the three cases that need DIFFERENT
actions from the user, and hands them to the shared #errors alerter:

  token_lapsed  — the weekly browser login expired. Run `scripts/schwab_login.py`.
  auth_rejected — the app key/secret is wrong or the app was revoked. Check `.env`.
  api_down      — Schwab's servers are 5xx/timing out. Wait; nothing to do.

Callers report on every attempt (`note_schwab_failure` / `note_schwab_ok`); the
alerter is the thing that stays silent unless the state actually changed.
"""

from __future__ import annotations

import logging
from typing import Tuple

log = logging.getLogger(__name__)

TOKEN_LAPSED = "schwab_token"
AUTH_REJECTED = "schwab_auth"
API_DOWN = "schwab_api"

ALERT_KEY = "schwab_feed"

_TITLES = {
    TOKEN_LAPSED: "Schwab real-time data has stopped — the weekly login expired",
    AUTH_REJECTED: "Schwab is refusing our app's credentials",
    API_DOWN: "Schwab's servers are not responding",
}

_DETAILS = {
    TOKEN_LAPSED: (
        "The Schwab login has to be redone by hand every 7 days, and that window has "
        "passed. Options prices and quotes have quietly fallen back to the free feed, "
        "which is about 15 minutes behind. Everything still works — it is just stale."
    ),
    AUTH_REJECTED: (
        "Schwab rejected the app key or secret outright. This is not the weekly login "
        "expiring; the credentials themselves are wrong or the app was switched off. "
        "Options prices have fallen back to the free 15-minute-delayed feed."
    ),
    API_DOWN: (
        "Schwab's own servers are erroring or timing out. Options prices have fallen "
        "back to the free 15-minute-delayed feed until they recover."
    ),
}

_FIXES = {
    TOKEN_LAPSED: "Run `python3 scripts/schwab_login.py` and follow the two steps it prints.",
    AUTH_REJECTED: "Check SCHWAB_APP_KEY and SCHWAB_APP_SECRET in ~/.openclaw/.env "
                   "(and .env.service), and that the app is still approved at Schwab.",
    API_DOWN: "Nothing — this one fixes itself. You'll get a note here when it does.",
}


def classify_failure(exc: BaseException) -> str:
    """Which of the three Schwab failures is this?

    Order matters: a refresh that comes back `invalid_client` is a credentials
    problem even though it surfaces as a token error, and re-logging in will not
    fix it. Check the credential signature before the token signature.
    """
    from consensus_engine.scanners.schwab_client import SchwabRefreshTokenExpired

    text = str(exc).lower()
    if "invalid_client" in text or "unauthorized_client" in text:
        return AUTH_REJECTED
    if isinstance(exc, SchwabRefreshTokenExpired):
        return TOKEN_LAPSED
    if "invalid_grant" in text or "refresh token" in text:
        return TOKEN_LAPSED
    return API_DOWN


def describe(failure_class: str) -> Tuple[str, str, str]:
    """(title, detail, fix) for one failure class, in plain English."""
    return (_TITLES.get(failure_class, _TITLES[API_DOWN]),
            _DETAILS.get(failure_class, _DETAILS[API_DOWN]),
            _FIXES.get(failure_class, _FIXES[API_DOWN]))


async def note_schwab_failure(exc: BaseException) -> bool:
    """Report a failed Schwab call. Alerts only on a state/class change."""
    from consensus_engine.alerts.ops_alert import report_ops_state

    klass = classify_failure(exc)
    title, detail, fix = describe(klass)
    return await report_ops_state(
        ALERT_KEY, down=True, failure_class=klass,
        title=title, detail=detail, fix=fix,
    )


async def note_schwab_ok() -> bool:
    """Report a successful Schwab call. Posts a 'restored' note only if we had
    previously said it was down."""
    from consensus_engine.alerts.ops_alert import report_ops_state

    return await report_ops_state(
        ALERT_KEY, down=False, failure_class=None,
        title="Schwab real-time data is back",
    )
