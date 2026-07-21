"""Schwab failures must be classified into the action the user actually needs.

The 2026-07-14 incident: the saved token file was left owned by root, so the
engine (running as openclaw) got EACCES on every Schwab call. `classify_failure`
had no case for that, so it fell through to `api_down` — whose message is
"Schwab's own servers are erroring... you'll get a note here when it recovers".

That was wrong in the worst possible direction. Nothing was wrong at Schwab, the
problem could not clear on its own, and the promised recovery note could never
come. The user got five "Schwab is down" alerts over six days and no recovery,
and when they asked the bot why, it had no way to find out.

A local permission problem must never be reported as a remote outage.
"""
import pytest

from consensus_engine.scanners import schwab_health as sh
from consensus_engine.scanners.schwab_client import SchwabRefreshTokenExpired


def test_permission_error_is_not_reported_as_a_schwab_outage():
    """The exact failure from the incident."""
    exc = PermissionError(
        13, "Permission denied", "/home/openclaw/.openclaw/schwab_token.json")

    assert sh.classify_failure(exc) == sh.TOKEN_UNREADABLE
    assert sh.classify_failure(exc) != sh.API_DOWN


def test_permission_denied_by_message_is_also_caught():
    """Some call paths surface EACCES as a plain wrapped string."""
    assert sh.classify_failure(
        Exception("[Errno 13] Permission denied: schwab_token.json")
    ) == sh.TOKEN_UNREADABLE


def test_unreadable_token_message_tells_the_truth_and_the_fix():
    """The message must not promise a recovery that cannot happen."""
    title, detail, fix = sh.describe(sh.TOKEN_UNREADABLE)

    assert "chown" in fix, "the fix must be the one command that resolves it"
    assert "NOT clear on its own" in detail, "must not imply it self-heals"
    # The api_down copy promises exactly what this failure can never deliver.
    _, _, api_down_fix = sh.describe(sh.API_DOWN)
    assert "fixes itself" in api_down_fix
    assert fix != api_down_fix


@pytest.mark.parametrize("exc, expected", [
    (SchwabRefreshTokenExpired("past its 7-day wall"), sh.TOKEN_LAPSED),
    (Exception("invalid_grant"), sh.TOKEN_LAPSED),
    (Exception("invalid_client"), sh.AUTH_REJECTED),
    (Exception("unauthorized_client"), sh.AUTH_REJECTED),
    (Exception("503 Service Unavailable"), sh.API_DOWN),
    (TimeoutError("read timeout"), sh.API_DOWN),
])
def test_existing_classifications_are_unchanged(exc, expected):
    """The new branch must not steal any case that already worked."""
    assert sh.classify_failure(exc) == expected


def test_every_class_has_a_title_detail_and_fix():
    """A class with no copy would post an empty alert."""
    for klass in (sh.TOKEN_LAPSED, sh.AUTH_REJECTED,
                  sh.TOKEN_UNREADABLE, sh.API_DOWN):
        title, detail, fix = sh.describe(klass)
        assert title and detail and fix, f"{klass} is missing alert copy"
