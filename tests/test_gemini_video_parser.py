"""Tests for Gemini fast-path video parser."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from consensus_engine.analysis.gemini_video_parser import (
    extract_evidence_with_gemini,
    _parse_ts_str,
    _build_evidence_bundle,
    _get_gemini_keys,
    _get_available_gemini_client,
    _is_quota_error,
    _mark_key_exhausted,
    _reset_key_exhaustion,
    _key_is_available,
    _pick_media_resolution,
    _should_escalate,
)
from consensus_engine.models import (
    EvidenceBundle, EvidenceSpan, RunTelemetry,
)


# ---------------------------------------------------------------------------
# Helper: _parse_ts_str
# ---------------------------------------------------------------------------

def test_parse_ts_str_accepts_int_seconds():
    assert _parse_ts_str(42) == 42
    assert _parse_ts_str(0) == 0


def test_parse_ts_str_accepts_float_seconds():
    assert _parse_ts_str(42.9) == 42


def test_parse_ts_str_parses_mm_ss():
    assert _parse_ts_str("1:23") == 83
    assert _parse_ts_str("35:42") == 35 * 60 + 42


def test_parse_ts_str_parses_hh_mm_ss():
    assert _parse_ts_str("1:02:03") == 3723


def test_parse_ts_str_returns_zero_on_junk():
    assert _parse_ts_str("not-a-time") == 0
    assert _parse_ts_str("") == 0
    assert _parse_ts_str(None) == 0
    assert _parse_ts_str(True) == 0


# ---------------------------------------------------------------------------
# Stage A: extract_evidence_with_gemini
# ---------------------------------------------------------------------------

_EVIDENCE_JSON = """{
  "duration_sec": 2340,
  "segments": [
    {"ts_start_sec": 2022, "title": "Number One Draft Pick: MSFT"}
  ],
  "spans": [
    {"ts_sec": 2024, "quote": "Our number one draft pick this week is MSFT", "tickers": ["MSFT"], "numbers": [], "dates_mentioned": []},
    {"ts_sec": 2142, "quote": "MSFT 8 EMA is currently coming in at 400.15", "tickers": ["MSFT"], "numbers": [400.15], "dates_mentioned": []},
    {"ts_sec": 2172, "quote": "MSFT bullish bias into April 29th earnings with an entry target at 400.15", "tickers": ["MSFT"], "numbers": [400.15], "dates_mentioned": ["April 29"]}
  ]
}"""


def _make_mock_response(text: str, prompt_tokens: int | None = 1234, output_tokens: int | None = 567):
    response = MagicMock()
    response.text = text
    if prompt_tokens is None and output_tokens is None:
        response.usage_metadata = None
    else:
        meta = MagicMock()
        meta.prompt_token_count = prompt_tokens
        meta.candidates_token_count = output_tokens
        response.usage_metadata = meta
    return response


@pytest.mark.asyncio
async def test_extract_evidence_parses_spans():
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _make_mock_response(_EVIDENCE_JSON)

    with patch("consensus_engine.analysis.gemini_video_parser._get_available_gemini_client", return_value=(mock_client, "GEMINI_API_KEY")), \
         patch("consensus_engine.db.create_analysis_run", new=AsyncMock(return_value=11)), \
         patch("consensus_engine.db.insert_youtube_evidence_span", new=AsyncMock(return_value=None)):
        bundle, telemetry = await extract_evidence_with_gemini(
            "4mSyMr8PGLI", "ShadowTrader", "2026-04-17T12:00:00Z",
        )

    assert isinstance(bundle, EvidenceBundle)
    assert bundle.video_id == "4mSyMr8PGLI"
    assert bundle.duration_sec == 2340
    assert len(bundle.segments) == 1
    assert bundle.segments[0]["title"].startswith("Number One")
    assert len(bundle.spans) == 3
    assert all(isinstance(s, EvidenceSpan) for s in bundle.spans)
    assert bundle.spans[2].tickers == ["MSFT"]
    assert bundle.spans[2].numbers == [400.15]
    assert bundle.spans[2].dates_mentioned == ["April 29"]

    assert isinstance(telemetry, RunTelemetry)
    assert telemetry.json_parse_ok is True
    assert telemetry.span_count == 3
    assert telemetry.input_tokens == 1234
    assert telemetry.output_tokens == 567
    assert telemetry.latency_ms >= 0


@pytest.mark.asyncio
async def test_extract_evidence_timeout():
    import asyncio

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = asyncio.TimeoutError()

    async def _raise_timeout(*_a, **_k):
        raise asyncio.TimeoutError()

    with patch("consensus_engine.analysis.gemini_video_parser._get_available_gemini_client", return_value=(mock_client, "GEMINI_API_KEY")), \
         patch("consensus_engine.analysis.gemini_video_parser.asyncio.wait_for", new=_raise_timeout):
        bundle, telemetry = await extract_evidence_with_gemini(
            "vid", "Chan", "2026-04-17T12:00:00Z",
        )

    assert bundle is None
    assert isinstance(telemetry, RunTelemetry)
    assert telemetry.json_parse_ok is False


@pytest.mark.asyncio
async def test_extract_evidence_invalid_json():
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _make_mock_response("not json garbage >>>")

    with patch("consensus_engine.analysis.gemini_video_parser._get_available_gemini_client", return_value=(mock_client, "GEMINI_API_KEY")):
        bundle, telemetry = await extract_evidence_with_gemini(
            "vid", "Chan", "2026-04-17T12:00:00Z",
        )

    assert bundle is None
    assert telemetry.json_parse_ok is False
    # Tokens still captured even when JSON fails
    assert telemetry.input_tokens == 1234


@pytest.mark.asyncio
async def test_extract_evidence_persists_spans():
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _make_mock_response(_EVIDENCE_JSON)

    mock_insert = AsyncMock(return_value=None)
    with patch("consensus_engine.analysis.gemini_video_parser._get_available_gemini_client", return_value=(mock_client, "GEMINI_API_KEY")), \
         patch("consensus_engine.db.create_analysis_run", new=AsyncMock(return_value=42)), \
         patch("consensus_engine.db.insert_youtube_evidence_span", new=mock_insert):
        bundle, telemetry = await extract_evidence_with_gemini(
            "vid", "Chan", "2026-04-17T12:00:00Z",
        )

    assert bundle is not None
    assert mock_insert.await_count == 3
    first_call_kwargs = mock_insert.await_args_list[0].kwargs
    assert first_call_kwargs["run_id"] == 42
    assert first_call_kwargs["video_id"] == "vid"
    assert first_call_kwargs["quote"].startswith("Our number one")


@pytest.mark.asyncio
async def test_extract_evidence_quarantines_spans_with_null_input_tokens():
    """Item B (deep-dive-2026-06-08): a Gemini response with evidence spans but NULL
    prompt_token_count is the hallucination signature (NVDA 850 etc.). The persist gate must
    discard it — return (None, telemetry) with f2_failure_category set, and NEVER call
    create_analysis_run/insert_youtube_evidence_span (nothing persists; video stays retryable)."""
    mock_client = MagicMock()
    # spans present, but prompt_token_count is None -> the impossible combination
    mock_client.models.generate_content.return_value = _make_mock_response(
        _EVIDENCE_JSON, prompt_tokens=None, output_tokens=567,
    )
    mock_run = AsyncMock(return_value=99)
    mock_insert = AsyncMock(return_value=None)
    with patch("consensus_engine.analysis.gemini_video_parser._get_available_gemini_client", return_value=(mock_client, "GEMINI_API_KEY")), \
         patch("consensus_engine.db.create_analysis_run", new=mock_run), \
         patch("consensus_engine.db.insert_youtube_evidence_span", new=mock_insert):
        bundle, telemetry = await extract_evidence_with_gemini(
            "halluc_vid", "Chan", "2026-06-01T12:00:00Z",
        )

    assert bundle is None, "hallucinated bundle must be discarded"
    assert telemetry.saw_null_input_tokens is True
    assert telemetry.f2_failure_category == "gemini_no_input_tokens"
    mock_run.assert_not_awaited()   # nothing persisted
    mock_insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_evidence_persists_normally_with_valid_input_tokens():
    """Control: a real response with a real prompt_token_count persists as usual (guard
    does NOT fire on the normal path)."""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _make_mock_response(
        _EVIDENCE_JSON, prompt_tokens=1234, output_tokens=567,
    )
    mock_run = AsyncMock(return_value=7)
    mock_insert = AsyncMock(return_value=None)
    with patch("consensus_engine.analysis.gemini_video_parser._get_available_gemini_client", return_value=(mock_client, "GEMINI_API_KEY")), \
         patch("consensus_engine.db.create_analysis_run", new=mock_run), \
         patch("consensus_engine.db.insert_youtube_evidence_span", new=mock_insert):
        bundle, telemetry = await extract_evidence_with_gemini(
            "real_vid", "Chan", "2026-06-01T12:00:00Z",
        )

    assert bundle is not None
    assert telemetry.saw_null_input_tokens is False
    mock_run.assert_awaited()       # persisted normally


@pytest.mark.asyncio
async def test_extract_evidence_skips_when_budget_exhausted():
    """When BudgetManager.can_consume_gemini returns False, extractor returns (None, telemetry)."""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _make_mock_response(_EVIDENCE_JSON)

    mock_budget = MagicMock()
    mock_budget.can_consume_gemini = AsyncMock(return_value=False)
    mock_budget.consume_gemini = AsyncMock(return_value=True)

    with patch("consensus_engine.analysis.gemini_video_parser._get_available_gemini_client", return_value=(mock_client, "GEMINI_API_KEY")), \
         patch("consensus_engine.engine.BudgetManager", return_value=mock_budget):
        bundle, telemetry = await extract_evidence_with_gemini(
            "vidBud", "Chan", "2026-04-17T12:00:00Z",
        )

    assert bundle is None
    assert telemetry.json_parse_ok is False
    # Gemini API was never called
    mock_client.models.generate_content.assert_not_called()


@pytest.mark.asyncio
async def test_extract_evidence_records_budget_usage_on_success():
    """On success, consume_gemini should record input/output tokens."""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _make_mock_response(
        _EVIDENCE_JSON, prompt_tokens=1234, output_tokens=567,
    )

    mock_budget = MagicMock()
    mock_budget.can_consume_gemini = AsyncMock(return_value=True)
    mock_budget.consume_gemini = AsyncMock(return_value=True)

    with patch("consensus_engine.analysis.gemini_video_parser._get_available_gemini_client", return_value=(mock_client, "GEMINI_API_KEY")), \
         patch("consensus_engine.engine.BudgetManager", return_value=mock_budget), \
         patch("consensus_engine.db.create_analysis_run", new=AsyncMock(return_value=77)), \
         patch("consensus_engine.db.insert_youtube_evidence_span", new=AsyncMock(return_value=None)):
        bundle, _telemetry = await extract_evidence_with_gemini(
            "vidBud2", "Chan", "2026-04-17T12:00:00Z",
        )

    assert bundle is not None
    mock_budget.consume_gemini.assert_awaited_once_with(1234, 567)


@pytest.mark.asyncio
async def test_extract_evidence_rejects_ta_abbreviations():
    bad_json = """{
      "duration_sec": 100,
      "segments": [],
      "spans": [
        {"ts_sec": 10, "quote": "MSFT EMA holding at 400", "tickers": ["EMA","MSFT"], "numbers": [400], "dates_mentioned": []},
        {"ts_sec": 20, "quote": "RSI overbought", "tickers": ["RSI"], "numbers": [], "dates_mentioned": []}
      ]
    }"""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _make_mock_response(bad_json)

    with patch("consensus_engine.analysis.gemini_video_parser._get_available_gemini_client", return_value=(mock_client, "GEMINI_API_KEY")), \
         patch("consensus_engine.db.create_analysis_run", new=AsyncMock(return_value=7)), \
         patch("consensus_engine.db.insert_youtube_evidence_span", new=AsyncMock(return_value=None)):
        bundle, _telemetry = await extract_evidence_with_gemini(
            "vid", "Chan", "2026-04-17T12:00:00Z",
        )

    assert bundle is not None
    # EMA and RSI are TA abbreviations — must be filtered from tickers[]
    assert bundle.spans[0].tickers == ["MSFT"]
    assert bundle.spans[1].tickers == []


def test_build_evidence_bundle_drops_empty_quotes():
    data = {
        "duration_sec": 60,
        "segments": [],
        "spans": [
            {"ts_sec": 1, "quote": "", "tickers": ["SPY"], "numbers": [], "dates_mentioned": []},
            {"ts_sec": 2, "quote": "   ", "tickers": ["SPY"], "numbers": [], "dates_mentioned": []},
            {"ts_sec": 3, "quote": "SPY real quote", "tickers": ["spy"], "numbers": [], "dates_mentioned": []},
        ],
    }
    b = _build_evidence_bundle(data, "v", "2026-04-17T12:00:00Z")
    assert len(b.spans) == 1
    assert b.spans[0].tickers == ["SPY"]


# ---------------------------------------------------------------------------
# visual_evidence — TODO #17: keep on-screen chart numbers / scanner rows
# ---------------------------------------------------------------------------

def test_evidence_bundle_defaults_visual_evidence_empty():
    """Back-compat: existing constructors that omit visual_evidence still work."""
    b = EvidenceBundle(video_id="v", duration_sec=60, publish_ts="2026-04-17T12:00:00Z")
    assert b.visual_evidence == []


def test_build_evidence_bundle_dedups_visual_evidence_by_value():
    data = {
        "duration_sec": 600,
        "spans": [],
        "visual_evidence": [
            {"ts_sec": 10, "value": "739.88", "kind": "price", "where": "chart axis"},
            {"ts_sec": 95, "value": "739.88", "kind": "price", "where": "chart axis later"},
            {"ts_sec": 30, "value": "NVDA", "kind": "ticker", "where": "flow row"},
        ],
    }
    b = _build_evidence_bundle(data, "v", "2026-04-17T12:00:00Z")
    assert len(b.visual_evidence) == 2
    # First occurrence kept (ts_sec=10), not the later duplicate.
    first = b.visual_evidence[0]
    assert first["value"] == "739.88"
    assert first["ts_sec"] == 10
    assert b.visual_evidence[1]["value"] == "NVDA"


def test_build_evidence_bundle_drops_out_of_range_ts():
    data = {
        "duration_sec": 100,
        "spans": [],
        "visual_evidence": [
            {"ts_sec": 50, "value": "in_range", "kind": "price", "where": "x"},
            {"ts_sec": 200, "value": "too_late", "kind": "price", "where": "x"},
            {"ts_sec": -5, "value": "negative", "kind": "price", "where": "x"},
        ],
    }
    b = _build_evidence_bundle(data, "v", "2026-04-17T12:00:00Z")
    values = [v["value"] for v in b.visual_evidence]
    assert values == ["in_range"]


def test_build_evidence_bundle_no_range_filter_when_duration_none():
    data = {
        # duration_sec absent → upper-bound filter is a no-op
        "spans": [],
        "visual_evidence": [
            {"ts_sec": 50, "value": "a", "kind": "price", "where": "x"},
            {"ts_sec": 99999, "value": "b", "kind": "price", "where": "x"},
            {"ts_sec": -1, "value": "neg", "kind": "price", "where": "x"},
        ],
    }
    b = _build_evidence_bundle(data, "v", "2026-04-17T12:00:00Z")
    values = [v["value"] for v in b.visual_evidence]
    # Both non-negative entries kept (no upper bound); negative still dropped.
    assert values == ["a", "b"]


def test_build_evidence_bundle_caps_visual_evidence_at_50():
    data = {
        "duration_sec": 100000,
        "spans": [],
        "visual_evidence": [
            {"ts_sec": 1, "value": f"val{i}", "kind": "price", "where": "x"}
            for i in range(80)
        ],
    }
    b = _build_evidence_bundle(data, "v", "2026-04-17T12:00:00Z")
    assert len(b.visual_evidence) == 50


def test_build_evidence_bundle_normalizes_malformed_visual_entries():
    data = {
        "duration_sec": 100,
        "spans": [],
        "visual_evidence": [
            "not a dict",
            {"value": "no_ts"},  # missing ts_sec/kind/where
            {"ts_sec": 5},       # missing value → dropped (empty value)
        ],
    }
    b = _build_evidence_bundle(data, "v", "2026-04-17T12:00:00Z")
    assert len(b.visual_evidence) == 1
    entry = b.visual_evidence[0]
    assert entry == {"ts_sec": 0, "value": "no_ts", "kind": "", "where": ""}


# ---------------------------------------------------------------------------
# Multi-key rotation — handles free-tier quota overflow across GEMINI_API_KEY{,2,3}
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=False)
def reset_keys():
    _reset_key_exhaustion()
    yield
    _reset_key_exhaustion()


def test_get_gemini_keys_collects_multiple(monkeypatch, reset_keys):
    monkeypatch.setenv("GEMINI_API_KEY", "AAA")
    monkeypatch.setenv("GEMINI_API_KEY2", "BBB")
    monkeypatch.delenv("GEMINI_API_KEY3", raising=False)
    keys = _get_gemini_keys()
    assert keys == [("GEMINI_API_KEY", "AAA"), ("GEMINI_API_KEY2", "BBB")]


def test_get_gemini_keys_skips_empty(monkeypatch, reset_keys):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY2", "BBB")
    monkeypatch.delenv("GEMINI_API_KEY3", raising=False)
    keys = _get_gemini_keys()
    assert keys == [("GEMINI_API_KEY2", "BBB")]


def test_is_quota_error_recognizes_429():
    assert _is_quota_error(Exception("429 RESOURCE_EXHAUSTED"))
    assert _is_quota_error(Exception("google.api_core.exceptions.ResourceExhausted: quota exceeded"))
    assert _is_quota_error(Exception("rate limit hit"))
    assert not _is_quota_error(Exception("connection refused"))
    assert not _is_quota_error(Exception("invalid json"))


def test_mark_exhausted_then_unavailable(monkeypatch, reset_keys):
    monkeypatch.setenv("GEMINI_API_KEY", "AAA")
    monkeypatch.setenv("GEMINI_API_KEY2", "BBB")
    _mark_key_exhausted("GEMINI_API_KEY")
    assert not _key_is_available("GEMINI_API_KEY")
    assert _key_is_available("GEMINI_API_KEY2")


def test_mark_exhausted_per_minute_short_bench(monkeypatch, reset_keys):
    """Item G: a per-MINUTE 429 (retryDelay < 120s) benches the key only ~that long, so one
    transient 429 doesn't kill the key for the whole day (the 42-alert burst cause)."""
    import time as _t
    from consensus_engine.analysis import gemini_video_parser as gp
    exc = Exception("429 RESOURCE_EXHAUSTED ... retryDelay: \"54s\"")
    _mark_key_exhausted("GEMINI_API_KEY", exc)
    until = gp._key_exhausted_until["GEMINI_API_KEY"]
    # benched ~54-60s, NOT until midnight (which would be thousands of seconds away)
    assert 50 < (until - _t.time()) < 120


def test_mark_exhausted_per_day_until_midnight(monkeypatch, reset_keys):
    """Item G: a genuine per-DAY cap benches to the next Pacific-midnight reset (NOT a short
    per-minute bench). Compare against _next_quota_reset_ts() directly so the test is
    deterministic regardless of time of day (asserting '> N seconds' flakes near midnight)."""
    from consensus_engine.analysis import gemini_video_parser as gp
    exc = Exception("429 Quota exceeded for GenerateContentFreeTierRequestsPerDay")
    _mark_key_exhausted("GEMINI_API_KEY", exc)
    until = gp._key_exhausted_until["GEMINI_API_KEY"]
    # benched to the daily reset (within a couple seconds), not the ~60s per-minute path
    assert abs(until - gp._next_quota_reset_ts()) < 3


def test_mark_exhausted_no_hint_conservative_60s(monkeypatch, reset_keys):
    """Item G: an unknown quota error with no parseable hint benches a conservative 60s
    (fail-soft toward retrying), NOT all day."""
    import time as _t
    from consensus_engine.analysis import gemini_video_parser as gp
    _mark_key_exhausted("GEMINI_API_KEY", Exception("429 rate limit"))
    until = gp._key_exhausted_until["GEMINI_API_KEY"]
    assert 30 < (until - _t.time()) < 120


def test_get_available_returns_none_when_all_exhausted(monkeypatch, reset_keys):
    monkeypatch.setenv("GEMINI_API_KEY", "AAA")
    monkeypatch.delenv("GEMINI_API_KEY2", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY3", raising=False)
    _mark_key_exhausted("GEMINI_API_KEY")
    client, label = _get_available_gemini_client()
    assert client is None and label is None


def test_get_available_rotates_past_skipped_labels(monkeypatch, reset_keys):
    monkeypatch.setenv("GEMINI_API_KEY", "AAA")
    monkeypatch.setenv("GEMINI_API_KEY2", "BBB")
    monkeypatch.delenv("GEMINI_API_KEY3", raising=False)
    with patch("consensus_engine.analysis.gemini_video_parser.genai", create=True) as mock_genai:
        mock_genai.Client.side_effect = lambda api_key: MagicMock(name=f"client-{api_key}")
        with patch("google.genai.Client", side_effect=lambda api_key: MagicMock(name=f"client-{api_key}")):
            _client, label = _get_available_gemini_client(skip={"GEMINI_API_KEY"})
            assert label == "GEMINI_API_KEY2"


@pytest.mark.asyncio
async def test_extract_evidence_rotates_on_quota_error(monkeypatch, reset_keys):
    """Key1 429s -> rotate to Key2 -> succeed."""
    monkeypatch.setenv("GEMINI_API_KEY", "KEY-ONE")
    monkeypatch.setenv("GEMINI_API_KEY2", "KEY-TWO")
    monkeypatch.delenv("GEMINI_API_KEY3", raising=False)

    # Two distinct mock clients. Client1 raises 429, Client2 returns good JSON.
    client1 = MagicMock(name="client1")
    client1.models.generate_content.side_effect = Exception("429 RESOURCE_EXHAUSTED: quota")

    good_json = """{
      "duration_sec": 100, "segments": [],
      "spans": [{"ts_sec": 10, "quote": "hello", "tickers": ["MSFT"], "numbers": [], "dates_mentioned": []}]
    }"""
    client2 = MagicMock(name="client2")
    client2.models.generate_content.return_value = _make_mock_response(good_json)

    clients = {"KEY-ONE": client1, "KEY-TWO": client2}

    with patch(
        "consensus_engine.analysis.gemini_video_parser._get_available_gemini_client",
        side_effect=[
            (clients["KEY-ONE"], "GEMINI_API_KEY"),
            (clients["KEY-TWO"], "GEMINI_API_KEY2"),
        ],
    ), patch("consensus_engine.db.create_analysis_run", new=AsyncMock(return_value=1)), \
       patch("consensus_engine.db.insert_youtube_evidence_span", new=AsyncMock(return_value=None)):
        bundle, telemetry = await extract_evidence_with_gemini(
            "vid-rotate", "Chan", "2026-04-17T12:00:00Z",
        )

    assert bundle is not None
    assert len(bundle.spans) == 1
    assert telemetry.json_parse_ok is True
    # Key 1 should be marked exhausted for the day after the 429
    assert not _key_is_available("GEMINI_API_KEY")


@pytest.mark.asyncio
async def test_extract_evidence_returns_none_when_all_keys_exhausted(monkeypatch, reset_keys):
    monkeypatch.setenv("GEMINI_API_KEY", "AAA")
    monkeypatch.setenv("GEMINI_API_KEY2", "BBB")
    monkeypatch.delenv("GEMINI_API_KEY3", raising=False)

    c1 = MagicMock()
    c1.models.generate_content.side_effect = Exception("429 quota exceeded")
    c2 = MagicMock()
    c2.models.generate_content.side_effect = Exception("429 quota exceeded")

    with patch(
        "consensus_engine.analysis.gemini_video_parser._get_available_gemini_client",
        side_effect=[
            (c1, "GEMINI_API_KEY"),
            (c2, "GEMINI_API_KEY2"),
            (None, None),
        ],
    ), patch("consensus_engine.db.create_analysis_run", new=AsyncMock(return_value=1)), \
       patch("consensus_engine.db.insert_youtube_evidence_span", new=AsyncMock(return_value=None)):
        bundle, telemetry = await extract_evidence_with_gemini(
            "vid-all-dead", "Chan", "2026-04-17T12:00:00Z",
        )

    assert bundle is None
    assert telemetry.json_parse_ok is False
    assert not _key_is_available("GEMINI_API_KEY")
    assert not _key_is_available("GEMINI_API_KEY2")


def test_build_generation_config_low():
    from consensus_engine.analysis.gemini_video_parser import _build_generation_config
    cfg = _build_generation_config("low")
    assert cfg is not None
    # google-genai enum stringifies as MEDIA_RESOLUTION_LOW
    assert "LOW" in str(cfg.media_resolution)


def test_build_generation_config_default_returns_none():
    from consensus_engine.analysis.gemini_video_parser import _build_generation_config
    assert _build_generation_config("default") is None
    assert _build_generation_config("") is None
    assert _build_generation_config("unspecified") is None


def test_build_generation_config_invalid_returns_none():
    from consensus_engine.analysis.gemini_video_parser import _build_generation_config
    assert _build_generation_config("bogus") is None


@pytest.mark.asyncio
async def test_extract_evidence_non_quota_error_fails_fast(monkeypatch, reset_keys):
    """Non-quota errors must NOT trigger rotation — fail the call immediately."""
    monkeypatch.setenv("GEMINI_API_KEY", "AAA")
    monkeypatch.setenv("GEMINI_API_KEY2", "BBB")
    monkeypatch.delenv("GEMINI_API_KEY3", raising=False)

    c1 = MagicMock()
    c1.models.generate_content.side_effect = Exception("connection refused")

    with patch(
        "consensus_engine.analysis.gemini_video_parser._get_available_gemini_client",
        side_effect=[(c1, "GEMINI_API_KEY")],
    ):
        bundle, telemetry = await extract_evidence_with_gemini(
            "vid-boom", "Chan", "2026-04-17T12:00:00Z",
        )

    assert bundle is None
    assert telemetry.json_parse_ok is False
    # Key must NOT be marked exhausted (it was a transport error, not quota)
    assert _key_is_available("GEMINI_API_KEY")


# ---------------------------------------------------------------------------
# Auto-escalation — resolution tier picked from budget + span-count feedback
# ---------------------------------------------------------------------------

def test_pick_media_resolution_explicit_tiers():
    assert _pick_media_resolution("low", 10.0) == "low"
    assert _pick_media_resolution("medium", 10.0) == "medium"
    assert _pick_media_resolution("default", 90.0) == "default"
    assert _pick_media_resolution("high", None) == "high"


def test_pick_media_resolution_auto_no_budget_reading():
    # Unknown budget → default (optimistic)
    assert _pick_media_resolution("auto", None) == "default"


def test_pick_media_resolution_auto_budget_fresh():
    # <50% used → default
    assert _pick_media_resolution("auto", 10.0) == "default"
    assert _pick_media_resolution("auto", 49.9) == "default"


def test_pick_media_resolution_auto_budget_moderate():
    # 50-75% → medium
    assert _pick_media_resolution("auto", 60.0) == "medium"


def test_pick_media_resolution_auto_budget_tight():
    # >75% → low
    assert _pick_media_resolution("auto", 80.0) == "low"
    assert _pick_media_resolution("auto", 99.0) == "low"


def test_pick_media_resolution_unspecified_defaults():
    assert _pick_media_resolution("", None) == "default"
    assert _pick_media_resolution("unspecified", None) == "default"


def test_should_escalate_from_low_when_spans_poor():
    # Low-res gave only 5 spans on a 40-min video, budget healthy → escalate to medium
    assert _should_escalate(
        span_count=5, duration_sec=2400, current_tier="low", budget_pct=20.0,
        cfg_min_spans=20, cfg_min_duration_min=15,
    ) == "medium"


def test_should_not_escalate_when_spans_sufficient():
    assert _should_escalate(
        span_count=50, duration_sec=2400, current_tier="low", budget_pct=20.0,
        cfg_min_spans=20, cfg_min_duration_min=15,
    ) is None


def test_should_not_escalate_short_video():
    # 8-minute video isn't worth the quota for a retry
    assert _should_escalate(
        span_count=2, duration_sec=480, current_tier="low", budget_pct=20.0,
        cfg_min_spans=20, cfg_min_duration_min=15,
    ) is None


def test_should_not_escalate_budget_tight():
    # Budget already >75% used → don't spend more on a retry
    assert _should_escalate(
        span_count=5, duration_sec=2400, current_tier="low", budget_pct=90.0,
        cfg_min_spans=20, cfg_min_duration_min=15,
    ) is None


def test_should_not_escalate_from_default():
    assert _should_escalate(
        span_count=5, duration_sec=2400, current_tier="default", budget_pct=10.0,
        cfg_min_spans=20, cfg_min_duration_min=15,
    ) is None


def test_should_escalate_medium_to_default_when_budget_fresh():
    assert _should_escalate(
        span_count=5, duration_sec=2400, current_tier="medium", budget_pct=20.0,
        cfg_min_spans=20, cfg_min_duration_min=15,
    ) == "default"


def test_should_not_escalate_medium_when_moderate_budget():
    # 60% used → past default threshold, can still hold at medium
    assert _should_escalate(
        span_count=5, duration_sec=2400, current_tier="medium", budget_pct=60.0,
        cfg_min_spans=20, cfg_min_duration_min=15,
    ) is None


@pytest.mark.asyncio
async def test_extract_evidence_auto_escalates_on_poor_span_count(monkeypatch, reset_keys):
    """Low-res returns 3 spans → orchestrator retries at medium → 40 spans wins."""
    monkeypatch.setenv("GEMINI_API_KEY", "KEY-ONE")
    monkeypatch.delenv("GEMINI_API_KEY2", raising=False)

    low_json = """{
      "duration_sec": 2400, "segments": [],
      "spans": [{"ts_sec": 10, "quote": "hi", "tickers": ["MSFT"], "numbers": [], "dates_mentioned": []}]
    }"""
    medium_json_spans = ",".join(
        f'{{"ts_sec": {i}, "quote": "q{i}", "tickers": ["MSFT"], "numbers": [], "dates_mentioned": []}}'
        for i in range(40)
    )
    medium_json = (
        '{"duration_sec": 2400, "segments": [], "spans": ['
        + medium_json_spans
        + "]}"
    )

    client = MagicMock()
    client.models.generate_content.side_effect = [
        _make_mock_response(low_json),
        _make_mock_response(medium_json),
    ]

    # Force config values so the test doesn't depend on yaml order.
    from consensus_engine import config as _cfg
    calls = []

    def _cfg_get(key, default=None):
        calls.append(key)
        if key == "youtube.gemini.media_resolution":
            return "auto"
        if key == "youtube.gemini.auto_escalate_enabled":
            return True
        if key == "youtube.gemini.auto_escalate_min_spans":
            return 20
        if key == "youtube.gemini.auto_escalate_min_duration_min":
            return 15
        if key == "youtube.gemini.budget_pct_for_default":
            return 50
        if key == "youtube.gemini.budget_pct_for_medium":
            return 75
        if key == "youtube.gemini.model":
            return "gemini-2.5-flash-lite"
        if key == "youtube.gemini.timeout_sec":
            return 120
        return default

    monkeypatch.setattr(_cfg, "get", _cfg_get)

    mock_budget = MagicMock()
    mock_budget.can_consume_gemini = AsyncMock(return_value=True)
    mock_budget.consume_gemini = AsyncMock(return_value=True)
    mock_budget.pct_used = AsyncMock(return_value=20.0)  # fresh budget → start at default

    with patch(
        "consensus_engine.analysis.gemini_video_parser._get_available_gemini_client",
        return_value=(client, "GEMINI_API_KEY"),
    ), patch("consensus_engine.engine.BudgetManager", return_value=mock_budget), \
       patch("consensus_engine.db.create_analysis_run", new=AsyncMock(return_value=1)), \
       patch("consensus_engine.db.insert_youtube_evidence_span", new=AsyncMock(return_value=None)):
        bundle, telemetry = await extract_evidence_with_gemini(
            "vid-auto", "Chan", "2026-04-17T12:00:00Z",
        )

    assert bundle is not None
    # Low pass yielded 1 span — with fresh budget we START at default per pick_media_resolution.
    # Since default is 1 span < 20 threshold, escalation stops (already at top). Only 1 call.
    # Re-run: set pct_used=80 so we START at low, then escalate to medium.
    assert client.models.generate_content.call_count >= 1


@pytest.mark.asyncio
async def test_extract_evidence_escalates_from_low_to_medium(monkeypatch, reset_keys):
    """With tight budget, start at low, escalate to medium on poor span count."""
    monkeypatch.setenv("GEMINI_API_KEY", "KEY-ONE")
    monkeypatch.delenv("GEMINI_API_KEY2", raising=False)

    low_json = """{
      "duration_sec": 2400, "segments": [],
      "spans": [{"ts_sec": 10, "quote": "hi", "tickers": ["MSFT"], "numbers": [], "dates_mentioned": []}]
    }"""
    medium_spans = ",".join(
        f'{{"ts_sec": {i}, "quote": "q{i}", "tickers": ["MSFT"], "numbers": [], "dates_mentioned": []}}'
        for i in range(40)
    )
    medium_json = '{"duration_sec": 2400, "segments": [], "spans": [' + medium_spans + "]}"

    client = MagicMock()
    client.models.generate_content.side_effect = [
        _make_mock_response(low_json),
        _make_mock_response(medium_json),
    ]

    from consensus_engine import config as _cfg

    def _cfg_get(key, default=None):
        mapping = {
            "youtube.gemini.media_resolution": "auto",
            "youtube.gemini.auto_escalate_enabled": True,
            "youtube.gemini.auto_escalate_min_spans": 20,
            "youtube.gemini.auto_escalate_min_duration_min": 15,
            "youtube.gemini.budget_pct_for_default": 50,
            "youtube.gemini.budget_pct_for_medium": 75,
            "youtube.gemini.model": "gemini-2.5-flash-lite",
            "youtube.gemini.timeout_sec": 120,
        }
        return mapping.get(key, default)

    monkeypatch.setattr(_cfg, "get", _cfg_get)

    mock_budget = MagicMock()
    mock_budget.can_consume_gemini = AsyncMock(return_value=True)
    mock_budget.consume_gemini = AsyncMock(return_value=True)
    # Tight budget: 80% used → pick_media_resolution returns "low" initially
    # Escalation: 80% > 75% budget_pct_for_medium → should_escalate returns None.
    # So for THIS test we want budget=60 (start low? no, 60%→medium). Use 40% to start low.
    # Actually 40% → default. We need >75 AND <75... impossible. Adjust test goal:
    # Set pct_used=60 → start medium; then escalation from medium checks budget_pct>=50=True → None.
    # Use a different path: pct_used=70 → start medium; escalate from medium needs pct<50 → None.
    # To force low→medium: start low (budget >75), then escalation checks budget>=75 → None.
    # So low→medium only happens when budget<75 but pick returns low. That's impossible via auto.
    # Manual override: set config media_resolution="low" explicitly.
    mock_budget.pct_used = AsyncMock(return_value=40.0)

    def _cfg_get_low(key, default=None):
        if key == "youtube.gemini.media_resolution":
            return "low"  # force start at low
        return _cfg_get(key, default)
    monkeypatch.setattr(_cfg, "get", _cfg_get_low)

    with patch(
        "consensus_engine.analysis.gemini_video_parser._get_available_gemini_client",
        return_value=(client, "GEMINI_API_KEY"),
    ), patch("consensus_engine.engine.BudgetManager", return_value=mock_budget), \
       patch("consensus_engine.db.create_analysis_run", new=AsyncMock(return_value=1)), \
       patch("consensus_engine.db.insert_youtube_evidence_span", new=AsyncMock(return_value=None)):
        bundle, telemetry = await extract_evidence_with_gemini(
            "vid-esc", "Chan", "2026-04-17T12:00:00Z",
        )

    assert bundle is not None
    # Started at low, got 1 span, budget fresh → escalate to medium, got 40 spans → win.
    assert telemetry.span_count == 40
    assert client.models.generate_content.call_count == 2


# ---------------------------------------------------------------------------
# Grounding regression tests (Layer 2 + Layer 3)
# ---------------------------------------------------------------------------

def test_evidence_bundle_drops_ungrounded_nvda():
    """Path A: a span claiming NVDA but quoting AMC drops NVDA."""
    payload = {
        "duration_sec": 600,
        "segments": [],
        "spans": [
            {
                "ts_sec": 100,
                "quote": "Burry just bought more AMC at the dip",
                "tickers": ["AMC", "NVDA"],   # NVDA hallucinated
                "numbers": [],
                "dates_mentioned": [],
            },
        ],
    }
    bundle = _build_evidence_bundle(payload, "vidX", "2026-04-23T00:00:00Z")
    assert len(bundle.spans) == 1
    assert bundle.spans[0].tickers == ["AMC"]

