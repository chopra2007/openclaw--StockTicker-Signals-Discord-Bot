"""Tests for the daily LLM chain health check."""
import pytest
from unittest.mock import AsyncMock

from consensus_engine import health


CHAIN_CFG = {
    "llm.model": "primary-llm:free",
    "llm.fallback_models": ["fb1:free", "fb2:free"],
    "llm.text_model": "primary-text:free",
    "llm.text_fallback_models": ["tfb1:free", "tfb2:free"],
}


def test_partial_model_failure_alert_is_accurate():
    assert "Every model" not in health._LLM_HEALTH_ALERT_DETAIL
    assert "At least one configured model failed" in health._LLM_HEALTH_ALERT_DETAIL
    assert "Other models may still be working" in health._LLM_HEALTH_ALERT_DETAIL


def test_enumerate_chain_models_in_order(monkeypatch):
    monkeypatch.setattr("consensus_engine.health.cfg.get",
                        lambda k, default=None: CHAIN_CFG.get(k, default))
    out = health._enumerate_chain_models()
    assert [m for _, _, m in out] == [
        "primary-llm:free", "fb1:free", "fb2:free",
        "primary-text:free", "tfb1:free", "tfb2:free",
    ]
    assert out[0][:2] == ("LLM", "primary")
    assert out[3][:2] == ("TEXT", "primary")
    assert out[1][:2] == ("LLM", "fallback 1")


def test_enumerate_skips_empty_entries(monkeypatch):
    cfg_map = {
        "llm.model": "only-llm:free",
        "llm.fallback_models": ["", None, "real:free"],
        "llm.text_model": "",
        "llm.text_fallback_models": [],
    }
    monkeypatch.setattr("consensus_engine.health.cfg.get",
                        lambda k, default=None: cfg_map.get(k, default))
    out = health._enumerate_chain_models()
    assert [m for _, _, m in out] == ["only-llm:free", "real:free"]


class _Resp:
    def __init__(self, status, payload=None, body=""):
        self.status = status
        self._p = payload or {}
        self._b = body
    async def json(self): return self._p
    async def text(self): return self._b
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


class _Session:
    def __init__(self, responses):
        self._r = list(responses)
        self.calls = []
    def __call__(self, *a, **kw): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(json["model"])
        return self._r.pop(0) if self._r else _Resp(500, body="exhausted")


def _ok(text="2+2 equals 4."):
    return _Resp(200, payload={"choices": [{"message": {"content": text}}]})


@pytest.fixture
def patched_cfg(monkeypatch):
    monkeypatch.setattr("consensus_engine.health.cfg.get",
                        lambda k, default=None: CHAIN_CFG.get(k, default))
    monkeypatch.setattr("consensus_engine.health.cfg.get_api_key",
                        lambda k: "fake-key" if k == "openrouter" else "")
    # Suppress gateway-chain reads in tests that only care about consensus.yaml.
    # Gateway-specific behavior is covered by test_gateway_chain_sync.py.
    monkeypatch.setattr("consensus_engine.health._enumerate_gateway_chain_models",
                        lambda: ([], ""))


async def test_run_chain_check_all_green(patched_cfg, monkeypatch):
    sess = _Session([_ok(), _ok(), _ok(), _ok(), _ok(), _ok()])
    monkeypatch.setattr("consensus_engine.health.get_session",
                        AsyncMock(return_value=sess))
    failed, report = await health.run_chain_check()
    assert failed is False
    assert report.count("✅") == 6
    assert "❌" not in report
    assert sess.calls == [
        "primary-llm:free", "fb1:free", "fb2:free",
        "primary-text:free", "tfb1:free", "tfb2:free",
    ]


async def test_run_chain_check_flags_429(patched_cfg, monkeypatch):
    sess = _Session([
        _ok(), _Resp(429, body="rate limited"),
        _ok(), _ok(), _ok(), _ok(),
    ])
    monkeypatch.setattr("consensus_engine.health.get_session",
                        AsyncMock(return_value=sess))
    failed, report = await health.run_chain_check()
    assert failed is True
    assert "HTTP 429" in report
    assert "fb1:free" in report
    assert report.count("❌") == 1


async def test_run_chain_check_flags_empty_content(patched_cfg, monkeypatch):
    sess = _Session([_ok(""), _ok(), _ok(), _ok(), _ok(), _ok()])
    monkeypatch.setattr("consensus_engine.health.get_session",
                        AsyncMock(return_value=sess))
    failed, report = await health.run_chain_check()
    assert failed is True
    assert "EMPTY" in report
    assert "primary-llm:free" in report


async def test_run_chain_check_no_api_key(patched_cfg, monkeypatch):
    """With no provider key, every model reports KEY MISSING individually —
    the report is no longer blanked by a single early abort."""
    monkeypatch.setattr("consensus_engine.health.cfg.get_api_key",
                        lambda k: "")
    failed, report = await health.run_chain_check()
    assert failed is True
    assert "KEY MISSING" in report


async def test_run_chain_check_no_models_configured(monkeypatch):
    monkeypatch.setattr("consensus_engine.health.cfg.get",
                        lambda k, default=None: default)
    monkeypatch.setattr("consensus_engine.health.cfg.get_api_key",
                        lambda k: "fake-key" if k == "openrouter" else "")
    monkeypatch.setattr("consensus_engine.health._enumerate_gateway_chain_models",
                        lambda: ([], ""))
    failed, report = await health.run_chain_check()
    assert failed is True
    assert "no models configured" in report


async def test_probe_model_does_not_send_allowed_mentions(monkeypatch):
    """_probe_model must not inject the Discord-only allowed_mentions field into
    the LLM chat-completions request body (regression for groq HTTP 400 bug)."""
    captured_bodies = []

    class _CapturingResp:
        status = 200
        async def json(self):
            return {"choices": [{"message": {"content": "4"}}]}
        async def text(self):
            return ""
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class _CapturingSession:
        def post(self, url, headers=None, json=None, timeout=None):
            captured_bodies.append(json)
            return _CapturingResp()

    monkeypatch.setattr("consensus_engine.health.cfg.get_api_key",
                        lambda k: "fake-key")
    monkeypatch.setattr("consensus_engine.health.get_session",
                        AsyncMock(return_value=_CapturingSession()))

    await health._probe_model(_CapturingSession(), "groq/llama-3.3-70b-versatile")

    assert captured_bodies, "probe must have sent at least one request"
    for body in captured_bodies:
        assert "allowed_mentions" not in body, (
            "allowed_mentions (a Discord-only field) must never appear in an "
            "LLM chat-completions request body"
        )


def test_seconds_until_next_handles_today(monkeypatch):
    """Future time today should give a small positive interval."""
    from datetime import datetime, timezone
    fixed = datetime(2026, 5, 7, 5, 0, 0, tzinfo=timezone.utc)

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed

    monkeypatch.setattr("consensus_engine.health.datetime", _DT)
    secs = health._seconds_until_next(8, 30)
    assert 0 < secs < 86400
