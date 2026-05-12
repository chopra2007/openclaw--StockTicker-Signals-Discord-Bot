"""Fallback chain behavior for consensus_engine.llm_client.call_with_fallback."""
import pytest
from unittest.mock import AsyncMock

from consensus_engine import llm_client


class _FakeResp:
    def __init__(self, status: int, payload: dict | None = None, body: str = ""):
        self.status = status
        self._payload = payload or {}
        self._body = body or ""

    async def json(self):
        return self._payload

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _SequentialSession:
    """Returns scripted responses in order; records the model on each call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[str] = []

    def __call__(self, *a, **kw):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(json["model"])
        if not self._responses:
            return _FakeResp(500, body="exhausted")
        return self._responses.pop(0)


def _ok_resp(content: str = "answer") -> _FakeResp:
    return _FakeResp(200, payload={"choices": [{"message": {"content": content}}]})


@pytest.fixture
def patch_config(monkeypatch):
    """Apply a stable config: primary + 2 fallbacks for both roles."""
    cfg_map = {
        "llm.model": "primary-llm:free",
        "llm.fallback_models": ["fallback-llm-1:free", "fallback-llm-2:free"],
        "llm.text_model": "primary-text:free",
        "llm.text_fallback_models": ["fallback-text-1:free", "fallback-text-2:free"],
    }
    monkeypatch.setattr("consensus_engine.llm_client.cfg.get",
                        lambda k, default=None: cfg_map.get(k, default))
    monkeypatch.setattr("consensus_engine.llm_client.cfg.get_api_key",
                        lambda k: "fake-key" if k == "openrouter" else "")


def _install_session(monkeypatch, responses):
    session = _SequentialSession(responses)
    monkeypatch.setattr("consensus_engine.llm_client.get_session",
                        AsyncMock(return_value=session))
    return session


async def test_primary_success_no_fallback_used(patch_config, monkeypatch):
    session = _install_session(monkeypatch, [_ok_resp("hello")])
    out = await llm_client.call_with_fallback(
        "primary", [{"role": "user", "content": "x"}])
    assert out == "hello"
    assert session.calls == ["primary-llm:free"]


async def test_429_falls_through_to_fallback_1(patch_config, monkeypatch):
    session = _install_session(monkeypatch, [
        _FakeResp(429, body="rate limited"),
        _ok_resp("recovered"),
    ])
    out = await llm_client.call_with_fallback(
        "primary", [{"role": "user", "content": "x"}])
    assert out == "recovered"
    assert session.calls == ["primary-llm:free", "fallback-llm-1:free"]


async def test_5xx_falls_through(patch_config, monkeypatch):
    session = _install_session(monkeypatch, [
        _FakeResp(503, body="service unavailable"),
        _ok_resp("from-second"),
    ])
    out = await llm_client.call_with_fallback(
        "primary", [{"role": "user", "content": "x"}])
    assert out == "from-second"
    assert session.calls == ["primary-llm:free", "fallback-llm-1:free"]


async def test_all_models_fail_returns_empty(patch_config, monkeypatch):
    session = _install_session(monkeypatch, [
        _FakeResp(429), _FakeResp(503), _FakeResp(429),
    ])
    out = await llm_client.call_with_fallback(
        "primary", [{"role": "user", "content": "x"}])
    assert out == ""
    assert session.calls == [
        "primary-llm:free", "fallback-llm-1:free", "fallback-llm-2:free",
    ]


async def test_fatal_4xx_aborts_chain(patch_config, monkeypatch):
    """A 400/401/403 means the request itself is broken; no point retrying."""
    session = _install_session(monkeypatch, [
        _FakeResp(400, body="bad request"),
        _ok_resp("should-not-be-reached"),
    ])
    out = await llm_client.call_with_fallback(
        "primary", [{"role": "user", "content": "x"}])
    assert out == ""
    assert session.calls == ["primary-llm:free"]


async def test_empty_content_falls_through(patch_config, monkeypatch):
    session = _install_session(monkeypatch, [
        _ok_resp(""),
        _ok_resp("real-content"),
    ])
    out = await llm_client.call_with_fallback(
        "primary", [{"role": "user", "content": "x"}])
    assert out == "real-content"
    assert session.calls == ["primary-llm:free", "fallback-llm-1:free"]


async def test_text_role_uses_text_chain(patch_config, monkeypatch):
    session = _install_session(monkeypatch, [_ok_resp("text-reply")])
    out = await llm_client.call_with_fallback(
        "text", [{"role": "user", "content": "hi"}])
    assert out == "text-reply"
    assert session.calls == ["primary-text:free"]


async def test_text_role_falls_through_text_chain(patch_config, monkeypatch):
    session = _install_session(monkeypatch, [
        _FakeResp(429),
        _FakeResp(429),
        _ok_resp("third-time-lucky"),
    ])
    out = await llm_client.call_with_fallback(
        "text", [{"role": "user", "content": "hi"}])
    assert out == "third-time-lucky"
    assert session.calls == [
        "primary-text:free", "fallback-text-1:free", "fallback-text-2:free",
    ]


async def test_no_api_key_returns_empty(monkeypatch):
    monkeypatch.setattr("consensus_engine.llm_client.cfg.get_api_key",
                        lambda k: "")
    out = await llm_client.call_with_fallback(
        "primary", [{"role": "user", "content": "x"}])
    assert out == ""


async def test_chain_dedupes_when_primary_in_fallbacks(monkeypatch):
    """If the same model appears in primary and fallbacks, don't call it twice."""
    cfg_map = {
        "llm.model": "same-model:free",
        "llm.fallback_models": ["same-model:free", "different:free"],
    }
    monkeypatch.setattr("consensus_engine.llm_client.cfg.get",
                        lambda k, default=None: cfg_map.get(k, default))
    monkeypatch.setattr("consensus_engine.llm_client.cfg.get_api_key",
                        lambda k: "fake-key" if k == "openrouter" else "")

    session = _install_session(monkeypatch, [
        _FakeResp(429),
        _ok_resp("from-different"),
    ])
    out = await llm_client.call_with_fallback(
        "primary", [{"role": "user", "content": "x"}])
    assert out == "from-different"
    assert session.calls == ["same-model:free", "different:free"]
