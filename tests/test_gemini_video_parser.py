"""Tests for Gemini fast-path video parser."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from consensus_engine.analysis.gemini_video_parser import (
    parse_video_with_gemini,
    extract_evidence_with_gemini,
    _parse_ts_str,
    _build_evidence_bundle,
    _get_gemini_keys,
    _get_available_gemini_client,
    _is_quota_error,
    _mark_key_exhausted,
    _reset_key_exhaustion,
    _key_is_available,
)
from consensus_engine.models import (
    ParsedVideo, Conviction,
    EvidenceBundle, EvidenceSpan, RunTelemetry,
)


# ---------------------------------------------------------------------------
# Legacy single-call parser (kept unchanged as P6 fallback)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_parse_video_with_gemini_returns_parsed_video():
    fake_json = """{
      "tickers": [{"symbol": "NVDA", "direction": "long", "conviction": "high", "mention_count": 3, "context": "breakout above 850"}],
      "price_levels": [{"ticker": "NVDA", "type": "support", "price": 820.0, "context": "key support annotated on chart"}],
      "macro_thesis": {"direction": "bullish", "themes": ["tech rally"], "timeframe": "short", "summary": "Markets rallying."},
      "options": [],
      "setups": [{"ticker": "NVDA", "entry_low": 850.0, "entry_high": 855.0, "stop": 820.0, "targets": [920.0], "timeframe": "swing", "setup_type": "breakout", "context": "buy NVDA at 850"}],
      "overall_conviction": "high"
    }"""

    mock_response = MagicMock()
    mock_response.text = fake_json

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("consensus_engine.analysis.gemini_video_parser._get_available_gemini_client", return_value=(mock_client, "GEMINI_API_KEY")), \
         patch("consensus_engine.db.create_analysis_run", new=AsyncMock(return_value=5)):
        result = await parse_video_with_gemini("dQw4w9WgXcQ", "ClickCapital", "2026-04-22T10:00:00Z")

    assert isinstance(result, ParsedVideo)
    assert result.run_id == 5
    assert any(t["symbol"] == "NVDA" for t in result.tickers)
    assert result.overall_conviction == Conviction.HIGH
    assert len(result.setups) == 1
    assert result.setups[0].ticker == "NVDA"
    assert len(result.price_levels) == 1


@pytest.mark.asyncio
async def test_parse_video_with_gemini_returns_none_on_api_error():
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception("API error")

    with patch("consensus_engine.analysis.gemini_video_parser._get_available_gemini_client", return_value=(mock_client, "GEMINI_API_KEY")):
        result = await parse_video_with_gemini("dQw4w9WgXcQ", "Chan", "2026-04-22T10:00:00Z")

    assert result is None


@pytest.mark.asyncio
async def test_parse_video_with_gemini_returns_none_when_no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with patch("consensus_engine.analysis.gemini_video_parser._get_available_gemini_client", return_value=(None, None)):
        result = await parse_video_with_gemini("dQw4w9WgXcQ", "Chan", "2026-04-22T10:00:00Z")

    assert result is None


@pytest.mark.asyncio
async def test_parse_video_with_gemini_handles_bad_json():
    mock_response = MagicMock()
    mock_response.text = "Sorry, I cannot process this video."

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("consensus_engine.analysis.gemini_video_parser._get_available_gemini_client", return_value=(mock_client, "GEMINI_API_KEY")), \
         patch("consensus_engine.db.create_analysis_run", new=AsyncMock(return_value=6)):
        result = await parse_video_with_gemini("dQw4w9WgXcQ", "Chan", "2026-04-22T10:00:00Z")

    # Bad JSON → returns None (caller will fall back to transcript pipeline)
    assert result is None


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
    {"ts_sec": 2142, "quote": "the 8 EMA is currently coming in at 400.15", "tickers": ["MSFT"], "numbers": [400.15], "dates_mentioned": []},
    {"ts_sec": 2172, "quote": "Bullish bias into April 29th earnings with an entry target at 400.15", "tickers": ["MSFT"], "numbers": [400.15], "dates_mentioned": ["April 29"]}
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
        {"ts_sec": 10, "quote": "EMA holding at 400", "tickers": ["EMA","MSFT"], "numbers": [400], "dates_mentioned": []},
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
            {"ts_sec": 3, "quote": "real quote", "tickers": ["spy"], "numbers": [], "dates_mentioned": []},
        ],
    }
    b = _build_evidence_bundle(data, "v", "2026-04-17T12:00:00Z")
    assert len(b.spans) == 1
    assert b.spans[0].tickers == ["SPY"]


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
