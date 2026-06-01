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


async def test_non_429_4xx_falls_through(patch_config, monkeypatch):
    """A non-429 4xx (e.g. 400) is no longer fatal: the payload may be bad
    for one model but fine for another, so the chain continues."""
    session = _install_session(monkeypatch, [
        _FakeResp(400, body="bad request"),
        _ok_resp("from-second"),
    ])
    out = await llm_client.call_with_fallback(
        "primary", [{"role": "user", "content": "x"}])
    assert out == "from-second"
    assert session.calls == ["primary-llm:free", "fallback-llm-1:free"]


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


# --- #6 latency-speedup: head_start / race / circuit-breaker ----------------
import asyncio as _asyncio  # noqa: E402


class _RaceResp:
    """Timed/scriptable response: optional delay, then either raise `exc` or
    return a 200/`status` body with `content`."""

    def __init__(self, status=200, content="answer", delay=0.0, exc=None, body=""):
        self.status = status
        self._payload = {"choices": [{"message": {"content": content}}]}
        self._delay = delay
        self._exc = exc
        self._body = body

    async def __aenter__(self):
        if self._delay:
            await _asyncio.sleep(self._delay)
        if self._exc is not None:
            raise self._exc
        return self

    async def __aexit__(self, *a):
        return False

    async def json(self):
        return self._payload

    async def text(self):
        return self._body


class _RaceSession:
    """Maps wire model-id -> _RaceResp kwargs; records call order."""

    def __init__(self, specs):
        self._specs = specs
        self.calls: list[str] = []

    def post(self, url, headers=None, json=None, timeout=None):
        wire = json["model"]
        self.calls.append(wire)
        return _RaceResp(**self._specs[wire])


def _install_race(monkeypatch, specs, *, cfg_get=None):
    session = _RaceSession(specs)
    monkeypatch.setattr("consensus_engine.llm_client.get_session",
                        AsyncMock(return_value=session))
    monkeypatch.setattr("consensus_engine.llm_client.cfg.get_api_key",
                        lambda k: "fake-key")
    monkeypatch.setattr("consensus_engine.llm_client.rate_limiter.acquire",
                        AsyncMock(return_value=True))
    monkeypatch.setattr("consensus_engine.llm_client.cfg.get",
                        cfg_get or (lambda k, default=None: default))
    return session


@pytest.fixture(autouse=True)
def _reset_breaker():
    llm_client._reset_groq_breaker()
    yield
    llm_client._reset_groq_breaker()


_HS_CHAIN = ["groq/m0", "m1", "m2"]


def _accept(s: str) -> bool:
    return "VALID" in s


async def test_head_start_groq_wins_no_fanout(monkeypatch):
    """Groq answers within the window -> fallbacks are never even called."""
    session = _install_race(monkeypatch, {
        "m0": dict(content="VALID groq"),
        "m1": dict(content="VALID one"),
        "m2": dict(content="VALID two"),
    })
    out = await llm_client.call_with_fallback(
        "primary", [{"role": "user", "content": "x"}],
        chain=list(_HS_CHAIN), strategy="head_start", head_start=15, accept=_accept)
    assert out == "VALID groq"
    assert session.calls == ["m0"]


async def test_head_start_stall_fans_out(monkeypatch):
    """Groq stalls (timeout) -> race the fallbacks, first valid wins."""
    session = _install_race(monkeypatch, {
        "m0": dict(exc=_asyncio.TimeoutError()),
        "m1": dict(content="VALID fallback", delay=0.01),
        "m2": dict(content="VALID other", delay=0.05),
    })
    out = await llm_client.call_with_fallback(
        "primary", [{"role": "user", "content": "x"}],
        chain=list(_HS_CHAIN), strategy="head_start", head_start=15, accept=_accept)
    assert out == "VALID fallback"
    assert "m0" in session.calls and "m1" in session.calls


async def test_race_prefers_valid_over_fast_invalid(monkeypatch):
    """A fast structurally-INVALID answer must not beat a slower valid one."""
    _install_race(monkeypatch, {
        "m1": dict(content="incomplete", delay=0.01),
        "m2": dict(content="VALID full", delay=0.05),
    })
    out = await llm_client.call_with_fallback(
        "primary", [{"role": "user", "content": "x"}],
        chain=["m1", "m2"], strategy="race_all", accept=_accept)
    assert out == "VALID full"


async def test_race_falls_back_to_first_nonempty_when_none_valid(monkeypatch):
    """If nothing passes `accept`, keep the first non-empty answer seen."""
    _install_race(monkeypatch, {
        "m1": dict(content="incomplete-a", delay=0.01),
        "m2": dict(content="incomplete-b", delay=0.05),
    })
    out = await llm_client.call_with_fallback(
        "primary", [{"role": "user", "content": "x"}],
        chain=["m1", "m2"], strategy="race_all", accept=_accept)
    assert out == "incomplete-a"


async def test_race_all_fail_returns_empty(monkeypatch):
    _install_race(monkeypatch, {
        "m1": dict(status=503, body="down"),
        "m2": dict(exc=_asyncio.TimeoutError()),
    })
    out = await llm_client.call_with_fallback(
        "primary", [{"role": "user", "content": "x"}],
        chain=["m1", "m2"], strategy="race_all", accept=_accept)
    assert out == ""


async def test_serial_strategy_explicit_matches_default(patch_config, monkeypatch):
    """strategy='serial' is byte-for-byte the dark-ship default path."""
    session = _install_session(monkeypatch, [_FakeResp(429), _ok_resp("recovered")])
    out = await llm_client.call_with_fallback(
        "primary", [{"role": "user", "content": "x"}], strategy="serial")
    assert out == "recovered"
    assert session.calls == ["primary-llm:free", "fallback-llm-1:free"]


async def test_breaker_opens_after_threshold_stalls(monkeypatch):
    """N consecutive groq stalls open the breaker (so the wait is skipped next)."""
    specs = {
        "m0": dict(exc=_asyncio.TimeoutError()),
        "m1": dict(content="VALID f", delay=0.01),
        "m2": dict(content="VALID g", delay=0.02),
    }
    cfg_get = (lambda k, default=None:
               2 if k == "llm.all_command_circuit_breaker_threshold" else default)
    for _ in range(2):
        _install_race(monkeypatch, specs, cfg_get=cfg_get)
        await llm_client.call_with_fallback(
            "primary", [{"role": "user", "content": "x"}],
            chain=list(_HS_CHAIN), strategy="head_start", head_start=5, accept=_accept)
    assert llm_client._breaker_is_open()


async def test_breaker_resets_on_groq_success(monkeypatch):
    """A groq head-start success clears the stall streak."""
    cfg_get = (lambda k, default=None:
               3 if k == "llm.all_command_circuit_breaker_threshold" else default)
    # one stall -> streak 1
    _install_race(monkeypatch, {
        "m0": dict(exc=_asyncio.TimeoutError()),
        "m1": dict(content="VALID f", delay=0.01),
        "m2": dict(content="VALID g", delay=0.02),
    }, cfg_get=cfg_get)
    await llm_client.call_with_fallback(
        "primary", [{"role": "user", "content": "x"}],
        chain=list(_HS_CHAIN), strategy="head_start", head_start=5, accept=_accept)
    assert llm_client._groq_fail_streak == 1
    # groq now succeeds -> streak resets
    _install_race(monkeypatch, {"m0": dict(content="VALID groq")}, cfg_get=cfg_get)
    out = await llm_client.call_with_fallback(
        "primary", [{"role": "user", "content": "x"}],
        chain=list(_HS_CHAIN), strategy="head_start", head_start=5, accept=_accept)
    assert out == "VALID groq"
    assert llm_client._groq_fail_streak == 0
