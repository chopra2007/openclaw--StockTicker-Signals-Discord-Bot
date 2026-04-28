# Spec 01 — Prompt Hardening (Layer 1)

**Goal:** Reduce ticker hallucinations at the source by tightening the two Gemini prompts so the model is explicitly forbidden from inferring tickers it didn't literally observe.

**Sizing:** TINY (~20 LOC, prompt strings only).

**Scope:** Prompt strings only. No code logic changes. No tests for prompt content beyond a snapshot test.

---

## Why this layer is cheap and worth doing first

Both prompts already exist and run on every video. We get the benefit (lower hallucination rate) on the *next* video processed after merge — no migration, no backfill needed for newly-extracted spans. The layer below (quote grounding) catches what slips through; this layer reduces what slips through in the first place.

---

## (a) `_EVIDENCE_PROMPT` — used by Path A (v2 evidence-first)

**File:** `consensus_engine/analysis/gemini_video_parser.py`
**Current location:** lines 68–90

**Current weakness:** The prompt says "tickers = UPPERCASE real stock/ETF symbols only" but never explicitly forbids inference. A model under low-resolution video tokenization (`media_resolution: low`) can fill in tickers that "feel right" given the topic.

```diff
 _EVIDENCE_PROMPT = """You are a transcription assistant for a financial YouTube video. You do NOT classify. You do NOT label support/resistance. You do NOT give direction or conviction. Your job is only to extract verbatim timestamped evidence.

 Watch the full video and respond ONLY with this exact JSON (no markdown fences, no commentary):
 {
   "duration_sec": 2340,
   "segments": [
     {"ts_start_sec": 2022, "title": "Number One Draft Pick: MSFT"}
   ],
   "spans": [
     {"ts_sec": 2024, "quote": "exact verbatim sentence as spoken", "tickers": ["MSFT"], "numbers": [], "dates_mentioned": []},
     {"ts_sec": 2172, "quote": "Bullish bias into April 29th earnings with an entry target at 400.15", "tickers": ["MSFT"], "numbers": [400.15], "dates_mentioned": ["April 29"]}
   ]
 }

 Extraction rules:
 - Include EVERY span mentioning a ticker, a price, or a date. Skip pure chit-chat and off-topic banter.
 - `ts_sec` is an integer second offset from the video start. Use the speaker's actual time, not the segment's.
 - `quote` must be verbatim or near-verbatim auto-caption text — NO paraphrase, NO summarization.
-- `tickers` = UPPERCASE real stock/ETF symbols only (e.g., NVDA, SPY, MSFT). Reject technical-analysis abbreviations (RSI, EMA, MACD, VWAP, SMA, ATR, MA). Empty array if none.
+- `tickers` = UPPERCASE real stock/ETF symbols only (e.g., NVDA, SPY, MSFT). Reject technical-analysis abbreviations (RSI, EMA, MACD, VWAP, SMA, ATR, MA). Empty array if none.
+- CRITICAL — only include a ticker in `tickers` if EITHER the symbol is literally spoken in the quote (e.g., "NVDA", "Nvidia"), OR it is visibly displayed as a chart label / on-screen text within ±5 seconds of `ts_sec`. Do NOT infer tickers from sector context, related-stock chatter, or general topic. If the quote does not name a specific company, leave `tickers` empty.
+- A span about "the chip sector" without a named company has `tickers: []`. A span about Burry buying AMC has `tickers: ["AMC"]` only — never add NVDA, GOOGL, or other "related" names.
 - `numbers` = raw numeric values that appear in the quote (e.g., 400.15, 18). Empty array if none.
 - `dates_mentioned` = raw date strings exactly as spoken ("April 29", "next Wednesday", "Friday"). Do NOT resolve to ISO dates.
 - Do NOT emit direction, conviction, support/resistance labels, setup_type, or any macro summary. Those come from post-processing.
 - Target 30–80 spans for a 40-minute video. If no qualifying spans, return an empty `spans` array."""
```

**LOC delta:** +2 lines.

---

## (b) `_GEMINI_PROMPT` — used by Path B (legacy single-call Gemini)

**File:** `consensus_engine/analysis/gemini_video_parser.py`
**Current location:** lines 34–65

**Current weakness:** The prompt asks for tickers/levels/setups directly with no grounding constraint. This is the prompt that generated the NVDA hallucination on `vkqchQQnm88`.

```diff
 _GEMINI_PROMPT = """You are a financial analyst extracting structured trade intelligence from a YouTube video.

 Watch the full video and respond ONLY with this exact JSON (no markdown, no extra text):
 {
   "tickers": [
     {"symbol": "NVDA", "direction": "long|short|neutral", "conviction": "high|medium|low", "mention_count": 3, "context": "why this direction — quote or paraphrase"}
   ],
   ...
 }

 Extraction rules:
 - Only real stock tickers (AAPL, NVDA, SPY, etc.). Exclude RSI, EMA, MACD, VWAP, SMA, ATR, etc.
+- CRITICAL — every entry in `tickers`, `price_levels`, `options`, and `setups` MUST reference a company that is either spoken by name or shown on-screen in the video. Do NOT include "related" or "sector peer" tickers. The `context` field MUST contain a verbatim or near-verbatim quote that names the ticker (or its company name like "Nvidia", "Tesla").
+- If you find yourself adding a ticker because the topic is "tech stocks" or "AI" or "meme stocks" without the speaker naming the specific company, leave it out. Empty arrays are correct when nothing specific is discussed.
 - price_levels: include BOTH verbally mentioned prices AND price levels visible as annotated lines or labels on charts in the video.
 - options: empty array if none discussed. strike is null if not mentioned.
 - setups: link entry/stop/target only when the speaker presents them together. Empty array if unclear.
 - context: quote or closely paraphrase the speaker for every extracted item.
 - If no tickers found, return empty arrays for tickers, price_levels, options, setups."""
```

**LOC delta:** +2 lines.

---

## Verification

```bash
# Snapshot test: prompt content matches expected (catches accidental edits)
python3 -m pytest tests/analysis/test_prompts.py -v
```

Snapshot test asserts:
- `"do NOT infer tickers"` substring present in `_EVIDENCE_PROMPT`.
- `"do NOT include "related" or "sector peer" tickers"` substring present in `_GEMINI_PROMPT`.

No behavioural test — prompt effectiveness is measured by Layer 2's quote-grounding test that replays the incident video.

---

## Out of scope

- The transcript-fallback prompts in `video_parser.py` — those run on text we already have; grounding works differently and is handled in Layer 2.
- Switching models (`gemini-2.5-flash-lite` → `flash`) — orthogonal cost/quality decision.
