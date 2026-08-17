import pytest
from consensus_engine import db
from consensus_engine.briefing import alfred


@pytest.fixture(autouse=True)
async def _isolated(tmp_path, monkeypatch):
    import consensus_engine.db as dbmod
    from consensus_engine import config as cfg
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "t.db"), "signal_ttl_hours": 2, "alert_history_days": 90}
    dbmod._db = None
    await dbmod.init_db()
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: {
                            "vault.path": str(tmp_path / "vault"),
                        }.get(k, default))
    # No network in the outbox tests: SPY expected move is unavailable.
    async def _no_em(horizon): return None, None
    monkeypatch.setattr(alfred, "_spy_expected_move", _no_em)
    yield
    dbmod._db = None


async def test_post_briefing_runs_full_state_machine(monkeypatch, tmp_path):
    async def fake_render(data): return "brief content"
    async def fake_send(embeds, attachments=None): return "msg-42"
    monkeypatch.setattr(alfred, "_render_briefing", fake_render)
    monkeypatch.setattr(alfred, "send_briefing_message", fake_send)

    data = {"session_start_utc": 1.0, "session_end_utc": 2.0,
            "alerts": [], "levels": [], "yt_signals": [], "macro": None, "top_tickers": []}
    await alfred.post_briefing("2026-04-21", data)

    run = await db.get_briefing_run("2026-04-21")
    assert run["status"] == "archived"
    assert run["discord_message_id"] == "msg-42"
    assert (tmp_path / "vault" / "macro" / "briefings" / "2026-04-21.md").exists()


async def test_post_briefing_resumes_from_posted(monkeypatch, tmp_path):
    """If we crashed after posting, re-run should only archive (no double-post)."""
    await db.upsert_briefing_run(
        "2026-04-21",
        session_start_utc=1.0, session_end_utc=2.0,
        rendered_content="already-rendered",
        discord_message_id="old-msg",
        status="posted",
    )
    sent = {"count": 0}
    async def fake_send(embeds, attachments=None):
        sent["count"] += 1
        return "x"
    async def fake_render(data): return "would-never-be-called"
    monkeypatch.setattr(alfred, "send_briefing_message", fake_send)
    monkeypatch.setattr(alfred, "_render_briefing", fake_render)

    await alfred.post_briefing("2026-04-21",
                               {"session_start_utc": 1.0, "session_end_utc": 2.0,
                                "alerts": [], "levels": [], "yt_signals": [],
                                "macro": None, "top_tickers": []})
    run = await db.get_briefing_run("2026-04-21")
    assert run["status"] == "archived"
    assert sent["count"] == 0  # did not re-send


async def test_post_briefing_skips_if_archived(monkeypatch):
    await db.upsert_briefing_run(
        "2026-04-21",
        session_start_utc=1.0, session_end_utc=2.0,
        rendered_content="done", status="archived",
    )
    called = {"render": 0, "send": 0}
    async def fake_render(d): called["render"] += 1; return "x"
    async def fake_send(embeds, attachments=None): called["send"] += 1; return "y"
    monkeypatch.setattr(alfred, "_render_briefing", fake_render)
    monkeypatch.setattr(alfred, "send_briefing_message", fake_send)

    await alfred.post_briefing("2026-04-21",
                               {"session_start_utc": 1.0, "session_end_utc": 2.0,
                                "alerts": [], "levels": [], "yt_signals": [],
                                "macro": None, "top_tickers": []})
    assert called["render"] == 0
    assert called["send"] == 0


async def test_post_briefing_stays_retryable_and_never_double_posts(monkeypatch, tmp_path):
    """A failed send leaves the run pending; the retry posts exactly once."""
    async def fake_render(data): return "brief content"
    sends = {"n": 0}

    async def failing_send(embeds, attachments=None):
        sends["n"] += 1
        return None
    monkeypatch.setattr(alfred, "_render_briefing", fake_render)
    monkeypatch.setattr(alfred, "send_briefing_message", failing_send)

    data = {"session_start_utc": 1.0, "session_end_utc": 2.0,
            "alerts": [], "levels": [], "yt_signals": [], "macro": None, "top_tickers": []}
    await alfred.post_briefing("2026-04-22", data)

    run = await db.get_briefing_run("2026-04-22")
    assert run["status"] == "pending"
    assert run["discord_message_id"] is None
    assert sends["n"] == 1

    async def ok_send(embeds, attachments=None):
        sends["n"] += 1
        return "msg-9"
    monkeypatch.setattr(alfred, "send_briefing_message", ok_send)

    await alfred.post_briefing("2026-04-22", data)
    await alfred.post_briefing("2026-04-22", data)     # already archived — no re-send

    run = await db.get_briefing_run("2026-04-22")
    assert run["status"] == "archived"
    assert run["discord_message_id"] == "msg-9"
    assert sends["n"] == 2


async def test_post_briefing_stores_expected_move_metadata(monkeypatch, tmp_path):
    async def fake_render(data): return "brief content"
    async def fake_payload(content): return ([{"title": "x"}], [], '{"daily":{"chart":true}}')
    async def fake_send(embeds, attachments=None): return "msg-7"
    monkeypatch.setattr(alfred, "_render_briefing", fake_render)
    monkeypatch.setattr(alfred, "_build_briefing_payload", fake_payload)
    monkeypatch.setattr(alfred, "send_briefing_message", fake_send)

    await alfred.post_briefing("2026-04-23",
                               {"session_start_utc": 1.0, "session_end_utc": 2.0,
                                "alerts": [], "levels": [], "yt_signals": [],
                                "macro": None, "top_tickers": []})
    run = await db.get_briefing_run("2026-04-23")
    assert run["em_metadata"] == '{"daily":{"chart":true}}'
    # rendered_content stays the readable brief, not metadata
    assert run["rendered_content"] == "brief content"
