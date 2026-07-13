# Reliability-hardening deploy + 7-day soak

**Status:** DONE 2026-07-04 — all 7 switches ON. The 5 cautious ones were flipped after the soak was evaluated early (markets closed Fri–Sun gather no source-health data → 4 trading days Jun 29–Jul 2 was the real window). Data cleared all 5 (market_cap_failclosed 0 errors; retry/adapters internal-only; breaker: only exa dead=1296, healthy sources=0, none instant-alert). Flipped in 3 risk-tiered cycles, engine verified clean between each; go-live evidence in .claude/go-live-evidence/; Sunday soak timer retired. Live watch CONFIRMED 2026-07-12 (TODO #72 cleanup): journalctl shows the breaker cycling exa — half_open probe → OPEN (reason=402) e.g. 2026-07-06 00:00–00:11 PDT — while healthy sources stayed closed.
**Created:** 2026-06-28
**Switches:** llm.score_fallback_enabled=on; options_flow.staleness_failclosed=on; circuit_breaker.enabled=on; dead_source.ops_alert_enabled=on; retry.use_classifier=on; adapters.report_failure=on; social.market_cap_failclosed=on

**CURRENT STATUS (2026-07-12):** DONE, and the final live watch is now confirmed — the circuit breaker IS opening on exa (journalctl 2026-07-06 00:00–00:11 PDT: half_open probe → OPEN, reason=402 payment-required, repeatedly) while healthy sources stayed closed. Recorded during TODO #72 cleanup; nothing further required.

## What shipped (the discover run `reliability-hardening`)

15 surgical reliability/efficiency fixes to the live bot. Zero new dependencies. Independent review: COMMENT verdict, 0 critical / 0 high; the 2 medium findings were resolved (C19 flag-gated, C7 tie-claim corrected). Full plan: `/home/openclaw/wt-reliability-hardening/.claude/discover/reliability-hardening/final-plan.md`.

### Group 1 — live automatically (no switch)
- **C11** aiohttp session timeout (30s total / 10s connect / 20s read) — closes the sock_read=None hang.
- **C20** process-wide Yahoo concurrency cap (3) — stops self-inflicted Yahoo 429s.
- **C7** max-pain math vectorized (numpy) + moved into the executor thread — no longer blocks the event loop.
- **C13/C8** options fetch-outage logging + itertuples refactor.
- **C1** equal-jitter backoff + one-time kickoff stagger.
- **C10** higher peer-comparison time budget + bounded peer fetches.

### Group 2 — switch-gated
- **C4** `llm.score_fallback_enabled` — **ON 2026-06-28.** Safe: only runs when the AI chain returns empty; the instant alert already fired (base-score gated), so it can never block/create an alert — strictly better than a blank thesis.
- **C12** `options_flow.staleness_failclosed` — **ON 2026-06-28.** Proven safe: 0 of 92,933 stored `options_flow` rows ever had a blank `last_trade_ts`; it only TAGS such a contract, never drops it.
- **C2** `circuit_breaker.enabled` + **C5** `dead_source.ops_alert_enabled` — **OFF (soak).** Persistent 3-state breaker for finnhub_news / google_news_rss / brave_search / exa, plus one throttled ops alert when a source goes dark. None of those 4 is an instant-alert trigger (all are catalyst/corroboration sources needing a 2nd source), so the breaker cannot silence a real alert. Soak watches whether it ever opens a healthy source. Early signal: `exa` shows ~1200 backoff events/window (chronically dead — the breaker would correctly stop hammering it).
- **C3** `retry.use_classifier` — **OFF (soak).** Smarter retry pacing using server Retry-After hints. Internal-only; gathers no shadow data while off; can't drop/block an alert. Flip = flip-and-watch one cycle.
- **C14** `adapters.report_failure` — **OFF (soak).** Feeds price-adapter failures into the shared rate_limiter. Internal-only, same as C3.
- **C19** `social.market_cap_failclosed` — **OFF (soak).** When the "is this a real stock?" check ERRORS, skip the ticker (fail-closed). Flag-gated after review because a transient DB blip could drop a corroborating social source. Soak measures the live error rate (0 so far in the journal window — need a fuller week).

### Applied to the machine (not in git)
- **C15** systemd: `OOMScoreAdj`→`OOMScoreAdjust` (was a typo) on both units + `MemoryMax=3G` on the engine. Backups at `/etc/systemd/system/*.pre-c15.bak`.

## Day-7 decision (2026-07-05)
Read the soak report in `notifications.log`, then per flag:
- **C19:** if validation errors ≈ 0 over the week → flip `social.market_cap_failclosed: true`. If errors are common → keep OFF (a flaky check would drop real tickers).
- **C2/C5:** if the breaker would only open genuinely-dead sources (e.g. exa) and the ops channel wouldn't be spammed → flip BOTH `circuit_breaker.enabled: true` and `dead_source.ops_alert_enabled: true` together, then watch the ops channel.
- **C3, C14:** internal-only, lowest risk → flip `retry.use_classifier: true` and `adapters.report_failure: true`, watch one poll cycle for odd backoff timing.
- Flip ONE flag at a time, restart `consensus-engine.service`, confirm clean. Update this file's CURRENT STATUS and the `**Switches:**` line each time.

## C12 verification query (already run; re-run anytime)
```
cd /home/openclaw/.openclaw/workspace && sudo -u openclaw python3 -c "
import sqlite3; d=sqlite3.connect('consensus.db')
print('total', d.execute('SELECT count(*) FROM options_flow').fetchone()[0])
print('blank', d.execute('SELECT count(*) FROM options_flow WHERE last_trade_ts IS NULL OR last_trade_ts=0.0').fetchone()[0])"
```

## Files / where things live
- Live config flags: `config/consensus.yaml` (search the `C2`/`C3`/`C4`/`C5`/`C12`/`C14`/`C19` comments).
- New code: `consensus_engine/utils/circuit_breaker.py`, `utils/yahoo_limit.py`; edits across `scanners/{news,options,social}.py`, `analysis/{llm_scorer,peer_comparison}.py`, `api_adapters.py`, `llm_client.py`, `db.py`, `utils/{http,rate_limiter}.py`, `alerts/discord.py`, `models.py`.
- Soak task: `/root/task_system/scripts/notify_reliability_soak.sh` + timer `task_1782704382_12c893`.

## Open questions / watch-items
- A 2nd discover run (`feat/sanitize-timeout-fix`, worktree `/home/openclaw/wt-sanitize2`) was unmerged at deploy time. It touches some of the same shared files; when it merges it will 3-way-merge on top of these 14 commits (expected serialization — no clobber).
- Before flipping C2/C5, re-confirm against the THEN-current alert config that none of the 4 gated sources has become an independent instant-alert trigger (it wasn't at deploy time).
