# Make the video reader store real ticker symbols

**Status:** OPEN
**Created:** 2026-09-08

**CURRENT STATUS (2026-10-04):** Symbol part BUILT + committed (130ee75), NOT LIVE until `consensus-engine.service` is restarted (the restart was blocked by the auto-mode classifier as a production deploy; user must run it). `resolve_video_ticker` in `ticker_grounding.py` maps company names to symbols (NVIDIA to NVDA, NEBIUS to NBIS via `config/ticker_aliases.json`) and flags NASDAQ/SPXW/SPIRIT/forex/crypto pairs as `invalid_symbol`; the three YouTube insert functions in `db.py` apply it (flagged rows saved with suppressed=1); the level-alert ticker query now skips suppressed rows. Live rows backfilled (backup `consensus.db.bak.pre-ticker-fix-2026-10-04`). 16 new tests; full suite 4386 passed. The 404 log lines were already 0 in the prior 24h. STILL OPEN: the TLT direction-attribution finding below (video `Z2h0LIK-FPU`), untouched.

### Session notes — 2026-10-04
- **Decision:** forex, crypto and index mentions are suppressed, not remapped (user can ask for e.g. NASDAQ to QQQ).
- **Next:** user restarts the engine, then confirm a new video saves NVDA not NVIDIA; then the TLT classifier finding.

## Related direction-attribution finding — October 2, 2026, Pacific time

During the Usetranscribe comparison, a read-only database check found video
`Z2h0LIK-FPU` had an unsuppressed LONG TLT signal whose source snippet describes
falling long-dated Treasury bond prices. This record existed before the provider
integration. Both transcript suppliers returned essentially the same words, so
changing the transcript source does not resolve the direction/context mismatch.

When repairing video-reader validation, also trace this example through
`analysis/video_classifier.py` and the shared macro context used in signal
classification. Use the source snippet and video moment to determine direction,
and verify that bullish commentary about a different sector does not flip TLT.
No classifier change or historical record rewrite was made in the provider task.

The part of the bot that reads YouTube videos saves whatever the speaker called
a stock. When someone says "NVIDIA" it stores `NVIDIA`, not `NVDA`. Yahoo has no
symbol called NVIDIA, so every poll cycle the engine asks for a price and gets a
404 back:

```
HTTP Error 404: {"quoteSummary":{... "description":"Quote not found for symbol: NVIDIA"}}
```

Three of these fire every ~5 minutes right now (`NVIDIA`, `SPXW`, `USDJPY`) —
62 of each in the last log window. They are printed by yfinance itself, not by
our logger, so they cannot be silenced by log level; they have to be fixed at
the source.

## What is actually stored

Counted 2026-09-08 against `/home/openclaw/.openclaw/workspace/consensus.db`:

| Table | distinct tickers | bad ones found |
|---|---|---|
| `youtube_signals` | 694 | NVIDIA, NEBIUS, SPIRIT, NASDAQ, SPXW, USDJPY, BTCUSD, LOD.V |
| `youtube_levels` | 245 | NVIDIA, NASDAQ, SPXW, USDJPY |
| `youtube_catalysts` | 200 | NVIDIA, NASDAQ, USDJPY |

Four separate kinds of mistake:

1. **Company name instead of symbol** — NVIDIA, NEBIUS, SPIRIT.
2. **An index or exchange name** — NASDAQ. Not tradeable as typed.
3. **An option root, not a share** — SPXW is the S&P 500 weekly option root.
   There is no stock quote for it.
4. **Currency / crypto pairs** — USDJPY, BTCUSD. Yahoo wants `USDJPY=X` and
   `BTC-USD`. LOD.V is a Canadian listing.

## Why the existing filter does not catch this

`consensus_engine/scanners/youtube.py` already runs a per-video allowlist
(`build_video_allowlist` in `consensus_engine/analysis/ticker_grounding.py`,
called around line 947). That check answers *"did this video really talk about
this ticker?"* — a relevance test. It does not answer *"is this a real symbol?"*.
Off-allowlist rows are flagged `suppressed = 1, suppression_reason =
"off_allowlist"` and **still written to the table** (see `_suppress_meta`,
line 959). So an invalid symbol survives into the database either way, and
whatever later reads those tables hands it to yfinance.

## Possible next steps, priority order

1. **Add a symbol-validity gate** at the same point as the allowlist check, before
   the insert. Reject anything that is not a plausible US equity symbol, and
   resolve the ones that can be resolved rather than dropping the signal:
   company name → symbol (NVIDIA → NVDA), option root → underlying (SPXW → SPX
   or drop), currency pair → `=X` form or drop.
2. **Decide the policy per category** — this needs a call, not a guess. Do we
   want forex and crypto signals at all? If yes they need a separate path,
   because they will never work through the equity price fetch.
3. **Backfill the rows already stored.** ~10 distinct bad symbols across the
   three tables. Small enough to map by hand once the rules are agreed.
4. **Re-check after a full poll cycle** that the 404 lines are gone from
   `journalctl -u consensus-engine.service`.

## Files involved

- `consensus_engine/scanners/youtube.py` — the video reader; allowlist +
  insert path around lines 925–1000.
- `consensus_engine/analysis/ticker_grounding.py` — `build_video_allowlist`,
  where a validity check would naturally sit next to the relevance check.
- Tables: `youtube_signals`, `youtube_levels`, `youtube_catalysts`
  (also `ticker_metadata` and `measurement_candidates_v1` hold SPXW).

## Open questions

- Should an unresolvable name be dropped, or stored with a flag so the audit
  trail still shows the speaker mentioned it? The existing `suppressed` /
  `suppression_reason` columns already give a place to record it.
- Are forex and crypto mentions wanted at all, or should they be dropped at
  the parser?
