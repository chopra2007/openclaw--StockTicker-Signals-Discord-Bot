# TODO #85 — Real owner feature-questions extracted from #chat

**Source:** `chat-last-100.txt` (last 100 messages of Discord `#chat`, pulled 2026-08-17)
**Extracted:** 2026-08-17

## Headline finding

**Zero natural-language feature questions were found.** The last 100 messages break down as:

| Speaker | Count |
|---|---|
| `API` (the bot itself — alerts, cross-references, command replies) | 95 |
| `akash_chopra` (the owner) | 5 |

All 5 owner messages are bare slash-style commands. None is a question. There are no
`@`-mentions of the bot and no `!ask` calls in this window, therefore **no multi-turn
follow-up pairs exist to preserve in this file.**

**But real owner feature questions WERE recovered from a second source** — the
`chat_memory_rollups` database table. See the section "Second source" below. Three real
questions with three real follow-up chains came out of it.

## Every owner message in the window, verbatim

```
2026-08-17 02:03 AM PDT  akash_chopra: !market
2026-08-17 02:05 AM PDT  akash_chopra: !scan tsla
2026-08-17 02:06 AM PDT  akash_chopra: !em tsla
2026-08-17 02:07 AM PDT  akash_chopra: !emw tsla
2026-08-17 02:07 AM PDT  akash_chopra: !em spy
```

Usable feature questions found: **0 of 5** owner messages.

## What the window *does* give us

Even without questions, the window contains the bot's own **rendered output** for exactly
the features TODO #85 names as needing test coverage. That output is the surface an owner
question would be asked *about*, so it is the raw material for writing the test set and its
answer key. Quoted verbatim below with timestamps.

---

### 1. "Our own signal breadth" — the key example feature

Owner asked (line 291):
> `2026-08-17 02:03 AM PDT  akash_chopra: !market`

Bot replied (line 292–303, breadth portion at line 299):
> `2026-08-17 02:03 AM PDT  API:` … 🐂  Our own signal breadth: Net +72 (153 bullish − 81 bearish tickers), trend z-score +1.04 → more bullish than usual.
> _Market context only (a view, not a buy/sell signal). The bot's directional stream is structurally long-biase[d]…_

This is the live number a question like *"What is Our own signal breadth, what tickers are
measured, and can you add 2 more tickers to the list?"* would be pointed at. `153` and `81`
are counts of **distinct tickers**, not a watchlist.

### 2. "Fear of fear (VVIX vs VIX)" — named in TODO #85 step 1

Same `!market` reply (line 301–302):
> 😰  Fear of fear (VVIX vs VIX): Normal — protection against volatility costs about what the VIX explains.
> Today's reading is higher than 42% of the past year's readings.
> VVIX 87.5 (−2.2% today) vs VIX 14.2 (−2.6% today) (2026-08-14 …

### 3. Expected move — named in TODO #85 step 1

Owner asked (lines 329–337) — three commands in a row, two of which first failed:
> `2026-08-17 02:06 AM PDT  akash_chopra: !em tsla`
> `2026-08-17 02:06 AM PDT  API: Calculating daily expected move for $TSLA…`
> `2026-08-17 02:06 AM PDT  API: Options for this ticker/expiration are too illiquid for a reliable expected move (zero bids, wide spreads, or thin open interest).`
> `2026-08-17 02:07 AM PDT  akash_chopra: !emw tsla`
> `2026-08-17 02:07 AM PDT  API: Calculating weekly expected move for $TSLA…`
> `2026-08-17 02:07 AM PDT  API: Options for this ticker/expiration are too illiquid for a reliable expected move (zero bids, wide spreads, or thin open interest).`
> `2026-08-17 02:07 AM PDT  akash_chopra: !em spy`
> `2026-08-17 02:07 AM PDT  API: Calculating daily expected move for $SPY…`
> `2026-08-17 02:07 AM PDT  API: Options for this ticker/expiration are too illiquid for a reliable expected move (zero bids, wide spreads, or thin open interest).`

Then ~29 minutes later the same three came back with real numbers (lines 338–385), e.g.:
> `2026-08-17 02:36 AM PDT  API: [📊  TSLA — Daily Expected Move] | Daily · expires 2026-08-19 · 2 trading sessions left … Expected move: ±$10.95 / ±3.20% / ATM straddle price … ATM implied volatility 47.0% a year. An at-the-money straddle prices about 0.8 of one standard deviation, so the straddle range abov[e]…`

**This is the strongest natural source of a real follow-up question** ("why did `!em tsla`
say illiquid at 2:06 and then work at 2:36?"), and of a **wrong-premise** question
("the expected move is the price target, right?" — it is not; the reply explicitly says
"not which way").

### 4. Alert scores — named in TODO #85 step 1

Repeated cross-reference cards carry the full score breakdown, e.g. line 206:
> `2026-08-16 04:52 PM PDT  API: [Cross-Reference: $MU | Score: 56] … Precision Engine: 🟡 WATCHLIST | score=56 | market ✅ | Regime: 🟢 Market stress: 41/100 (normal) | Breakdown: base(25) + analysts(20) + news(15) + tech(8) + llm(10) = 88 raw → 56 after quality gates`

Note the raw-vs-final gap (88 raw → 56 final; and at line 163, 68 raw → **84** final — the
gates move the score *up* there). A question about why the raw and final numbers differ,
and why gates can raise as well as lower, is a good grounded test.

Owner also ran the score path directly (line 304–313):
> `2026-08-17 02:05 AM PDT  akash_chopra: !scan tsla`
> `2026-08-17 02:05 AM PDT  API: Scanning $TSLA...`
> `2026-08-17 02:06 AM PDT  API: **$TSLA Scan** 🔴 **Score: 50** Next earnings: 2026-10-20 … Technical: 1/6 filters passed`

### 5. Analyst groups — named in TODO #85 step 1

Line 428 (a staged test card, not an owner question):
> `2026-08-17 03:52 AM PDT  API: <@615525529537216513> 🧪 SAFE TEST — TODO #83/#84 — reviewed historical analyst-group card | [🚨 $AAPL — 2 analysts tweeting in 41 min] | Group bias: 🟢 Bullish · 2 bullish · 0 bearish · 0 unclear | Analyst views: [@DeItaone](…) — 🟢 Bullish — Analyst says: APPLE UPGRADED TO BUY — $400 TARGET [@OMillionaires](…`

### 6. Other features present in the window (potential extra coverage)

- Short-interest setup (line 444): `🩳 Squeeze candidate — 3.1 days to cover (about three normal trading days for short-sellers to buy back), short interest up 25.9% from the prior report. Latest report: 2026-07-31.`
- Sector rotation / style leadership / price-trend regime / NFCI (lines 294–303 in the same `!market` reply).
- Macro digest (line 445): `📊 Macro Digest (via YouTube): BULLISH (9 channels) / BEARISH (2) / NEUTRAL (35)`
- `Phase 2 skipped — low precision` (line 386) — an opaque internal phrase an owner would plausibly ask about.

---

## Second source: real owner questions RECOVERED from `chat_memory_rollups`

The 100-message window is a dead end, so I checked the database table the agent itself uses
to remember past chats: `chat_memory_rollups` in `consensus.db` (6 rows, spanning
2026-05-19 → 2026-06-02 UTC). Full dump saved as `chat-memory-rollups-dump.txt`.

**These rows contain genuine owner feature questions, including multi-turn repeats.** Caveats
first, because they matter for grading:

- The rollups are **summaries, not transcripts**. Every answer is truncated by the rollup
  writer at a trailing `…`, so the full bot answer is *not* recoverable from here.
- Owner questions appear **verbatim and complete** (they are short), so they are directly
  reusable as test inputs.
- All 6 rows predate the TODO #79 reliability fixes (May–June 2026), so the *failures* below
  are historical and may already be fixed — but the *questions* are still real.

### Q1 — feature question: where does a data feed come from

From rollup `id=6` (channel `1510722777923981432`, 2026-06-02) and rollup `id=4`:
> `Q: Where is the unusual options flow data coming from?`
> `A: [assistant turn failed before producing content]`

Owner then clarified — itself a usable test input:
> `Q: Internal host. (If I'm asking you a question, I never want general data.)`
> `A: [assistant turn failed before producing content]`

Asked a third time, it did answer (rollup `id=4`):
> `A: The unusual‑options‑flow alerts are built from the option‑chain data fetched by the yfinance library (Yahoo Finance) in `consensus_engine/scanners/options.py` (via the `_fetch_flow_chains`/`_fetch` functions that call `…`

But in rollup `id=6` the same question produced a **different and partly wrong** answer:
> `A: The unusual options flow data in this system originates from two distinct sources: 1. **Free Setups Data** - Located in: `/root/.openclaw/workspace/scanners/unusual_options_flow.py` - Free source files include `free_set…`

`scanners/unusual_options_flow.py` at that path is not the real module (the real one is
`consensus_engine/scanners/options.py`). **This is an invented-file-path failure — exactly the
failure mode TODO #85's grading criteria call out.** It is also now stale in a second way:
options flow moved to the Schwab feed (`features.schwab_options`), so a correct answer today
differs from the correct answer in June.

### Q2 — feature question with a follow-up demand, asked 5 times in a row

Rollup `id=6`, 2026-06-02 — the clearest **multi-turn** artifact in the whole dataset:
> `Q: What does Wolf say about Google? Can you show me where he mentions this in the email?`
> `A: The unusual options flow data in this system originates from two distinct sources: …`  ← **answered the PREVIOUS question**
> `Q: What does Wolf say about Google? Can you show me where he mentions this in the email?`  ← *(no answer recorded)*
> `Q: What does Wolf say about Google? Can you show me where he mentions this in the email?`  ← *(no answer recorded)*
> `Q: What does Wolf say about Google? Can you show me where he mentions this in the email?`
> `A: Wolf has a **bull‑forming** thesis for **GOOG** (Alphabet/Google) that is stored in the system's database. The entry was created from a Wolf newsletter email with the subject line: ``` [Wolf On Wall Street Trade] Higher…`
> `Q: What does Wolf say about Google? Can you show me where he mentions this in the email?`
> `A: **Wolf's view on Google (GOOG)** - **Direction:** bull - **Stage:** forming The thesis is stored in the SQLite database at `/home/openclaw/.openclaw/workspace/consensus.db` in the **`macro_theses`** table (row ID 59). T…`
> `Q: What does Wolf say about Google? Can you show me where he mentions this in the email?`
> `A: **Wolf's thesis on Google (GOOG)** - **Direction:** bull - **Stage:** forming **Source email** – *Subject:* **"[Wolf On Wall Street Trade] Higher Rates Hitting Long Duration Tech/Semis"** (Gmail message ID `19e3c677b009…`
> `Q: What does Wolf say about Google? Can you show me where he mentions this in the email?`
> `A: Wolf's current thesis on **GOOG** is **bull / forming**. **Source email** – Subject: **"[Wolf On Wall Street Trade] Higher Rates Hitting Long Duration Tech/Semis"** (Gmail message ID `19e3c677b009e2b4`). **Excerpt from…`

Three distinct failures visible in one exchange:
1. **Answer/question mismatch** — reply 1 answered the options-flow question, not the Google one.
2. **The owner had to re-ask five times** to get the email excerpt he asked for in turn one.
3. **Leaked retrieval plumbing** — the answers surface a Gmail message ID and a DB row ID. The
   current `_STEERING_TEMPLATE` explicitly forbids that ("no internal Gmail/Discord message IDs"),
   so this is a rule that was added *because* of this exchange, and it needs a regression test.

### Q3 — a real bug-hunt follow-up (rollups `id=1,2,3,4`, 2026-05-20)

> `Q: No shit Sherlock. I want you to find out why it's giving false signals and let me know.`
> `A: The problem is confirmed. The `fetch_recent_earnings_for_ticker` function returns `period: "2026-06-30"` for NVDA - this is **Q1 2026 earnings** that haven't been reported yet (scheduled for after today's market close).…`
> `Q: No shit Sherlock. I want you to find out why it's giving false signals and let me know.`  *(asked again)*
> `A: **Root Cause Found:** The `fetch_recent_earnings_for_ticker` function in `consensus_engine/scanners/earnings_calendar.py` doesn't filter for past earnings dates. Finnhub's `/stock/earnings` endpoint returns ALL quarters…`

Useful as a **tone/frustration** test case: the owner is annoyed and wants a root cause, not a
restatement. The first reply restated the symptom; the second found the cause.

### Non-feature probe questions in the rollups (not usable as feature tests)

`hello?`, `what is 2+2? one word`, `Reply with exactly the word: pong`, `PONG-VERIFY`,
`MODELSWAP-MENTION-… reply with 'pong-mention'`, `In one short sentence, what is the capital
of France?`, `Use web_search to find one recent NVDA stock news headline.` — all staged
liveness probes from prior sessions. Two of them show the **wrong-room-context bug**: the
capital-of-France question got the answer `Tokyo.` in one turn, and a `!all TSLA` context
block got answered `108`.

## Tally of recoverable owner questions

| Source | Real feature questions | Multi-turn pairs |
|---|---|---|
| `#chat` last 100 messages | **0** | 0 |
| `chat_memory_rollups` (6 rows, May–Jun 2026) | **3 distinct** (Q1, Q2, Q3) | **3** (Q1 ×3 asks, Q2 ×5 asks, Q3 ×2 asks) |

## Consequence for TODO #85 step 1

Step 1 says "Build a real test set from recoverable owner questions in `#chat` … Do not rely on
invented easy questions alone."

- From `#chat` itself: **nothing recoverable.**
- From the rollups: **3 real questions with 3 real follow-up chains** — enough to satisfy the
  "not invented" requirement, but nowhere near the 6+ feature areas step 1 lists.
- The remaining coverage (breadth, VVIX vs VIX, expected move, alert scores, analyst groups,
  wrong-premise) **must be authored**, using the live rendered output quoted earlier in this
  file as the grounding. That should be stated openly in the TODO rather than glossed.

See `README.md` in this folder for the gaps and how to widen the history pull.
