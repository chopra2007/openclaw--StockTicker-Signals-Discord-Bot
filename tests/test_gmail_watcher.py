"""Tests for the rebuilt Gmail watcher (Wolf macro-brain reader, TODO #20).

The watcher was rebuilt from signal-first ticker ingestion into the Wolf
newsletter reader. Old behavior (subject-substring gate, text/plain-only
_decode_body, extract_tickers -> insert_signal) is intentionally gone; these
tests cover the new contract.
"""
import base64

import pytest

from consensus_engine.scanners import gmail_watcher


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode()


def test_scopes_are_modify():
    """Labeling needs gmail.modify; the declared scope must say so."""
    assert gmail_watcher.SCOPES == ["https://www.googleapis.com/auth/gmail.modify"]


def test_sender_allowed(monkeypatch):
    monkeypatch.setattr(
        gmail_watcher.cfg, "get",
        lambda k, d=None: (["support@wolf-on-wallstreet.com"]
                           if k == "gmail_watcher.sender_allowlist" else d),
    )
    assert gmail_watcher._sender_allowed("Wolf <support@wolf-on-wallstreet.com>")
    assert not gmail_watcher._sender_allowed("spam@example.com")


def test_sender_allowed_glob(monkeypatch):
    monkeypatch.setattr(
        gmail_watcher.cfg, "get",
        lambda k, d=None: (["*@wolf-on-wallstreet.com"]
                           if k == "gmail_watcher.sender_allowlist" else d),
    )
    assert gmail_watcher._sender_allowed("a@wolf-on-wallstreet.com")
    assert not gmail_watcher._sender_allowed("a@evil.com")


def test_sender_allowed_empty_list(monkeypatch):
    monkeypatch.setattr(gmail_watcher.cfg, "get", lambda k, d=None: [])
    assert not gmail_watcher._sender_allowed("anyone@anywhere.com")


def _cfg_mock(monkeypatch, mod, mapping):
    """Patch mod.cfg.get to return values from `mapping` (else the default)."""
    monkeypatch.setattr(mod.cfg, "get", lambda k, d=None: mapping.get(k, d))


def test_sender_allowed_emails_split(monkeypatch):
    """phase-4 #5: the new allowed_emails list gates exact addresses."""
    _cfg_mock(monkeypatch, gmail_watcher,
              {"gmail_watcher.allowed_emails": ["support@wolf-on-wallstreet.com"]})
    assert gmail_watcher._sender_allowed("Wolf <support@wolf-on-wallstreet.com>")
    assert not gmail_watcher._sender_allowed("spam@example.com")


def test_sender_allowed_domains_split(monkeypatch):
    """phase-4 #5: the new allowed_domains list matches a whole domain (both forms)."""
    _cfg_mock(monkeypatch, gmail_watcher,
              {"gmail_watcher.allowed_domains": ["wolf-on-wallstreet.com"]})
    assert gmail_watcher._sender_allowed("a@wolf-on-wallstreet.com")
    assert not gmail_watcher._sender_allowed("a@evil.com")
    # the "*@domain" form is also accepted
    _cfg_mock(monkeypatch, gmail_watcher,
              {"gmail_watcher.allowed_domains": ["*@wolf-on-wallstreet.com"]})
    assert gmail_watcher._sender_allowed("b@wolf-on-wallstreet.com")


def test_sender_allowed_both_lists_independent(monkeypatch):
    """An address listed in either list passes; one not in either fails."""
    _cfg_mock(monkeypatch, gmail_watcher, {
        "gmail_watcher.allowed_emails": ["exact@a.com"],
        "gmail_watcher.allowed_domains": ["b.com"],
    })
    assert gmail_watcher._sender_allowed("exact@a.com")
    assert gmail_watcher._sender_allowed("anyone@b.com")
    assert not gmail_watcher._sender_allowed("nope@c.com")


def test_auth_results_all_pass():
    headers = [{"name": "Authentication-Results",
                "value": "mx.google.com; dkim=pass header.i=@x; spf=pass; dmarc=pass"}]
    assert gmail_watcher._auth_results_pass(headers)


def test_auth_results_one_fail():
    headers = [{"name": "Authentication-Results",
                "value": "mx.google.com; dkim=pass; spf=fail; dmarc=pass"}]
    assert not gmail_watcher._auth_results_pass(headers)


def test_auth_results_multi_header():
    """Gmail can emit several Authentication-Results headers; one all-pass is enough."""
    headers = [
        {"name": "Authentication-Results", "value": "relay; dkim=none"},
        {"name": "Authentication-Results", "value": "mx.google.com; dkim=pass; spf=pass; dmarc=pass"},
    ]
    assert gmail_watcher._auth_results_pass(headers)


def test_auth_results_word_boundary():
    """'dkim=passx' must NOT satisfy the dkim=pass requirement."""
    headers = [{"name": "Authentication-Results",
                "value": "mx; dkim=passx; spf=pass; dmarc=pass"}]
    assert not gmail_watcher._auth_results_pass(headers)


def test_auth_results_missing_header():
    assert not gmail_watcher._auth_results_pass([{"name": "From", "value": "x"}])


def test_auth_results_forwarded_arc():
    """Gmail-forwarded mail reports arc=pass (not dmarc=pass); accept it."""
    headers = [{"name": "Authentication-Results",
                "value": ("mx.google.com; dkim=pass header.i=@wolf-on-wallstreet.com; "
                          "arc=pass (i=2 spf=pass dkim=pass); spf=pass "
                          "smtp.mailfrom=\"sub+caf_=x=gmail.com@gmail.com\"")}]
    assert gmail_watcher._auth_results_pass(headers)


def test_auth_results_forwarded_dara():
    """Gmail-forwarded mail can report dara=pass (not dmarc=pass); accept it."""
    headers = [{"name": "Authentication-Results",
                "value": "mx.google.com; dkim=pass header.i=@x; spf=pass; dara=pass header.i=@gmail.com"}]
    assert gmail_watcher._auth_results_pass(headers)


def test_auth_results_no_dmarc_equiv_fails():
    """dkim+spf pass but no dmarc/arc/dara token at all -> still rejected."""
    headers = [{"name": "Authentication-Results",
                "value": "mx; dkim=pass; spf=pass"}]
    assert not gmail_watcher._auth_results_pass(headers)


def test_decode_body_html_only():
    """Wolf emails are HTML-only: text is empty, html is returned."""
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/html", "body": {"data": _b64("<p>SPX toppy</p>")}},
        ],
    }
    text, html = gmail_watcher._decode_body(payload)
    assert text == ""
    assert "SPX toppy" in html


def test_decode_body_both_parts():
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("plain ver")}},
            {"mimeType": "text/html", "body": {"data": _b64("<p>html ver</p>")}},
        ],
    }
    text, html = gmail_watcher._decode_body(payload)
    assert text == "plain ver"
    assert "html ver" in html


def test_decode_body_nested():
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "multipart/alternative", "parts": [
                {"mimeType": "text/html", "body": {"data": _b64("<b>deep</b>")}},
            ]},
        ],
    }
    text, html = gmail_watcher._decode_body(payload)
    assert "deep" in html


def test_decode_body_empty():
    text, html = gmail_watcher._decode_body({"mimeType": "text/plain", "body": {}})
    assert text == ""
    assert html == ""


def test_strip_quoted():
    body = "Real content here.\n\nOn Mon, someone wrote:\n> quoted stuff"
    assert "Real content here." in gmail_watcher._strip_quoted(body)
    assert "quoted stuff" not in gmail_watcher._strip_quoted(body)
