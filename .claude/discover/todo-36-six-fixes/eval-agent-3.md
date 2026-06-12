# Eval Agent 3 — Issue 3a (TweetShift bull/bear field) + Issue 1 (@-mention warning boxes)

Read-only investigation. No files/config/services changed. Repo root: `/home/openclaw/.openclaw/workspace`.
Active DB: `/home/openclaw/.openclaw/workspace/consensus.db` (449 MB, written today 18:12; path from `config/consensus.yaml` line 662 `database.path`).

---

## ISSUE 3a — TweetShift bull/bear field

### A. The detail file's suggested query is WRONG — there is no `tweetshift` source_type

The detail file says run `SELECT source_type, direction FROM signal_events WHERE source_type='tweetshift'`.
That returns ZERO rows. The actual source_type for tweets is `twitter`, not `tweetshift`.

```
sqlite> SELECT source_type, COUNT(*) FROM signal_events GROUP BY source_type;
twitter   2966
youtube   23
```
(No `tweetshift` row exists.) TweetShift is the Discord source; the engine stores those rows under `source_type='twitter'`.

### B. `direction` EXISTS and IS POPULATED — in TWO tables

**`signal_events` table** — schema (`PRAGMA table_info(signal_events)`):
```
id INTEGER pk | source_type TEXT | source_detail TEXT | ticker TEXT |
direction TEXT | quality_score REAL | latency_sec REAL | provenance TEXT |
model_version TEXT | recorded_at REAL | consumed_by_cluster_id INTEGER | source_link TEXT
```
`direction` distribution for `source_type='twitter'`:
```
long    1669
''       755   (empty string)
short   542
```
So ~68% carry a non-empty direction (`long`/`short`). BUT `signal_events.provenance` is the literal string `"tweet"` — **the actual tweet text is NOT stored here.** No `text` column exists.

**`ticker_signals` table** — THE BETTER SOURCE. schema:
```
id INTEGER pk | ticker TEXT | source_type TEXT | source_detail TEXT |
raw_text TEXT | sentiment TEXT default 'neutral' | detected_at REAL | expires_at REAL
```
This table has BOTH:
- `sentiment` (`bullish` / `bearish` / `neutral`) — the bull/bear classification, already populated
- `raw_text` — the actual tweet text (for the "one random example")

Sentiment distribution for `source_type='twitter'`:
```
bullish   1726
neutral    907
bearish    606
```

Sample rows (latest, with real text):
```
ticker=SNDK  sentiment=bullish  source_detail=EliteOptions2  raw="TRADE PLAN for LOTTO Friday 📈 $SPX wow what a day.. We got Iran news..."
ticker=ASTS  sentiment=bearish  source_detail=SpacGuru       raw="So do I sell $RKLB $ASTS $PL Prior to $SPCE?..."
ticker=TSLA  sentiment=bullish  source_detail=The_RockTrading raw="$TSLA Divergence posted yesterday working out here."
ticker=PZZA  sentiment=bearish  source_detail=MarketRebels    raw="$PZZA shutters nearly 50 locations across 17 states..."
```

### C. Retention — old rows are KEPT (a midnight→now query works)

`ticker_signals` twitter rows span `2026-04-07` → `2026-06-12` (n=3239). Of those, **3237 are already past `expires_at`** but still in the table. The TTL (`signal_ttl_hours: 2`) only affects the `get_active_tickers` "unexpired" query (`WHERE expires_at > now`); it does NOT delete rows. (There IS a `DELETE FROM ticker_signals WHERE expires_at < ?` at db.py:1476 — but evidently not run, or runs rarely; rows from April survive.) **A "today midnight→now" SELECT on `detected_at` returns full-day data with no TTL problem.**

### D. The classification ALREADY EXISTS — no new classifier needed

The TweetShift parser assigns each tweet a `direction` (`long`/`short`/`neutral`) at ingest time. At db.py:1015-1016 that direction is written to `signal_events.direction`. At main.py:1019 `_tweet_sentiment(tweet)` maps the SAME parsed direction to `Sentiment.BULLISH/BEARISH/NEUTRAL`, written to `ticker_signals.sentiment` (main.py:1141, 1158).

So the bull/bear label is produced ONCE by the existing parser and stored in both tables. **You do not need keyword heuristics, and you do not need an LLM.** Just read `sentiment` from `ticker_signals`.

### E. The 30-minute window claim — CONFIRMED

`aggregator.py:233`: `twitter_task = _db_call("get_twitter_signals", ticker, window_seconds=1800)` — 1800 s = 30 min.

`get_twitter_signals` (db.py:1058-1069):
```python
async def get_twitter_signals(ticker: str, window_seconds: int = 1800) -> list[dict]:
    cutoff = time.time() - window_seconds
    cursor = await db.execute(
        """SELECT source_detail, raw_text, detected_at FROM ticker_signals
           WHERE ticker = ? AND source_type = 'twitter' AND detected_at >= ?
           ORDER BY detected_at DESC""",
        (ticker, cutoff))
    return [dict(r) for r in rows]
```
Note it selects `source_detail, raw_text, detected_at` but **NOT `sentiment`** — even though the column is right there. The result flows only to `_build_twitter_snippets` (aggregator.py:727) → narrator text (lines 1250-1323). It is never counted, never split bull/bear, never shown as a field. **Premise confirmed: today's full-day volume is invisible.**

### F. Today's volume — real but SMALL (the "10 NVDA tweets" premise is inflated)

Last-24h per-ticker peak is ~3 tweets. Over the last 3 DAYS:
```
TSLA 11 (8 bull / 2 bear / 1 neut)
MU    9 (6 / 2 / 1)
MSFT  8 (4 / 3 / 1)
NVDA  6 (4 / 1 / 1)
```
So a single market day for a busy ticker is roughly 3-6 tweets, not 10. The field is still worthwhile, but the example "Today's Tweets (10)" overstates typical volume; many tickers will show `(1)` or `(0)`.

### RECOMMENDATION (Issue 3a)

**Use the stored `sentiment` from `ticker_signals` directly. No classifier of any kind.**

Rationale vs the three options the detail file lists:
- **(a) keyword heuristics** — unnecessary; the label is already computed and stored. Re-deriving it would risk DISAGREEING with the direction the rest of the engine already uses (the parser's direction drives alerts and `signal_events`). Two sources of truth = inconsistency.
- **(b) reuse existing classification** — THIS. The parser already did it; `ticker_signals.sentiment` holds `bullish`/`bearish`/`neutral`. Zero latency, zero new code beyond a SELECT, and guaranteed-consistent with the alert pipeline.
- **(c) LLM (incl. folding it into the !all narrator call)** — agree it's overkill. The label exists for free; spending tokens/latency to re-classify what's already in a column is pure waste. The narrator call is also on the latency critical path (!all already fights an 80s+ budget), so adding a structured bull/bear extraction to it adds parsing fragility for no accuracy gain over the stored field.

Map `bullish→bull`, `bearish→bear`, `neutral→neither`. Counts: bull = COUNT(sentiment='bullish'), bear = COUNT(sentiment='bearish'). (Decide whether to show neutral; recommend total = all rows, and "X bull · Y bear" with neutral implicit in the total.)

### Exact DB query to add (new function in db.py, next to get_twitter_signals ~line 1070)

```python
async def get_twitter_signals_today(ticker: str, day_start_epoch: float) -> list[dict]:
    """All TweetShift (source_type='twitter') rows for ticker since local market
    midnight. Carries sentiment + raw_text for the bull/bear count and example."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT source_detail, raw_text, sentiment, detected_at FROM ticker_signals
           WHERE ticker = ? AND source_type = 'twitter' AND detected_at >= ?
           ORDER BY detected_at DESC""",
        (ticker, day_start_epoch),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]
```
Compute `day_start_epoch` in the caller (aggregator) using ET — see timezone note below. Pass it in (don't compute "now" inside db.py, to keep it testable).

### Exact aggregator wire-in point

In `_gather_all_sources` (aggregator.py ~233), ADD a task ALONGSIDE the existing 30-min one (do not replace it — the 30-min snippets still feed the narrator):
```python
from zoneinfo import ZoneInfo
from datetime import datetime
_et_now = datetime.now(ZoneInfo("America/New_York"))
_day_start = _et_now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
twitter_today_task = _db_call("get_twitter_signals_today", ticker, _day_start)
```
Add `twitter_today_task` to the `asyncio.gather` list (alongside `twitter_task` at line 315), unpack it in the results tuple (~line 343), and add to the returned data dict (~line 388):
```python
"twitter_today": _result_or_default(twitter_today, []),
```
Then build a small summary (count, bull, bear, one random raw_text) and pass it through to `build_embed`. Because `build_embed` is called at aggregator.py:1341, you either (i) add a new kwarg `twitter_today=...` to `build_embed`, or (ii) stash the summary onto `StructuredFields` (structured_fields.py:23) like the other levers (`max_pain`, `peer_strength`, `relative_volume` are already attributes read via `getattr(structured, ...)`). Option (ii) matches the existing pattern best.

### Exact embed field location

`embed.py` `build_embed`, the `fields` list (lines 759-819). Append the new field after the `📊 Snapshot` block (line 797) and before the YouTube links field (line 799), mirroring the existing pattern:
```python
tw = getattr(structured, "tweets_today", None)   # {"total":int,"bull":int,"bear":int,"example":str}
if isinstance(tw, dict) and tw.get("total"):
    ex = (tw.get("example") or "").strip().replace("\n", " ")
    if len(ex) > 100:
        ex = ex[:100].rstrip() + "…"
    val = f"{tw['bull']} bull · {tw['bear']} bear" + (f' — "{ex}"' if ex else "")
    fields.append({"name": f"🐦 Today's Tweets ({tw['total']})", "value": val, "inline": False})
```
(Discord field `value` max 1024 chars; truncating the example to ~100 is plenty.)

### Market timezone for "today"

Use **`America/New_York` (Eastern, DST-correct via `zoneinfo.ZoneInfo`)**. The engine's market-day boundary is ET everywhere that matters: `briefing/alfred.py:16`, `research/sessions.py:7` (defines market open 9:30 / close 16:00 ET), `research/vault.py:12`, `health.py:28` all use `ZoneInfo("America/New_York")`.
Caveats:
- Do NOT copy `main.py:49` `ET = timezone(timedelta(hours=-4))` — that's a hardcoded EDT offset that breaks under standard time (winter). Use `ZoneInfo("America/New_York")`.
- The Wolf digest (`alerts/wolf_digest.py:29`) uniquely uses PT — that's Wolf-specific, do not follow it here.

### Failure modes + handling

| Case | What happens | Handling |
|---|---|---|
| 0 tweets today | query returns `[]` | render NOTHING (skip the field) — typical for quiet tickers; an empty "(0)" field is noise. Recommended: only show field when total ≥ 1. |
| All neutral (e.g. 3 neutral, 0 bull, 0 bear) | "0 bull · 0 bear" | acceptable, but consider showing total only: "3 tweets today (sentiment unclear)". Minor. |
| raw_text empty for the chosen example | `raw_text` can be empty | pick the example from rows WHERE raw_text != ''; fall back to source_detail; if none, omit the quote and show counts only. |
| "random" example | use `random.choice` over the rows (with non-empty raw_text). It's a real stored message — no fabrication risk. Seed-free is fine; user said random is acceptable. |
| Multi-ticker tweet mis-attribution | A tweet like "$SPX wow what a day" is stored under SNDK and MU (the parser tags every cashtag). So the example shown for SNDK may be about $SPX, not SNDK. | Known data-quality limitation of the parser, not this field. Acceptable for v1; flag it. Could filter examples to rows whose raw_text contains the ticker's cashtag, but that would drop legitimately-relevant tweets that name the company by word. Recommend: show as-is for v1. |
| Timezone edge at ET midnight | a tweet at 23:59 ET vs 00:01 ET lands in different days | correct by design with ET `day_start`; just don't use UTC midnight (that would cut the day at 8pm ET in summer). |
| Tweet text with Discord markdown/`@`/`http` | could render oddly or ping | the embed value is plain text in a quote; low risk. Existing narrator already sanitizes via `narrator._sanitize_text` — optionally reuse it on the example. |

---

## ISSUE 1 — @-mention / !ask returns health-warning boxes

### Mechanism — CONFIRMED and LIVE-REPRODUCED

`_handle_mention` (main.py:509). It runs (lines 545-554):
```python
proc = await asyncio.create_subprocess_exec(
    "openclaw", "agent", "--local", "--agent", "main",
    "--session-id", f"channel-{channel_id}", "--message", wrapped_message,
    "--timeout", "240",
    stdout=PIPE, stderr=PIPE)
stdout, stderr = await proc.communicate()
stdout_text = stdout.decode(errors="replace")
stdout_text = _strip_secrets_preamble(stdout_text)   # line 556
reply = stdout_text.strip()                            # line 557
... send_command_reply(channel_id, message_id, reply) # line 559
```
It captures **all of stdout**, runs `_strip_secrets_preamble`, and posts the rest. No `--json`.

`_strip_secrets_preamble` (main.py:431) ONLY removes blocks matching:
- start: `^\[secrets\] agent:` (`_SECRETS_PREFIX_RE`, line 427)
- end: `resolved command secrets locally.` (`_SECRETS_TERMINATOR_RE`, line 428)

It does NOT match the doctor warning boxes (which start with `│` / `◇  Doctor warnings`).

**Live reproduction** (ran `openclaw agent --local --agent main --message "Reply with exactly: PONGTEST2"` on this host, no --json):

stdout contained, in order:
```
◇  Doctor warnings ─────────────────────────╮
│  - Left plugin install index in place because shared SQLite state has
│    conflicting plugin install metadata for: brave, discord,
│    web-search-plus-plugin-v2
├────────────────────────────────────────────╯
◇  Doctor warnings ─────────────────────────╮
│  - ... conflicting plugin install metadata for: brave, discord, web-search-plus-plugin-v2
│  - Left migrated task registry sidecar in place ...
├────────────────────────────────────────────╯
PONGTEST2
```
So Discord users see TWO doctor-warning boxes followed by the actual answer. Verified `_strip_secrets_preamble` leaves the boxes 100% intact (0 lines match `^[secrets] agent:`; boxes present before AND after strip). The `[secrets]` lines themselves went to **stderr**, not stdout — so the strip function is operating on the wrong stream's content for this particular noise.

The boxes name exactly `brave, discord, web-search-plus-plugin-v2` — the same plugin conflicts as Issues 2 & 4. So the root cause is confirmed: the plugin install-index conflict makes `openclaw` emit doctor warnings on every invocation.

### Does fixing Issues 2 & 4 really resolve it? — YES, but it is FRAGILE

I confirmed with `--json`: running the same command WITH `--json` puts a clean JSON document on stdout (`payloads[0].text == "PONGTEST"`, 0 box characters) and routes BOTH the `[secrets]` preamble AND the doctor/gateway warning box to **stderr**. The current code does not use `--json`, so it gets the human-formatted stdout that interleaves warnings + answer.

Fixing Issues 2 & 4 (remove `web-search-plus-plugin-v2`, update `discord`, clear the install-index conflict) WILL stop the "Doctor warnings" box from being emitted, so the current raw-stdout code would then post a clean answer — **no code change strictly required.** The detail file's claim is true.

### Verdict: a small defensive change IS warranted (and cheap)

Relying solely on a clean gateway is fragile because:
1. ANY future plugin drift, migration sidecar, or doctor advisory re-introduces a stdout box, and the bug silently returns — users get warning boxes again with zero code-level guard.
2. `_strip_secrets_preamble` is already a defensive layer for ONE noise class (`[secrets]`), proving the author expected stdout to carry non-answer noise. Boxes are just another class it doesn't cover.
3. The fix is nearly free: `openclaw agent` already supports `--json`, which puts the answer in a structured field and pushes ALL warnings to stderr.

**Recommended defensive fix (small, robust):** add `--json` to the subprocess args (line 546-552) and parse `json.loads(stdout)["payloads"][0]["text"]` for the reply, with a fallback to the existing raw-text path if JSON parse fails (so a non-JSON build still works). This makes stdout a clean contract and is immune to any future doctor/warning box, regardless of plugin state. It also lets you drop or keep `_strip_secrets_preamble` as a belt-and-suspenders fallback.

A lighter alternative (if you don't want to touch the JSON contract): extend `_strip_secrets_preamble` (or add a sibling) to also drop lines that are box-drawing noise — i.e. strip any block bracketed by `◇  Doctor warnings` … `├───╯` and lines beginning with box chars `│╭╮╰╯├┤─`. This is more brittle than `--json` (depends on the exact box glyphs) but requires no behavior change to parsing.

**Recommendation: do the `--json` switch.** It's the structurally correct fix; "fix Issues 2&4" addresses today's trigger but leaves the leak path open for the next one.
