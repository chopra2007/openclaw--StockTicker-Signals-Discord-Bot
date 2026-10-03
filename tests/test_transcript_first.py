import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from consensus_engine.analysis import captions_llm_parser as parser
from consensus_engine.models import CandidateLevel, EvidenceBundle, EvidenceSpan, RunTelemetry


@pytest.mark.asyncio
async def test_timed_source_preserves_tail_and_rejects_invented_quote():
    segments = [{"start": i * 10, "end": i * 10 + 5, "text": "market context " * 80}
                for i in range(30)]
    segments.append({"start": 1120, "end": 1125, "text": "Tesla is breaking out above 250."})
    seen = []

    async def answer(**kw):
        seen.append(kw["messages"][1]["content"])
        if "Tesla is breaking out" in seen[-1]:
            return json.dumps({"spans": [
                {"quote": "Tesla is breaking out above 250.", "tickers": ["TSLA"],
                 "start_segment": 29, "end_segment": 29, "numbers": [250]},
                {"quote": "Tesla will triple tomorrow.", "tickers": ["TSLA"],
                 "start_segment": 30, "end_segment": 30},
            ]})
        return '{"spans": []}'

    with patch.object(parser, "call_with_fallback", side_effect=answer):
        bundle = await parser.extract_evidence_from_captions(
            "dQw4w9WgXcQ", " ".join(s["text"] for s in segments), "", RunTelemetry(),
            source_segments=segments,
        )
    assert bundle is not None
    assert [s.ts_sec for s in bundle.spans] == [1120]
    assert bundle.spans[0].numbers == [250]
    assert len(seen) > 1 and all(len(p) < 20000 for p in seen)
    assert bundle.duration_sec == 1125


@pytest.mark.asyncio
async def test_one_failed_text_chunk_does_not_claim_complete():
    responses = iter(['{"spans": []}', None, '{"spans": []}'])
    with patch.object(parser, "call_with_fallback", side_effect=lambda **kw: next(responses)) as call:
        bundle = await parser.extract_evidence_from_captions(
            "dQw4w9WgXcQ", "word " * 8000, "", RunTelemetry(),
        )
    assert bundle is None
    assert call.await_count == 2


@pytest.mark.asyncio
async def test_transcript_first_adds_visuals_without_gemini_speech():
    from consensus_engine import local_video_ingest as ingest
    spoken = EvidenceBundle("dQw4w9WgXcQ", 60, "", spans=[EvidenceSpan(20, "Tesla chart", ["TSLA"])])
    def config(key, default=None):
        return True if key in {"youtube.transcript_first", "youtube.captions.enabled"} else default
    with (
        patch("consensus_engine.config.get", side_effect=config),
        patch.object(ingest, "pre_flight_check", return_value=True),
        patch.object(ingest, "_stage_captions", new=AsyncMock(return_value=spoken)),
        patch.object(ingest, "_stage_gemini", new=AsyncMock()) as speech,
        patch("consensus_engine.analysis.youtube_visual_jobs.queue_visuals", new=AsyncMock(return_value=True)) as visuals,
    ):
        bundle, tel = await ingest._run_chain("dQw4w9WgXcQ", "Channel", "")
    assert bundle is spoken
    speech.assert_not_awaited()
    visuals.assert_awaited_once()
    assert tel.chain_winner == "transcript+visual/v1"


@pytest.mark.asyncio
async def test_visual_failure_keeps_spoken_success_and_queues(tmp_path):
    from consensus_engine.analysis import youtube_visual_jobs as jobs
    spoken = EvidenceBundle("dQw4w9WgXcQ", 60, "", spans=[EvidenceSpan(20, "Tesla chart", ["TSLA"])])
    def config(key, default=None):
        return str(tmp_path) if key == "youtube.visual.jobs_dir" else default
    with (
        patch("consensus_engine.config.get", side_effect=config),
        patch.object(jobs, "extract_visual_evidence_with_gemini", new=AsyncMock(return_value=(None, RunTelemetry(f2_failure_category="quota")))),
    ):
        assert not await jobs.add_visuals(spoken, RunTelemetry())
    record = json.loads((tmp_path / "dQw4w9WgXcQ.json").read_text())
    assert record["status"] == "pending"
    assert record["bundle"]["spans"][0]["ts_sec"] == 20


@pytest.mark.asyncio
async def test_successful_empty_timed_transcript_is_valid():
    with patch.object(parser, "call_with_fallback", new=AsyncMock(return_value='{"spans": []}')):
        bundle = await parser.extract_evidence_from_captions(
            "dQw4w9WgXcQ", "Hello everyone.", "", RunTelemetry(),
            source_segments=[{"text": "Hello everyone.", "start": 0, "end": 5}],
        )
    assert bundle is not None and bundle.spans == []


@pytest.mark.asyncio
@pytest.mark.parametrize("input_tokens", [1234, None])
async def test_visual_request_samples_frames_and_rejects_speech(input_tokens):
    from consensus_engine.analysis import gemini_video_parser as gem
    client = MagicMock()
    client.models.generate_content.return_value = MagicMock(
        text=json.dumps({"duration_sec": 60, "visual_evidence": [
            {"ts_sec": 20, "value": "250", "kind": "price", "where": "marked support", "ticker": "TSLA"}],
            "spans": [{"ts_sec": 20, "quote": "Tesla", "tickers": ["TSLA"]}]}),
        usage_metadata=MagicMock(prompt_token_count=input_tokens, candidates_token_count=100),
    )
    budget = MagicMock(can_consume_gemini=AsyncMock(return_value=True), consume_gemini=AsyncMock())
    with (
        patch.object(gem, "_get_available_gemini_client", return_value=(client, "test")),
        patch("consensus_engine.engine.BudgetManager", return_value=budget),
        patch("consensus_engine.utils.rate_limiter.rate_limiter.acquire", new=AsyncMock(return_value=True)),
    ):
        bundle, tel = await gem.extract_visual_evidence_with_gemini("dQw4w9WgXcQ", "")
    parts = client.models.generate_content.call_args.kwargs["contents"]
    assert "Do not transcribe" in parts[0].text
    assert parts[1].video_metadata.fps == 0.05
    if input_tokens is None:
        assert bundle is None
        assert tel.f2_failure_category == "gemini_no_input_tokens"
    else:
        assert bundle.spans == [] and bundle.segments == []
        assert bundle.visual_evidence[0]["ticker"] == "TSLA"
        assert tel.input_tokens == 1234


@pytest.mark.asyncio
async def test_visual_retry_survives_restart_and_deduplicates(tmp_path, monkeypatch):
    from consensus_engine import db, config
    from consensus_engine.analysis import youtube_visual_jobs as jobs
    from consensus_engine.scanners import youtube
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "probe.db"))
    monkeypatch.setattr(db, "_db", None)
    original = config.get
    monkeypatch.setattr(config, "get", lambda key, default=None: str(tmp_path / "jobs")
                        if key == "youtube.visual.jobs_dir" else original(key, default))
    bundle = EvidenceBundle("dQw4w9WgXcQ", 60, "", spans=[EvidenceSpan(20, "Tesla chart", ["TSLA"])])
    visual = EvidenceBundle(bundle.video_id, 60, "", visual_evidence=[
        {"ts_sec": 20, "value": "250", "kind": "price", "where": "marked support", "ticker": "TSLA"}])
    try:
        await db.init_db()
        await db.upsert_youtube_video(bundle.video_id, "channel", "Tesla chart", "", 0)
        monkeypatch.setattr(db, "get_channel_display_name", AsyncMock(return_value="Trusted channel"))
        await db.mark_youtube_video_status(bundle.video_id, "analyzed_gemini_v2")
        jobs._write(tmp_path / "jobs" / f"{bundle.video_id}.json", {
            "status": "pending", "retry_at": 0, "bundle": __import__("dataclasses").asdict(bundle)})
        monkeypatch.setattr(jobs, "_lock", None)  # new process, disk job remains
        model = AsyncMock(return_value=(visual, RunTelemetry(input_tokens=1234)))
        monkeypatch.setattr(jobs, "extract_visual_evidence_with_gemini", model)
        build = AsyncMock(side_effect=[
            [CandidateLevel("TSLA", "support", 250, "Tesla chart support", classifier_confidence=0.55)],
            [CandidateLevel("TSLA", "resistance", 250, "Tesla chart resistance", classifier_confidence=0.55)],
        ])
        monkeypatch.setattr(youtube, "_build_visual_levels", build)
        monkeypatch.setattr(youtube, "_apply_price_sanity_to_levels", AsyncMock())
        await jobs.retry_pending_visuals()
        record = jobs._read(tmp_path / "jobs" / f"{bundle.video_id}.json")
        assert record["status"] == "complete"
        # Simulate crash after persistence but before the completion marker.
        record["status"] = "ready"
        jobs._write(tmp_path / "jobs" / f"{bundle.video_id}.json", record)
        await jobs.retry_pending_visuals()
        await jobs.retry_pending_visuals()
        model.assert_awaited_once()
        build.assert_awaited_once()  # a price move cannot change crash-replayed levels
        conn = await db.get_db()
        row = await (await conn.execute("SELECT count(*) FROM youtube_visual_evidence")).fetchone()
        assert row[0] == 1
        row = await (await conn.execute("SELECT channel_name FROM youtube_levels")).fetchone()
        assert row[0] == "Trusted channel"
        row = await (await conn.execute("SELECT count(*) FROM youtube_analysis_runs")).fetchone()
        assert row[0] == 1
        row = await (await conn.execute("SELECT count(*) FROM youtube_levels")).fetchone()
        assert row[0] == 1
    finally:
        await db.close_db()


@pytest.mark.asyncio
async def test_visual_exception_sets_retry_delay(tmp_path):
    from consensus_engine.analysis import youtube_visual_jobs as jobs
    bundle = EvidenceBundle("dQw4w9WgXcQ", 60, "")
    with patch.object(jobs, "_directory", return_value=tmp_path), patch.object(
            jobs, "extract_visual_evidence_with_gemini", new=AsyncMock(side_effect=ValueError("bad result"))):
        assert not await jobs.add_visuals(bundle, RunTelemetry())
        record = jobs._read(tmp_path / f"{bundle.video_id}.json")
        assert record["retry_at"] > __import__("time").time()


@pytest.mark.asyncio
async def test_visual_clips_cover_tail_use_known_times_and_require_all_frames():
    from consensus_engine.analysis import gemini_video_parser as gem
    client = MagicMock()
    calls = []
    def respond(**kw):
        parts = kw["contents"]
        clips = [p for p in parts if p.video_metadata]
        calls.append(clips)
        return MagicMock(text=json.dumps({"clips": [
            {"clip_index": i, "visual_evidence": [{"value": str(250 + i + len(calls) * 10), "kind": "price", "where": "marked support", "ticker": "TSLA"}]}
            for i in range(len(clips))]}),
            usage_metadata=MagicMock(prompt_token_count=4000, candidates_token_count=100))
    client.models.generate_content.side_effect = respond
    budget = MagicMock(can_consume_gemini=AsyncMock(return_value=True), consume_gemini=AsyncMock())
    with (
        patch.object(gem, "_get_available_gemini_client", return_value=(client, "test")),
        patch("consensus_engine.engine.BudgetManager", return_value=budget),
        patch("consensus_engine.utils.rate_limiter.rate_limiter.acquire", new=AsyncMock(return_value=True)),
    ):
        bundle, tel = await gem.extract_visual_evidence_with_gemini("dQw4w9WgXcQ", "", duration_sec=1197)
    assert len(calls) == 6 and all(len(batch) <= 10 for batch in calls)
    assert calls[-1][-1].video_metadata.start_offset == "1189s"
    assert all(p.video_metadata.fps == 0.25 for batch in calls for p in batch)
    assert tel.input_tokens == 24000
    assert bundle.duration_sec == 1197
    assert bundle.visual_evidence[-1]["ts_sec"] == 1189


@pytest.mark.asyncio
async def test_incomplete_visual_batch_remains_retryable():
    from consensus_engine.analysis import gemini_video_parser as gem
    client = MagicMock()
    client.models.generate_content.return_value = MagicMock(text='{"clips": []}',
        usage_metadata=MagicMock(prompt_token_count=4000, candidates_token_count=100))
    budget = MagicMock(can_consume_gemini=AsyncMock(return_value=True), consume_gemini=AsyncMock())
    with (
        patch.object(gem, "_get_available_gemini_client", return_value=(client, "test")),
        patch("consensus_engine.engine.BudgetManager", return_value=budget),
        patch("consensus_engine.utils.rate_limiter.rate_limiter.acquire", new=AsyncMock(return_value=True)),
    ):
        bundle, tel = await gem.extract_visual_evidence_with_gemini("dQw4w9WgXcQ", "", duration_sec=60)
    assert bundle is None and tel.f2_failure_category == "incomplete_visual_batch"


@pytest.mark.asyncio
async def test_quote_cannot_change_decimal_to_thousands_separator():
    with patch.object(parser, "call_with_fallback", new=AsyncMock(return_value=json.dumps({"spans": [
        {"quote": "Tesla support is $250,000.", "tickers": ["TSLA"], "start_segment": 0, "end_segment": 0}]}))):
        bundle = await parser.extract_evidence_from_captions("dQw4w9WgXcQ", "Tesla support is $250.000.", "", RunTelemetry(),
            source_segments=[{"text": "Tesla support is $250.000.", "start": 30, "end": 35}])
    assert bundle.spans == []


@pytest.mark.asyncio
async def test_oversized_source_segment_does_not_lose_words_to_overlap():
    seen = []
    async def respond(**kw):
        seen.append(kw["messages"][1]["content"])
        return '{"spans": []}'
    segments = [{"text": "intro " * 160, "start": 0, "end": 1},
                {"text": "a " * 7400 + "Tesla appears only here. " + "b " * 1000, "start": 1, "end": 40}]
    with patch.object(parser, "call_with_fallback", side_effect=respond):
        await parser.extract_evidence_from_captions("dQw4w9WgXcQ", " ".join(s["text"] for s in segments), "", RunTelemetry(), source_segments=segments)
    assert any("Tesla appears only here." in prompt for prompt in seen)
    assert all(len(prompt) < 20000 for prompt in seen)


@pytest.mark.asyncio
async def test_untimed_spans_do_not_invent_video_duration():
    with patch.object(parser, "call_with_fallback", new=AsyncMock(return_value='{"spans":[{"quote":"Tesla chart","tickers":["TSLA"]}]}')):
        bundle = await parser.extract_evidence_from_captions("dQw4w9WgXcQ", "Tesla chart", "", RunTelemetry())
    assert bundle.duration_sec is None


@pytest.mark.asyncio
async def test_visual_batch_checkpoints_avoid_repeating_completed_reads(tmp_path):
    from consensus_engine.analysis import gemini_video_parser as gem
    batch_bundle = EvidenceBundle("dQw4w9WgXcQ", 1197, "", visual_evidence=[])
    mock = AsyncMock(side_effect=[(batch_bundle, RunTelemetry(input_tokens=4000)),
                                 (None, RunTelemetry(f2_failure_category="quota"))])
    with patch.object(gem, "_extract_evidence_single_pass", mock):
        bundle, tel = await gem.extract_visual_evidence_with_gemini("dQw4w9WgXcQ", "", duration_sec=1197, cache_dir=tmp_path)
    assert bundle is None and (tmp_path / "0.json").exists()
    mock = AsyncMock(return_value=(batch_bundle, RunTelemetry(input_tokens=4000)))
    with patch.object(gem, "_extract_evidence_single_pass", mock):
        bundle, tel = await gem.extract_visual_evidence_with_gemini("dQw4w9WgXcQ", "", duration_sec=1197, cache_dir=tmp_path)
    assert bundle is not None and mock.await_count == 5
    assert tel.input_tokens == 24000


@pytest.mark.asyncio
async def test_queue_does_not_wait_for_google_or_transcribe_again(tmp_path):
    from consensus_engine.analysis import youtube_visual_jobs as jobs
    bundle = EvidenceBundle("dQw4w9WgXcQ", 1197, "", spans=[EvidenceSpan(20, "Tesla chart", ["TSLA"])])
    with patch.object(jobs, "_directory", return_value=tmp_path), patch.object(jobs,
        "extract_visual_evidence_with_gemini", new=AsyncMock()) as model:
        assert not await jobs.queue_visuals(bundle)
        assert not await jobs.queue_visuals(bundle)
    model.assert_not_awaited()
    assert jobs._read(tmp_path / f"{bundle.video_id}.json")["status"] == "pending"


@pytest.mark.asyncio
async def test_visual_worker_lifetime_follows_owner_stop():
    import asyncio
    from consensus_engine.analysis import youtube_visual_jobs as jobs
    stop, started = asyncio.Event(), asyncio.Event()
    async def worker(event):
        started.set()
        await event.wait()
    with patch("consensus_engine.config.get", return_value=True), patch.object(jobs, "visual_poll_loop", worker):
        task = jobs.start_visual_worker(stop)
        await asyncio.wait_for(started.wait(), 1)
        assert not task.done()
        stop.set()
        await asyncio.wait_for(task, 1)
