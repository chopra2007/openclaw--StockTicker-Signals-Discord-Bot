# Spec 02 — Quote Grounding (Layer 2, the core fix)

**Goal:** Drop any ticker label that does not appear literally (or via alias) in the evidence text the LLM itself produced. This is the deterministic check that would have prevented the NVDA-on-AMC-video incident on its own.

**Sizing:** SMALL-MEDIUM (~180 LOC + ~140 test LOC).

---

## Why this is the most important layer

The LLM emits two pieces of data per span:
- `quote`: a verbatim string the model claims it heard / read in the video.
- `tickers[]`: a list of stock symbols the model claims belong to that span.

The `quote` is anchored to actual content. The `tickers[]` list is a label the model produced. **The label can be wrong even when the quote is right.**

Quote grounding is: for each ticker in `tickers[]`, require a literal match in `quote`. If the model says NVDA but writes a quote about AMC, drop NVDA from that span.

This is a $0-cost runtime check (one regex per ticker per span; spans are typically <100 per video, tickers <5 per span).

---

## (a) New module: `consensus_engine/analysis/ticker_grounding.py`

```python
"""Ticker grounding — verify a ticker label is literally supported by evidence text.

The LLM (Gemini in v2 + legacy paths, OpenRouter in transcript fallback) emits a
ticker label alongside an evidence string. The label is hallucination-prone; the
evidence string is anchored. This module checks that the label is supported by
the string.

Used by:
- gemini_video_parser._build_evidence_bundle (Path A)
- gemini_video_parser._build_parsed_video (Path B)
- video_parser._parse_llm_response and _fallback_parse (Path C)
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("consensus_engine.analysis.ticker_grounding")

# ─── Alias map ─────────────────────────────────────────────────────────────
# Curated company-name → ticker map for common cases where speakers say the
# company name without the symbol. Loaded from config/ticker_aliases.json so
# operators can add tickers without code changes.
#
# Format: { "TICKER": ["alias1", "alias2", ...] } — aliases stored lowercase
# during runtime normalization.

_DEFAULT_ALIASES_PATH = "config/ticker_aliases.json"


@lru_cache(maxsize=1)
def _load_aliases() -> dict[str, tuple[str, ...]]:
    """Load alias map. Lowercase aliases. Cached for process lifetime."""
    path = Path(_DEFAULT_ALIASES_PATH)
    if not path.exists():
        log.warning("ticker_grounding: alias file %s missing — using empty map", path)
        return {}
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("ticker_grounding: failed to parse %s: %s", path, exc)
        return {}
    out: dict[str, tuple[str, ...]] = {}
    for ticker, aliases in raw.items():
        if not isinstance(aliases, list):
            continue
        norm = tuple(a.strip().lower() for a in aliases if isinstance(a, str) and a.strip())
        if norm:
            out[ticker.upper()] = norm
    return out


def _reset_alias_cache() -> None:
    """Test helper — clear the alias cache so reloads pick up edits."""
    _load_aliases.cache_clear()


# ─── Core grounding API ────────────────────────────────────────────────────

def is_ticker_grounded(ticker: str, text: str) -> bool:
    """True if `ticker` is literally supported by `text`.

    Grounding succeeds if any of:
    - $TICKER appears (e.g., $NVDA)
    - Bare TICKER appears as a word (e.g., NVDA, but not NVDAQ)
    - A registered alias appears as a word (e.g., "nvidia" for NVDA)

    Case-insensitive. Punctuation tolerant. Diacritics not handled (rare in EN
    finance content).
    """
    if not ticker or not text:
        return False
    sym = ticker.strip().upper()
    if not sym:
        return False
    low = text.lower()
    sym_low = sym.lower()

    # $NVDA — strongest signal
    if re.search(rf"\${re.escape(sym_low)}\b", low):
        return True

    # Bare NVDA as a whole word (not part of NVDAQ, etc.)
    if re.search(rf"\b{re.escape(sym_low)}\b", low):
        return True

    # Alias check
    for alias in _load_aliases().get(sym, ()):
        if re.search(rf"\b{re.escape(alias)}\b", low):
            return True

    return False


def filter_tickers_by_grounding(
    tickers: list[str], text: str,
) -> tuple[list[str], list[str]]:
    """Split a ticker list into (grounded, dropped).

    Use this when you have a ticker list per evidence span/snippet.
    """
    grounded: list[str] = []
    dropped: list[str] = []
    for t in tickers:
        if is_ticker_grounded(t, text):
            grounded.append(t)
        else:
            dropped.append(t)
    return grounded, dropped


def assert_ticker_grounded_in_any(
    ticker: str, texts: list[str],
) -> bool:
    """True if `ticker` is grounded in at least one of the provided texts.

    Used for video-level allowlisting where a ticker is allowed if grounded in
    title, description, OR any span quote (Layer 3 wires this up).
    """
    return any(is_ticker_grounded(ticker, t) for t in texts if t)
```

---

## (b) Integrate into Path A (`_build_evidence_bundle`)

**File:** `consensus_engine/analysis/gemini_video_parser.py`
**Current function:** lines 309–347

```diff
 def _build_evidence_bundle(data: dict, video_id: str, published_at: str) -> EvidenceBundle:
     """Convert evidence-only JSON into an EvidenceBundle. Filters TA abbreviations."""
+    from consensus_engine.analysis.ticker_grounding import filter_tickers_by_grounding
+
     duration = data.get("duration_sec")
     try:
         duration_sec = int(duration) if duration is not None else None
     except (TypeError, ValueError):
         duration_sec = None

     segments: list[dict] = []
     for seg in data.get("segments", []) or []:
         if not isinstance(seg, dict):
             continue
         segments.append({
             "ts_start_sec": _parse_ts_str(seg.get("ts_start_sec", 0)),
             "title": str(seg.get("title", "")),
         })

     spans: list[EvidenceSpan] = []
+    drop_count = 0
     for sp in data.get("spans", []) or []:
         if not isinstance(sp, dict):
             continue
         quote = str(sp.get("quote", "")).strip()
         if not quote:
             continue
+        # Filter tickers to those grounded in this span's quote.
+        raw_tickers = _clean_tickers(sp.get("tickers", []))
+        grounded, dropped = filter_tickers_by_grounding(raw_tickers, quote)
+        if dropped:
+            log.info(
+                "ticker_grounding: dropped %s from span ts=%s video=%s quote=%r",
+                dropped, sp.get("ts_sec"), video_id, quote[:80],
+            )
+            drop_count += len(dropped)
         spans.append(EvidenceSpan(
             ts_sec=_parse_ts_str(sp.get("ts_sec", 0)),
             quote=quote,
-            tickers=_clean_tickers(sp.get("tickers", [])),
+            tickers=grounded,
             numbers=_clean_numbers(sp.get("numbers", [])),
             dates_mentioned=_clean_dates(sp.get("dates_mentioned", [])),
         ))
+    if drop_count:
+        log.warning(
+            "ticker_grounding: video=%s dropped %d ungrounded ticker labels across spans",
+            video_id, drop_count,
+        )

     return EvidenceBundle(
         video_id=video_id,
         duration_sec=duration_sec,
         publish_ts=published_at,
         segments=segments,
         spans=spans,
     )
```

**Note on classifier impact:** `video_classifier._unique_tickers` collects tickers from span lists; with grounding upstream, ungrounded tickers never reach `_unique_tickers`. Existing classifier rules and tests are unaffected.

**LOC delta:** +13 lines.

---

## (c) Integrate into Path B (`_build_parsed_video`)

**File:** `consensus_engine/analysis/gemini_video_parser.py`
**Current function:** lines 371–500

Path B has no `quote` field — the model returns `tickers[].context`, `price_levels[].context`, `options[].context`, `setups[].context`. Use `context` as the grounding string.

If `context` is empty (legacy responses sometimes omit it), the row is dropped — we cannot ground a label without evidence. This is intentional: an ungrounded $850 NVDA setup is exactly the failure mode we are eliminating.

```diff
 def _build_parsed_video(
     data: dict, video_id: str, channel_name: str, published_at: str, run_id: int
 ) -> ParsedVideo:
     """Convert Gemini JSON response dict into a ParsedVideo."""
+    from consensus_engine.analysis.ticker_grounding import is_ticker_grounded
+
     # Tickers
     raw_tickers = data.get("tickers", [])
     _dir_norm = {"long": "long", "short": "short", "neutral": "neutral",
                  "bullish": "long", "bearish": "short"}
     normalized_tickers = []
+    dropped_legacy: list[str] = []
     for t in raw_tickers:
         if not isinstance(t, dict):
             continue
         sym = str(t.get("symbol", "")).upper()
         if not sym:
             continue
+        ctx = str(t.get("context", ""))
+        if not is_ticker_grounded(sym, ctx):
+            dropped_legacy.append(sym)
+            continue
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
+    if dropped_legacy:
+        log.warning(
+            "ticker_grounding (Path B): video=%s dropped ungrounded ticker labels: %s",
+            video_id, dropped_legacy,
+        )

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
+        ticker = str(lv.get("ticker", "")).upper()
+        ctx = str(lv.get("context", ""))
+        if ticker and not is_ticker_grounded(ticker, ctx):
+            log.info("ticker_grounding (Path B): dropped level %s @ %.2f, ungrounded", ticker, price)
+            continue
         price_levels.append(PriceLevel(
-            ticker=str(lv.get("ticker", "")).upper(),
+            ticker=ticker,
             level_type=str(lv.get("type", "support")).lower(),
             price=price,
-            condition=str(lv.get("context", "")),
+            condition=ctx,
             consequence="",
             confidence=0.8,
         ))
```

Apply the same `is_ticker_grounded(ticker, context)` gate to the `options` loop (lines ~427–450) and the `setups` loop (lines ~452–488). Each addition is +3 lines.

**LOC delta:** +30 lines (across tickers/price_levels/options/setups).

---

## (d) Integrate into Path C (`video_parser._parse_llm_response` + `_fallback_parse`)

**File:** `consensus_engine/analysis/video_parser.py`

For the LLM-JSON path (`_parse_llm_response`, lines 559–638), apply grounding using the original transcript text. The function already receives `transcript: str`; it just doesn't use it for ticker filtering today. We thread the transcript through and ground each ticker.

```diff
 def _parse_llm_response(raw: str, video_id: str, transcript: str) -> dict:
     """Parse the LLM JSON response into structured data. Falls back to regex on failure."""
+    from consensus_engine.analysis.ticker_grounding import is_ticker_grounded
+
     ...
     normalized_tickers = []
     for t in tickers:
         if isinstance(t, dict):
             symbol = str(t.get("symbol", "")).upper()
+            context = t.get("context", "")
+            # Ground against ticker's own context, falling back to full transcript
+            # (transcript can be 10K+ words; context is the LLM's own quoted reason).
+            if symbol and not (
+                is_ticker_grounded(symbol, context)
+                or is_ticker_grounded(symbol, transcript)
+            ):
+                continue
             ...
```

Apply same pattern to the `price_levels` loop in `_parse_llm_response` (lines 607–622).

For `_fallback_parse` (lines 695–734), the transcript-only regex path already filters via `_has_financial_context`. Add a final grounding pass:

```diff
 def _fallback_parse(transcript: str) -> dict:
     ...
     # Disambiguation gate: reject plain-word tickers without financial context
     tickers_found = [t for t in tickers_found if _has_financial_context(t, transcript)]
+    # Grounding (alias-aware) — redundant with extract_tickers but cheap and
+    # ensures Path C output is consistent with Paths A/B.
+    from consensus_engine.analysis.ticker_grounding import is_ticker_grounded
+    tickers_found = [t for t in tickers_found if is_ticker_grounded(t, transcript)]
     ...
```

**LOC delta:** +15 lines.

---

## (e) Alias config: `config/ticker_aliases.json`

Top-N aliases curated by hand. Include the most-mentioned tickers in finance YouTube content.

```json
{
  "AAPL": ["apple"],
  "MSFT": ["microsoft"],
  "GOOGL": ["google", "alphabet"],
  "GOOG": ["google", "alphabet"],
  "AMZN": ["amazon"],
  "META": ["meta", "facebook"],
  "NVDA": ["nvidia"],
  "TSLA": ["tesla"],
  "AMD": ["amd"],
  "NFLX": ["netflix"],
  "DIS": ["disney"],
  "BRK.B": ["berkshire", "berkshire hathaway"],
  "BRK.A": ["berkshire class a"],
  "JPM": ["jpmorgan", "jp morgan", "morgan chase"],
  "BAC": ["bank of america"],
  "GS": ["goldman", "goldman sachs"],
  "WMT": ["walmart"],
  "COST": ["costco"],
  "BA": ["boeing"],
  "GE": ["general electric"],
  "F": ["ford"],
  "GM": ["general motors"],
  "PYPL": ["paypal"],
  "SQ": ["block", "square"],
  "INTC": ["intel"],
  "CRM": ["salesforce"],
  "ORCL": ["oracle"],
  "ADBE": ["adobe"],
  "NKE": ["nike"],
  "MCD": ["mcdonald"],
  "SBUX": ["starbucks"],
  "PEP": ["pepsi", "pepsico"],
  "KO": ["coca-cola", "coca cola"],
  "AMC": ["amc entertainment"],
  "GME": ["gamestop"],
  "PLTR": ["palantir"],
  "RBLX": ["roblox"],
  "COIN": ["coinbase"],
  "HOOD": ["robinhood"],
  "SNOW": ["snowflake"],
  "UBER": ["uber"],
  "LYFT": ["lyft"],
  "ABNB": ["airbnb"],
  "SHOP": ["shopify"],
  "RIVN": ["rivian"],
  "LCID": ["lucid"]
}
```

~45 entries cover the 90th-percentile of finance YouTube ticker mentions. Operators add more on demand by editing the file (cache TTL is one process — restart picks up edits, plus `_reset_alias_cache()` for tests).

---

## Verification

```bash
# Unit tests
python3 -m pytest tests/analysis/test_ticker_grounding.py -v

# Integration: NVDA-on-AMC-video case must not pass
python3 -m pytest tests/analysis/test_gemini_video_parser.py::test_evidence_bundle_drops_ungrounded_nvda -v
python3 -m pytest tests/analysis/test_gemini_video_parser.py::test_legacy_path_drops_ungrounded_nvda -v
python3 -m pytest tests/analysis/test_video_parser.py::test_transcript_path_drops_ungrounded_nvda -v
```

Test cases in `tests/analysis/test_ticker_grounding.py` (covered fully in Spec 06):
- `is_ticker_grounded("NVDA", "Burry bought more AMC")` → False
- `is_ticker_grounded("NVDA", "Nvidia is my favorite")` → True (alias)
- `is_ticker_grounded("NVDA", "$NVDA breakout")` → True ($-prefix)
- `is_ticker_grounded("NVDA", "NVDA breaking out")` → True (bare symbol)
- `is_ticker_grounded("NVDA", "the NVDAQ exchange")` → False (substring, not word)
- `is_ticker_grounded("AAPL", "apple stock")` → True (alias, case-insensitive)
- 20+ alias cases covering the JSON config.

---

## Out of scope

- Diacritic normalization (rare in EN finance content; deferred).
- Phonetic matching ("invidia" / typos) — deferred; alias map is the upgrade path.
- Stock-name fuzzy match (Levenshtein) — overkill; literal + curated alias is sufficient evidence.
