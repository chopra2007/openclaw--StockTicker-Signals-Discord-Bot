"""The weekly Schwab re-auth reminder must say the right thing in each state.

TODO #88 check 4: every script whose output gates a decision needs a known-good
and a known-bad case. This one tells the user whether their Schwab login is about
to lapse or has already lapsed — and "already lapsed" means the real-time options
feed is gone, so getting it wrong either way costs real data.
"""
import importlib.util
import os
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "schwab_reauth_check.py"
_spec = importlib.util.spec_from_file_location("schwab_reauth_check", _SCRIPT)
reauth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reauth)


def test_healthy_token_gets_a_countdown_not_an_expiry_notice():
    msg = reauth._build_message(days_left=1.6, marker_present=False)
    assert "expires in 1.6 days" in msg
    assert "EXPIRED" not in msg


def test_marker_on_disk_means_expired():
    """The engine drops a marker file the moment a Schwab call fails on a dead
    token. That marker outranks any countdown."""
    msg = reauth._build_message(days_left=1.6, marker_present=True)
    assert "EXPIRED" in msg


def test_negative_days_left_means_expired():
    msg = reauth._build_message(days_left=-0.5, marker_present=False)
    assert "EXPIRED" in msg


def test_every_message_carries_the_three_renewal_steps():
    for msg in (reauth._build_message(1.0, False), reauth._build_message(-1.0, True)):
        assert "https://127.0.0.1/?code=" in msg
        assert msg.count("\n1. ") == 1

def test_the_deadline_is_shown_in_pacific_time_only():
    """PDT only is a hard rule — an 'ET' label anywhere is a bug."""
    msg = reauth._build_message(days_left=2.0, marker_present=False)
    assert " PT" in msg
    assert " ET" not in msg


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read any file, so the case cannot be staged")
def test_an_unreadable_login_file_is_not_called_expired(tmp_path, monkeypatch, capsys):
    """The 2026-08-17 incident: root took over the login file, so the bot could not
    read it. `reauth_days_left()` returns -1 for ANY read failure, so the reminder
    announced "login has EXPIRED" on top of the correct permission alert — one cause,
    two alerts, one of them wrong. The permission case now says what it really is.
    """
    token = tmp_path / "schwab_token.json"
    token.write_text("{}")
    token.chmod(0o000)
    monkeypatch.setattr(reauth.schwab_client, "TOKEN_PATH", str(token))

    assert reauth._token_unreadable() is True
    monkeypatch.setattr("sys.argv", ["schwab_reauth_check.py", "--dry-run"])
    reauth.main()
    out = capsys.readouterr().out
    assert "EXPIRED" not in out
    assert "cannot read it" in out


def test_a_readable_login_file_is_not_a_permission_problem(tmp_path, monkeypatch):
    token = tmp_path / "schwab_token.json"
    token.write_text("{}")
    monkeypatch.setattr(reauth.schwab_client, "TOKEN_PATH", str(token))
    assert reauth._token_unreadable() is False


def test_a_missing_login_file_is_a_login_problem_not_a_permission_one(tmp_path, monkeypatch):
    """No file at all means nobody ever logged in — that IS the login's problem."""
    monkeypatch.setattr(reauth.schwab_client, "TOKEN_PATH", str(tmp_path / "nope.json"))
    assert reauth._token_unreadable() is False
