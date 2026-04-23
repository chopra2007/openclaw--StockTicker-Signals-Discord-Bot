# YouTube Intelligence Upgrade — Ideas

Raw brainstorm for improving how OpenClaw extracts actionable intelligence
from YouTube financial transcripts. All ideas must be compatible with free or
very cheap LLM models (openrouter free tier, minimax2.5, GLM, etc.).

---

## 1. Options Flow & Trade Ideas Extraction

**What's missing today:**
The parser extracts tickers and direction but the system prompt has no concept
of options. Channels like CheddarFlow, Lottery Stocks, and TheStockWatch
regularly discuss specific options plays — this is all currently dropped.

**What to extract:**
- Option type: call or put
- Strike price
- Expiration (e.g. "weekly", "May 17", "next Friday")
- Strategy type: single leg, spread, debit/credit, LEAPS
- Whether it's a flow observation ("seeing unusual call buying") vs. a
  personal trade idea ("I'm buying the $450 calls")
- Implied conviction: speculative / moderate / high-conviction

**Implementation idea:**
Add a dedicated `"options"` array to the JSON schema the LLM is asked to fill.
Keep it separate from `"tickers"` so the parser can handle videos that mention
options without a directional stock view. Example schema:
```json
"options": [
  {
    "ticker": "TSLA",
    "type": "call",
    "strike": 250.0,
    "expiry": "weekly",
    "strategy": "single",
    "source": "flow_observation|personal_idea",
    "conviction": "high|medium|low",
    "context": "seeing massive call sweep at 250 strike"
  }
]
```

**Cheap model note:**
This is a structured extraction task — even small models do well when the
schema is explicit. A focused prompt for options only (separate from the main
ticker/macro prompt) will outperform a single mega-prompt.

---

## 2. Trade Setups as a Cohesive Unit

**What's missing today:**
Entry, stop, and target are stored as three separate `price_levels` rows with
no link between them. A setup like "buy NVDA at $850, stop at $820, target
$920" is fragmented into three unrelated records.

**What to extract:**
- Entry price or entry zone
- Stop-loss price
- Target price(s) — can be multiple (T1, T2)
- Risk/reward ratio (can be computed from the above)
- Timeframe: intraday / swing / positional / long-term
- Setup type: breakout / pullback-to-support / earnings play / trend continuation

**Implementation idea:**
Add a `"setups"` array distinct from `"price_levels"`:
```json
"setups": [
  {
    "ticker": "NVDA",
    "entry": 850.0,
    "stop": 820.0,
    "targets": [920.0, 980.0],
    "timeframe": "swing",
    "setup_type": "breakout",
    "context": "above $850 triggers the breakout"
  }
]
```
Risk/reward can be computed in Python post-parse: `(target - entry) / (entry - stop)`.

**Why this matters:**
A coherent setup is far more actionable than three loose price levels. It also
enables backtesting: did price reach the target before hitting the stop?

---

## 3. Demand / Supply Zones (Not Just Levels)

**What's missing today:**
The parser extracts single price levels (a number). Zones have a floor and a
ceiling (e.g. "strong demand between $430 and $445") and carry additional
context about how many times they've been tested.

**What to extract:**
- Zone type: demand / supply
- Zone low and high price
- Number of prior tests mentioned ("tested three times")
- Strength assessment from the speaker: "very strong" / "weak" / "fresh"
- Whether the zone is currently being tested vs. is a future level to watch

**Implementation idea:**
Extend or replace `price_levels` for zone-type mentions:
```json
"zones": [
  {
    "ticker": "SPY",
    "type": "demand|supply",
    "low": 430.0,
    "high": 445.0,
    "tests": 3,
    "strength": "strong|moderate|weak",
    "status": "testing_now|watching|broken"
  }
]
```

**Cheap model note:**
Zone extraction from transcripts is harder than level extraction — speakers
describe zones with varied language ("around 430 to 445", "the 430-445 area",
"between 430 and 445"). May need a regex pre-pass to find price ranges before
passing to the LLM for classification.

---

## 4. Multi-Video Consensus Across Channels

**What's missing today:**
Each video is parsed in isolation. There's no aggregation layer that says
"5 of 13 channels mentioned NVDA long this week with high conviction."

**What to build:**
A weekly consensus digest that:
1. Pulls all `youtube_signals` from the last 7 days
2. Counts ticker mentions, direction votes, and conviction-weighted scores
3. Identifies tickers with ≥3 independent channel mentions in the same direction
4. Surfaces contrarian tickers (channels disagreeing on direction)

**Implementation idea:**
A new DB query + digest function, callable via `!yt-consensus` Discord command
or triggered automatically on Mondays. Output format:
```
NVDA: 7 bullish / 1 bearish (confidence: 0.87) — mentioned by Click Capital,
      StockedUp, The Technical Take, CheddarFlow (+4 more)
TSLA: 4 bullish / 4 bearish — split signal, watch for resolution
SPY:  6 bearish / 1 bullish — majority bearish, macro driven
```

This is pure SQL + Python with no LLM needed for the aggregation step.

---

## 5. Sector & Macro Theme Tracking Over Time

**What's missing today:**
Macro themes are extracted per-video but never aggregated or trended. There's
no way to see "energy sector is the dominant theme across the last 10 videos."

**What to build:**
- Store macro themes in a dedicated table (already partially exists as
  `youtube_macro`)
- Add a `themes_trend` view or query: most common themes in last 7 / 30 days
- Track direction shift: was the channel bullish 2 weeks ago but bearish now?
- Surface theme convergence: when ≥4 channels share the same macro theme,
  flag it as a high-confidence macro signal

**Discord command:** `!macro-themes` — rolling 7-day top themes with channel count.

---

## 6. Prompt Decomposition for Cheap Models

**What's missing today:**
The current system prompt asks the LLM to do everything in one shot: tickers,
price levels, macro thesis, conviction. Cheap/small models struggle with
multi-objective prompts and tend to hallucinate or miss fields.

**Better approach — split into focused sub-prompts:**

| Pass | Task | Prompt size | Cheap model? |
|------|------|-------------|--------------|
| 1 | Extract raw mentions: tickers, prices, options | Small | Yes |
| 2 | Classify direction per ticker | Tiny | Yes |
| 3 | Extract macro thesis only | Small | Yes |
| 4 | Build setups by linking entry/stop/target | Small | Yes |

Each pass is cheaper, faster, and more accurate for small models because
the instruction surface is narrow. Results are merged in Python.

This also makes it easy to skip passes (e.g. skip pass 4 if no price levels
were found in pass 1), saving API credits.

---

## 7. Confidence Scoring Based on Channel Track Record

**What's missing today:**
All channels have `trust_score = 1.0` by default. There's no feedback loop
from actual price outcomes to channel trust.

**What to build:**
- After a video's ticker signals are extracted, track whether price moved in
  the predicted direction over the next 24h / 72h / 7d
- Update `youtube_channels.trust_score` based on hit rate
- Weight signals from high-trust channels more heavily in the consensus digest
  and in cross-reference scoring

**Implementation note:**
The `price_outcome_loop` in `main.py` already does outcome tracking for tweet
signals. The same logic could be applied to `youtube_signals` rows — the
infrastructure largely exists, it just needs to be wired up.

---

## 8. Transcript Quality Gating

**What's missing today:**
The minimum word count gate (250 words) is the only quality filter. Some
transcripts are real content; others are intros, ads, or low-information
"market recap" videos that don't contain actionable setups.

**Better gates to add:**
- **Ticker density**: if fewer than 2 unique tickers are mentioned in the
  full transcript, skip LLM analysis (not a trade idea video)
- **Price mention check**: if no price numbers appear in the transcript,
  skip price level extraction (save tokens)
- **Language check**: auto-captions from non-English videos pass through
  as garbled text — detect and skip
- **Duplicate content**: hash-compare transcript bodies to avoid re-analyzing
  reposts or near-identical upload pairs

These gates are all pure Python / regex — no LLM cost.

---

## 9. Actionable Alert Formatting

**What's missing today:**
Discord alerts for YouTube signals are minimal: "🎬 YouTube Signal: $TSLA
[LONG] — CheddarFlow". No price context, no setup, no why.

**Better alert format:**
```
🎬 [CheddarFlow] $TSLA LONG (high conviction)
Entry zone: $240–$245 | Stop: $230 | Target: $275
Setup: breakout above $245 after 3-day consolidation
Options: May $250 calls mentioned
Macro: broad market bullish, tech leading
```

This requires the setup extraction (idea #2) and options extraction (idea #1)
to be implemented first, but the Discord formatting is trivial once the data
exists.

---

## 10. Backfill Existing Transcripts

**What's missing today:**
The 10 transcripts already saved in `artifacts/transcripts/` were fetched but
the LLM analysis pass only runs during the live engine cycle (`process_video`
in `youtube.py`). The catch-up script bypassed dedup but didn't trigger
analysis.

**What to build:**
A `backfill_analysis.py` script that:
1. Scans `artifacts/transcripts/` for JSON files
2. For each, checks if a `youtube_signals` row already exists
3. If not, calls `parse_video_transcript()` directly
4. Writes signals, levels, and macro to DB

This is a one-shot script to extract intelligence from already-saved transcripts
without re-fetching them. Should be run after any parser prompt upgrade so
existing transcripts benefit from the improved extraction.

---

## Priority Order (Suggested)

1. **Prompt decomposition** (idea #6) — foundational, improves all other extraction
2. **Options extraction** (idea #1) — highest signal value for the followed channels
3. **Trade setups as units** (idea #2) — makes levels actionable
4. **Backfill script** (idea #10) — extract value from already-saved transcripts
5. **Multi-video consensus** (idea #4) — aggregation layer, no LLM cost
6. **Transcript quality gates** (idea #8) — reduce wasted API calls
7. **Demand/supply zones** (idea #3) — refinement of existing level extraction
8. **Sector/macro theme tracking** (idea #5) — longer-term intelligence layer
9. **Confidence scoring** (idea #7) — requires outcome data to accumulate first
10. **Alert formatting** (idea #9) — depends on #1 and #2 being done first
