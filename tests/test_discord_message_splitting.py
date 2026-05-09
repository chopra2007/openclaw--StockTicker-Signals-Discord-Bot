"""Multi-message splitting for Discord replies.

Discord caps a single message at 2000 chars. send_command_reply previously
hard-truncated to 2000, dropping anything longer. The new behavior splits
long content into multiple sequential reply messages so neither the text
nor the primary LLM gets clipped.
"""
from __future__ import annotations

import pytest


def test_short_content_returns_single_chunk():
    from consensus_engine.alerts.discord import _split_for_discord
    chunks = _split_for_discord("hello world")
    assert chunks == ["hello world"]


def test_content_under_limit_returns_single_chunk():
    from consensus_engine.alerts.discord import _split_for_discord
    text = "x" * 1999
    chunks = _split_for_discord(text)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_long_content_splits_into_multiple_chunks_each_under_limit():
    from consensus_engine.alerts.discord import _split_for_discord
    text = "x" * 5500
    chunks = _split_for_discord(text)
    assert len(chunks) >= 3
    for c in chunks:
        assert len(c) <= 2000, f"chunk over 2000 chars: {len(c)}"
    assert "".join(chunks) == text


def test_split_prefers_paragraph_boundary():
    from consensus_engine.alerts.discord import _split_for_discord
    para1 = "A" * 1500
    para2 = "B" * 1500
    text = para1 + "\n\n" + para2
    chunks = _split_for_discord(text)
    assert len(chunks) == 2
    assert chunks[0].rstrip() == para1
    assert chunks[1].lstrip() == para2


def test_split_falls_back_to_line_when_no_paragraph():
    from consensus_engine.alerts.discord import _split_for_discord
    line1 = "C" * 1500
    line2 = "D" * 800
    text = line1 + "\n" + line2
    chunks = _split_for_discord(text)
    assert len(chunks) == 2
    assert chunks[0].rstrip() == line1
    assert chunks[1].lstrip() == line2


def test_empty_content_returns_empty_list():
    from consensus_engine.alerts.discord import _split_for_discord
    assert _split_for_discord("") == []


@pytest.mark.asyncio
async def test_send_command_reply_short_uses_one_post(monkeypatch):
    """Short reply → one POST to Discord (existing behavior preserved)."""
    from consensus_engine.alerts import discord as d
    posts: list[dict] = []

    class _Resp:
        status = 200
        async def json(self): return {"id": "msg_id"}
        async def text(self): return ""
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None

    class _Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        def post(self, url, headers=None, json=None, timeout=None):
            posts.append(json)
            return _Resp()

    monkeypatch.setattr("consensus_engine.alerts.discord.aiohttp.ClientSession",
                        lambda *a, **kw: _Session())
    monkeypatch.setattr("consensus_engine.alerts.discord.cfg.get_api_key",
                        lambda *_a, **_kw: "fake_token")

    out = await d.send_command_reply("ch", "msg", "short reply")
    assert out == "msg_id"
    assert len(posts) == 1
    assert posts[0]["content"] == "short reply"


@pytest.mark.asyncio
async def test_send_command_reply_long_splits_into_chained_posts(monkeypatch):
    """5500-char reply → multiple POSTs, each ≤ 2000 chars."""
    from consensus_engine.alerts import discord as d
    posts: list[dict] = []

    class _Resp:
        status = 200
        _ctr = {"i": 0}
        async def json(self):
            self._ctr["i"] += 1
            return {"id": f"msg_{self._ctr['i']}"}
        async def text(self): return ""
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None

    class _Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        def post(self, url, headers=None, json=None, timeout=None):
            posts.append(json)
            return _Resp()

    monkeypatch.setattr("consensus_engine.alerts.discord.aiohttp.ClientSession",
                        lambda *a, **kw: _Session())
    monkeypatch.setattr("consensus_engine.alerts.discord.cfg.get_api_key",
                        lambda *_a, **_kw: "fake_token")

    out = await d.send_command_reply("ch", "msg", "X" * 5500)
    assert out is not None, "should return last message id"
    assert len(posts) >= 3
    for p in posts:
        assert len(p["content"]) <= 2000
    # First post replies to the original; remaining posts are unchained or
    # chain to the previous bot message — either is acceptable, but the
    # entire content must round-trip.
    rejoined = "".join(p["content"] for p in posts)
    assert rejoined == "X" * 5500
