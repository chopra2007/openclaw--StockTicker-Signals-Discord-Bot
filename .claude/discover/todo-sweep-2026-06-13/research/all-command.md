# TODO #6 — `!all` quality umbrella — research sweep 2026-06-13

Cluster owner: all-command. Source TODO: `todo/all-command-quality.md` (read fully).

---

## Bucket + evidence

**#6 = bucket 4 (OFF/menu) for the umbrella; the named 2026-06-10 open item = ALREADY DONE (bucket "done", no work needed).**

- The umbrella's acceptance bar ("ship at least one user-visible quality improvement with before/after evidence") was **MET on 2026-05-19** and many more levers have shipped since (max-pain, peer RS, snapshot, R:R, RVOL, 52wk, P/C-OI, earnings-move). It stays open as a **menu**, not a defect.
- The one concrete open defect in the TODO — the 2026-06-10 "smart-levels alerts show closing price, not live price" item — **is already fixed in committed production code** (proof below). So there is no Part-A code change to ship.

---

## PART A — the named "current price = stale close" bug: ALREADY FIXED (proof)

### What the bug was
The TODO (line 193-195) says level-proximity alerts like
`🎯 $SPY approaching resistance @ $728.00 — current $725.43`
label the price "current" but it was actually the last daily close, stale when the market is closed.

### The single code path
There is exactly ONE producer of that alert text. Found via `grep -rn "approaching"`:

- **`consensus_engine/main.py:1023` `_check_youtube_level_alerts()`** — the only function that posts "approaching" alerts. The text is built at **lines 1080-1083**:
  ```python
  msg = (
      f"🎯 ${ticker} approaching {ltype} @ ${lv_price:.2f}"
      f" (flagged by {channel}{days_ago}) — {price_label}"
  )
  ```
  `{ltype}` is the level type — covers **resistance, support, breakdown, target, ema, ma** (the stored `level_type` values; confirmed via `sqlite3 -readonly consensus.db "SELECT DISTINCT level_type FROM youtube_levels"` → target 334, resistance 122, support 84, breakdown 4, …). So all three alert types the TODO names (resistance/support/breakout) go through this one string and are fixed together.
- The all_command "breakout" hits in grep are unrelated — that's the `!all` writeup's `breakout_timeframe` field, not an alert.

### Why it is already fixed
`price_label` (line 1074-1079) is built from a `price_kind` returned by `_level_price()`. The price comes from **`_level_price(ticker)` at main.py:153**, not a daily candle:

```python
async def _level_price(ticker):
    if _us_market_open():                       # Mon–Fri 9:30–16:00 ET
        price = await get_live_quote_price(ticker)   # Finnhub /quote field "c" — LIVE
        return (price, "current") if price else (None, None)
    # outside regular hours:
    return await loop.run_in_executor(None, _yf_extended_price, ticker)  # pre/post-market
```

- During market hours → **Finnhub `/quote`** (`api_adapters.get_live_quote_price`, line 300, reads field `c`) → labeled `"current"`. This is the exact call the TODO says to use and the same one `aggregator.py` uses.
- Outside hours → **`_yf_extended_price`** (main.py:124) reads yfinance `marketState` + `postMarketPrice`/`preMarketPrice`/`regularMarketPrice` → labels it `"after-hours $X"`, `"pre-market $X"`, or `"last close $X (market closed)"`. So a closed-market price is now **explicitly labeled "last close … (market closed)"**, never falsely "current".
- On total failure `_level_price` returns `(None, None)` → caller `continue`s (skips) rather than alerting on stale data.

The fix comment is right there at main.py:1037-1043 describing exactly this change. `git status --short consensus_engine/main.py` → blank = no uncommitted changes = the fix is committed and live.

### Live proof of the difference (captured 2026-06-13, a Saturday — market closed)
```
date                                        → Sat Jun 13 2026 (weekend)
Finnhub /quote SPY  → {"c":741.77, "t":1781294400}   # t = Fri Jun 12 16:00 ET close
yfinance SPY .info  → marketState=CLOSED, regularMarketPrice=741.75, postMarketPrice=742.36
```
- The OLD code would have posted `— current $741.77` on a Saturday (Finnhub `c` IS Friday's close when closed).
- The NEW code: `_us_market_open()` → False (weekend) → routes to `_yf_extended_price` → returns `(742.36, "after-hours")` → labels it **`after-hours $742.36`** (the real last extended print), or `last close $741.75 (market closed)` if no after-hours print. Either way, accurate and honestly labeled.
- yfinance extended-hours pre-flight from this VPS **WORKED**: SPY post=$742.36 (vs reg $741.75), NVDA post=$205.42 — real after-hours prints the old close-only path would have missed.

### Verdict
**No diff to apply.** Part A is closed. The orchestrator should mark the 2026-06-10 open item as DONE in the TODO (the fix predates this sweep). If anything, the only residual is the documented `_us_market_open()` holiday gap (main.py:114-115): on a market *holiday* it has no calendar, so it'd say "current" when the quote is the prior close. That's a known, minor, accepted edge (the TODO didn't ask for a holiday calendar) — flag only.

---

## PART B — competitor audit

Full table at **`.claude/discover/all-command-rebuild/external-feature-audit-2026-06-13.md`** (14 rows, every promising source pre-flighted live from this VPS).

### What `!all` already has (so nothing below is redundant)
Analyst PT mean/high/low + count + rating, forward P/E, short % + days-to-cover, 52wk hi/lo distance, max-pain (weekly+monthly), P/C-OI, RVOL, earnings-move history (±%), peer relative strength, R:R, chart pattern, TweetShift today's-tweets, YouTube analyst-call links, plus the LLM trade-plan/thesis/risks.

### Top 3 audit findings (feature + pre-flight verdict)
1. **EPS-estimate-revision trend** — "34 analysts raised, 3 cut (30d)". Source `yf.Ticker(t).eps_revisions`. **Pre-flight WORKED** (NVDA 0q: 34 up / 3 down). Forward-looking analyst conviction; distinct from the static price target `!all` shows. Trivial build.
2. **Stocktwits community sentiment + 5-day trend** — "73% bullish, −3 pts/5d; 650k watchers". Source `api.stocktwits.com/api/2/symbols/<T>/sentiment.json` (no key). **Pre-flight WORKED** (HTTP 200, 61 daily points, NVDA 73.09% bull, 5d delta −2.7). The only cheap *new external* source; the broad retail crowd, not the analyst tweets `!all` already shows.
3. **Institutional/insider ownership + quality one-liner** — Inst 69%, PEG 0.63, rev growth +85%, beta 2.2. **Pre-flight WORKED, ZERO new fetch** — all already inside the `.info` blob `snapshot.py` fetches. Near-universal on competitor pages; `!all` doesn't show it.

### Blockers (not candidates)
- **Unusual Whales / dark-pool prints / real GEX** — paid / Cloudflare-gated. Confirmed inaccessible free from this VPS.
- **DCF fair-value (SimplyWallSt) / 13F fund deltas** — inputs exist in `.info`/SEC but the build is big and easy to get wrong; deferred.
- Finviz *looked* blocked (301, 0 bytes) but actually **WORKED** with `curl -L` (URL moved to `/quote?t=`); however everything it gives is already in yfinance `.info`, so no need to scrape it.

---

## PART C — recommended cheap levers + build plans

Pick **Lever 1 (EPS-revision trend)** as the primary — best ubiquity-to-cost ratio, pre-flight green, near-zero latency. **Lever 2 (Stocktwits sentiment)** as the second — only cheap new external signal, retail-ubiquitous. Both are flag-gated OFF by default (project convention) until live-verified and signed off.

### Lever 1 — EPS-estimate-revision trend (PRIMARY)
**User-observable outcome:** the 📊 Snapshot field gains one segment, e.g. `EPS rev: 34↑ 3↓ (30d)` — meaning 34 analysts raised and 3 cut their current-quarter EPS estimate in the last 30 days. Visible on `!all NVDA`.

- **Data source / fetch:** `yf.Ticker(t).eps_revisions` — a DataFrame indexed by period (`0q,+1q,0y,+1y`). **[codex revision — pin the exact column casing with a fixture]** Verified live, the real columns are inconsistently cased: `['upLast7days', 'upLast30days', 'downLast30days', 'downLast7Days']` — note `downLast7Days` has a capital D while `upLast30days`/`downLast30days` are lowercase. The plan reads the two `*Last30days` columns, which are BOTH lowercase (correct) — but a guard that assumes uniform casing will silently omit the field or throw. Record a real `eps_revisions` DataFrame as a test fixture and write the column reads + guard against it (cases: present, empty table, missing column, renamed column). Use the `0q` (current quarter) row.
- **Where the fetch lives:** `consensus_engine/scanners/snapshot.py` → `_fetch_info()` already calls `t.earnings_estimate` in the SAME blocking call. Add `t.eps_revisions` right beside it, stash under a synthetic key like `info["_eps_rev"] = {"up": int(up30), "down": int(down30)}`.
  > **[codex revision 2026-06-13 — the "no new fetch, no new latency" claim is FALSE; do not rely on it]** Verified live: `yf.Ticker("NVDA").eps_revisions` returns a populated DataFrame, and in yfinance these analyst properties are lazy-loaded — `eps_revisions` triggers its OWN network fetch (quoteSummary), it does NOT ride `.info`. So this adds a blocking request inside the snapshot path. **Build accordingly: wrap the `eps_revisions` read in its OWN `asyncio.wait_for` timeout (don't let it extend the snapshot tail), measure the added latency before flipping the flag, and null it independently of `.info` on timeout** (a slow/hanging analyst fetch must not delay the rest of the snapshot).
- **Where it's shaped:** in `fetch_ticker_snapshot()` (snapshot.py ~line 112) add `snap["eps_rev"] = info.get("_eps_rev")` (guarded: only when up+down > 0).
- **Where it renders:** `embed.py` `_format_snapshot()` (line 414) — add a new conditional segment after the fundamentals segment:
  ```python
  rev = snap.get("eps_rev")
  if isinstance(rev, dict) and (rev.get("up") or rev.get("down")):
      segments.append(f"EPS rev {rev['up']}↑ {rev['down']}↓ (30d)")
  ```
- **Dataclass:** `snapshot` is already carried on `StructuredFields` as a dict, so no new field needed — the new key rides inside the existing `snap` dict.
- **Config key:** reuse `features.snapshot.enabled` (already gates the whole snapshot), OR add `features.snapshot.eps_revisions` defaulting False for a flag-gated rollout per convention.
- **Test:** unit test `_format_snapshot({"eps_rev":{"up":34,"down":3}})` renders the segment; and a snapshot.py test asserting `eps_rev` is parsed from a fixture. Live-verify on `!all NVDA`/`!all AMD`.
- **Risk:** sparse tickers return an empty `eps_revisions` table → guard with `up+down > 0` (handled). yfinance throttle already handled by the existing snapshot timeout/None path.

### Lever 2 — Stocktwits community sentiment + trend (SECONDARY)
**User-observable outcome:** a new embed field `💬 Retail (Stocktwits)` → e.g. `73% bullish · −3 pts/5d · 650k watching`. Visible on `!all NVDA`.

- **Data source / fetch:** `https://api.stocktwits.com/api/2/symbols/<T>/sentiment.json` (daily bull/bear % series, no key) for the % + 5-day delta; `https://api.stocktwits.com/api/2/streams/symbol/<T>.json` for `symbol.watchlist_count`. Both HTTP 200 from this VPS, no auth.
- **New file:** `consensus_engine/scanners/stocktwits_sentiment.py` — mirror `snapshot.py`'s pattern exactly: a bounded `aiohttp` GET with `asyncio.wait_for` timeout (~6s), returns `{"bull_pct": 73.1, "delta_5d": -2.7, "watchers": 649827}` or `None` on any failure. Use the shared aiohttp session (`api_adapters.get_session`).
- **Where called:** `aggregator.py` fan-out (alongside the other scanner gathers, ~line 595 where `StructuredFields` is packed). Add `stocktwits=...` to the dataclass and the construction.
- **Where it renders:** `embed.py` add after the 🐦 Today's Tweets field (line 809):
  ```python
  _st = getattr(structured, "stocktwits", None)
  if isinstance(_st, dict) and _st.get("bull_pct") is not None:
      v = f"{_st['bull_pct']:.0f}% bullish"
      d = _st.get("delta_5d")
      if isinstance(d, (int, float)): v += f" · {d:+.0f} pts/5d"
      w = _st.get("watchers")
      if w: v += f" · {w/1000:.0f}k watching"
      fields.append({"name": "💬 Retail (Stocktwits)", "value": v, "inline": False})
  ```
- **Dataclass:** add `stocktwits: Optional[dict] = None` to `StructuredFields` in `structured_fields.py`.
- **Config key:** `features.stocktwits_sentiment.enabled` default False (flag-gated rollout).
- **Test:** scanner test against a recorded JSON fixture; embed render test. Live-verify on `!all NVDA`/`!all TSLA`. Re-run the Layer-C Gemini blind-compare after both levers to confirm no quality regression.
- **Risk:** Stocktwits is an undocumented public API — could rate-limit or change shape. Mitigate: bounded timeout + None-on-failure (field just omits, never breaks `!all`); flag-gated so it can be disabled instantly. Note `social.stocktwits_enabled=False` in the main engine (different code path — that's the alerting scanner; this is a `!all`-only read). Don't confuse the two.
  > **[codex revision 2026-06-13 — try/except + 15-min cache is necessary but NOT sufficient]** Three gaps the bounded-timeout + cache plan still leaves open:
  > 1. **Cache stampede.** A 15-min cache doesn't help the FIRST N concurrent `!all NVDA` calls — they all miss the cold cache and each hits Stocktwits before the first write lands. Add **per-ticker in-flight coalescing** (one outstanding request per ticker; the others await its result), not just a TTL cache.
  > 2. **No negative caching.** If Stocktwits is down/rate-limiting, every `!all` re-hits it. **Cache failures briefly too** (e.g. 60-120s negative TTL) so a down API isn't hammered.
  > 3. **Two endpoints fail independently.** Lever 2 reads BOTH `sentiment.json` (bull %/5d delta) AND `streams/symbol` (watcher count). They can fail separately. **Give each its own timeout and render whatever succeeds** (e.g. show "73% bullish" even if the watcher-count call failed), rather than treating them as one all-or-nothing "response".

### Why these two (and not the bigger ones)
GEX, dark-pool, DCF, 13F all scored **big build + partial/blocked pre-flight** — exactly the "build the integration then discover the source is inaccessible" trap discipline rule 2 warns against. Levers 1 and 2 are the only rows that are both ubiquitous AND pre-flight-green AND cheap.

---

## Risks / watch-items
- **Don't re-touch main.py for Part A** — it's already fixed; a "fix" would be a no-op or a regression.
- **Flag-OFF convention:** ship both levers behind `features.*.enabled` defaults False, run shadow/live-verify, then flip with user sign-off (matches every prior `!all` lever in this TODO's history).
- **Shared-file tripwire:** Lever 2 touches `aggregator.py` + `structured_fields.py` + `embed.py` — per CLAUDE.md DoD, test the WHOLE `!all` path live (real `!all NVDA` round-trip), not just the new field. Lever 1 only touches snapshot.py + embed.py (lower blast radius).
- **Latency budget:** Lever 1 = zero new fetch (rides the existing `.info`). Lever 2 = one new bounded HTTP call (~0.3-1s) parallel in the fan-out — keep it inside its own `wait_for` so it can't extend the tail.
- **Testing trap (from TODO 2026-06-02 notes):** when live-testing `!all`, only mock the 15-min cache + the Discord send — never the AI-call layer, or you get false-empty narratives.
