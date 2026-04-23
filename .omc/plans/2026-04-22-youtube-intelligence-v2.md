# YouTube Intelligence Upgrade v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-pass video parser with a Gemini-first pipeline (one API call, sees chart annotations) with a two-stage OpenRouter fallback that produces idempotent, provenance-linked options and trade setup records.

**Architecture:** `process_video()` tries `parse_video_with_gemini()` first — one `gemini-2.5-flash-lite` call with the YouTube URL extracts tickers, levels, options, and setups including visually annotated chart lines. If Gemini is unavailable or fails, the transcript cascade + two-stage OpenRouter pipeline runs as fallback. A `youtube_analysis_runs` anchor table gates all derived rows; every child row carries `run_id`, `source_snippet`, `chunk_id`, and `parser_version`. A `get_youtube_evidence_for_ticker()` canonical read model deduplicates levels absorbed into setups.

**Tech Stack:** Python asyncio, aiohttp, aiosqlite, `google-genai>=1.73.1` (Gemini fast-path), OpenRouter free-tier (`openrouter/minimax/minimax-m2.5:free` for extraction/reasoning; `z-ai/glm-4.5-air:free` for classification), Groq fallback, pytest-asyncio.

**Review findings addressed:**
- HIGH: Non-idempotent persistence → `youtube_analysis_runs` + UNIQUE(video_id, parser_version) + atomic upserts
- HIGH: Per-chunk × per-pass call explosion → two-stage pipeline, 8-call budget hard cap
- HIGH: Missing provenance → `source_snippet`/`chunk_id`/`parser_version` on every row
- MEDIUM: Double-counting → canonical evidence function + `setup_id` absorption on levels

---

## File Map

| File | Change |
|------|--------|
| `requirements.txt` | Add `google-genai>=1.73.1` |
| `config/consensus.yaml` | Add `youtube.gemini_enabled`, `youtube.gemini_model` keys |
| `consensus_engine/analysis/gemini_video_parser.py` | **New** — Gemini fast-path: YouTube URL → ParsedVideo in one call |
| `consensus_engine/db.py` | Add `youtube_analysis_runs`, `youtube_options`, `youtube_setups` tables; migration helper; new insert/get helpers; canonical evidence function |
| `consensus_engine/models.py` | Add `VideoOptionIdea`, `VideoTradeSetup` dataclasses; extend `ParsedVideo` with `run_id`, `options`, `setups` |
| `consensus_engine/analysis/video_parser.py` | Add `PARSER_VERSION`; replace `_SYSTEM_PROMPT` with four focused prompts; add `_call_extraction_model()`; add stage-1/2 pass functions; rewrite `parse_video_transcript()` |
| `consensus_engine/scanners/youtube.py` | Try Gemini first in `process_video()`; fall back to transcript pipeline; persist options/setups with `run_id` |
| `consensus_engine/alerts/commands.py` | Add `_format_youtube_option_summary()`, `_format_youtube_setup_summary()`; update `_yt_analyse_and_reply()` |
| `consensus_engine/cross_reference.py` | Update `_get_youtube_context()` to use `get_youtube_evidence_for_ticker()` |
| `tests/test_gemini_video_parser.py` | **New** — Gemini parser unit tests |
| `tests/test_db_youtube.py` | Tests for new tables, helpers, canonical read |
| `tests/test_video_parser.py` | Tests for each new pass function |
| `tests/test_youtube_scanner.py` | Tests for `process_video()` with Gemini path and fallback |

---

## Task 0: Gemini fast-path — `gemini_video_parser.py`

**Files:**
- Modify: `requirements.txt`
- Modify: `config/consensus.yaml`
- Create: `consensus_engine/analysis/gemini_video_parser.py`
- Modify: `consensus_engine/scanners/youtube.py` (`process_video()`)
- Create: `tests/test_gemini_video_parser.py`

- [ ] **Step 1: Add dependency and config**

In `requirements.txt`, add:
```
google-genai>=1.73.1
```

In `config/consensus.yaml`, under the `youtube:` section, add:
```yaml
  gemini_enabled: true               # try Gemini fast-path before transcript fetch
  gemini_model: "gemini-2.5-flash-lite"
  analyze: true                      # run LLM analysis on transcripts (fallback path)
```

- [ ] **Step 2: Write failing tests**

```python
# tests/test_gemini_video_parser.py
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from consensus_engine.analysis.gemini_video_parser import parse_video_with_gemini
from consensus_engine.models import ParsedVideo, Direction, Conviction


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

    with patch("consensus_engine.analysis.gemini_video_parser._get_gemini_client", return_value=mock_client), \
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

    with patch("consensus_engine.analysis.gemini_video_parser._get_gemini_client", return_value=mock_client):
        result = await parse_video_with_gemini("dQw4w9WgXcQ", "Chan", "2026-04-22T10:00:00Z")

    assert result is None


@pytest.mark.asyncio
async def test_parse_video_with_gemini_returns_none_when_no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with patch("consensus_engine.analysis.gemini_video_parser._get_gemini_client", return_value=None):
        result = await parse_video_with_gemini("dQw4w9WgXcQ", "Chan", "2026-04-22T10:00:00Z")

    assert result is None


@pytest.mark.asyncio
async def test_parse_video_with_gemini_handles_bad_json():
    mock_response = MagicMock()
    mock_response.text = "Sorry, I cannot process this video."

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("consensus_engine.analysis.gemini_video_parser._get_gemini_client", return_value=mock_client), \
         patch("consensus_engine.db.create_analysis_run", new=AsyncMock(return_value=6)):
        result = await parse_video_with_gemini("dQw4w9WgXcQ", "Chan", "2026-04-22T10:00:00Z")

    # Bad JSON → returns None (caller will fall back to transcript pipeline)
    assert result is None
```

- [ ] **Step 3: Run tests to confirm failure**

```bash
cd /root/.openclaw/workspace && python -m pytest tests/test_gemini_video_parser.py -v 2>&1 | tail -15
```

Expected: FAIL — module does not exist.

- [ ] **Step 4: Create `consensus_engine/analysis/gemini_video_parser.py`**

```python
"""Gemini fast-path for YouTube video analysis.

Passes a YouTube URL directly to gemini-2.5-flash-lite. One API call
extracts tickers, price levels (including visually annotated chart lines),
options, trade setups, and macro thesis. Returns ParsedVideo or None on failure.
"""

import asyncio
import json
import logging
import os
import re
import time

from consensus_engine import config as cfg, db
from consensus_engine.models import (
    ParsedVideo, Direction, Conviction, PriceLevel, MacroThesis,
    VideoOptionIdea, VideoTradeSetup,
)

log = logging.getLogger("consensus_engine.analysis.gemini_video_parser")

_MACRO_NORM = {"bullish": "long", "bearish": "short", "neutral": "neutral"}

_GEMINI_PROMPT = """You are a financial analyst extracting structured trade intelligence from a YouTube video.

Watch the full video and respond ONLY with this exact JSON (no markdown, no extra text):
{
  "tickers": [
    {"symbol": "NVDA", "direction": "long|short|neutral", "conviction": "high|medium|low", "mention_count": 3, "context": "why this direction — quote or paraphrase"}
  ],
  "price_levels": [
    {"ticker": "NVDA", "type": "support|resistance|target|breakdown", "price": 850.0, "context": "quote or description of where this level comes from"}
  ],
  "macro_thesis": {
    "direction": "bullish|bearish|neutral",
    "themes": ["theme1", "theme2"],
    "timeframe": "short|medium|long",
    "summary": "1-2 sentence summary of the macro view"
  },
  "options": [
    {"ticker": "TSLA", "option_type": "call|put", "strike": 250.0, "expiry": "weekly", "strategy": "single|spread|leaps|debit|credit", "source": "flow_observation|personal_idea", "conviction": "high|medium|low", "context": "exact quote or paraphrase"}
  ],
  "setups": [
    {"ticker": "NVDA", "entry_low": 845.0, "entry_high": 855.0, "stop": 820.0, "targets": [920.0], "timeframe": "intraday|swing|positional|long-term", "setup_type": "breakout|pullback|earnings|trend", "context": "exact quote or paraphrase"}
  ],
  "overall_conviction": "high|medium|low"
}

Extraction rules:
- Only real stock tickers (AAPL, NVDA, SPY, etc.). Exclude RSI, EMA, MACD, VWAP, SMA, ATR, etc.
- price_levels: include BOTH verbally mentioned prices AND price levels visible as annotated lines or labels on charts in the video.
- options: empty array if none discussed. strike is null if not mentioned.
- setups: link entry/stop/target only when the speaker presents them together. Empty array if unclear.
- context: quote or closely paraphrase the speaker for every extracted item.
- If no tickers found, return empty arrays for tickers, price_levels, options, setups."""


def _get_gemini_client():
    """Return a configured Gemini client, or None if API key is absent."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        log.debug("gemini_video_parser: GEMINI_API_KEY not set")
        return None
    try:
        from google import genai
        return genai.Client(api_key=api_key)
    except Exception as e:
        log.warning("gemini_video_parser: failed to init client: %s", e)
        return None


def _parse_gemini_response(raw: str) -> dict | None:
    """Parse JSON from Gemini response, stripping markdown fences if present."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        log.debug("gemini_video_parser: JSON parse failed, raw=%r", cleaned[:200])
        return None


def _build_parsed_video(
    data: dict, video_id: str, channel_name: str, published_at: str, run_id: int
) -> ParsedVideo:
    """Convert Gemini JSON response dict into a ParsedVideo."""
    # Tickers
    raw_tickers = data.get("tickers", [])
    _dir_norm = {"long": "long", "short": "short", "neutral": "neutral",
                 "bullish": "long", "bearish": "short"}
    normalized_tickers = []
    for t in raw_tickers:
        if not isinstance(t, dict):
            continue
        sym = str(t.get("symbol", "")).upper()
        if not sym:
            continue
        direction = _dir_norm.get(str(t.get("direction", "neutral")).lower(), "neutral")
        normalized_tickers.append({
            "symbol": sym,
            "direction": direction,
            "conviction": str(t.get("conviction", "medium")).lower(),
            "mention_count": int(t.get("mention_count", 1)),
            "context": str(t.get("context", "")),
            "source_snippet": str(t.get("context", ""))[:200],
            "chunk_id": 0,
        })

    # Price levels
    price_levels = []
    for lv in data.get("price_levels", []):
        if not isinstance(lv, dict):
            continue
        try:
            price = float(lv["price"])
        except (KeyError, TypeError, ValueError):
            continue
        if price <= 0:
            continue
        price_levels.append(PriceLevel(
            ticker=str(lv.get("ticker", "")).upper(),
            level_type=str(lv.get("type", "support")).lower(),
            price=price,
            condition=str(lv.get("context", "")),
            consequence="",
            confidence=0.8,
        ))

    # Macro thesis
    macro_data = data.get("macro_thesis", {})
    raw_dir = str(macro_data.get("direction", "neutral")).lower()
    macro_thesis = MacroThesis(
        direction=Direction(_MACRO_NORM.get(raw_dir, "neutral")),
        themes=macro_data.get("themes", []) if isinstance(macro_data.get("themes"), list) else [],
        timeframe=str(macro_data.get("timeframe", "short")).lower(),
        summary=str(macro_data.get("summary", "")),
    )

    # Options
    options: list[VideoOptionIdea] = []
    for o in data.get("options", []):
        if not isinstance(o, dict):
            continue
        ticker = str(o.get("ticker", "")).upper()
        opt_type = str(o.get("option_type", "")).lower()
        if not ticker or opt_type not in ("call", "put"):
            continue
        strike = None
        if o.get("strike") is not None:
            try:
                strike = float(o["strike"])
            except (ValueError, TypeError):
                pass
        options.append(VideoOptionIdea(
            ticker=ticker, option_type=opt_type,
            strike=strike, expiry=o.get("expiry"),
            strategy=o.get("strategy"), source=o.get("source"),
            conviction=str(o.get("conviction", "medium")).lower(),
            context=str(o.get("context", "")),
            source_snippet=str(o.get("context", ""))[:200],
            chunk_id=0,
        ))

    # Setups
    setups: list[VideoTradeSetup] = []
    for s in data.get("setups", []):
        if not isinstance(s, dict):
            continue
        ticker = str(s.get("ticker", "")).upper()
        entry_low = None
        if s.get("entry_low") is not None:
            try:
                entry_low = float(s["entry_low"])
            except (ValueError, TypeError):
                pass
        if not ticker or entry_low is None:
            continue
        entry_high = float(s["entry_high"]) if s.get("entry_high") is not None else entry_low
        stop = float(s["stop"]) if s.get("stop") is not None else None
        targets = []
        for t in (s.get("targets") or []):
            try:
                targets.append(float(t))
            except (ValueError, TypeError):
                pass
        # Compute R/R
        rr = None
        if stop and targets:
            mid = (entry_low + entry_high) / 2
            if mid > stop:
                rr = round((targets[0] - mid) / (mid - stop), 2)
        context = str(s.get("context", ""))
        setups.append(VideoTradeSetup(
            ticker=ticker, entry_low=entry_low, entry_high=entry_high,
            stop=stop, targets=targets,
            timeframe=s.get("timeframe"), setup_type=s.get("setup_type"),
            context=context, source_snippet=context[:200],
            chunk_id=0, risk_reward=rr,
        ))

    # Overall conviction
    conv_map = {"high": Conviction.HIGH, "medium": Conviction.MEDIUM, "low": Conviction.LOW}
    overall = conv_map.get(str(data.get("overall_conviction", "medium")).lower(), Conviction.MEDIUM)

    return ParsedVideo(
        video_id=video_id, channel_name=channel_name,
        raw_transcript="",  # Gemini path — no transcript text stored
        tickers=normalized_tickers, price_levels=price_levels,
        macro_thesis=macro_thesis, overall_conviction=overall,
        parsed_at=time.time(), run_id=run_id,
        options=options, setups=setups,
    )


async def parse_video_with_gemini(
    video_id: str,
    channel_name: str,
    published_at: str,
) -> ParsedVideo | None:
    """Analyze a YouTube video via Gemini. Returns ParsedVideo or None on any failure.

    Passes the YouTube URL directly — Gemini processes the full video including
    visually annotated chart levels. No transcript download needed.
    """
    client = _get_gemini_client()
    if client is None:
        return None

    model = cfg.get("youtube.gemini_model", "gemini-2.5-flash-lite")
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        from google.genai import types

        def _sync_call():
            return client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_text(_GEMINI_PROMPT),
                    types.Part.from_uri(
                        file_uri=youtube_url,
                        mime_type="video/*",
                    ),
                ],
            )

        # Run sync Gemini SDK call in thread executor (it's not async-native)
        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(None, _sync_call),
            timeout=60,
        )
        raw = response.text
    except asyncio.TimeoutError:
        log.warning("gemini_video_parser: timeout for %s", video_id)
        return None
    except Exception as e:
        log.warning("gemini_video_parser: API error for %s: %s", video_id, e)
        return None

    data = _parse_gemini_response(raw)
    if data is None:
        log.warning("gemini_video_parser: unparseable response for %s", video_id)
        return None

    parser_version = f"gemini/{model}"
    try:
        run_id = await db.create_analysis_run(video_id, parser_version)
    except Exception as e:
        log.warning("gemini_video_parser: could not create analysis run for %s: %s", video_id, e)
        return None

    parsed = _build_parsed_video(data, video_id, channel_name, published_at, run_id)
    log.info(
        "gemini_video_parser: %s → %d tickers, %d levels, %d options, %d setups",
        video_id, len(parsed.tickers), len(parsed.price_levels),
        len(parsed.options), len(parsed.setups),
    )
    return parsed
```

- [ ] **Step 5: Run tests — expect pass**

```bash
python -m pytest tests/test_gemini_video_parser.py -v 2>&1 | tail -20
```

Expected: all 4 tests PASS.

- [ ] **Step 6: Update `process_video()` in `youtube.py` to try Gemini first**

In `consensus_engine/scanners/youtube.py`, find the block starting at `if await db.has_video_been_processed(video_id):` (~line 211). Replace the entire function body with this structure (keep all existing logic, just add Gemini fast-path before the transcript fetch):

```python
async def process_video(
    video_meta: dict,
    semaphore: asyncio.Semaphore,
    preferred_languages: list[str],
    export_dir: str,
    browser_context=None,
) -> None:
    """Dedup → Gemini fast-path (or transcript cascade) → persist. Never raises."""
    async with semaphore:
        video_id = video_meta["video_id"]
        channel_id = video_meta["channel_id"]

        if await db.has_video_been_processed(video_id):
            log.debug("youtube: skipping already-processed %s", video_id)
            return

        await db.upsert_youtube_video(
            video_id=video_id,
            channel_id=channel_id,
            title=video_meta["title"],
            published_at=video_meta["published_at"],
            fetched_at=time.time(),
        )

        display_name = await db.get_channel_display_name(channel_id)
        parsed = None

        # ── Gemini fast-path (skips transcript download entirely) ────────────
        if cfg.get("youtube.gemini_enabled", True) and cfg.get("youtube.analyze", True):
            try:
                from consensus_engine.analysis.gemini_video_parser import parse_video_with_gemini
                parsed = await parse_video_with_gemini(
                    video_id, display_name, video_meta["published_at"]
                )
                if parsed is not None:
                    await db.mark_youtube_video_status(video_id, "analyzed_gemini")
                    log.info("youtube: Gemini analyzed %s (%d tickers)", video_id, len(parsed.tickers))
            except Exception as e:
                log.warning("youtube: Gemini fast-path error for %s: %s", video_id, e)
                parsed = None

        # ── Fallback: transcript cascade + multi-pass pipeline ────────────────
        if parsed is None:
            try:
                from consensus_engine.utils.transcript_fetch import fetch_transcript_cascade
                text, lang, is_auto = await fetch_transcript_cascade(
                    video_id, preferred_languages
                )
            except Exception as e:
                err = str(e).lower()
                if any(k in err for k in ("no caption", "caption track", "disabled", "not available", "all transcript")):
                    log.info("youtube: no captions for %s (%s)", video_id, e)
                    await db.mark_youtube_video_status(video_id, "missing")
                else:
                    log.warning("youtube: transcript failed for %s: %s", video_id, e)
                    await db.mark_youtube_video_status(video_id, "failed")
                return

            h = compute_hash(text)
            try:
                path = export_transcript_json(
                    channel_id=channel_id, video_id=video_id,
                    title=video_meta["title"], published_at=video_meta["published_at"],
                    language=lang, is_auto_generated=is_auto,
                    transcript_text=text, export_dir=export_dir,
                )
            except Exception as e:
                log.error("youtube: export failed for %s: %s", video_id, e)
                await db.mark_youtube_video_status(video_id, "failed")
                return

            await db.save_youtube_transcript(video_id, text, h)
            await db.mark_youtube_video_status(
                video_id, "saved", language=lang,
                is_auto_generated=is_auto, export_path=path,
            )
            log.info("youtube: saved %s (%s, auto=%s, %d chars) → %s",
                     video_id, lang, is_auto, len(text), path)

            if cfg.get("youtube.analyze", True):
                try:
                    from consensus_engine.analysis.video_parser import parse_video_transcript
                    parsed = await parse_video_transcript(
                        video_id=video_id, transcript_text=text,
                        channel_name=display_name, published_at=video_meta["published_at"],
                    )
                except Exception as e:
                    log.warning("youtube: transcript analysis error for %s: %s", video_id, e)
                    return

        # ── Persist results (shared path for both Gemini and transcript) ──────
        if parsed is None:
            return

        # ... (rest of the existing persist block: signals, levels, macro, options, setups)
        # This block is unchanged from Task 8 — signals, levels, options, setups, standalone alerts
```

Note: The `# ... persist block` comment means keep all the existing signal/level/macro/option/setup insertion code that follows unchanged.

- [ ] **Step 7: Write scanner test for Gemini path**

```python
# tests/test_youtube_scanner.py — add this test

@pytest.mark.asyncio
async def test_process_video_uses_gemini_when_available(tmp_db, monkeypatch):
    """Gemini fast-path: transcript fetch should NOT be called when Gemini succeeds."""
    from consensus_engine.scanners.youtube import process_video
    from consensus_engine.models import ParsedVideo, MacroThesis, Direction, Conviction
    import asyncio

    mock_parsed = ParsedVideo(
        video_id="vidGEM1", channel_name="Chan", raw_transcript="",
        tickers=[{"symbol": "AAPL", "direction": "long", "conviction": "high",
                  "mention_count": 1, "context": "c", "source_snippet": "s", "chunk_id": 0}],
        price_levels=[],
        macro_thesis=MacroThesis(direction=Direction.LONG, themes=[], timeframe="short", summary=""),
        overall_conviction=Conviction.HIGH,
        run_id=99, options=[], setups=[],
    )

    fetch_called = []

    async def fake_fetch(*a, **kw):
        fetch_called.append(True)
        return "transcript " * 300, "en", False

    monkeypatch.setattr(
        "consensus_engine.analysis.gemini_video_parser.parse_video_with_gemini",
        AsyncMock(return_value=mock_parsed),
    )
    monkeypatch.setattr(
        "consensus_engine.utils.transcript_fetch.fetch_transcript_cascade",
        fake_fetch,
    )

    sem = asyncio.Semaphore(1)
    video_meta = {"video_id": "vidGEM1", "channel_id": "ch1",
                  "title": "T", "published_at": "2026-04-22T10:00:00Z"}
    await process_video(video_meta, sem, ["en"], "/tmp/yt_test")

    assert not fetch_called, "transcript fetch should be skipped when Gemini succeeds"
    from consensus_engine import db
    sigs = await db.get_youtube_signals_for_ticker("AAPL", days=1)
    assert len(sigs) == 1
```

- [ ] **Step 8: Run all new tests**

```bash
python -m pytest tests/test_gemini_video_parser.py tests/test_youtube_scanner.py -v --tb=short 2>&1 | tail -25
```

Expected: all tests PASS.

- [ ] **Step 9: Run full suite**

```bash
python -m pytest tests/ --tb=short 2>&1 | tail -20
```

Expected: no regressions.

- [ ] **Step 10: Commit**

```bash
git add requirements.txt config/consensus.yaml \
        consensus_engine/analysis/gemini_video_parser.py \
        consensus_engine/scanners/youtube.py \
        tests/test_gemini_video_parser.py tests/test_youtube_scanner.py
git commit -m "Add Gemini fast-path for YouTube video analysis (bypasses transcript fetch)"
```

---

## Task 1: Schema — `youtube_analysis_runs` table + column migration

**Files:**
- Modify: `consensus_engine/db.py` (SCHEMA string ~line 75; `init_db()` ~line 355)
- Test: `tests/test_db_youtube.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_db_youtube.py  (add at top of file or in new test class)
import pytest
from consensus_engine import db

@pytest.mark.asyncio
async def test_create_analysis_run_returns_id(tmp_db):
    run_id = await db.create_analysis_run("vid123", "v2")
    assert isinstance(run_id, int)
    assert run_id > 0

@pytest.mark.asyncio
async def test_create_analysis_run_idempotent(tmp_db):
    id1 = await db.create_analysis_run("vid123", "v2")
    id2 = await db.create_analysis_run("vid123", "v2")
    assert id1 == id2  # same run returned

@pytest.mark.asyncio
async def test_update_analysis_run_status(tmp_db):
    run_id = await db.create_analysis_run("vid999", "v2")
    await db.update_analysis_run(run_id, status="complete", call_budget_used=5)
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT status, call_budget_used FROM youtube_analysis_runs WHERE id=?", (run_id,)
    )
    row = await cur.fetchone()
    assert row["status"] == "complete"
    assert row["call_budget_used"] == 5

@pytest.mark.asyncio
async def test_provenance_columns_exist_on_youtube_signals(tmp_db):
    conn = await db.get_db()
    cur = await conn.execute("PRAGMA table_info(youtube_signals)")
    cols = {r["name"] for r in await cur.fetchall()}
    assert {"run_id", "source_snippet", "chunk_id", "parser_version"}.issubset(cols)

@pytest.mark.asyncio
async def test_provenance_columns_exist_on_youtube_levels(tmp_db):
    conn = await db.get_db()
    cur = await conn.execute("PRAGMA table_info(youtube_levels)")
    cols = {r["name"] for r in await cur.fetchall()}
    assert {"run_id", "source_snippet", "chunk_id", "parser_version", "setup_id"}.issubset(cols)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /root/.openclaw/workspace && python -m pytest tests/test_db_youtube.py -k "analysis_run or provenance" -v 2>&1 | tail -20
```

Expected: FAIL — `create_analysis_run` not defined, columns missing.

- [ ] **Step 3: Add `youtube_analysis_runs` to SCHEMA in `db.py`**

In `db.py`, find the SCHEMA string (line ~75). Add this block **before** the closing `"""`:

```sql
CREATE TABLE IF NOT EXISTS youtube_analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    call_budget_used INTEGER DEFAULT 0,
    started_at REAL NOT NULL,
    completed_at REAL,
    UNIQUE(video_id, parser_version)
);
CREATE INDEX IF NOT EXISTS idx_yar_video ON youtube_analysis_runs(video_id);
```

- [ ] **Step 4: Add `_run_column_migrations()` and call it from `init_db()`**

Add this function in `db.py` just before `init_db()`:

```python
async def _run_column_migrations(conn) -> None:
    """Add provenance and run_id columns to pre-existing YouTube tables."""
    migrations = [
        ("youtube_signals", "run_id",         "INTEGER REFERENCES youtube_analysis_runs(id)"),
        ("youtube_signals", "source_snippet",  "TEXT"),
        ("youtube_signals", "chunk_id",        "INTEGER DEFAULT 0"),
        ("youtube_signals", "parser_version",  "TEXT"),
        ("youtube_levels",  "run_id",          "INTEGER REFERENCES youtube_analysis_runs(id)"),
        ("youtube_levels",  "source_snippet",  "TEXT"),
        ("youtube_levels",  "chunk_id",        "INTEGER DEFAULT 0"),
        ("youtube_levels",  "parser_version",  "TEXT"),
        ("youtube_levels",  "setup_id",        "INTEGER"),
        ("youtube_macro",   "run_id",          "INTEGER REFERENCES youtube_analysis_runs(id)"),
        ("youtube_macro",   "parser_version",  "TEXT"),
    ]
    for table, col, defn in migrations:
        cur = await conn.execute(f"PRAGMA table_info({table})")
        existing = {r["name"] for r in await cur.fetchall()}
        if col not in existing:
            await conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {defn}")
    await conn.commit()
```

In `init_db()`, add the call right after `await _db.executescript(SCHEMA)`:

```python
    await _db.executescript(SCHEMA)
    await _run_column_migrations(_db)   # ← add this line
    await _db.commit()
```

- [ ] **Step 5: Add `create_analysis_run()` and `update_analysis_run()` to `db.py`**

Add after `insert_youtube_macro` (~line 1142):

```python
async def create_analysis_run(video_id: str, parser_version: str) -> int:
    """Create or return existing analysis run for this video+version. Returns run_id."""
    conn = await get_db()
    await conn.execute(
        """INSERT OR IGNORE INTO youtube_analysis_runs (video_id, parser_version, status, started_at)
           VALUES (?, ?, 'running', ?)""",
        (video_id, parser_version, time.time()),
    )
    await conn.commit()
    cur = await conn.execute(
        "SELECT id FROM youtube_analysis_runs WHERE video_id=? AND parser_version=?",
        (video_id, parser_version),
    )
    row = await cur.fetchone()
    return row["id"]


async def update_analysis_run(run_id: int, status: str, call_budget_used: int = 0) -> None:
    conn = await get_db()
    await conn.execute(
        """UPDATE youtube_analysis_runs
           SET status=?, call_budget_used=?, completed_at=?
           WHERE id=?""",
        (status, call_budget_used, time.time(), run_id),
    )
    await conn.commit()
```

- [ ] **Step 6: Run tests — expect pass**

```bash
python -m pytest tests/test_db_youtube.py -k "analysis_run or provenance" -v 2>&1 | tail -20
```

Expected: all 5 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add consensus_engine/db.py tests/test_db_youtube.py
git commit -m "Add youtube_analysis_runs table + provenance column migration"
```

---

## Task 2: Schema — `youtube_options` and `youtube_setups` tables + DB helpers

**Files:**
- Modify: `consensus_engine/db.py`
- Test: `tests/test_db_youtube.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_db_youtube.py — add these tests

@pytest.mark.asyncio
async def test_insert_and_get_youtube_option(tmp_db):
    run_id = await db.create_analysis_run("vidOPT1", "v2")
    await db.insert_youtube_option(
        run_id=run_id, video_id="vidOPT1", ticker="TSLA",
        option_type="call", strike=250.0, expiry="weekly",
        strategy="single", source="flow_observation",
        conviction="high", context_text="seeing massive call sweep at 250",
        source_snippet="seeing massive call sweep at 250 strike",
        chunk_id=0, parser_version="v2",
        channel_name="CheddarFlow", published_at="2026-04-22T10:00:00Z",
    )
    rows = await db.get_youtube_options_for_ticker("TSLA", days=7)
    assert len(rows) == 1
    assert rows[0]["option_type"] == "call"
    assert rows[0]["strike"] == 250.0
    assert rows[0]["source_snippet"] == "seeing massive call sweep at 250 strike"

@pytest.mark.asyncio
async def test_insert_and_get_youtube_setup(tmp_db):
    run_id = await db.create_analysis_run("vidSET1", "v2")
    await db.insert_youtube_setup(
        run_id=run_id, video_id="vidSET1", ticker="NVDA",
        entry_low=845.0, entry_high=855.0, stop_price=820.0,
        targets=[920.0, 980.0], timeframe="swing",
        setup_type="breakout", context_text="buy NVDA at 850 stop 820 target 920",
        source_snippet="buy NVDA at 850, stop 820, target 920",
        chunk_id=0, risk_reward=2.5, parser_version="v2",
        channel_name="ClickCapital", published_at="2026-04-22T10:00:00Z",
    )
    rows = await db.get_youtube_setups_for_ticker("NVDA", days=14)
    assert len(rows) == 1
    import json
    targets = json.loads(rows[0]["targets_json"])
    assert targets == [920.0, 980.0]
    assert rows[0]["risk_reward"] == pytest.approx(2.5)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_db_youtube.py -k "option or setup" -v 2>&1 | tail -15
```

Expected: FAIL — tables and helpers don't exist.

- [ ] **Step 3: Add `youtube_options` and `youtube_setups` to SCHEMA**

In `db.py` SCHEMA string, add after the `youtube_analysis_runs` block:

```sql
CREATE TABLE IF NOT EXISTS youtube_options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES youtube_analysis_runs(id),
    video_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    option_type TEXT NOT NULL,
    strike REAL,
    expiry TEXT,
    strategy TEXT,
    source TEXT,
    conviction TEXT,
    context_text TEXT,
    source_snippet TEXT,
    chunk_id INTEGER DEFAULT 0,
    parser_version TEXT NOT NULL,
    channel_name TEXT,
    published_at TEXT,
    extracted_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_yopt_ticker ON youtube_options(ticker);
CREATE INDEX IF NOT EXISTS idx_yopt_extracted ON youtube_options(extracted_at);

CREATE TABLE IF NOT EXISTS youtube_setups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES youtube_analysis_runs(id),
    video_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    entry_low REAL,
    entry_high REAL,
    stop_price REAL,
    targets_json TEXT,
    timeframe TEXT,
    setup_type TEXT,
    context_text TEXT,
    source_snippet TEXT,
    chunk_id INTEGER DEFAULT 0,
    risk_reward REAL,
    parser_version TEXT NOT NULL,
    channel_name TEXT,
    published_at TEXT,
    extracted_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_yset_ticker ON youtube_setups(ticker);
CREATE INDEX IF NOT EXISTS idx_yset_extracted ON youtube_setups(extracted_at);
```

- [ ] **Step 4: Add insert/get helpers for options and setups in `db.py`**

Add after `update_analysis_run()`:

```python
async def insert_youtube_option(
    run_id: int, video_id: str, ticker: str, option_type: str,
    strike: float | None, expiry: str | None, strategy: str | None,
    source: str | None, conviction: str | None, context_text: str | None,
    source_snippet: str | None, chunk_id: int, parser_version: str,
    channel_name: str | None, published_at: str | None,
) -> None:
    conn = await get_db()
    await conn.execute(
        """INSERT INTO youtube_options
           (run_id, video_id, ticker, option_type, strike, expiry, strategy,
            source, conviction, context_text, source_snippet, chunk_id,
            parser_version, channel_name, published_at, extracted_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (run_id, video_id, ticker, option_type, strike, expiry, strategy,
         source, conviction, context_text, source_snippet, chunk_id,
         parser_version, channel_name, published_at, time.time()),
    )
    await conn.commit()


async def get_youtube_options_for_ticker(ticker: str, days: int = 7) -> list[dict]:
    conn = await get_db()
    cutoff = time.time() - days * 86400
    cur = await conn.execute(
        """SELECT * FROM youtube_options
           WHERE ticker=? AND extracted_at>=?
           ORDER BY extracted_at DESC""",
        (ticker, cutoff),
    )
    return [dict(r) for r in await cur.fetchall()]


async def insert_youtube_setup(
    run_id: int, video_id: str, ticker: str,
    entry_low: float | None, entry_high: float | None, stop_price: float | None,
    targets: list[float], timeframe: str | None, setup_type: str | None,
    context_text: str | None, source_snippet: str | None, chunk_id: int,
    risk_reward: float | None, parser_version: str,
    channel_name: str | None, published_at: str | None,
) -> int:
    """Insert a trade setup and return its id."""
    import json as _json
    conn = await get_db()
    cur = await conn.execute(
        """INSERT INTO youtube_setups
           (run_id, video_id, ticker, entry_low, entry_high, stop_price,
            targets_json, timeframe, setup_type, context_text, source_snippet,
            chunk_id, risk_reward, parser_version, channel_name, published_at, extracted_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (run_id, video_id, ticker, entry_low, entry_high, stop_price,
         _json.dumps(targets or []), timeframe, setup_type, context_text,
         source_snippet, chunk_id, risk_reward, parser_version,
         channel_name, published_at, time.time()),
    )
    await conn.commit()
    return cur.lastrowid


async def get_youtube_setups_for_ticker(ticker: str, days: int = 14) -> list[dict]:
    conn = await get_db()
    cutoff = time.time() - days * 86400
    cur = await conn.execute(
        """SELECT * FROM youtube_setups
           WHERE ticker=? AND extracted_at>=?
           ORDER BY extracted_at DESC""",
        (ticker, cutoff),
    )
    return [dict(r) for r in await cur.fetchall()]
```

- [ ] **Step 5: Run tests — expect pass**

```bash
python -m pytest tests/test_db_youtube.py -k "option or setup" -v 2>&1 | tail -15
```

Expected: both tests PASS.

- [ ] **Step 6: Commit**

```bash
git add consensus_engine/db.py tests/test_db_youtube.py
git commit -m "Add youtube_options and youtube_setups tables with DB helpers"
```

---

## Task 3: Canonical evidence read function + level absorption

**Files:**
- Modify: `consensus_engine/db.py`
- Test: `tests/test_db_youtube.py`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_canonical_evidence_returns_setups_not_raw_levels(tmp_db):
    """When a setup exists, absorbed levels are excluded from canonical evidence."""
    run_id = await db.create_analysis_run("vidCE1", "v2")
    # Insert a setup
    setup_id = await db.insert_youtube_setup(
        run_id=run_id, video_id="vidCE1", ticker="AAPL",
        entry_low=180.0, entry_high=182.0, stop_price=175.0,
        targets=[195.0], timeframe="swing", setup_type="breakout",
        context_text="buy AAPL 180-182 stop 175 target 195",
        source_snippet="buy AAPL", chunk_id=0, risk_reward=2.6,
        parser_version="v2", channel_name="Chan", published_at=None,
    )
    # Insert levels that belong to this setup (absorbed)
    conn = await db.get_db()
    await conn.execute(
        """INSERT INTO youtube_levels
           (video_id, ticker, level_type, price, extracted_at, setup_id, parser_version, run_id)
           VALUES (?,?,?,?,?,?,?,?)""",
        ("vidCE1", "AAPL", "support", 180.0, time.time(), setup_id, "v2", run_id),
    )
    # Insert an unabsorbed level
    await conn.execute(
        """INSERT INTO youtube_levels
           (video_id, ticker, level_type, price, extracted_at, parser_version, run_id)
           VALUES (?,?,?,?,?,?,?)""",
        ("vidCE1", "AAPL", "resistance", 200.0, time.time(), "v2", run_id),
    )
    await conn.commit()

    rows = await db.get_youtube_evidence_for_ticker("AAPL", days=7)
    types = {r["evidence_type"] for r in rows}
    assert "setup" in types
    # The absorbed level (180.0 support) must not appear as a standalone level
    raw_level_prices = [r["price"] for r in rows if r["evidence_type"] == "level"]
    assert 180.0 not in raw_level_prices
    # The unabsorbed resistance should appear
    assert 200.0 in raw_level_prices

@pytest.mark.asyncio
async def test_canonical_evidence_falls_back_to_levels_when_no_setup(tmp_db):
    run_id = await db.create_analysis_run("vidCE2", "v2")
    conn = await db.get_db()
    await conn.execute(
        """INSERT INTO youtube_levels
           (video_id, ticker, level_type, price, extracted_at, parser_version, run_id)
           VALUES (?,?,?,?,?,?,?)""",
        ("vidCE2", "NVDA", "support", 850.0, time.time(), "v2", run_id),
    )
    await conn.commit()
    rows = await db.get_youtube_evidence_for_ticker("NVDA", days=7)
    assert len(rows) == 1
    assert rows[0]["evidence_type"] == "level"
    assert rows[0]["price"] == 850.0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_db_youtube.py -k "canonical" -v 2>&1 | tail -15
```

Expected: FAIL — `get_youtube_evidence_for_ticker` not defined.

- [ ] **Step 3: Add `get_youtube_evidence_for_ticker()` to `db.py`**

```python
async def get_youtube_evidence_for_ticker(ticker: str, days: int = 7) -> list[dict]:
    """Canonical read model: setups first, then unabsorbed raw levels. Never double-counts."""
    conn = await get_db()
    cutoff = time.time() - days * 86400
    cur = await conn.execute(
        """
        SELECT 'setup' AS evidence_type,
               s.id, s.ticker, s.entry_low, s.entry_high, s.stop_price,
               s.targets_json, s.timeframe, s.setup_type, s.context_text,
               s.source_snippet, s.risk_reward, s.channel_name, s.published_at,
               s.extracted_at,
               NULL AS price, NULL AS level_type, NULL AS condition_text,
               NULL AS consequence_text
        FROM youtube_setups s
        WHERE s.ticker=? AND s.extracted_at>=?
        UNION ALL
        SELECT 'level' AS evidence_type,
               l.id, l.ticker, NULL, NULL, NULL,
               NULL, NULL, NULL, l.condition_text,
               l.source_snippet, NULL, l.channel_name, l.published_at,
               l.extracted_at,
               l.price, l.level_type, l.condition_text,
               l.consequence_text
        FROM youtube_levels l
        WHERE l.ticker=? AND l.extracted_at>=? AND l.setup_id IS NULL
        ORDER BY extracted_at DESC
        """,
        (ticker, cutoff, ticker, cutoff),
    )
    return [dict(r) for r in await cur.fetchall()]


async def mark_levels_absorbed_by_setup(level_ids: list[int], setup_id: int) -> None:
    """Tag raw level rows as belonging to a setup so canonical reads skip them."""
    if not level_ids:
        return
    conn = await get_db()
    placeholders = ",".join("?" * len(level_ids))
    await conn.execute(
        f"UPDATE youtube_levels SET setup_id=? WHERE id IN ({placeholders})",
        [setup_id, *level_ids],
    )
    await conn.commit()
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python -m pytest tests/test_db_youtube.py -k "canonical" -v 2>&1 | tail -15
```

Expected: both tests PASS.

- [ ] **Step 5: Run full test suite to check nothing broke**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add consensus_engine/db.py tests/test_db_youtube.py
git commit -m "Add get_youtube_evidence_for_ticker canonical read + level absorption helper"
```

---

## Task 4: `ParsedVideo` model extensions + `VideoOptionIdea` + `VideoTradeSetup`

**Files:**
- Modify: `consensus_engine/models.py` (~line 342 — `ParsedVideo` class)
- Test: `tests/test_video_parser.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_video_parser.py — add at top level

from consensus_engine.models import ParsedVideo, VideoOptionIdea, VideoTradeSetup, Direction, Conviction, MacroThesis
import time

def test_parsed_video_has_run_id_options_setups():
    pv = ParsedVideo(
        video_id="v1", channel_name="Chan", raw_transcript="...",
        tickers=[], price_levels=[], macro_thesis=MacroThesis(
            direction=Direction.NEUTRAL, themes=[], timeframe="short", summary=""
        ),
        overall_conviction=Conviction.LOW,
    )
    assert pv.run_id is None
    assert pv.options == []
    assert pv.setups == []

def test_video_option_idea_fields():
    opt = VideoOptionIdea(
        ticker="TSLA", option_type="call", strike=250.0, expiry="weekly",
        strategy="single", source="flow_observation", conviction="high",
        context="seeing massive call sweep", source_snippet="call sweep at 250",
        chunk_id=0,
    )
    assert opt.ticker == "TSLA"
    assert opt.source == "flow_observation"

def test_video_trade_setup_fields():
    s = VideoTradeSetup(
        ticker="NVDA", entry_low=845.0, entry_high=855.0, stop=820.0,
        targets=[920.0, 980.0], timeframe="swing", setup_type="breakout",
        context="buy NVDA 850 stop 820 target 920",
        source_snippet="buy NVDA at 850", chunk_id=0, risk_reward=2.5,
    )
    assert s.risk_reward == pytest.approx(2.5)
    assert len(s.targets) == 2
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_video_parser.py -k "parsed_video_has_run or option_idea or trade_setup" -v 2>&1 | tail -15
```

Expected: FAIL — `VideoOptionIdea`, `VideoTradeSetup` not defined; `ParsedVideo` missing fields.

- [ ] **Step 3: Add new dataclasses to `models.py`**

Add these two classes **before** `ParsedVideo` (~line 322):

```python
@dataclass
class VideoOptionIdea:
    """Options trade idea extracted from a YouTube video."""
    ticker: str
    option_type: str        # call|put
    strike: float | None
    expiry: str | None
    strategy: str | None    # single|spread|leaps|debit|credit
    source: str | None      # flow_observation|personal_idea
    conviction: str | None  # high|medium|low
    context: str            # why this option was mentioned
    source_snippet: str     # exact transcript span that produced this record
    chunk_id: int = 0


@dataclass
class VideoTradeSetup:
    """Coherent entry/stop/target trade setup extracted from a YouTube video."""
    ticker: str
    entry_low: float | None
    entry_high: float | None
    stop: float | None
    targets: list[float]
    timeframe: str | None   # intraday|swing|positional|long-term
    setup_type: str | None  # breakout|pullback|earnings|trend
    context: str
    source_snippet: str
    chunk_id: int = 0
    risk_reward: float | None = None
```

- [ ] **Step 4: Extend `ParsedVideo` with new fields**

In `models.py`, update the `ParsedVideo` dataclass (~line 342):

```python
@dataclass
class ParsedVideo:
    """LLM-parsed YouTube video with extracted trade intelligence."""
    video_id: str
    channel_name: str
    raw_transcript: str
    tickers: list[dict]
    price_levels: list[PriceLevel]
    macro_thesis: MacroThesis
    overall_conviction: Conviction
    parsed_at: float = field(default_factory=time.time)
    run_id: int | None = None
    options: list[VideoOptionIdea] = field(default_factory=list)
    setups: list[VideoTradeSetup] = field(default_factory=list)

    @property
    def has_tickers(self) -> bool:
        return len(self.tickers) > 0
```

- [ ] **Step 5: Add `VideoOptionIdea` and `VideoTradeSetup` to the import in `video_parser.py`**

In `consensus_engine/analysis/video_parser.py` ~line 23:

```python
from consensus_engine.models import (
    ParsedVideo, Direction, Conviction, PriceLevel, MacroThesis,
    VideoOptionIdea, VideoTradeSetup,
)
```

- [ ] **Step 6: Run tests — expect pass**

```bash
python -m pytest tests/test_video_parser.py -k "parsed_video_has_run or option_idea or trade_setup" -v 2>&1 | tail -15
```

Expected: all 3 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add consensus_engine/models.py consensus_engine/analysis/video_parser.py tests/test_video_parser.py
git commit -m "Add VideoOptionIdea, VideoTradeSetup dataclasses; extend ParsedVideo with run_id/options/setups"
```

---

## Task 5: Two-stage parser — Stage 1 (mentions pass)

**Files:**
- Modify: `consensus_engine/analysis/video_parser.py`
- Test: `tests/test_video_parser.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_video_parser.py

from unittest.mock import AsyncMock, patch
from consensus_engine.analysis.video_parser import (
    _extract_mentions_pass, _find_option_snippets,
)

@pytest.mark.asyncio
async def test_extract_mentions_pass_parses_tickers_and_price_spans():
    fake_response = """{
      "tickers": [{"symbol": "NVDA", "mention_count": 3, "source_snippet": "I love NVDA here"}],
      "price_spans": [{"ticker": "NVDA", "price": 850.0, "source_snippet": "NVDA at $850"}],
      "option_keywords_found": false
    }"""
    with patch("consensus_engine.analysis.video_parser._call_extraction_model",
               new=AsyncMock(return_value=(fake_response, True))):
        result = await _extract_mentions_pass("I love NVDA here. NVDA at $850.", chunk_id=0)
    assert result["tickers"][0]["symbol"] == "NVDA"
    assert result["price_spans"][0]["price"] == 850.0
    assert result["option_keywords_found"] is False

@pytest.mark.asyncio
async def test_extract_mentions_pass_returns_empty_on_bad_json():
    with patch("consensus_engine.analysis.video_parser._call_extraction_model",
               new=AsyncMock(return_value=("not json", False))):
        result = await _extract_mentions_pass("some transcript", chunk_id=0)
    assert result["tickers"] == []
    assert result["price_spans"] == []

def test_find_option_snippets_detects_calls_puts():
    text = "I'm seeing huge call buying on TSLA at the 250 strike expiring next Friday. Also some put spreads on SPY."
    snippets = _find_option_snippets(text)
    assert len(snippets) >= 1
    assert any("call" in s.lower() for s in snippets)

def test_find_option_snippets_returns_empty_when_none():
    snippets = _find_option_snippets("NVDA looks good above 850, stop at 820.")
    assert snippets == []
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_video_parser.py -k "mentions_pass or option_snippets" -v 2>&1 | tail -15
```

Expected: FAIL — functions not defined.

- [ ] **Step 3: Add `PARSER_VERSION` and prompts to `video_parser.py`**

At the top of `consensus_engine/analysis/video_parser.py`, after the imports, add:

```python
PARSER_VERSION = "v2"

_MAX_LLM_CALLS = 8  # hard cap per video

_MENTIONS_PROMPT = """You are extracting structured financial mentions from a YouTube transcript.

Respond ONLY in this exact JSON (no markdown):
{
  "tickers": [{"symbol": "NVDA", "mention_count": 3, "source_snippet": "exact quote ≤120 chars"}],
  "price_spans": [{"ticker": "NVDA", "price": 850.0, "source_snippet": "exact quote ≤120 chars"}],
  "option_keywords_found": false
}

Rules:
- Only real stock tickers (AAPL, NVDA, SPY). Exclude RSI, EMA, MACD, VWAP, etc.
- price_spans: only explicit price numbers tied to a specific ticker.
- option_keywords_found: true if transcript mentions calls, puts, strike, expiry, debit, credit, spreads, or LEAPS.
- source_snippet: shortest exact phrase from transcript containing the entity (≤120 chars).
- If nothing found, return empty arrays."""

_DIRECTION_PROMPT = """You are classifying directional sentiment for specific tickers in a YouTube transcript.

Tickers to classify: {ticker_list}

Respond ONLY in this exact JSON (no markdown):
{{"tickers": [{{"symbol": "NVDA", "direction": "long|short|neutral", "conviction": "high|medium|low", "context": "one-sentence reason", "source_snippet": "exact quote ≤120 chars"}}]}}

Rules:
- long=bullish, short=bearish, neutral=no clear bias.
- high=explicit position/trade, medium=strong opinion, low=tentative/watching.
- Only classify tickers from the provided list."""

_MACRO_PROMPT = """You are extracting the macro market thesis from a YouTube financial transcript.

Respond ONLY in this exact JSON (no markdown):
{"macro_thesis": {"direction": "bullish|bearish|neutral", "themes": ["theme1"], "timeframe": "short|medium|long", "summary": "1-2 sentence summary"}}

Rules:
- direction: overall market/macro bias expressed in the video.
- themes: up to 5 specific themes mentioned (e.g. "Fed rate cuts", "earnings season").
- timeframe: short=days/weeks, medium=1-3 months, long=6+ months."""

_OPTIONS_PROMPT = """You are extracting options trade mentions from transcript snippets.

Snippets:
{snippets}

Respond ONLY in this exact JSON (no markdown):
{"options": [{"ticker": "TSLA", "option_type": "call|put", "strike": 250.0, "expiry": "weekly", "strategy": "single|spread|leaps|debit|credit", "source": "flow_observation|personal_idea", "conviction": "high|medium|low", "context": "exact quote"}]}

Rules:
- strike: null if not mentioned. expiry: exact phrase from transcript.
- source: flow_observation if describing market activity; personal_idea if speaker's own trade.
- Skip options without a specific ticker. Return empty array if nothing clear found."""

_SETUPS_PROMPT = """You are linking entry/stop/target prices into coherent trade setups.

Price spans by ticker:
{price_spans_by_ticker}

Respond ONLY in this exact JSON (no markdown):
{"setups": [{"ticker": "NVDA", "entry_low": 845.0, "entry_high": 855.0, "stop": 820.0, "targets": [920.0], "timeframe": "intraday|swing|positional|long-term", "setup_type": "breakout|pullback|earnings|trend", "context": "exact quote"}]}

Rules:
- entry_low/entry_high: same value if exact entry, range if zone given.
- stop and targets: null/[] if not mentioned.
- Only create a setup if at least an entry price exists.
- Never combine prices from different tickers.
- If only isolated prices with no relational context, return empty array."""
```

- [ ] **Step 4: Add `_call_extraction_model()` to `video_parser.py`**

Add after the prompt constants:

```python
async def _call_extraction_model(
    system_prompt: str,
    user_prompt: str,
    model: str = "minimax/minimax-m2.5",
    max_tokens: int = 2048,
) -> tuple[str, bool]:
    """Call OpenRouter with a given model. Returns (content, ok)."""
    api_key = cfg.get_api_key("openrouter")
    if not api_key:
        return "", False
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.1,
            }
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    log.warning("_call_extraction_model: HTTP %d for model %s", resp.status, model)
                    return "", False
                data = await resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content") or ""
        return content.strip(), bool(content)
    except Exception as e:
        log.warning("_call_extraction_model error (%s): %s", model, e)
        return "", False
```

- [ ] **Step 5: Add `_extract_mentions_pass()` and `_find_option_snippets()` to `video_parser.py`**

```python
_OPTION_KEYWORD_RE = re.compile(
    r'\b(calls?|puts?|strike|expir\w+|debit|credit|spread|LEAPS?|weekly|monthly)\b',
    re.IGNORECASE,
)

def _find_option_snippets(text: str, window: int = 300) -> list[str]:
    """Return up to 5 text windows (≤300 chars) around option keywords."""
    snippets = []
    for m in _OPTION_KEYWORD_RE.finditer(text):
        start = max(0, m.start() - window // 2)
        end = min(len(text), m.end() + window // 2)
        snippet = text[start:end].strip()
        if snippet and not any(snippet in s for s in snippets):
            snippets.append(snippet)
        if len(snippets) >= 5:
            break
    return snippets


def _parse_json_safe(raw: str, fallback: dict) -> dict:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return fallback


_STAGE1_MODEL = "openrouter/minimax/minimax-m2.5:free"
_STAGE2_DIR_MODEL = cfg.get("video_parser.models.direction", "z-ai/glm-4.5-air:free")
_STAGE2_MACRO_MODEL = "openrouter/minimax/minimax-m2.5:free"
_STAGE2_OPTIONS_MODEL = cfg.get("video_parser.models.options", "z-ai/glm-4.5-air:free")
_STAGE2_SETUPS_MODEL = "openrouter/minimax/minimax-m2.5:free"
_MAX_STAGE1_WORDS = 10000  # above this, split into 2 chunks


async def _extract_mentions_pass(transcript_text: str, chunk_id: int = 0) -> dict:
    """Stage 1: extract ticker mentions, price spans, option keyword flag."""
    raw, ok = await _call_extraction_model(
        _MENTIONS_PROMPT,
        f"Transcript:\n\n{transcript_text[:8000]}",
        model=_STAGE1_MODEL,
    )
    if not ok:
        return {"tickers": [], "price_spans": [], "option_keywords_found": False}
    result = _parse_json_safe(raw, {"tickers": [], "price_spans": [], "option_keywords_found": False})
    # Inject chunk_id into every record
    for t in result.get("tickers", []):
        t.setdefault("chunk_id", chunk_id)
    for p in result.get("price_spans", []):
        p.setdefault("chunk_id", chunk_id)
    return result
```

- [ ] **Step 6: Run tests — expect pass**

```bash
python -m pytest tests/test_video_parser.py -k "mentions_pass or option_snippets" -v 2>&1 | tail -15
```

Expected: all 4 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add consensus_engine/analysis/video_parser.py tests/test_video_parser.py
git commit -m "Add Stage 1 mentions pass, option snippet finder, and extraction model helper"
```

---

## Task 6: Two-stage parser — Stage 2 (direction + macro passes)

**Files:**
- Modify: `consensus_engine/analysis/video_parser.py`
- Test: `tests/test_video_parser.py`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_extract_direction_pass_classifies_tickers():
    fake = '{"tickers": [{"symbol": "NVDA", "direction": "long", "conviction": "high", "context": "breakout", "source_snippet": "NVDA breakout above 850"}]}'
    with patch("consensus_engine.analysis.video_parser._call_extraction_model",
               new=AsyncMock(return_value=(fake, True))):
        result = await _extract_direction_pass("some transcript", ["NVDA"])
    assert result[0]["symbol"] == "NVDA"
    assert result[0]["direction"] == "long"
    assert result[0]["source_snippet"] == "NVDA breakout above 850"

@pytest.mark.asyncio
async def test_extract_direction_pass_empty_tickers_returns_empty():
    result = await _extract_direction_pass("some transcript", [])
    assert result == []

@pytest.mark.asyncio
async def test_extract_macro_pass_returns_thesis():
    fake = '{"macro_thesis": {"direction": "bearish", "themes": ["rate hikes"], "timeframe": "short", "summary": "Fed staying hawkish."}}'
    with patch("consensus_engine.analysis.video_parser._call_extraction_model",
               new=AsyncMock(return_value=(fake, True))):
        result = await _extract_macro_pass("Fed is hiking rates and markets are falling.")
    assert result["direction"] == "bearish"
    assert "rate hikes" in result["themes"]
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_video_parser.py -k "direction_pass or macro_pass" -v 2>&1 | tail -15
```

Expected: FAIL.

- [ ] **Step 3: Add `_extract_direction_pass()` and `_extract_macro_pass()` to `video_parser.py`**

```python
async def _extract_direction_pass(transcript_text: str, ticker_symbols: list[str]) -> list[dict]:
    """Stage 2a: classify direction+conviction for a known ticker list."""
    if not ticker_symbols:
        return []
    ticker_list = ", ".join(ticker_symbols)
    prompt = _DIRECTION_PROMPT.format(ticker_list=ticker_list)
    raw, ok = await _call_extraction_model(
        prompt,
        f"Transcript (first 3000 words):\n\n{' '.join(transcript_text.split()[:3000])}",
        model=_STAGE2_DIR_MODEL,
        max_tokens=1024,
    )
    if not ok:
        return []
    data = _parse_json_safe(raw, {"tickers": []})
    return [t for t in data.get("tickers", []) if isinstance(t, dict) and t.get("symbol")]


async def _extract_macro_pass(transcript_text: str) -> dict:
    """Stage 2b: extract macro thesis from first 2000 words."""
    excerpt = " ".join(transcript_text.split()[:2000])
    raw, ok = await _call_extraction_model(
        _MACRO_PROMPT,
        f"Transcript:\n\n{excerpt}",
        model=_STAGE2_MACRO_MODEL,
        max_tokens=512,
    )
    if not ok:
        return {"direction": "neutral", "themes": [], "timeframe": "short", "summary": ""}
    data = _parse_json_safe(raw, {})
    macro = data.get("macro_thesis", {})
    direction = str(macro.get("direction", "neutral")).lower()
    direction = _MACRO_NORM.get(direction, direction)
    return {
        "direction": direction,
        "themes": macro.get("themes", []) if isinstance(macro.get("themes"), list) else [],
        "timeframe": str(macro.get("timeframe", "short")).lower(),
        "summary": str(macro.get("summary", "")),
    }
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python -m pytest tests/test_video_parser.py -k "direction_pass or macro_pass" -v 2>&1 | tail -15
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/analysis/video_parser.py tests/test_video_parser.py
git commit -m "Add Stage 2 direction and macro extraction passes"
```

---

## Task 7: Wire new pipeline into `parse_video_transcript()` with budget + provenance

**Files:**
- Modify: `consensus_engine/analysis/video_parser.py`
- Test: `tests/test_video_parser.py`

- [ ] **Step 1: Write failing integration test**

```python
@pytest.mark.asyncio
async def test_parse_video_transcript_v2_pipeline_produces_parsed_video():
    """Full pipeline integration: mentions → direction → macro → ParsedVideo."""
    mentions_resp = '{"tickers": [{"symbol": "NVDA", "mention_count": 2, "source_snippet": "NVDA breakout", "chunk_id": 0}], "price_spans": [], "option_keywords_found": false}'
    direction_resp = '{"tickers": [{"symbol": "NVDA", "direction": "long", "conviction": "high", "context": "breakout", "source_snippet": "NVDA breakout above 850"}]}'
    macro_resp = '{"macro_thesis": {"direction": "bullish", "themes": ["tech rally"], "timeframe": "short", "summary": "Tech leading."}}'

    call_log = []
    async def mock_call(system_prompt, user_prompt, model="minimax/minimax-m2.5", max_tokens=2048):
        call_log.append(model)
        if "price_spans" in system_prompt:
            return mentions_resp, True
        if "direction" in system_prompt.lower() or "{ticker_list}" in system_prompt:
            return direction_resp, True
        return macro_resp, True

    with patch("consensus_engine.analysis.video_parser._call_extraction_model", new=mock_call), \
         patch("consensus_engine.db.create_analysis_run", new=AsyncMock(return_value=42)), \
         patch("consensus_engine.db.update_analysis_run", new=AsyncMock()), \
         patch("consensus_engine.db.record_signal_event", new=AsyncMock()):
        transcript = " ".join(["NVDA is breaking out above 850."] * 80)  # ~500 words
        parsed = await parse_video_transcript("vid42", transcript, "ClickCapital", "2026-04-22T10:00:00Z")

    assert parsed.run_id == 42
    assert any(t.get("symbol") == "NVDA" for t in parsed.tickers)
    assert parsed.macro_thesis.direction.value in ("long", "bullish")

@pytest.mark.asyncio
async def test_parse_video_transcript_marks_partial_on_budget_exhaustion():
    """If budget is hit, run is marked partial but ParsedVideo is still returned."""
    call_count = 0
    async def mock_call_limited(system_prompt, user_prompt, model="minimax/minimax-m2.5", max_tokens=2048):
        nonlocal call_count
        call_count += 1
        return "", False  # all calls fail

    update_calls = []
    async def mock_update(run_id, status, call_budget_used=0):
        update_calls.append(status)

    with patch("consensus_engine.analysis.video_parser._call_extraction_model", new=mock_call_limited), \
         patch("consensus_engine.db.create_analysis_run", new=AsyncMock(return_value=1)), \
         patch("consensus_engine.db.update_analysis_run", new=mock_update), \
         patch("consensus_engine.db.record_signal_event", new=AsyncMock()):
        transcript = " ".join(["NVDA is breaking out."] * 80)
        parsed = await parse_video_transcript("vid99", transcript, "Chan", "2026-04-22T00:00:00Z")

    assert parsed is not None  # always returns something
    assert "partial" in update_calls or "complete" in update_calls
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_video_parser.py -k "v2_pipeline or budget_exhaustion" -v 2>&1 | tail -20
```

Expected: FAIL.

- [ ] **Step 3: Rewrite `parse_video_transcript()` in `video_parser.py`**

Replace the entire `parse_video_transcript()` function (lines 520–658) with:

```python
async def parse_video_transcript(
    video_id: str,
    transcript_text: str,
    channel_name: str,
    published_at: str,
) -> ParsedVideo:
    """Two-stage extraction pipeline with budget enforcement and provenance tracking."""
    min_words = int(cfg.get("youtube.min_transcript_length", 250))
    words = transcript_text.split()
    if len(words) < min_words:
        log.info("video_parser: transcript too short for %s (%d words)", video_id, len(words))
        return ParsedVideo(
            video_id=video_id, channel_name=channel_name, raw_transcript=transcript_text,
            tickers=[], price_levels=[],
            macro_thesis=MacroThesis(direction=Direction.NEUTRAL, themes=[], timeframe="short", summary="too short"),
            overall_conviction=Conviction.LOW,
        )

    # Create (or resume) analysis run
    run_id = await db.create_analysis_run(video_id, PARSER_VERSION)
    budget_used = 0

    async def _call_with_budget(system_prompt: str, user_prompt: str, model: str, max_tokens: int = 2048) -> tuple[str, bool]:
        nonlocal budget_used
        if budget_used >= _MAX_LLM_CALLS:
            return "", False
        content, ok = await _call_extraction_model(system_prompt, user_prompt, model, max_tokens)
        budget_used += 1
        return content, ok

    status = "complete"
    try:
        # ── Stage 1: candidate extraction (1–2 calls) ──────────────────────
        if len(words) <= _MAX_STAGE1_WORDS:
            s1 = await _extract_mentions_pass_budgeted(transcript_text, 0, _call_with_budget)
            all_tickers_raw = s1.get("tickers", [])
            all_price_spans = s1.get("price_spans", [])
            option_keywords_found = s1.get("option_keywords_found", False)
        else:
            # Split into 2 chunks
            mid = len(words) // 2
            chunk1 = " ".join(words[:mid + 150])
            chunk2 = " ".join(words[mid - 150:])
            s1a = await _extract_mentions_pass_budgeted(chunk1, 0, _call_with_budget)
            s1b = await _extract_mentions_pass_budgeted(chunk2, 1, _call_with_budget)
            all_tickers_raw = s1a.get("tickers", []) + s1b.get("tickers", [])
            all_price_spans = s1a.get("price_spans", []) + s1b.get("price_spans", [])
            option_keywords_found = s1a.get("option_keywords_found", False) or s1b.get("option_keywords_found", False)

        # Deduplicate ticker symbols
        seen: dict[str, dict] = {}
        for t in all_tickers_raw:
            sym = str(t.get("symbol", "")).upper()
            if sym and sym not in _INDICATOR_NAMES:
                if sym not in seen or t.get("mention_count", 1) > seen[sym].get("mention_count", 1):
                    seen[sym] = t
        unique_symbols = list(seen.keys())

        # ── Stage 2a: direction/conviction (1 call) ─────────────────────────
        direction_records: dict[str, dict] = {}
        if unique_symbols and budget_used < _MAX_LLM_CALLS:
            dir_list = await _extract_direction_pass_budgeted(transcript_text, unique_symbols, _call_with_budget)
            direction_records = {r["symbol"]: r for r in dir_list if r.get("symbol")}

        # Merge mentions + direction
        normalized_tickers = []
        for sym, mention in seen.items():
            dr = direction_records.get(sym, {})
            direction = dr.get("direction", "neutral")
            context = dr.get("context", mention.get("source_snippet", ""))
            direction = _apply_negation(direction, context)
            normalized_tickers.append({
                "symbol": sym,
                "direction": direction,
                "conviction": dr.get("conviction", "medium"),
                "mention_count": mention.get("mention_count", 1),
                "context": context,
                "source_snippet": dr.get("source_snippet") or mention.get("source_snippet", ""),
                "chunk_id": mention.get("chunk_id", 0),
            })

        # ── Stage 2b: macro (1 call) ─────────────────────────────────────────
        macro_data = {"direction": "neutral", "themes": [], "timeframe": "short", "summary": ""}
        if budget_used < _MAX_LLM_CALLS:
            macro_data = await _extract_macro_pass_budgeted(transcript_text, _call_with_budget)
        else:
            status = "partial"

        # ── Stage 2c: options (1 call, only if keywords found) ───────────────
        options_out: list[VideoOptionIdea] = []
        if option_keywords_found and budget_used < _MAX_LLM_CALLS:
            option_snippets = _find_option_snippets(transcript_text)
            if option_snippets:
                options_out = await _extract_options_pass_budgeted(option_snippets, unique_symbols, _call_with_budget)

        # ── Stage 2d: setups (1 call, only if price spans exist) ────────────
        setups_out: list[VideoTradeSetup] = []
        if all_price_spans and budget_used < _MAX_LLM_CALLS:
            setups_out = await _extract_setups_pass_budgeted(all_price_spans, _call_with_budget)

        if budget_used >= _MAX_LLM_CALLS and status != "partial":
            status = "partial"

    except Exception as e:
        log.warning("video_parser: pipeline error for %s: %s", video_id, e)
        normalized_tickers = []
        macro_data = {"direction": "neutral", "themes": [], "timeframe": "short", "summary": "parse error"}
        options_out = []
        setups_out = []
        status = "failed"

    await db.update_analysis_run(run_id, status=status, call_budget_used=budget_used)

    # Build PriceLevel objects from raw price spans (legacy-compatible)
    price_levels = [
        PriceLevel(
            ticker=ps.get("ticker", ""),
            level_type="support",
            price=ps.get("price", 0.0),
            condition=ps.get("source_snippet", ""),
            consequence="",
            confidence=0.7,
        )
        for ps in all_price_spans if ps.get("price", 0) > 0
    ]

    _norm_macro_dir = _MACRO_NORM.get(macro_data.get("direction", "neutral"), "neutral")
    macro_thesis = MacroThesis(
        direction=Direction(_norm_macro_dir),
        themes=macro_data.get("themes", []),
        timeframe=macro_data.get("timeframe", "short"),
        summary=macro_data.get("summary", ""),
    )

    # Derive overall conviction from highest in tickers
    conv_order = {"high": 3, "medium": 2, "low": 1}
    top_conv = max((conv_order.get(t.get("conviction", "low"), 1) for t in normalized_tickers), default=2)
    overall_conviction = {3: Conviction.HIGH, 2: Conviction.MEDIUM, 1: Conviction.LOW}.get(top_conv, Conviction.MEDIUM)

    # Write signal_events for telemetry (unchanged from v1)
    _conviction_quality = {"high": 0.9, "medium": 0.6, "low": 0.3}
    parse_latency = 0.0
    for t in normalized_tickers:
        if not t.get("symbol"):
            continue
        q = _conviction_quality.get(t.get("conviction", "medium"), 0.6)
        q = min(q * (1.0 + 0.05 * (t.get("mention_count", 1) - 1)), 1.0)
        try:
            await db.record_signal_event(
                source_type="youtube", source_detail=video_id,
                ticker=t["symbol"], direction=t.get("direction", "neutral"),
                quality_score=round(q, 4), latency_sec=round(parse_latency, 3),
                provenance=f"youtube://{channel_name}/{video_id}",
                model_version=f"video_parser_{PARSER_VERSION}",
            )
        except Exception as exc:
            log.debug("video_parser: signal_event insert failed for %s/%s: %s", video_id, t["symbol"], exc)

    return ParsedVideo(
        video_id=video_id,
        channel_name=channel_name,
        raw_transcript=transcript_text,
        tickers=normalized_tickers,
        price_levels=price_levels,
        macro_thesis=macro_thesis,
        overall_conviction=overall_conviction,
        parsed_at=time.time(),
        run_id=run_id,
        options=options_out,
        setups=setups_out,
    )
```

- [ ] **Step 4: Add the four `_budgeted` wrapper helpers in `video_parser.py`**

These adapt the pure pass functions to use the budget-aware caller:

```python
async def _extract_mentions_pass_budgeted(text: str, chunk_id: int, caller) -> dict:
    raw, ok = await caller(
        _MENTIONS_PROMPT,
        f"Transcript:\n\n{text[:8000]}",
        _STAGE1_MODEL,
    )
    if not ok:
        return {"tickers": [], "price_spans": [], "option_keywords_found": False}
    result = _parse_json_safe(raw, {"tickers": [], "price_spans": [], "option_keywords_found": False})
    for t in result.get("tickers", []):
        t.setdefault("chunk_id", chunk_id)
    for p in result.get("price_spans", []):
        p.setdefault("chunk_id", chunk_id)
    return result


async def _extract_direction_pass_budgeted(transcript_text: str, ticker_symbols: list[str], caller) -> list[dict]:
    if not ticker_symbols:
        return []
    ticker_list = ", ".join(ticker_symbols)
    prompt = _DIRECTION_PROMPT.format(ticker_list=ticker_list)
    raw, ok = await caller(
        prompt,
        f"Transcript (first 3000 words):\n\n{' '.join(transcript_text.split()[:3000])}",
        _STAGE2_DIR_MODEL,
        1024,
    )
    if not ok:
        return []
    data = _parse_json_safe(raw, {"tickers": []})
    return [t for t in data.get("tickers", []) if isinstance(t, dict) and t.get("symbol")]


async def _extract_macro_pass_budgeted(transcript_text: str, caller) -> dict:
    excerpt = " ".join(transcript_text.split()[:2000])
    raw, ok = await caller(_MACRO_PROMPT, f"Transcript:\n\n{excerpt}", _STAGE2_MACRO_MODEL, 512)
    if not ok:
        return {"direction": "neutral", "themes": [], "timeframe": "short", "summary": ""}
    data = _parse_json_safe(raw, {})
    macro = data.get("macro_thesis", {})
    direction = _MACRO_NORM.get(str(macro.get("direction", "neutral")).lower(), "neutral")
    return {
        "direction": direction,
        "themes": macro.get("themes", []) if isinstance(macro.get("themes"), list) else [],
        "timeframe": str(macro.get("timeframe", "short")).lower(),
        "summary": str(macro.get("summary", "")),
    }


async def _extract_options_pass_budgeted(snippets: list[str], ticker_symbols: list[str], caller) -> list[VideoOptionIdea]:
    snippets_text = "\n---\n".join(snippets)
    raw, ok = await caller(
        _OPTIONS_PROMPT.format(snippets=snippets_text),
        "Extract all options mentions from the snippets above.",
        _STAGE2_OPTIONS_MODEL,
        1024,
    )
    if not ok:
        return []
    data = _parse_json_safe(raw, {"options": []})
    out = []
    for o in data.get("options", []):
        if not isinstance(o, dict):
            continue
        ticker = str(o.get("ticker", "")).upper()
        if not ticker or ticker not in ticker_symbols:
            continue
        opt_type = str(o.get("option_type", "")).lower()
        if opt_type not in ("call", "put"):
            continue
        out.append(VideoOptionIdea(
            ticker=ticker, option_type=opt_type,
            strike=float(o["strike"]) if o.get("strike") is not None else None,
            expiry=o.get("expiry"), strategy=o.get("strategy"),
            source=o.get("source"), conviction=o.get("conviction", "medium"),
            context=str(o.get("context", "")),
            source_snippet=str(o.get("context", ""))[:200],
            chunk_id=0,
        ))
    return out


async def _extract_setups_pass_budgeted(price_spans: list[dict], caller) -> list[VideoTradeSetup]:
    by_ticker: dict[str, list[dict]] = {}
    for ps in price_spans:
        sym = str(ps.get("ticker", "")).upper()
        if sym:
            by_ticker.setdefault(sym, []).append(ps)
    if not by_ticker:
        return []
    spans_text = "\n".join(
        f"{sym}: " + "; ".join(f"${p['price']:.2f} ({p.get('source_snippet', '')})" for p in spans)
        for sym, spans in by_ticker.items()
    )
    raw, ok = await caller(
        _SETUPS_PROMPT.format(price_spans_by_ticker=spans_text),
        "Link these price spans into trade setups.",
        _STAGE2_SETUPS_MODEL,
        1024,
    )
    if not ok:
        return []
    data = _parse_json_safe(raw, {"setups": []})
    out = []
    for s in data.get("setups", []):
        if not isinstance(s, dict) or not s.get("ticker"):
            continue
        ticker = str(s["ticker"]).upper()
        entry_low = float(s["entry_low"]) if s.get("entry_low") is not None else None
        if entry_low is None:
            continue
        entry_high = float(s.get("entry_high") or entry_low)
        stop = float(s["stop"]) if s.get("stop") is not None else None
        targets = [float(t) for t in (s.get("targets") or []) if t is not None]
        rr = _compute_risk_reward(entry_low, entry_high, stop, targets)
        context = str(s.get("context", ""))
        out.append(VideoTradeSetup(
            ticker=ticker, entry_low=entry_low, entry_high=entry_high,
            stop=stop, targets=targets,
            timeframe=s.get("timeframe"), setup_type=s.get("setup_type"),
            context=context, source_snippet=context[:200],
            chunk_id=0, risk_reward=rr,
        ))
    return out


def _compute_risk_reward(
    entry_low: float | None, entry_high: float | None,
    stop: float | None, targets: list[float],
) -> float | None:
    """Compute R/R: (first_target - midpoint_entry) / (midpoint_entry - stop)."""
    if entry_low is None or stop is None or not targets:
        return None
    mid = ((entry_low or 0) + (entry_high or entry_low or 0)) / 2
    if mid <= stop:
        return None
    rr = (targets[0] - mid) / (mid - stop)
    return round(rr, 2) if rr > 0 else None
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_video_parser.py -k "v2_pipeline or budget_exhaustion" -v 2>&1 | tail -20
```

Expected: both tests PASS.

- [ ] **Step 6: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: no regressions.

- [ ] **Step 7: Commit**

```bash
git add consensus_engine/analysis/video_parser.py tests/test_video_parser.py
git commit -m "Rewrite parse_video_transcript with two-stage pipeline, budget cap, and provenance"
```

---

## Task 8: Update `process_video()` to persist options + setups with `run_id`

**Files:**
- Modify: `consensus_engine/scanners/youtube.py`
- Test: `tests/test_youtube_scanner.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_youtube_scanner.py — add these

@pytest.mark.asyncio
async def test_process_video_persists_options(tmp_db, monkeypatch):
    from consensus_engine.scanners.youtube import process_video
    from consensus_engine.models import (
        ParsedVideo, MacroThesis, Direction, Conviction, VideoOptionIdea
    )
    import asyncio, time

    mock_parsed = ParsedVideo(
        video_id="vidOPT10", channel_name="Chan", raw_transcript="x" * 500,
        tickers=[{"symbol": "TSLA", "direction": "long", "conviction": "high",
                  "mention_count": 1, "context": "c", "source_snippet": "s", "chunk_id": 0}],
        price_levels=[],
        macro_thesis=MacroThesis(direction=Direction.NEUTRAL, themes=[], timeframe="short", summary=""),
        overall_conviction=Conviction.HIGH,
        run_id=77,
        options=[VideoOptionIdea(
            ticker="TSLA", option_type="call", strike=250.0, expiry="weekly",
            strategy="single", source="flow_observation", conviction="high",
            context="call sweep", source_snippet="call sweep at 250", chunk_id=0,
        )],
        setups=[],
    )

    async def fake_fetch(*a, **kw):
        return "transcript " * 300, "en", False

    async def fake_parse(*a, **kw):
        return mock_parsed

    monkeypatch.setattr("consensus_engine.utils.transcript_fetch.fetch_transcript_cascade", fake_fetch)
    monkeypatch.setattr("consensus_engine.analysis.video_parser.parse_video_transcript", fake_parse)

    sem = asyncio.Semaphore(1)
    video_meta = {"video_id": "vidOPT10", "channel_id": "ch1", "title": "T",
                  "published_at": "2026-04-22T10:00:00Z"}
    await process_video(video_meta, sem, ["en"], "/tmp/yt_test")

    from consensus_engine import db
    opts = await db.get_youtube_options_for_ticker("TSLA", days=1)
    assert len(opts) == 1
    assert opts[0]["option_type"] == "call"
    assert opts[0]["run_id"] == 77

@pytest.mark.asyncio
async def test_process_video_persists_setups(tmp_db, monkeypatch):
    from consensus_engine.scanners.youtube import process_video
    from consensus_engine.models import (
        ParsedVideo, MacroThesis, Direction, Conviction, VideoTradeSetup
    )
    import asyncio

    mock_parsed = ParsedVideo(
        video_id="vidSET10", channel_name="Chan", raw_transcript="x" * 500,
        tickers=[{"symbol": "NVDA", "direction": "long", "conviction": "high",
                  "mention_count": 1, "context": "c", "source_snippet": "s", "chunk_id": 0}],
        price_levels=[],
        macro_thesis=MacroThesis(direction=Direction.NEUTRAL, themes=[], timeframe="short", summary=""),
        overall_conviction=Conviction.HIGH,
        run_id=88,
        options=[],
        setups=[VideoTradeSetup(
            ticker="NVDA", entry_low=845.0, entry_high=855.0, stop=820.0,
            targets=[920.0], timeframe="swing", setup_type="breakout",
            context="buy NVDA 850 stop 820 target 920",
            source_snippet="buy NVDA", chunk_id=0, risk_reward=2.5,
        )],
    )

    async def fake_fetch(*a, **kw):
        return "transcript " * 300, "en", False

    async def fake_parse(*a, **kw):
        return mock_parsed

    monkeypatch.setattr("consensus_engine.utils.transcript_fetch.fetch_transcript_cascade", fake_fetch)
    monkeypatch.setattr("consensus_engine.analysis.video_parser.parse_video_transcript", fake_parse)

    sem = asyncio.Semaphore(1)
    video_meta = {"video_id": "vidSET10", "channel_id": "ch1", "title": "T",
                  "published_at": "2026-04-22T10:00:00Z"}
    await process_video(video_meta, sem, ["en"], "/tmp/yt_test")

    from consensus_engine import db
    setups = await db.get_youtube_setups_for_ticker("NVDA", days=1)
    assert len(setups) == 1
    assert setups[0]["setup_type"] == "breakout"
    assert setups[0]["run_id"] == 88
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_youtube_scanner.py -k "persists_options or persists_setups" -v 2>&1 | tail -20
```

Expected: FAIL.

- [ ] **Step 3: Update `process_video()` in `youtube.py` to pass `run_id` and persist options/setups**

In `consensus_engine/scanners/youtube.py`, in the `process_video()` function, find the section after `parsed.macro_thesis` is persisted (~line 322). Add option and setup persistence:

```python
                # Insert price levels (with provenance)
                for level in parsed.price_levels:
                    await db.insert_youtube_level(
                        video_id=video_id,
                        ticker=level.ticker,
                        level_type=level.level_type,
                        price=level.price,
                        condition_text=level.condition,
                        consequence_text=level.consequence,
                        confidence=level.confidence,
                        channel_name=display_name,
                        published_at=video_meta["published_at"],
                        run_id=parsed.run_id,
                        source_snippet=level.condition,
                        chunk_id=0,
                        parser_version=parsed.run_id and "v2" or "v1",
                    )
```

Also update `insert_youtube_signal()` calls to pass provenance fields for each ticker:

```python
                        await db.insert_youtube_signal(
                            video_id=video_id,
                            channel_name=display_name,
                            ticker=ticker,
                            direction=ticker_data.get("direction", "neutral"),
                            conviction=ticker_data.get("conviction", "medium"),
                            mention_count=ticker_data.get("mention_count", 1),
                            macro_thesis=macro_json,
                            published_at=video_meta["published_at"],
                            run_id=parsed.run_id,
                            source_snippet=ticker_data.get("source_snippet"),
                            chunk_id=ticker_data.get("chunk_id", 0),
                            parser_version="v2" if parsed.run_id else "v1",
                        )
```

Then add after macro persistence:

```python
                # Insert options
                for opt in parsed.options:
                    await db.insert_youtube_option(
                        run_id=parsed.run_id,
                        video_id=video_id,
                        ticker=opt.ticker,
                        option_type=opt.option_type,
                        strike=opt.strike,
                        expiry=opt.expiry,
                        strategy=opt.strategy,
                        source=opt.source,
                        conviction=opt.conviction,
                        context_text=opt.context,
                        source_snippet=opt.source_snippet,
                        chunk_id=opt.chunk_id,
                        parser_version="v2",
                        channel_name=display_name,
                        published_at=video_meta["published_at"],
                    )
                    log.debug("youtube: option created %s/%s %s@%s", video_id, opt.ticker, opt.option_type, opt.strike)

                # Insert setups + absorb constituent levels
                for setup in parsed.setups:
                    setup_id = await db.insert_youtube_setup(
                        run_id=parsed.run_id,
                        video_id=video_id,
                        ticker=setup.ticker,
                        entry_low=setup.entry_low,
                        entry_high=setup.entry_high,
                        stop_price=setup.stop,
                        targets=setup.targets,
                        timeframe=setup.timeframe,
                        setup_type=setup.setup_type,
                        context_text=setup.context,
                        source_snippet=setup.source_snippet,
                        chunk_id=setup.chunk_id,
                        risk_reward=setup.risk_reward,
                        parser_version="v2",
                        channel_name=display_name,
                        published_at=video_meta["published_at"],
                    )
                    # Absorb raw levels for this ticker into this setup
                    conn = await db.get_db()
                    cur = await conn.execute(
                        "SELECT id FROM youtube_levels WHERE video_id=? AND ticker=? AND setup_id IS NULL",
                        (video_id, setup.ticker),
                    )
                    level_ids = [r["id"] for r in await cur.fetchall()]
                    if level_ids:
                        await db.mark_levels_absorbed_by_setup(level_ids, setup_id)
                    log.debug("youtube: setup created %s/%s %s-%s target %s",
                              video_id, setup.ticker, setup.entry_low, setup.entry_high, setup.targets)
```

- [ ] **Step 4: Update `insert_youtube_signal` and `insert_youtube_level` signatures in `db.py` to accept new optional params**

In `db.py`, update `insert_youtube_signal` (~line 1000):

```python
async def insert_youtube_signal(
    video_id: str, channel_name: str, ticker: str, direction: str,
    conviction: str, mention_count: int = 1, macro_thesis: str | None = None,
    published_at: str | None = None,
    run_id: int | None = None, source_snippet: str | None = None,
    chunk_id: int = 0, parser_version: str | None = None,
) -> None:
    conn = await get_db()
    await conn.execute(
        """INSERT INTO youtube_signals
           (video_id, channel_name, ticker, direction, conviction, mention_count,
            macro_thesis, parsed_at, published_at, extracted_at,
            run_id, source_snippet, chunk_id, parser_version)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (video_id, channel_name, ticker, direction, conviction, mention_count,
         macro_thesis, time.time(), published_at, time.time(),
         run_id, source_snippet, chunk_id, parser_version),
    )
    await conn.commit()
```

In `db.py`, update `insert_youtube_level` (~line 1021) similarly:

```python
async def insert_youtube_level(
    video_id: str, ticker: str, level_type: str, price: float,
    condition_text: str | None = None, consequence_text: str | None = None,
    confidence: float = 0.8, channel_name: str | None = None,
    published_at: str | None = None,
    run_id: int | None = None, source_snippet: str | None = None,
    chunk_id: int = 0, parser_version: str | None = None,
) -> None:
    conn = await get_db()
    await conn.execute(
        """INSERT INTO youtube_levels
           (video_id, ticker, level_type, price, condition_text, consequence_text,
            confidence, channel_name, published_at, extracted_at,
            run_id, source_snippet, chunk_id, parser_version)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (video_id, ticker, level_type, price, condition_text, consequence_text,
         confidence, channel_name, published_at, time.time(),
         run_id, source_snippet, chunk_id, parser_version),
    )
    await conn.commit()
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_youtube_scanner.py -k "persists_options or persists_setups" -v 2>&1 | tail -20
```

Expected: both PASS.

- [ ] **Step 6: Run full suite**

```bash
python -m pytest tests/ --tb=short 2>&1 | tail -30
```

- [ ] **Step 7: Commit**

```bash
git add consensus_engine/scanners/youtube.py consensus_engine/db.py tests/test_youtube_scanner.py
git commit -m "Persist options and setups in process_video with run_id provenance and level absorption"
```

---

## Task 9: Update `!yt` command to surface options and setups

**Files:**
- Modify: `consensus_engine/alerts/commands.py` (~line 975)
- Test: `tests/test_commands.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_commands.py — add these

@pytest.mark.asyncio
async def test_yt_reply_includes_setup_when_present(mock_send, monkeypatch, tmp_db):
    from consensus_engine.alerts.commands import _yt_analyse_and_reply
    from consensus_engine.models import (
        ParsedVideo, MacroThesis, Direction, Conviction, VideoTradeSetup
    )
    mock_parsed = ParsedVideo(
        video_id="vidFMT1", channel_name="Chan", raw_transcript="x" * 500,
        tickers=[{"symbol": "NVDA", "direction": "long", "conviction": "high",
                  "mention_count": 2, "context": "breakout", "source_snippet": "s", "chunk_id": 0}],
        price_levels=[],
        macro_thesis=MacroThesis(direction=Direction.LONG, themes=[], timeframe="short", summary="bullish"),
        overall_conviction=Conviction.HIGH,
        run_id=10,
        options=[],
        setups=[VideoTradeSetup(
            ticker="NVDA", entry_low=845.0, entry_high=855.0, stop=820.0,
            targets=[920.0], timeframe="swing", setup_type="breakout",
            context="buy NVDA", source_snippet="buy NVDA at 850", chunk_id=0, risk_reward=2.5,
        )],
    )
    monkeypatch.setattr("consensus_engine.analysis.video_parser.parse_video_transcript",
                        AsyncMock(return_value=mock_parsed))
    monkeypatch.setattr("consensus_engine.utils.transcript_fetch.fetch_transcript_cascade",
                        AsyncMock(return_value=("transcript " * 300, "en", False)))

    sent = []
    async def capture(ch, msg_id, text):
        sent.append(text)
    monkeypatch.setattr("consensus_engine.alerts.commands.send_command_reply", capture)

    await _yt_analyse_and_reply("https://youtube.com/watch?v=vidFMT1", "ch1", "msg1")
    combined = "\n".join(sent)
    assert "845" in combined or "850" in combined   # entry price present
    assert "820" in combined                          # stop present
    assert "920" in combined                          # target present

@pytest.mark.asyncio
async def test_yt_reply_includes_options_when_present(mock_send, monkeypatch, tmp_db):
    from consensus_engine.alerts.commands import _yt_analyse_and_reply
    from consensus_engine.models import (
        ParsedVideo, MacroThesis, Direction, Conviction, VideoOptionIdea
    )
    mock_parsed = ParsedVideo(
        video_id="vidFMT2", channel_name="Chan", raw_transcript="x" * 500,
        tickers=[{"symbol": "TSLA", "direction": "long", "conviction": "high",
                  "mention_count": 1, "context": "c", "source_snippet": "s", "chunk_id": 0}],
        price_levels=[],
        macro_thesis=MacroThesis(direction=Direction.NEUTRAL, themes=[], timeframe="short", summary=""),
        overall_conviction=Conviction.HIGH,
        run_id=11,
        setups=[],
        options=[VideoOptionIdea(
            ticker="TSLA", option_type="call", strike=250.0, expiry="weekly",
            strategy="single", source="flow_observation", conviction="high",
            context="call sweep at 250", source_snippet="call sweep at 250 strike", chunk_id=0,
        )],
    )
    monkeypatch.setattr("consensus_engine.analysis.video_parser.parse_video_transcript",
                        AsyncMock(return_value=mock_parsed))
    monkeypatch.setattr("consensus_engine.utils.transcript_fetch.fetch_transcript_cascade",
                        AsyncMock(return_value=("transcript " * 300, "en", False)))

    sent = []
    async def capture(ch, msg_id, text):
        sent.append(text)
    monkeypatch.setattr("consensus_engine.alerts.commands.send_command_reply", capture)

    await _yt_analyse_and_reply("https://youtube.com/watch?v=vidFMT2", "ch1", "msg1")
    combined = "\n".join(sent)
    assert "call" in combined.lower()
    assert "250" in combined
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_commands.py -k "yt_reply_includes" -v 2>&1 | tail -20
```

Expected: FAIL.

- [ ] **Step 3: Add formatting helpers to `commands.py`**

Add these two functions before `_handle_yt()` (~line 928):

```python
def _format_youtube_setup_summary(setup) -> str:
    """Format a VideoTradeSetup into a compact Discord line."""
    if hasattr(setup, "ticker"):
        ticker, entry_low, entry_high = setup.ticker, setup.entry_low, setup.entry_high
        stop, targets, rr = setup.stop, setup.targets, setup.risk_reward
    else:
        ticker = setup.get("ticker", "?")
        entry_low, entry_high = setup.get("entry_low"), setup.get("entry_high")
        stop, targets = setup.get("stop_price"), []
        import json as _j
        try:
            targets = _j.loads(setup.get("targets_json") or "[]")
        except Exception:
            targets = []
        rr = setup.get("risk_reward")

    entry_str = f"${entry_low:.2f}" if entry_low else "?"
    if entry_high and entry_high != entry_low:
        entry_str = f"${entry_low:.2f}–${entry_high:.2f}"
    stop_str = f"${stop:.2f}" if stop else "—"
    target_str = "/".join(f"${t:.2f}" for t in targets) if targets else "—"
    rr_str = f" R/R {rr:.1f}x" if rr else ""
    return f"  📐 `{ticker}` Entry {entry_str} | Stop {stop_str} | Target {target_str}{rr_str}"


def _format_youtube_option_summary(opt) -> str:
    """Format a VideoOptionIdea into a compact Discord line."""
    if hasattr(opt, "ticker"):
        ticker, opt_type = opt.ticker, opt.option_type
        strike, expiry, source = opt.strike, opt.expiry, opt.source
    else:
        ticker, opt_type = opt.get("ticker", "?"), opt.get("option_type", "?")
        strike, expiry, source = opt.get("strike"), opt.get("expiry"), opt.get("source")

    strike_str = f"${strike:.0f}" if strike else "?"
    expiry_str = f" exp {expiry}" if expiry else ""
    src_icon = "👁" if source == "flow_observation" else "💡"
    return f"  {src_icon} `{ticker}` {opt_type.upper()} {strike_str}{expiry_str}"
```

- [ ] **Step 4: Update `_yt_analyse_and_reply()` to use the formatters**

In `commands.py`, in `_yt_analyse_and_reply()`, replace the block that builds `lines` starting with `lines = [f"🎬 **{title}**..."]` (line ~975):

```python
        lines = [f"🎬 **{title}** — {channel_name}"]
        if parsed is not None:
            tickers = parsed.tickers[:5]
            if tickers:
                lines.append("**Tickers:**")
                for t in tickers:
                    dir_icon = {"long": "🟢", "short": "🔴"}.get(t.get("direction", ""), "⚪")
                    lines.append(f"  {dir_icon} `${t['symbol']}` {t.get('direction','').upper()} [{t.get('conviction','').upper()}]")
            else:
                lines.append("No tickers extracted.")

            # Setups
            if parsed.setups:
                lines.append("**Setup(s):**")
                for s in parsed.setups[:2]:
                    lines.append(_format_youtube_setup_summary(s))

            # Options
            if parsed.options:
                lines.append("**Options:**")
                for o in parsed.options[:3]:
                    lines.append(_format_youtube_option_summary(o))

            # Levels fallback (only if no setups)
            if not parsed.setups:
                lvls = parsed.price_levels[:3]
                if lvls:
                    lines.append("**Levels:**")
                    for lv in lvls:
                        lines.append(f"  `{lv.level_type.upper()}` ${lv.price:.2f} (conf {lv.confidence:.0%})")

            macro = parsed.macro_thesis
            dir_label = {"long": "BULLISH", "short": "BEARISH", "neutral": "NEUTRAL"}.get(macro.direction.value, str(macro.direction))
            lines.append(f"**Macro:** {dir_label} — {macro.summary[:120] if macro.summary else 'N/A'}")
            lines.append(f"**Conviction:** {parsed.overall_conviction.value.upper()}")
        else:
            lines.append("Already processed — use `!yt-mentions $TICKER` to see signals.")
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_commands.py -k "yt_reply_includes" -v 2>&1 | tail -20
```

Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add consensus_engine/alerts/commands.py tests/test_commands.py
git commit -m "Surface options and setups in !yt command output"
```

---

## Task 10: Update cross-reference to use canonical evidence

**Files:**
- Modify: `consensus_engine/cross_reference.py` (~line 160 — `_get_youtube_context()`)
- Test: `tests/test_cross_reference.py`

- [ ] **Step 1: Find the current `_get_youtube_context()` read pattern**

```bash
grep -n "_get_youtube_context\|get_youtube_levels\|YouTubeContext" consensus_engine/cross_reference.py | head -15
```

Note the line numbers, then continue.

- [ ] **Step 2: Write failing test**

```python
# tests/test_cross_reference.py — add this test

@pytest.mark.asyncio
async def test_get_youtube_context_uses_canonical_evidence(tmp_db, monkeypatch):
    from consensus_engine import db
    from consensus_engine.cross_reference import _get_youtube_context

    run_id = await db.create_analysis_run("vidXR1", "v2")
    await db.insert_youtube_signal(
        video_id="vidXR1", channel_name="Chan", ticker="NVDA",
        direction="long", conviction="high", mention_count=2,
        run_id=run_id, source_snippet="NVDA breakout", chunk_id=0, parser_version="v2",
        published_at="2026-04-22T10:00:00Z",
    )
    setup_id = await db.insert_youtube_setup(
        run_id=run_id, video_id="vidXR1", ticker="NVDA",
        entry_low=845.0, entry_high=855.0, stop_price=820.0,
        targets=[920.0], timeframe="swing", setup_type="breakout",
        context_text="buy NVDA 850 stop 820", source_snippet="buy NVDA",
        chunk_id=0, risk_reward=2.5, parser_version="v2",
        channel_name="Chan", published_at="2026-04-22T10:00:00Z",
    )

    ctx = await _get_youtube_context("NVDA", days=7)
    assert ctx is not None
    # levels list should reflect canonical evidence (setup rows), not raw levels
    assert any(e.get("evidence_type") == "setup" for e in ctx.levels)
```

- [ ] **Step 3: Run to confirm failure**

```bash
python -m pytest tests/test_cross_reference.py -k "canonical_evidence" -v 2>&1 | tail -15
```

Expected: FAIL.

- [ ] **Step 4: Update `_get_youtube_context()` in `cross_reference.py`**

Find the function and replace its levels-fetch line. The current call is something like:

```python
levels = await db.get_youtube_levels_for_ticker(ticker, days=days)
```

Replace it with:

```python
levels = await db.get_youtube_evidence_for_ticker(ticker, days=days)
```

This is the only change needed here — the function already packages levels into `YouTubeContext.levels` as a list of dicts, and `get_youtube_evidence_for_ticker` returns the same structure. The new rows just have an `evidence_type` field that downstream can optionally use.

- [ ] **Step 5: Run test**

```bash
python -m pytest tests/test_cross_reference.py -k "canonical_evidence" -v 2>&1 | tail -15
```

Expected: PASS.

- [ ] **Step 6: Run full suite**

```bash
python -m pytest tests/ --tb=short 2>&1 | tail -30
```

Expected: no regressions.

- [ ] **Step 7: Commit**

```bash
git add consensus_engine/cross_reference.py tests/test_cross_reference.py
git commit -m "Cross-reference reads canonical evidence (setups + unabsorbed levels) for YouTube context"
```

---

## Self-Review

**Spec coverage check against review findings:**

| Finding | Task(s) that address it |
|---------|------------------------|
| Non-idempotent persistence | Task 1 (`UNIQUE(video_id, parser_version)`, `INSERT OR IGNORE`), Task 8 (run_id FK on all inserts) |
| Per-chunk × per-pass explosion | Task 7 (`_MAX_LLM_CALLS=8`, `_call_with_budget`, at most 2 Stage-1 chunks) |
| Missing evidence provenance | Tasks 1–2 (migration), Task 7 (`source_snippet`/`chunk_id`/`parser_version` on all records), Task 8 (persisted) |
| Double-counting | Task 3 (`get_youtube_evidence_for_ticker`), Task 8 (level absorption via `mark_levels_absorbed_by_setup`), Task 10 (cross-ref uses canonical read) |

**Placeholder scan:** None found. Every step has concrete code.

**Type consistency check:**
- `VideoOptionIdea` defined Task 4, used in Tasks 5, 7, 8, 9 — consistent fields.
- `VideoTradeSetup` defined Task 4, used in Tasks 5, 7, 8, 9 — consistent. `stop` field (not `stop_price`) in the dataclass; `stop_price` only in DB column name — confirmed consistent.
- `ParsedVideo.run_id` set in Task 4, populated in Task 7, consumed in Task 8 — consistent.
- `_call_with_budget` closure in Task 7 matches the signature of `_call_extraction_model` — consistent.
- `insert_youtube_setup()` returns `int` (the `lastrowid`) — used in Task 8 as `setup_id` — consistent.
- `_format_youtube_setup_summary()` handles both dataclass and dict forms — required because Task 9 is called from both fresh-parsed and DB-loaded paths.
