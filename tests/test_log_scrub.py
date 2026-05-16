"""Tests for consensus_engine.utils.log_scrub.scrub — credential-safe
exception-string scrubbing before structured logging.

Pattern set is from pass-3-security.md §H1. Each test covers one leak path
observed in the wild from Gemini SDK / proxy / generic LLM stack errors.
"""
from __future__ import annotations

import pytest

from consensus_engine.utils.log_scrub import scrub


def test_empty_and_none_input_returns_empty_string():
    assert scrub("") == ""
    assert scrub(None) == ""  # type: ignore[arg-type]


def test_redacts_google_aiza_key():
    # AIza... followed by 35 [A-Za-z0-9_\-] chars = 39 chars total
    raw = "googleapiclient.errors.HttpError: api_key=AIzaSyD-9tSrke72PouQMnMX-a7eZSW0jkFMBWY status=400"
    out = scrub(raw)
    assert "AIzaSy" not in out
    assert "[REDACTED]" in out


def test_redacts_x_goog_api_key_header():
    raw = "metadata=(('x-goog-api-key', 'AIzaSyABCDE_FGHIJKLMNOPQRSTUVWXYZ1234567'),)"
    out = scrub(raw)
    assert "AIzaSy" not in out
    assert "[REDACTED]" in out


def test_redacts_api_key_kv_form():
    raw = "URL?api_key=abcdef1234567890ABCDEFGHIJK&other=ok"
    out = scrub(raw)
    assert "abcdef1234567890" not in out
    assert "[REDACTED]" in out


def test_redacts_authorization_bearer():
    raw = "Headers: Authorization: Bearer abc.DEF-456_ghijkl-mnopqrs789"
    out = scrub(raw)
    assert "abc.DEF-456_ghijkl-mnopqrs789" not in out
    assert "[REDACTED]" in out


def test_redacts_query_string_key():
    raw = "GET https://generativelanguage.googleapis.com/v1/...?key=ABCDEFGHIJKLMNOPQRSTUVWXYZ12 HTTP/1.1"
    out = scrub(raw)
    assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ12" not in out
    assert "[REDACTED]" in out


def test_redacts_groq_gsk_key():
    raw = "groq.AuthenticationError: 401 — gsk_" + "Ab1Cd2Ef3" * 5  # 45 chars after prefix
    out = scrub(raw)
    assert "gsk_Ab1Cd2Ef3" not in out
    assert "[REDACTED]" in out


def test_redacts_openai_style_sk_key():
    raw = "openai.AuthenticationError: sk-abc123DEFghi456JKL789mno"
    out = scrub(raw)
    assert "sk-abc123DEFghi456JKL789mno" not in out
    assert "[REDACTED]" in out


def test_redacts_jwt():
    raw = (
        "401 Unauthorized — token=eyJhbGciOiJIUzI1NiJ9."
        "eyJzdWIiOiIxMjM0NSJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    out = scrub(raw)
    assert "eyJhbGciOiJIUzI1NiJ9" not in out
    assert "[REDACTED]" in out


def test_redacts_long_hex_blob():
    # Session / signature blobs often appear as 40+ hex chars
    raw = "session_id=d41d8cd98f00b204e9800998ecf8427edeadbeefcafebabe1234567890abcdef"
    out = scrub(raw)
    assert "d41d8cd9" not in out
    assert "[REDACTED]" in out


def test_redacts_long_base64_blob():
    raw = "payload: " + "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5+/=="
    out = scrub(raw)
    assert "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5" not in out
    assert "[REDACTED]" in out


def test_truncates_to_maxlen():
    # Use prose (with spaces) so word-boundary anchored secret patterns
    # don't match and eat the whole string. We're only testing the cap.
    raw = "an exception message that just goes on and on. " * 100
    out = scrub(raw, maxlen=300)
    assert len(out) == 300


def test_truncation_default_500():
    raw = "another long benign error trace without secrets. " * 100
    out = scrub(raw)
    assert len(out) == 500


def test_multiple_secrets_in_one_string_all_redacted():
    raw = (
        "Error: api_key=AIzaSyDABCDEFGHIJKLMNOPQRSTUVWXYZ1234567 "
        "Authorization: Bearer abc.DEF-456_ghijkl-mnopqrs789xy "
        "and sk-1234567890ABCDEFGhij"
    )
    out = scrub(raw)
    assert "AIzaSyDABC" not in out
    assert "Bearer abc.DEF" not in out.lower() or "[REDACTED]" in out
    assert "sk-1234567890" not in out
    # At least three redactions
    assert out.count("[REDACTED]") >= 3


def test_non_secret_text_passes_through_unchanged():
    raw = "F2 failure category=timeout video=dQw4w9WgXcQ key=GEMINI_API_KEY3"
    out = scrub(raw)
    assert out == raw


def test_short_hex_not_redacted():
    # 31-char hex is below the 32 floor — keep it visible (e.g. log IDs)
    raw = "request_id=abc123def456abc123def456abc1234"
    out = scrub(raw)
    assert out == raw


@pytest.mark.parametrize("prefix,key,leftover", [
    ("api_key=", "AIzaSy" + "x" * 33, ""),                                    # 39 total
    ("api-key: ", "AIza" + "y" * 35, ""),                                     # 39 total
    ("X-Goog-Api-Key: ", "AIza" + "z" * 35, " extra=safe"),                   # 39 total
])
def test_aiza_canonical_forms(prefix, key, leftover):
    """AIza-prefix Google keys must always be redacted — multiple wrappings."""
    raw = f"some error: {prefix}{key}{leftover}"
    out = scrub(raw)
    assert key not in out
    assert "[REDACTED]" in out
