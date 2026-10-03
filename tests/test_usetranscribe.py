"""Exercise the provider boundary: cached JSON, streamed jobs, and fallback."""
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from consensus_engine.utils import transcript_fetch as fetcher

VID = "dQw4w9WgXcQ"


def cached_payload():
    return {
        "platform": "youtube", "external_id": VID,
        "permalink": f"https://www.usetranscribe.io/yt/{VID}/test",
        "title": "Test video", "duration_seconds": 20,
        "summary": "A synthesized summary, never transcript text.",
        "transcript": {
            "language": "en",
            "segments": [
                {"start": 0, "end": 5, "text": "Tesla reported deliveries."},
                {"start": 5, "end": 20, "text": "Bonds fell.", "speaker": "Speaker 1"},
            ],
            "sections": [{"start": 0, "title": "Markets"}],
            "chat_pills": ["What happened?"],
        },
    }


def response(payload=None, status=200, lines=None, headers=None):
    resp = MagicMock()
    resp.status = status
    resp.headers = headers or {}
    resp.json = AsyncMock(return_value=payload)

    async def stream():
        for line in lines or []:
            yield line.encode()

    resp.content.__aiter__.side_effect = stream
    resp.content.iter_chunked.side_effect = lambda size: stream()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


@pytest.fixture
def provider(tmp_path):
    from consensus_engine.utils import usetranscribe as U
    settings = {
        "youtube.usetranscribe.enabled": True,
        "youtube.usetranscribe.cache_dir": str(tmp_path),
    }
    session = MagicMock()
    with patch.object(U.cfg, "get", side_effect=lambda k, d=None: settings.get(k, d)), \
            patch.object(U, "get_session", AsyncMock(return_value=session)):
        yield U, session, tmp_path, settings


async def test_cached_transcript_preserves_features_and_reads_locally(provider):
    U, session, directory, _ = provider
    session.get.side_effect = [response({"cached": True}), response(cached_payload())]
    result = await U.fetch_usetranscribe(VID)
    assert result == ("Tesla reported deliveries. Bonds fell.", "en", True)
    record = json.loads((directory / f"{VID}.json").read_text())
    assert record["transcript"]["segments"][1]["speaker"] == "Speaker 1"
    assert record["transcript"]["sections"] == [{"start": 0, "title": "Markets"}]
    assert record["transcript"]["chat_pills"] == ["What happened?"]
    assert record["summary"] == "A synthesized summary, never transcript text."
    session.get.side_effect = AssertionError("local cache must avoid network")
    assert await U.fetch_usetranscribe(VID) == result


async def test_cache_miss_parses_sse_done_shape(provider):
    U, session, directory, _ = provider
    cached = cached_payload()
    done = {
        **cached["transcript"], "summary_md": "Job summary",
        "permalink": cached["permalink"], "metadata": {"duration_seconds": 20},
        "source": "captions",
    }
    session.get.side_effect = [response({"cached": False}), response(lines=[
        ": keepalive\n", "\n", "event: stage\n", 'data: {"stage":"transcribing"}\n', "\n",
        "event: done\n", "data: " + json.dumps(done) + "\n", "\n",
    ])]
    assert await U.fetch_usetranscribe(VID) == ("Tesla reported deliveries. Bonds fell.", "en", True)
    assert json.loads((directory / f"{VID}.json").read_text())["summary"] == "Job summary"
    assert session.get.call_args.kwargs["params"]["summarize"] == "1"


async def test_daily_limit_survives_restart_but_cached_reads_still_work(provider):
    U, session, directory, _ = provider
    session.get.side_effect = [response({"cached": False}), response(
        {"error": "rate_limit", "scope": "ip"}, status=429)]
    assert await U.fetch_usetranscribe(VID) is None
    assert (directory / "cooldown.json").exists()
    session.get.side_effect = [response({"cached": False})]
    assert await U.fetch_usetranscribe(VID) is None  # no second job
    assert session.get.call_args.args[0].endswith("/api/check")
    session.get.side_effect = [response({"cached": True}), response(cached_payload())]
    assert (await U.fetch_usetranscribe(VID))[0] == "Tesla reported deliveries. Bonds fell."


@pytest.mark.parametrize("mutation", ["wrong_video", "empty", "summary_only", "bad_time", "wrong_language"])
async def test_unusable_cache_is_rejected(provider, mutation):
    U, session, directory, _ = provider
    payload = cached_payload()
    if mutation == "wrong_video":
        payload["external_id"] = "aaaaaaaaaaa"
    elif mutation == "empty":
        payload["transcript"]["segments"] = []
    elif mutation == "summary_only":
        del payload["transcript"]
    elif mutation == "bad_time":
        payload["transcript"]["segments"][0]["start"] = -5
    else:
        payload["transcript"]["language"] = "fr"
    session.get.side_effect = [response({"cached": True}), response(payload)]
    assert await U.fetch_usetranscribe(VID) is None
    assert not (directory / f"{VID}.json").exists()


async def test_permanent_error_does_not_repeat_job(provider):
    U, session, _, _ = provider
    session.get.side_effect = [response({"cached": False}), response(lines=[
        "event: error\n", 'data: {"code":"too_long","message":"Too long"}\n', "\n",
    ])]
    assert await U.fetch_usetranscribe(VID) is None
    session.get.side_effect = [response({"cached": False})]
    assert await U.fetch_usetranscribe(VID) is None
    assert session.get.call_args.args[0].endswith("/api/check")


async def test_disabled_provider_makes_no_network_call(provider):
    U, session, _, settings = provider
    settings["youtube.usetranscribe.enabled"] = False
    assert await U.fetch_usetranscribe(VID) is None
    session.get.assert_not_called()


async def test_free_source_wins_before_paid_source():
    with patch.object(fetcher, "_fetch_via_usetranscribe", AsyncMock(return_value=("Free text", "en", True)), create=True), \
            patch.object(fetcher, "_fetch_via_supadata", AsyncMock(side_effect=AssertionError("paid source used"))):
        assert await fetcher.fetch_transcript_cascade(VID) == ("Free text", "en", True)


async def test_paid_source_still_works_when_free_source_fails():
    with patch.object(fetcher, "_fetch_via_usetranscribe", AsyncMock(return_value=None), create=True), \
            patch.object(fetcher, "_fetch_via_supadata", AsyncMock(return_value=("Paid text", "en", True))):
        assert await fetcher.fetch_transcript_cascade(VID) == ("Paid text", "en", True)


async def test_evidence_caption_path_uses_shared_cascade():
    from consensus_engine.local_video_ingest import fetch_captions
    with patch("consensus_engine.config.get", side_effect=lambda k, d=None: True if k == "youtube.captions.enabled" else d), \
            patch.object(fetcher, "fetch_transcript_cascade", AsyncMock(return_value=("Free evidence text", "en", True))):
        assert await fetch_captions(VID) == "Free evidence text"


async def test_transcript_command_links_to_summary_sections_and_qa(provider):
    U, session, _, _ = provider
    session.get.side_effect = [response({"cached": True}), response(cached_payload())]
    result = await U.fetch_usetranscribe(VID)
    from consensus_engine.alerts.commands import _transcript_and_reply
    with patch.object(fetcher, "fetch_transcript_cascade", AsyncMock(return_value=result)), \
            patch("consensus_engine.alerts.commands.send_command_reply", AsyncMock()) as reply:
        await _transcript_and_reply(f"https://youtu.be/{VID}", "channel", "message")
    message = reply.call_args.args[2]
    assert "Tesla reported deliveries. Bonds fell." in message
    assert f"https://www.usetranscribe.io/yt/{VID}/test" in message


async def test_sse_done_larger_than_aiohttp_line_limit(provider):
    import aiohttp
    U, _, _, _ = provider
    reader = aiohttp.StreamReader(MagicMock(_reading_paused=False), 65536,
                                  loop=asyncio.get_running_loop())
    payload = {"segments": [{"start": 0, "end": 30, "text": "a" * 200000}]}
    reader.feed_data(("event: done\ndata: " + json.dumps(payload) + "\n\n").encode())
    reader.feed_eof()
    events = [item async for item in U._events(MagicMock(content=reader))]
    assert events == [("done", payload)]


async def test_local_cached_read_does_not_wait_for_new_job(provider):
    U, _, directory, _ = provider
    (directory / f"{VID}.json").write_text(json.dumps(cached_payload()))
    # Represent another caller's outstanding new job, independent of HTTP timing.
    U._job_lock = asyncio.Semaphore(1)
    await U._job_lock.acquire()
    try:
        assert await asyncio.wait_for(U.fetch_usetranscribe(VID), .2) == (
            "Tesla reported deliveries. Bonds fell.", "en", True)
    finally:
        U._job_lock.release()
