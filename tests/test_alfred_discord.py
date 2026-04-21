import pytest
from consensus_engine.briefing import alfred


async def test_send_discord_returns_message_id_on_success(monkeypatch):
    class FakeResp:
        status = 200
        async def json(self): return {"id": "99988877"}
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class FakeSession:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def post(self, url, headers=None, json=None, timeout=None):
            assert "chan123" in url
            assert json["content"].startswith("hello")
            return FakeResp()

    monkeypatch.setattr("consensus_engine.briefing.alfred.aiohttp.ClientSession", FakeSession)
    monkeypatch.setattr("consensus_engine.config.get_api_key",
                        lambda k: "bot-token" if k == "discord_bot_token" else "")
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: "chan123" if "channel" in (k or "") else default)

    msg_id = await alfred._send_discord_briefing("hello world")
    assert msg_id == "99988877"


async def test_send_discord_returns_none_when_no_channel(monkeypatch):
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: "" if "channel" in (k or "") else default)
    out = await alfred._send_discord_briefing("x")
    assert out is None
