# Multi-ticker Discord commands — plan

**Date:** 2026-07-01
**Goal (plain):** Let one command run several tickers at once. Instead of typing
`!all nvda`, enter, `!all amd`, enter, `!all mu`, enter — you type `!all nvda amd mu`
(or `!all nvda, amd, mu`) and get a separate reply for each ticker. Same for every
command that takes a `<ticker>`.

---

## 1. Why this is a small change, not a big one

`parse_command` already splits your message on spaces: `!all nvda amd mu` already
arrives as command=`all`, args=`["nvda","amd","mu"]`. Today each command uses only
`args[0]` and ignores the rest. The multi-ticker list is already sitting there unused —
the job is to loop over it instead of grabbing the first item.

Each command **already posts its own Discord reply**, so running a command 3 times
naturally makes 3 separate replies, one per ticker. No single reply is ever bloated —
the per-ticker split the user wanted falls out for free. No special "send 3 messages
to beat the context limit" mechanism is needed.

---

## 2. Decisions locked in (from the user)

| Command | Bucket | Run order | Max tickers |
|---|---|---|---|
| `!signals` `!analysts` `!alert-history` `!yt-mentions` `!levels` `!cluster` | light (local DB read) | **all at once** | 5 |
| `!technical` | medium, but user chose parallel | **all at once** | 5 |
| `!news` `!sec` `!options` `!em` `!google-trends` | medium (outside API) | **one at a time** | 5 |
| `!scan` | heavy (AI + 6 sources) | **one at a time** | 5 |
| `!all` | heavy (AI synth, 30+ sources) | **one at a time** | 3 |

- **Bad ticker** (fails format check): **skip it, run the rest**, with a short note.
- **Over the cap:** run up to the cap, note the dropped ones.
- **`!yt` and `!transcript`:** untouched — they take a URL, not a ticker.
- **`long` / `short`:** never treated as a ticker (see §4 and §5).

---

## 3. Architecture facts this relies on (verified in `consensus_engine/alerts/commands.py`)

- **Dispatch:** big `if/elif` on `command` inside `_route_command_inner` (L258+). Aliases
  live in the `elif` conditions (e.g. `google-trends`/`trends`/`gtrends`,
  `alert-history`/`history`, `yt-mentions`/`yt_mentions`).
- **Validation:** commands use `is_valid_ticker_format()` (format only: 1–5 uppercase
  letters). It **deliberately skips the blacklist** so users can ask about `SPY`, `QQQ`,
  `ETF` by name. → We must NOT switch commands to the blacklist-enforcing check, or
  `!all SPY` breaks.
- **Concurrency:** `_OUTER_SEM` (default 4) is held for the whole `_route_command_inner`
  call; `_INNER_SEM` (default 64) bounds background tasks. `_dispatch_inner(coro)`
  schedules `coro` as a background `asyncio.Task` under `_INNER_SEM` and returns at once.
- **Two handler shapes:**
  - **Light (inline await):** `_handle_signals`, `_handle_analysts`,
    `_handle_alert_history`, `_handle_yt_mentions`, `_handle_levels`,
    `_handle_cluster_history` — do a DB read and reply inline.
  - **Medium/heavy (background):** each `_handle_X` fires a clean **inner coroutine** via
    `_dispatch_inner` and returns immediately:
    | command | inner coroutine |
    |---|---|
    | scan | `_scan_and_reply(ticker, ch, mid)` |
    | all | `handle_all(ticker, ch, mid)` (from `all_command`) |
    | news | `_news_and_reply(ticker, ch, mid)` |
    | sec | `_sec_and_reply(ticker, ch, mid)` |
    | options | `_options_and_reply(ticker, ch, mid)` |
    | em | `_em_and_reply(ticker, ch, mid)` |
    | technical | `_technical_and_reply(ticker, direction, ch, mid)` |
    | google-trends | `_google_trends_and_reply(ticker, ch, mid)` |
  - `_handle_all` (L675) also attaches a done-callback that logs task exceptions — the new
    batch runner must keep logging per-ticker exceptions so nothing is silently swallowed.

**Consequence:** a naive `for t in tickers: await _handle_X(t)` would run medium/heavy
tickers **in parallel** (the handler returns before the work finishes). To serialize, the
batch calls the **inner** coroutine directly and awaits it. To parallelize, it gathers the
inner coroutines. This is the core mechanism of the design.

---

## 4. `long` / `short` — two coordinated pieces

The words collide with valid ticker format (`SHORT` = 5 letters, `LONG` = 4 — both pass
`is_valid_ticker_format`). So:

- **Piece A — free-text scanner hygiene:** add `"SHORT"` and `"LONG"` to `BLACKLIST` in
  `consensus_engine/utils/tickers.py`. This only affects ticker *extraction* from tweets/
  transcripts (uppercase tokens). It does **not** censor the words or change bullish/bearish
  reasoning — that logic lives in `analysis/technical.py` and never touches the blacklist.
- **Piece B — command parser:** treat `LONG`/`SHORT` as **reserved direction words**, never
  as tickers, for *every* ticker command. For `!technical` the reserved word becomes the
  batch **direction**; for all others it is simply dropped from the ticker list. This is a
  small explicit set (`{"LONG","SHORT"}`) — NOT the whole blacklist — so `SPY`/`QQQ` keep
  working.

---

## 5. Implementation

All code lives in `consensus_engine/alerts/commands.py` unless noted.

### 5.1 New parser helper — `_parse_ticker_args`

```
_DIRECTION_WORDS = {"LONG", "SHORT"}

def _parse_ticker_args(args, *, cap, takes_direction=False):
    # 1. join args, split on commas AND spaces  -> raw tokens
    # 2. per token: strip leading '$', uppercase
    # 3. if takes_direction: pull the (last) token in _DIRECTION_WORDS as `direction`
    #    (default "long"); remove ALL direction words from the token stream
    #    else: just drop any direction words
    # 4. classify remaining tokens:
    #       valid   = is_valid_ticker_format(tok) and tok not in _DIRECTION_WORDS
    #       invalid = everything else (bad format)
    # 5. dedupe `valid`, preserve first-seen order (dict.fromkeys)
    # 6. dropped = valid[cap:]   ;   valid = valid[:cap]
    # returns (valid_tickers, direction, invalid, dropped)
```

Notes:
- Comma+space split: `re.split(r"[,\s]+", " ".join(args))`, drop empties.
- "invalid" = fails **format** (length >5, non-alpha, empty). A well-formed but
  non-existent symbol like `XYZQ` passes format and is left to the handler to report
  "no data" — same as today.

### 5.2 New batch runner — `_run_ticker_command`

```
async def _run_ticker_command(args, channel_id, message_id, *,
                              work, mode, cap, usage,
                              takes_direction=False):
    if not args:
        await send_command_reply(channel_id, message_id, usage); return

    tickers, direction, invalid, dropped = _parse_ticker_args(
        args, cap=cap, takes_direction=takes_direction)

    if not tickers:
        # nothing valid — mirror today's single-ticker error
        bad = (invalid or dropped or args)[0]
        await send_command_reply(channel_id, message_id,
            _INVALID_TICKER_MSG.format(ticker=bad.upper())); return

    # one short combined note if we skipped/dropped anything
    note = _batch_note(tickers, invalid, dropped, cap)   # e.g.
    #   "Running NVDA, AMD, MU. Skipped BADFMT (not a ticker). Dropped TSLA (max 3)."
    if note:
        await send_command_reply(channel_id, message_id, note)

    async def _batch():
        coros = [ (work(t, direction) if takes_direction else work(t))
                  for t in tickers ]
        if mode == "parallel":
            results = await asyncio.gather(*coros, return_exceptions=True)
            for t, r in zip(tickers, results):
                if isinstance(r, Exception):
                    log.error("multi %s failed for $%s: %s", ..., t, r, exc_info=r)
        else:  # sequential
            for t, c in zip(tickers, coros):
                try:
                    await c
                except Exception as e:
                    log.error("multi failed for $%s: %s", t, e, exc_info=e)

    await _dispatch_inner(_batch())   # keep route_command fast; release _OUTER_SEM
```

Why wrap the whole batch in a single `_dispatch_inner`:
- `route_command` returns fast (does not hold `_OUTER_SEM` for the minutes a 3× `!all`
  takes), so other users' commands aren't blocked.
- Sequential mode then runs the tickers one at a time inside that one background task.
- Per-ticker `try/except` + `log.error` preserves the exception-logging that
  `_handle_all`'s done-callback gives today.

### 5.3 Rewire the 14 dispatch branches

Keep the existing `elif` conditions (so all aliases keep working); replace each body with
one call. Examples:

```
elif command == "all":
    await _run_ticker_command(args, channel_id, message_id,
        work=lambda t: _all_work(t, channel_id, message_id),
        mode="sequential", cap=3,
        usage="Usage: `!all <TICKER>` — e.g. `!all AMD` (or `!all nvda amd mu`)")

elif command == "technical":
    await _run_ticker_command(args, channel_id, message_id,
        work=lambda t, d: _technical_and_reply(t, d, channel_id, message_id),
        mode="parallel", cap=5, takes_direction=True,
        usage="Usage: `!technical <TICKER> [long|short]` — e.g. `!technical nvda amd short`")

elif command == "signals":
    await _run_ticker_command(args, channel_id, message_id,
        work=lambda t: _handle_signals(t, channel_id, message_id),
        mode="parallel", cap=5,
        usage="Usage: `!signals <TICKER>` — e.g. `!signals nvda amd`")
```

- Light commands pass their existing `_handle_X` as `work` (they await inline; gather runs
  them together).
- Medium/heavy pass the **inner** coroutine (`_scan_and_reply`, `handle_all`,
  `_news_and_reply`, `_sec_and_reply`, `_options_and_reply`, `_em_and_reply`,
  `_technical_and_reply`, `_google_trends_and_reply`).
- For `!all`, add a tiny `_all_work` wrapper that imports and calls `handle_all` (matches
  today's lazy import inside `_handle_all`).

The old per-branch `args[0]` + `is_valid_ticker_format` + `_INVALID_TICKER_MSG` blocks are
removed — that logic now lives once in the parser. Net effect: **less** duplicated code.

### 5.4 Blacklist (Piece A)

In `consensus_engine/utils/tickers.py`, add `"SHORT", "LONG"` to the `BLACKLIST` set
(WSB-slang section, next to `HOLD`/`BULL`/`BEAR`).

---

## 6. Edge cases to cover

- `!all nvda, amd, mu` and `!all nvda amd mu` → identical result (comma+space split).
- `$nvda` / `nvda` / `NVDA` → same ticker; deduped case-insensitively, order preserved.
- `!all nvda nvda amd` → NVDA once, AMD once (dedupe).
- `!technical nvda amd short` → NVDA + AMD, both direction=short, parallel.
- `!technical short` → no ticker after pulling direction → invalid-ticker message.
- `!sec long` → `LONG` dropped as reserved word → no valid ticker → invalid message.
- `!all a b c d e` → cap 3 → run A,B,C, note "dropped D,E (max 3 for !all)".
- `!signals` (no args) → unchanged usage message.
- `!all SPY` / `!em SPY` → still works (SPY not a direction word; format check unchanged).
- Single ticker (`!all nvda`) → same output as today (batch of one).

---

## 7. Testing

**Unit (new `tests/test_multi_ticker.py`):**
1. `_parse_ticker_args`: comma/space split, `$` strip, dedupe+order, cap trimming,
   direction extraction, `LONG`/`SHORT` never a ticker, bad-format → invalid.
2. `!all nvda amd mu` calls `handle_all` 3× in order (mock `handle_all`), sequential.
3. A light command (`!signals nvda amd`) calls its work 2× (mock), parallel.
4. `!technical nvda amd short` calls `_technical_and_reply` with direction="short" 2×.
5. Cap: `!all a b c d` → 3 calls + drop note. `!scan`+5 tickers → 5 calls.
6. Skip-invalid: `!sec nvda <bad> mu` → 2 calls + skip note.

**Blacklist (extend `tests/` for tickers util):**
7. `extract_tickers("SHORT SQUEEZE ON GME")` → `{"GME"}` (no SHORT).
8. `"SHORT" in BLACKLIST` and `"LONG" in BLACKLIST`.

**Find hidden dependents before commit (per CLAUDE.md):**
- `grep -rn "_handle_all\|handle_all\|_scan_and_reply\|_technical_and_reply\|route_command\|parse_command" tests/`
  and run every match — assertions/mocks on the old single-ticker path must still pass.
- Refresh baseline diff: full `pytest -n 2`, compare to `.test-baseline`, zero new failures.

**Real-world (per CLAUDE.md — this changes live commands):**
- In #chat: `!signals nvda amd` → two replies. `!sec nvda amd mu` → three replies, in order.
  `!technical nvda amd short` → two replies marked SHORT. `!all nvda amd` → two analyses,
  one after the other. `!all a b c d` → drop note + three analyses.
- Always-on checks: `consensus-engine.service` + `openclaw-gateway.service` active; no
  GATEWAY-drift / LLM-health alert; `/root/.openclaw` symlink intact.

---

## 8. Rollout

- No new config flag needed — this is a command-parsing change, not an alert-path change,
  so a stored-data backtest isn't the relevant gate; the Discord end-to-end run in §7 is.
- `!help` text: optionally add "(accepts several: `!all nvda amd mu`)" once; not required
  for function.
- Commit after tests pass; push at session close through the full gate.

---

## 9. Files touched

- `consensus_engine/alerts/commands.py` — parser helper, batch runner, 14 rewired branches.
- `consensus_engine/utils/tickers.py` — add `SHORT`, `LONG` to `BLACKLIST`.
- `tests/test_multi_ticker.py` — new.
- (maybe) `consensus_engine/alerts/commands.py` `_build_help_embed` — one-line hint.
