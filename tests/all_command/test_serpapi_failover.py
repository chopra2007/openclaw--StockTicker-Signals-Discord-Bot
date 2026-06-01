"""TODO #21 — SerpAPI key rotation on exhaustion (gap_fill._serpapi_organic).

Verifies the bot rotates across its 3 independent SerpAPI accounts: a key that
returns HTTP 429 ("out of searches") is skipped, the next key is used, the dead
key is remembered for the day, and it's retried once the date rolls over.
"""
from __future__ import annotations

import datetime
from unittest.mock import patch

import pytest

from consensus_engine.alerts.all_command import gap_fill


class _FakeResp:
    def __init__(self, status: int, payload: dict):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def json(self):
        return self._payload


class _FakeSession:
    """Returns a per-key canned (status, payload); records which keys were hit."""

    def __init__(self, by_key: dict):
        self.by_key = by_key
        self.calls: list[str] = []

    def get(self, url, params=None, timeout=None):
        key = params["api_key"]
        self.calls.append(key)
        status, payload = self.by_key.get(key, (200, {"organic_results": []}))
        return _FakeResp(status, payload)


def _result(title: str):
    return {"organic_results": [{"title": title, "snippet": "s", "link": "x.com"}]}


_EXHAUSTED = (429, {"error": "Your account has run out of searches."})


def _patches(keymap: dict, session: _FakeSession, trusted: list | None = None):
    async def _fake_get_session():
        return session

    cfg_get = lambda k, d=None: (trusted if k == "news.trusted_sources" else d)  # noqa: E731
    return (
        patch.object(gap_fill, "get_session", new=_fake_get_session),
        patch.object(gap_fill.cfg, "get_api_key", side_effect=lambda a: keymap.get(a, "")),
        patch.object(gap_fill.cfg, "get", side_effect=cfg_get),
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    gap_fill._serpapi_exhausted.clear()
    yield
    gap_fill._serpapi_exhausted.clear()


async def test_rotation_skips_429_uses_next_key():
    keymap = {"serpapi": "K1", "serpapi2": "K2", "serpapi3": "K3"}
    session = _FakeSession({"K1": _EXHAUSTED, "K2": (200, _result("hit-from-k2"))})
    p1, p2, p3 = _patches(keymap, session)
    with p1, p2, p3:
        out = await gap_fill._search_serpapi_raw("q")
    assert out == ["hit-from-k2: s"]
    assert session.calls == ["K1", "K2"]          # tried primary first, then rotated
    assert gap_fill._serpapi_exhausted.get("serpapi") == datetime.date.today().isoformat()


async def test_all_keys_exhausted_returns_empty():
    keymap = {"serpapi": "K1", "serpapi2": "K2", "serpapi3": "K3"}
    session = _FakeSession({"K1": _EXHAUSTED, "K2": _EXHAUSTED, "K3": _EXHAUSTED})
    p1, p2, p3 = _patches(keymap, session)
    with p1, p2, p3:
        out = await gap_fill._search_serpapi_raw("q")
    assert out == []
    assert session.calls == ["K1", "K2", "K3"]    # all three tried, all marked dead
    assert set(gap_fill._serpapi_exhausted) == {"serpapi", "serpapi2", "serpapi3"}


async def test_exhausted_key_skipped_same_day():
    keymap = {"serpapi": "K1", "serpapi2": "K2", "serpapi3": "K3"}
    session = _FakeSession({"K1": _EXHAUSTED, "K2": (200, _result("k2"))})
    p1, p2, p3 = _patches(keymap, session)
    with p1, p2, p3:
        await gap_fill._search_serpapi_raw("q1")   # K1 dies, K2 serves
        await gap_fill._search_serpapi_raw("q2")   # K1 must be skipped now
    assert session.calls.count("K1") == 1          # only the first call probed K1
    assert session.calls.count("K2") == 2


async def test_dead_key_retried_after_date_rollover():
    keymap = {"serpapi": "K1"}
    session = _FakeSession({"K1": (200, _result("k1-back"))})
    gap_fill._serpapi_exhausted["serpapi"] = "2000-01-01"   # exhausted long ago
    p1, p2, p3 = _patches(keymap, session)
    with p1, p2, p3:
        out = await gap_fill._search_serpapi_raw("q")
    assert out == ["k1-back: s"]                    # stale date -> key retried
    assert session.calls == ["K1"]


async def test_trusted_filter_preserved_after_refactor():
    keymap = {"serpapi": "K1"}
    payload = {"organic_results": [
        {"title": "good", "snippet": "s", "link": "https://reuters.com/x"},
        {"title": "bad", "snippet": "s", "link": "https://randomblog.net/y"},
    ]}
    session = _FakeSession({"K1": (200, payload)})
    p1, p2, p3 = _patches(keymap, session, trusted=["reuters.com"])
    with p1, p2, p3:
        out = await gap_fill._search_serpapi_trusted("q")
    assert out == ["good: s"]                        # only the trusted-domain result


async def test_no_keys_configured_returns_empty():
    session = _FakeSession({})
    p1, p2, p3 = _patches({}, session)
    with p1, p2, p3:
        out = await gap_fill._search_serpapi_raw("q")
    assert out == []
    assert session.calls == []                       # never even built a request
