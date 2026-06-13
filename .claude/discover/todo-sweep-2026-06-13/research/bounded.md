# Bounded cluster research — TODO #35 + #38

Date: 2026-06-13. Mode: research/planning/proving only. No code changed, no services touched, DB read-only.

---

## TODO #35 — Teach @-mention/!ask that bare tickers mean stocks (WEN ≠ haircare)

**Bucket: 1 (not built).** The conversational answer path has zero ticker anchoring. The
deterministic resolver it would reuse already exists and is already imported.

### Mechanism — CONFIRMED

The mention path is:

1. `consensus_engine/scanners/discord_tweetshift.py` receives the Discord message, detects an
   @-mention (line ~428), and calls the `self._on_mention(clean, channel_id, message_id, author_id)`
   callback (line ~459).
2. That callback is `_handle_mention()` in `consensus_engine/main.py` (line 594).
3. `_handle_mention` wraps the raw user text in `_STEERING_TEMPLATE` (defined `main.py` lines
   546–591) via `wrapped_message = _STEERING_TEMPLATE.format(tctx=..., content=safe_content)`
   (line 616).
4. The wrapped text is handed to `openclaw agent --local --agent main ...` as a subprocess
   (line 630), which runs the agentic model with web-search tools (SearXNG / Brave).

The bug: `_STEERING_TEMPLATE` tells the agent "assume every question is about THIS bot," to use
tools, and not to invent things — but **nothing tells it that a bare uppercase token like `WEN`
is a stock symbol.** So when the user asks "tell me about WEN", the agent web-searches the bare
string `WEN`, and the haircare brand outranks Wendy's stock. The `!all` lane is unaffected because
it validates and pulls market data directly; this is purely the conversational lane.

There is **no ticker detection or resolution anywhere between the raw Discord text and the agent
subprocess.** The injection point is unambiguous: `_STEERING_TEMPLATE.format(...)` at `main.py:616`.

### The fix idea — PROVEN viable

**(a) Detect ticker-shaped tokens.** The repo already has the regex + format check:
`consensus_engine/utils/tickers.py` — `_TICKER_PATTERN` matches `$TICKER` and bare 1–5-letter
uppercase tokens; `is_valid_ticker(token)` does format-check **plus** the BLACKLIST filter.

**(b) Pre-resolve via Finnhub company lookup — SMOKE TEST PASSED.**

Live `profile2` calls (run today with the production `FINNHUB_API_KEY`):

```
WEN  → {"ticker":"WEN","name":"Wendy's Co","exchange":"NASDAQ NMS - GLOBAL MARKET", ...}
AAPL → {"name":"Apple Inc","exchange":"NASDAQ NMS - GLOBAL MARKET", ...}
NEWS → {}          (empty — not a ticker)
ZZZZ → {}          (empty — garbage)
```

So `WEN` resolves to **"Wendy's Co" on NASDAQ** — exactly the anchor we need. Non-ticker words and
garbage return an empty object, so the resolver self-rejects them.

**Even better — WEN is ALREADY CACHED.** The bot maintains a `ticker_metadata` table:

```
CREATE TABLE ticker_metadata (ticker TEXT PRIMARY KEY, name TEXT, market_cap REAL, exchange TEXT, last_checked REAL);
-- live rows today:
WEN  | Wendy's Co  | NASDAQ NMS - GLOBAL MARKET
AAPL | Apple Inc   | NASDAQ NMS - GLOBAL MARKET
NVDA | NVIDIA Corp | NASDAQ NMS - GLOBAL MARKET
```

`db.get_ticker_metadata(ticker, max_age_days=7)` returns this row with **zero API calls** when warm.
`validate_ticker_market_cap()` (tickers.py:144) already calls Finnhub `profile2` AND caches
name+exchange (tickers.py:183) on a cache miss. So the resolver is: cache → fall back to one
Finnhub call (which also warms the cache). The `!all` aggregator already uses exactly this name
(`aggregator.py:305: name = ticker_meta.get("name")`).

**No new import needed.** `main.py:37` already has:
`from consensus_engine.utils.tickers import is_valid_ticker, validate_ticker_market_cap`.

### Over-trigger guard — the critical finding

**Finnhub-emptiness alone is NOT a safe filter.** Common English words ARE real tickers:

```
ALL → "Allstate Corp" (NYSE)
IT  → "Gartner Inc"    (NYSE)
ON  → "ON Semiconductor Corp" (NASDAQ)
```

So "tell me about it" or "is that all" would wrongly resolve to Allstate/Gartner if we only
checked Finnhub. The guard is the existing **BLACKLIST** in `utils/tickers.py` (lines 6–65), which
already contains exactly these traps: `IT, ON, ALL, IN, FOR, ARE, ANY, FED, CPI, SPY, QQQ, WEB,
WIN, AI, EV, ETF, IPO, SEC` … (~250 entries: common words, financial acronyms, indicator names,
exchange names, WSB slang). `is_valid_ticker()` = format-check + BLACKLIST, so it passes `WEN`,
`AAPL`, `TSLA` and rejects `ALL`, `IT`, `ON`, `FED`, `SPY`. This is the right tool — it was built
for exactly this "is this uppercase token a real ticker mention or just a word" problem during
tweet/transcript scanning, and it's reusable verbatim.

**Recommended guard logic:** for each token matched by `_TICKER_PATTERN`:
- If it is `$`-prefixed → always treat as a ticker (user was explicit), use `is_valid_ticker_format`.
- If it is a bare uppercase token → require `is_valid_ticker(token)` is True (format + BLACKLIST).
- Then resolve via `get_ticker_metadata` (cache) → `validate_ticker_market_cap` (Finnhub). Only
  inject the anchor if a non-empty company name comes back. (This second gate also kills any rare
  word that slips past the blacklist but isn't a real listed company.)

This is a double gate: BLACKLIST removes the obvious common-word traps, and the Finnhub/cache
non-empty-name requirement removes anything that isn't an actually-listed company.

### Exact injection plan

In `_handle_mention` (`main.py:594`), **before** the `_STEERING_TEMPLATE.format(...)` at line 616:

1. Run `_TICKER_PATTERN.findall(content)` (import the pattern, or add a small helper
   `resolve_ticker_anchors(text) -> list[(symbol, name, exchange)]` in `utils/tickers.py` and
   import it).
2. For each surviving token (after the `is_valid_ticker` blacklist gate), look up the company name:
   `meta = await db.get_ticker_metadata(sym)`; if `None`, call `await validate_ticker_market_cap(sym)`
   (which warms the cache) then re-read `get_ticker_metadata(sym)`. Keep only tokens with a
   non-empty `name`.
3. Build an anchor string and prepend it into the template context, e.g. a new
   `{ticker_anchor}` slot inserted near the top of `_STEERING_TEMPLATE`:

   ```
   Ticker context — these uppercase tokens in the user's message are STOCK SYMBOLS, treat them
   as the company named and answer about the stock, not any same-spelled brand/product:
     WEN = The Wendy's Company (NASDAQ)
   Search "<SYMBOL> stock <company>" not the bare token.
   ```

   If no tokens resolve, inject an empty string so behavior is unchanged for normal questions.

**Why prepend into the template, not the agent's standing config:** the anchor is per-message
(depends on which tickers the user named), so it belongs in `_handle_mention`'s prompt assembly,
not in `openclaw.json` `agents.defaults` standing instructions. The standing config can't name
"WEN = Wendy's" because it doesn't know what the user will ask.

### The open decision — RECOMMENDATION

> Pre-resolve EVERY mention, or only short/ambiguous ones?

**Recommend: resolve every mention, but only inject anchors for tokens that pass BOTH gates
(BLACKLIST-clean AND resolve to a non-empty Finnhub/cache company name).** Reasons:
- The cost is tiny: most tickers are already cached (`get_ticker_metadata`, no API call); a cache
  miss is a single `profile2` call (~100–300 ms) that also warms the cache for `!all`.
- The BLACKLIST already prevents the over-trigger on `ALL/IT/ON/FED/...`, so "resolve every
  mention" does NOT mean "anchor every word" — a normal sentence with no clean ticker token
  injects nothing and behaves exactly as today.
- A "only when short/ambiguous" heuristic adds a fuzzy length/ambiguity threshold that's hard to
  tune and would miss cases like "what's the latest on WEN and how's the market" (long message,
  still a ticker). The two-gate approach is deterministic and self-limiting.
- Cap the number of anchored tokens (e.g. first 5) so a message stuffed with uppercase acronyms
  can't fan out into many Finnhub calls.

**Residual risk to note:** a word that is BOTH a common English word AND a real ticker but is NOT
in the BLACKLIST. `WEN` itself is fine (it's a ticker, not an English word). The blacklist is large
and already covers the dangerous set; new collisions can be added to BLACKLIST as found. The
Finnhub non-empty-name second gate does not help here (these resolve to real companies), so the
BLACKLIST is the only line of defense for true word/ticker homographs — acceptable given how
thorough it already is.

### #35 — proof / verification plan for the build session (not run now)

After building, the A/B test from the todo:
- Ask the bot "tell me about WEN" → expect a Wendy's (NASDAQ: WEN) answer.
- Ask "what's all of that about" → expect a normal answer, NO Allstate anchor (proves `ALL`/`it`
  blacklist guard holds; note: lowercase wouldn't match the pattern anyway, test an uppercase
  common word like "is that ALL").
- Confirm `consensus-engine.service` + `openclaw-gateway.service` both active after any restart.

---

## TODO #38 — Remaining `openclaw doctor` warnings

**Bucket: these are filesystem-cleanup COMMIT items (not code).** Exact commands below; orchestrator
executes — I did NOT run them.

### Current doctor warnings — captured verbatim (run today, read-only)

```
Config warnings:
- plugins.entries.brave: plugin brave: blocked plugin candidate: suspicious ownership
  (/home/openclaw/.openclaw/extensions/brave, uid=998, expected uid=0 or root)

Doctor warnings:
- Left task registry sidecar in place because 1 row already existed in shared state:
  fb684e25-ab1b-471c-a891-be00b649c026

Legacy state detected:
- Task registry sidecar: /home/openclaw/.openclaw/tasks/runs.sqlite → shared SQLite state

State integrity:
- OAuth dir not present (/home/openclaw/.openclaw/credentials). Skipping create because no
  WhatsApp/pairing channel config is active.
- Multiple state directories detected. This can split session history.
    - ~/.openclaw   (Active state dir: /home/openclaw/.openclaw)
- Found 142 orphan transcript files in /home/openclaw/.openclaw/agents/main/sessions.
  These .jsonl files are no longer referenced by sessions.json ... Doctor can archive them
  safely by renaming each file to *.deleted.<timestamp>.

Plugin diagnostics:
- WARN brave: blocked plugin candidate: suspicious ownership
  (/home/openclaw/.openclaw/extensions/brave, uid=998, expected uid=0 or root)

Plugins: Loaded 10, Errors 0.   Security: no warnings.   Skills: 20 eligible, 0 missing.
```

### (1) Duplicate brave plugin — SAFE to delete

**Verified it's a true duplicate that does NOT power the working brave search:**

- Blocked copy: `/home/openclaw/.openclaw/extensions/brave` — owned `openclaw:openclaw` (uid 998),
  a full plugin (`dist/`, `node_modules/`, `package.json`, `openclaw.plugin.json`). Openclaw blocks
  it because a local extension is expected to be root-owned; uid 998 looks suspicious.
- Working copy (the one actually loaded): `/home/openclaw/.openclaw/npm/projects/openclaw-brave-plugin-11fe9e3aa3/node_modules/@openclaw/brave-plugin/openclaw.plugin.json` —
  a completely separate path, npm-managed.
- `openclaw.json` configures brave by **name** (`"brave": {...}` at line 357, `enabled: true`) and
  does NOT reference the `extensions/brave` path. Extensions are auto-discovered by directory scan,
  so deleting the `extensions/brave` directory removes only the blocked duplicate; the npm plugin
  keeps serving web search. Doctor reports `Loaded: 10, Errors: 0` today — brave is loaded from npm,
  not from the blocked dir.

**EXACT SAFE COMMAND (Option A — cleanest, recommended):**

```bash
rm -rf /home/openclaw/.openclaw/extensions/brave
```

(Option B — `chown -R root:root /home/openclaw/.openclaw/extensions/brave && chmod 755 ...` — would
make openclaw ACCEPT the duplicate, leaving two brave plugins loaded. That's messier than deleting
the redundant copy. Recommend Option A.)

After the delete, reload plugins and re-check (orchestrator's call — involves a gateway reload):
`openclaw doctor` should no longer show the brave ownership warning. **Safety proof:** the working
brave plugin is on a different path that's untouched by this delete, and `openclaw.json` never names
the deleted path.

### (2) Orphan transcripts — SAFE to delete, but BLOCKED ON #39 (see flag)

- Count confirmed: **142** files matching
  `/home/openclaw/.openclaw/agents/main/sessions/*.deleted.*.jsonl`.
- These are already-archived (doctor itself renamed the orphans to `*.deleted.<timestamp>.jsonl` —
  its own "safe archive" step, done in the 2026-06-12 session). Deleting them only clears the
  cosmetic "142 orphan transcript files" warning.

**EXACT COMMAND:**

```bash
rm /home/openclaw/.openclaw/agents/main/sessions/*.deleted.*.jsonl
```

**⚠️ #39 DEPENDENCY — DO NOT DELETE YET (explicit conflict flag):**

I inspected these files. They are **full agent trajectory transcripts**, not empty husks. First
record of a sample is a `session.started` event; top-level keys include
`traceSchema, traceId, source, type, ts, seq, sessionId, sessionKey, runId, workspaceDir,
provider, modelId, modelApi, data`. They contain the real conversation history (model IDs +
`data` payloads), spanning **May 19 → Jun 11** (e.g. May 19: 35 files, Jun 2: 24, Jun 4: 30).

TODO #39 is the bot chat-memory redesign, whose recall **backtest** would want exactly this
historical chat data to test "does the new memory recall the right past conversation." Deleting all
142 now would destroy that backtest corpus.

**Recommendation:** defer the #38 transcript deletion until #39's design is settled. If the
orphan-warning needs clearing sooner, **keep a copy first** rather than deleting in place:

```bash
# preserve the corpus for #39 before any cleanup
mkdir -p /home/openclaw/.openclaw/archive/deleted-transcripts-2026-06-13
cp /home/openclaw/.openclaw/agents/main/sessions/*.deleted.*.jsonl \
   /home/openclaw/.openclaw/archive/deleted-transcripts-2026-06-13/
# only AFTER the copy:
rm /home/openclaw/.openclaw/agents/main/sessions/*.deleted.*.jsonl
```

The brave delete (item 1) has NO such dependency and can proceed immediately.

### (3) Permanent / non-fixable warnings — CONFIRMED genuinely unfixable / intentional

- **Multiple state directories** (`~/.openclaw` vs `/home/openclaw/.openclaw`): `/root/.openclaw`
  is a deliberate symlink to `/home/openclaw/.openclaw` from the 2026-05-11 VPS consolidation
  (memory: "VPS consolidated"). Doctor sees two paths for one physical directory. Active dir is
  correctly `/home/openclaw/.openclaw`. Cannot be removed without undoing the consolidation. Leave.
- **Task registry sidecar** (`/home/openclaw/.openclaw/tasks/runs.sqlite`, 1 row
  `fb684e25-...`): doctor intentionally left it because a row already existed in shared state.
  Not a real problem; clearing it would risk the deferred-task system. Leave.
- **OAuth dir not present** (`/home/openclaw/.openclaw/credentials`): doctor deliberately skips
  creating it because no WhatsApp/pairing channel is configured. Expected; not an error. Leave.

These three are informational; no action.

### #38 summary of actions for the orchestrator

| Item | Command | Safe now? |
|---|---|---|
| Brave duplicate | `rm -rf /home/openclaw/.openclaw/extensions/brave` then reload plugins | ✅ YES — npm copy is separate and untouched |
| Orphan transcripts | copy to archive, THEN `rm .../sessions/*.deleted.*.jsonl` | ⚠️ DEFER / copy-first — #39 backtest corpus |
| Symlink / task sidecar / OAuth dir | none | intentional, leave |
