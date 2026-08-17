import pytest
from consensus_engine.briefing import alfred


EMBED = {"title": "☀️  Morning Brief", "fields": [{"name": "Overnight", "value": "hello"}]}


async def test_send_briefing_returns_message_id_on_success(monkeypatch):
    class FakeResp:
        status = 200
        async def json(self): return {"id": "99988877"}
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class FakeSession:
        def post(self, url, headers=None, json=None, data=None, timeout=None):
            assert "chan123" in url
            assert json["embeds"][0]["fields"][0]["value"] == "hello"
            return FakeResp()

    async def fake_get_session(): return FakeSession()
    monkeypatch.setattr(alfred, "get_session", fake_get_session)
    monkeypatch.setattr("consensus_engine.config.get_api_key",
                        lambda k: "bot-token" if k == "discord_bot_token" else "")
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: "chan123" if "channel" in (k or "") else default)

    msg_id = await alfred.send_briefing_message([EMBED])
    assert msg_id == "99988877"


async def test_send_briefing_returns_none_when_no_channel(monkeypatch):
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: "" if "channel" in (k or "") else default)
    out = await alfred.send_briefing_message([EMBED])
    assert out is None


async def test_send_briefing_uploads_both_charts(monkeypatch):
    seen = {}

    class FakeResp:
        status = 200
        async def json(self): return {"id": "123"}
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class FakeSession:
        def post(self, url, headers=None, json=None, data=None, timeout=None):
            seen["form"] = data
            return FakeResp()

    async def fake_get_session(): return FakeSession()
    monkeypatch.setattr(alfred, "get_session", fake_get_session)
    monkeypatch.setattr("consensus_engine.config.get_api_key", lambda k: "bot-token")
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: "chan123" if "channel" in (k or "") else default)

    msg_id = await alfred.send_briefing_message(
        [EMBED, {"title": "SPY — Weekly Expected Move"}],
        [(alfred.SPY_EM_DAILY_FILE, b"png-a"), (alfred.SPY_EM_WEEKLY_FILE, b"png-b")],
    )
    assert msg_id == "123"
    assert seen["form"] is not None  # multipart, not plain json


async def test_send_briefing_falls_back_to_embeds_when_upload_fails(monkeypatch):
    calls = {"n": 0}

    class FakeResp:
        def __init__(self, status): self.status = status
        async def json(self): return {"id": "fallback-id"}
        async def text(self): return ""
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class FakeSession:
        def post(self, url, headers=None, json=None, data=None, timeout=None):
            calls["n"] += 1
            if data is not None:
                return FakeResp(500)          # multipart upload rejected
            assert "image" not in json["embeds"][0]
            return FakeResp(200)

    async def fake_get_session(): return FakeSession()
    monkeypatch.setattr(alfred, "get_session", fake_get_session)
    monkeypatch.setattr("consensus_engine.config.get_api_key", lambda k: "bot-token")
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: "chan123" if "channel" in (k or "") else default)

    embed = dict(EMBED, image={"url": f"attachment://{alfred.SPY_EM_DAILY_FILE}"})
    msg_id = await alfred.send_briefing_message(
        [embed], [(alfred.SPY_EM_DAILY_FILE, b"png-a")])
    assert msg_id == "fallback-id"
    assert calls["n"] == 2
