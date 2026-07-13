"""#71: the one-command Schwab re-login helper."""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "schwab_login", Path(__file__).resolve().parent.parent / "scripts" / "schwab_login.py")
login = importlib.util.module_from_spec(_SPEC)
sys.modules["schwab_login"] = login
_SPEC.loader.exec_module(login)


# --- authorize URL ----------------------------------------------------------

def test_authorize_url_encodes_the_callback():
    url = login.build_authorize_url("KEY123", "https://127.0.0.1")
    assert url.startswith("https://api.schwabapi.com/v1/oauth/authorize?")
    assert "client_id=KEY123" in url
    assert "redirect_uri=https%3A%2F%2F127.0.0.1" in url


def test_authorize_url_refuses_missing_creds():
    with pytest.raises(login.LoginError, match="SCHWAB_APP_KEY"):
        login.build_authorize_url("", "https://127.0.0.1")
    with pytest.raises(login.LoginError, match="SCHWAB_CALLBACK_URL"):
        login.build_authorize_url("KEY", "")


# --- pulling the code out of the pasted redirect ----------------------------

def test_extract_code_from_a_real_schwab_redirect():
    """Schwab appends '@' to the code and does not url-encode it."""
    url = ("https://127.0.0.1/?code=C0.b2F1dGgyLmJkYy5zY2h3YWIuY29t.abc-DEF_123@"
           "&session=fa2b7c")
    assert login.extract_code(url) == "C0.b2F1dGgyLmJkYy5zY2h3YWIuY29t.abc-DEF_123@"


def test_extract_code_tolerates_whitespace_and_quotes():
    inner = "https://127.0.0.1/?code=ABC@&session=x"
    assert login.extract_code(f'  "{inner}"  ') == "ABC@"
    assert login.extract_code(f"'{inner}'\n") == "ABC@"


def test_extract_code_rejects_an_address_with_no_code():
    with pytest.raises(login.LoginError, match="no `code=` in it"):
        login.extract_code("https://127.0.0.1/?error=access_denied")


def test_extract_code_rejects_empty_input():
    with pytest.raises(login.LoginError, match="No redirect URL"):
        login.extract_code("")


def test_extract_code_rejects_an_empty_code():
    with pytest.raises(login.LoginError, match="empty"):
        login.extract_code("https://127.0.0.1/?code=&session=x")


# --- token document ---------------------------------------------------------

def test_token_doc_matches_the_shape_get_access_token_reads():
    resp = {"access_token": "a", "refresh_token": "r", "expires_in": 1800}
    doc = login.build_token_doc(resp, now=1000.0)
    assert doc == {"token": resp, "creation_timestamp": 1000, "_refresh_created": 1000}


def test_token_doc_freezes_the_seven_day_wall_at_this_login():
    doc = login.build_token_doc(
        {"access_token": "a", "refresh_token": "r"}, now=1000.0)
    # _refresh_created is what reauth_days_left() counts from; a fresh login resets it.
    assert doc["_refresh_created"] == doc["creation_timestamp"]


@pytest.mark.parametrize("bad", [
    {"access_token": "a"},                 # no refresh token
    {"refresh_token": "r"},                # no access token
    {"error": "invalid_grant"},            # an error body, not a token
])
def test_token_doc_refuses_a_reply_with_no_token(bad):
    with pytest.raises(login.LoginError, match="missing a token"):
        login.build_token_doc(bad)


def test_the_written_doc_is_readable_by_the_client(tmp_path, monkeypatch):
    """Round-trip: what we write is what schwab_client._load_token() expects."""
    from consensus_engine.scanners import schwab_client
    path = tmp_path / "schwab_token.json"
    doc = login.build_token_doc(
        {"access_token": "a", "refresh_token": "r", "expires_in": 1800}, now=1000.0)
    login.write_token(doc, path=str(path))
    monkeypatch.setattr(schwab_client, "TOKEN_PATH", str(path))
    loaded = schwab_client._load_token()
    assert loaded["token"]["access_token"] == "a"
    assert schwab_client._refresh_created(loaded) == 1000.0
    assert oct(os.stat(path).st_mode)[-3:] == "600"


# --- error messages the user actually reads ---------------------------------

def test_invalid_grant_blames_the_30_second_timer():
    msg = login.explain_exchange_failure(400, '{"error":"invalid_grant"}')
    assert "expired" in msg and "30 seconds" in msg


def test_invalid_client_blames_the_credentials_not_the_timer():
    msg = login.explain_exchange_failure(401, '{"error":"invalid_client"}')
    assert "SCHWAB_APP_KEY" in msg
    assert "30 seconds" not in msg


def test_server_error_says_wait():
    assert "Wait" in login.explain_exchange_failure(503, "gateway timeout")


def test_unknown_error_still_shows_the_body():
    msg = login.explain_exchange_failure(418, "i am a teapot")
    assert "418" in msg and "teapot" in msg


# --- reading the redirect url -----------------------------------------------

def test_redirect_url_argument_wins(monkeypatch):
    assert login.read_redirect_url("https://x/?code=A@") == "https://x/?code=A@"


def test_redirect_url_read_from_a_pipe(monkeypatch):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO("https://x/?code=B@\n"))
    assert login.read_redirect_url(None) == "https://x/?code=B@"


def test_empty_pipe_is_an_error(monkeypatch):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    with pytest.raises(login.LoginError, match="Nothing on stdin"):
        login.read_redirect_url(None)
