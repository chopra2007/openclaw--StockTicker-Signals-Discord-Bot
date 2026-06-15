# TODO sweep — final plan (todo-sweep-2026-06-13)

Research + planning + plan-testing session. Every claim below was proven against the **live** VPS
(read-only DB, real API smoke-tests, real-email/real-archive backtests, adversarial re-verification).
Per-item build specs (the detailed "plan files") live in `research/<cluster>.md` alongside this file.
The deep competitor audit for #6 is at `../all-command-rebuild/external-feature-audit-2026-06-13.md`.

---

## 1. Triage table — every active item, what bucket, what to do

Buckets: **1** = not built · **2** = built but broken · **3** = built but untested · **4** = built but switched off.

| # | Item | Bucket | One-line verdict |
|---|------|--------|------------------|
| 6 | Improve `!all` | 4 (menu) — named bug **already fixed** | The "smart-levels shows stale close" bug is already fixed in live code. Two cheap new add-ons identified (analyst EPS-revision trend; Stocktwits retail mood). |
| 17 | Full YouTube transcription | 4 — **built, on, works** | Long-video chunked reading is live and genuinely reads videos start-to-finish (proven from logs + timestamps). Only videos >90 min are uncut — none exist. No build needed. |
| 20 | Wolf newsletter brain | **OPEN — live quality debt** (pipeline shipped, but wrong theses are user-facing NOW) | All 4 phases live and the "still open" follow-ups are actually shipped — BUT **[codex revision] this is NOT "done/soak":** 3 wrong theses are LIVE and surface to users (IGV bull → wrong LONG ideas + a `critical` @-ping; SPX/NDX bull from a misread bearish setup) plus orphan trade rows. Stays open until the #26 direction-guard + staleness fixes ship. |
| 26 | Wolf hedged direction + stale calls | 1 (staleness not built) + 2 (extractor bug) | The TODO's proposed fix was tested and **backfires** — drop it. Real wins: a "retire stale calls" sweep + a clean prompt fix for the SPX/NDX mislabel (tested 5/5 correct). |
| 32 | Switch on Phase-2 signal upgrades | 4 — built, off | The "wait 14 days then turn on" plan can't work (the watch-logs stay empty by design). Backtesting proved **2 are worth turning on now (E1, I15)**; 2 are safe but do nothing yet; 1 needs ~11 more days; 1 is unbuildable. |
| 34 | Wire in Apify | 1 — not built | $4.65 of the free $5 left, our side clean. The recommended Seeking Alpha actor **runs fine (HTTP 200, exit 0) but its upstream returns 0 items for every ticker AND every endpoint today**, logging a `credits_estimate` — i.e. an **upstream credit/rate limit on the author's private backend, NOT an outage** (it returned 10 NVDA articles on 6-10 with the same call; the earlier AAPL 500 is now a 200 = intermittent). Don't build on it; re-probe later. |
| 35 | Bare tickers = stocks (WEN≠haircare) | 1 — not built | Clean fix proven: detect ticker-shaped words, look up the company (WEN→"Wendy's Co"), tell the bot before it web-searches. Re-uses the existing blacklist so common words (ALL/IT/ON) don't misfire. |
| 37 | Stale YouTube parser test | 2 — test-only | One-line test fix, verified green. **Committing this session.** |
| 38 | openclaw doctor warnings | cleanup | Delete the duplicate Brave plugin (safe, **doing it this session**). Defer the leftover transcript deletion — #39 needs those files. 3 warnings are intentional, leave them. |
| 39 | Redesign bot chat memory | 1 — not built (+ plumbing mis-wired) | Recommended design proven on real data: a small summary table + an on-demand "recall" tool + a gated 30-day cleanup. The bot today forgets almost everything on restart; the save-feature it ships never fires. |

---

## 2. Scope — REVISED 2026-06-13 (user directive: build EVERYTHING, flip ON this session)

> **[user directive 2026-06-13 — supersedes the original "plans-only" scope]** "I want everything you
> can build to be built, nothing left off the table or delayed for a future session." AND: "all
> features built and switched off should be able to be switched on before the session ends (unless the
> feature is broken). Testing is not a good enough reason [to leave off] since there's tons of
> historical data in the db to test against for feature accuracy."

**New execution model for this build session (replaces "ship flag-OFF, defer the flip to a later session"):**
1. **Build every buildable item** (#6 levers, #20/#26 Wolf fixes incl. the IGV `bear` correction,
   #32 signal upgrades + the enablers, #35 chat tickers, #39 chat memory). Nothing deferred.
2. **Validate accuracy against the historical DB IN-SESSION** — the alert-preview / replay harness
   (and per-feature backtests) run against the months of history already in `consensus.db`. This IS
   the test; "wait for a shadow window / a future sign-off" is no longer a reason to leave a feature off.
3. **Flip ON before session end** every feature whose backtest passes. Leave OFF **only** if the feature
   is genuinely **broken or data-blocked** (see the explicit exception list below), and say so plainly.
4. **Already done earlier this session:** #37 (test fix, committed b326fe3), #38 brave-duplicate delete,
   #6 stale-price marked DONE.

**The only legitimate "can't switch on this session" exceptions (data-blocked / unbuildable, NOT "testing"):**
- **I13 (ApeWisdom z-score)** — needs ≥14-day baselines; only 3 days exist and there is **no historical
  backfill source**, so it cannot be validated against history. Eligible ~2026-06-24. (Blocked by data.)
- **E2-FRED leg** — no FRED key, zero code. (Unbuildable.)
- **#34 Apify Seeking-Alpha** — the only budget-viable actor returns 200-empty/500 (unreliable today);
  free per-ticker news is already covered by `google_rss`. **Recommended SKIP** unless it revives.
  (Build is blocked by an unreliable external source, not by testing.)
- For **I7 (consolidation)** and **I14 (regime panic)**: don't just leave them inert — **build their
  enablers this session** (seed `regime_daily` with 252-day vol history; take the consolidation engine
  out of shadow-only) so they can actually be validated against history and flipped ON too.

---

## 3. Per-item plans (detailed build specs in research/)

> **Read under the §2 execution model:** where an entry says "flag OFF", that is the *build mechanism*
> (ship the code behind a feature flag). Per the 2026-06-13 user directive, each flag is then
> **validated against the historical DB this session and flipped ON before session end** — unless the
> feature is data-blocked/unbuildable (I13, E2-FRED, #34). "Flag OFF" no longer means "deferred."

### #6 `!all` — `research/all-command.md` + the audit file
- **Already fixed:** the smart-levels "current price = stale close" bug. `_level_price()` (main.py:153) already uses Finnhub live during market hours and honestly labels closed-market prices ("last close … (market closed)"). No diff. (Minor residual: no market-holiday calendar — flag only.)
- **Lever 1 (primary) — EPS-revision trend.** Add `yf.Ticker(t).eps_revisions` to the existing `.info` fetch in `snapshot.py` (zero new latency), render `EPS rev 34↑ 3↓ (30d)` in `embed.py:_format_snapshot`. Flag `features.snapshot.eps_revisions` OFF.
- **Lever 2 (secondary) — Stocktwits retail sentiment.** New bounded scanner hitting the public Stocktwits JSON API (no key, pre-flight worked), new `💬 Retail` embed field. Flag `features.stocktwits_sentiment.enabled` OFF. Touches the shared-file tripwire → live-test whole `!all`.
- Both flag-OFF, then live-verify + Gemini blind-compare before sign-off.
- **[review revision]** Harden both against their fragile external sources: strict `try/except` + tight (~3s) timeout + omit-the-field-on-failure (never crash `!all`); **cache** the Stocktwits response ~15 min (concurrent `!all` users must not each hit it); **guard** the yfinance `eps_revisions` read for a present `0q` row + `upLast30days`/`downLast30days` columns before reading (yfinance schemas drift).

### #17 full transcription — `research/youtube.md`
- **No build.** Chunked reads verified working live (3 long videos read to the end; zero PARTIAL-READ warnings since the fix). Recommendation: **accept the 90-min ceiling**; the alarm fires if a >90 min video ever appears. Revisit only then (cheapest future fix = route only the >90-min tail to Supadata captions).

### #20 + #26 Wolf — `research/wolf.md`
- **Drop** the TODO's proposed hedged-stance prompt clause — multi-trial A/B proved it never catches the IGV shift and manufactures a wrong IGV bull + over-extracts elsewhere.
- **Ship (clean win):** tighten `_DIRECTION_GUARD_RULE` so "bounce to a **lower high** / forming an **H&S top** / failed breakout to fade" reads BEAR while plain "fill the gap" stays bull. Verifier tested a targeted clause → SPX/NDX corrected 5/5 with zero false positives. A/B at N≥10 + backfill before flip.
- **Build:** a nightly **staleness sweep** in `wolf_theses.py` — demote (not delete) a thesis when target-reached+stale, or stale-while-the-sector-flipped, or past an age cap. **[review revision → superseded by codex revision]** Gemini's tiered caps (90d acting/imminent, 30d forming/diverging) were a step up from a flat 45d, but **Codex split them further and fixed the reaffirmation rule — use the Codex version** (see `research/wolf.md` `[codex revision]`): **stage-split caps `imminent` ~14-21d (NOT 90d) / `forming`-`diverging` ~30d / `acting` ~90d, target+contradiction-aware; reset the clock ONLY on an explicit same-direction conviction reaffirmation (NOT on target-reached/watchlist/contradicted evidence — else the IGV bad-reaffirmation resets its own clock forever); add a `stale_review` state with manual override** (don't trust nondeterministic auto-self-heal); **and a polarity-signed same-complex map** (VIX vs UVXY/VXX are inverse — naive same-complex logic gets contradictions backwards).
- **Hygiene:** clear `wolf_beneficiaries` rows when a thesis is invalidated (orphan COIN-short rows exist for ids 114/126).
- **IGV — RESOLVED to BEAR (user directive 2026-06-13, confirmed vs live emails):** NOT "no active thesis." Wolf's IGV is a short waiting for the counter-trend backtest of the 200-day/$100 (toppy pattern + neckline). **Correct live id-140 `bull`→`bear`/forming** and generalize the direction-guard fix to catch "back-test/bounce to a level FROM BELOW + topping/lower-high/neckline → fade" as bear (this also fixes SPX/NDX). See `research/wolf.md` "USER DECISION — RESOLVED".

### #32 Phase-2 activation — `research/signals-phase2.md`
- **[codex revision] PREREQUISITE before any flip: build an offline alert-pipeline replay harness.** E1's "9/204 fire" and every other "ready" claim prove *term/score* behavior, not the *user-visible alert* delta. The replay must report alert-count change, new @-pings, tier upgrades, with examples. This gates E1, I4-full, I3/I10/E2-VIX, and the #6 levers' before/after.
- **Flip first (after the replay confirms the delta):** **E1** (FINRA short-volume confluence term, +5 cap, ~3% fire rate on live code) and **I15** (weighted Wolf votes — only demotes 2 over-ranked theses, zero spurious @-pings).
- **Fix-first, then flip:** the **dual-score divergence** (precision score caps ~56, never hits STRONG; alert path uses a different ≥75 score). Until **I4-full** unifies them, flipping **I3 / I10 / E2-VIX** is bounded-safe but **inert** (proven: 43 classifications, 0 reached STRONG). Top priority, not a footnote.
- **[review revision] Do NOT flip I3/I10/E2-VIX now, even though they're inert.** If they're already ON when I4-full unifies the scores, all three activate *simultaneously* in production — an alert-storm risk with no way to isolate which feature misbehaves. Correct order: **flip E1+I15 now** → build+ship I4-full → then flip I3/I10/E2-VIX **one at a time**, watching each. This supersedes the earlier "flip inert ones for code-coherence" option.
- **Wait:** **I13** (ApeWisdom) flip-eligible ~**2026-06-24** (needs ~11 more baseline days; no historical backfill exists).
- **Never:** **E2-FRED** leg (no key, zero code) — leave OFF permanently. **I9** alert-floor stays 0.
- **3 independent gaps to fix for Phase-2 to mean anything:** `regime_daily` empty (neuters I14), consolidation stuck shadow-only (neuters I7), the dual-score divergence (neuters I3/I10). Treat as their own tasks.

### #34 Apify — `research/apify.md`
- **Do NOT build now — but the reason is NOT "the actor is down" (corrected after a proper diagnosis).** The `doesaiknow` Seeking Alpha actor runs successfully every time (HTTP 200, exit 0, $0 charged for 0-item runs). Its **upstream backend returns 0 items for every ticker and both endpoints (news + dividends) today**, each logging `credits_estimate: 5`. It returned 10 NVDA articles on 6-10 with the identical input; the earlier AAPL "500" is now a 200 (intermittent, not an outage). Our Apify account is fine ($4.65/$5, not throttled). **Most likely cause: the author's private backend has hit a credit/rate limit on its own Seeking Alpha access** — a black box we can't see into or fix, but a *throttle/credit* state, not a dead service. The alternatives cost ~$0.95/run (blow the budget for polling).
- **Correction to the re-probe reasoning:** the Apify $5 cycle reset (6-14) does NOT fix this — that resets *our* Apify budget, which isn't the constraint. What has to recover is the *author's backend* (their credits/throttle), which is on their timeline, not ours. So "re-probe after 6-14" should be "re-probe periodically until the upstream returns data again, or drop it."
- **Plan:** re-probe `doesaiknow` after the **2026-06-14** credit reset (one NVDA delta run, ~$0.05). If it returns real data two days running → build the **Seeking Alpha tier** in `news_cascade` flag-OFF with a hard **budget fail-safe** (skip the call once monthly usage ≥ $4; fall through to existing tiers). If it stays dead → the only free win is the **Finviz direct scrape** (no Apify), gated hard by the relevance filter (its per-ticker page is ~94% off-ticker noise). Reddit stays out (~$170/mo).
- **[review revision] The bigger question: is #34 worth building at all?** The bot **already has free per-ticker news** via the `google_rss` cascade tier (config:98) + Finnhub. The ONLY signal Apify-Seeking-Alpha uniquely adds is the **analyst/engagement layer** (`comments_count`) — and its only budget-viable actor is upstream-throttled today (returns empty across all endpoints; not down — see the corrected diagnosis above). Gemini suggested Yahoo Finance per-ticker RSS as a free alternative, but I **smoke-tested it and it 404s** (Yahoo deprecated that endpoint) — so that's not a path. Recommendation: treat #34 as **low-priority / likely-skip** unless the `doesaiknow` actor revives with the unique engagement data; the news-coverage gap it was meant to fill is already covered for free.

### #35 ticker disambiguation — `research/bounded.md`
- In `_handle_mention` (main.py), before building the steering prompt: find ticker-shaped tokens, gate them through the existing `is_valid_ticker` blacklist (kills ALL/IT/ON/FED), resolve the survivors via `db.get_ticker_metadata` (cache) → `validate_ticker_market_cap` (Finnhub), and inject the company anchor into the prompt. Cap at ~5 tokens. Proven: WEN→"Wendy's Co", garbage→empty.
- **[codex revision + user correction 2026-06-13] Homograph handling:** **APP (Applovin) and GAP (Gap Inc) are real popular stocks — anchor them** (this corrects the earlier note that called them homographs to avoid). The genuine risk is only *slang/grammar-dominant* tokens like "**WEN** moon?" (crypto "when"), ON/IT/ALL/FOR. For those: **soft, conditional anchor** ("if WEN here refers to a stock, it's Wendy's (NASDAQ) — otherwise answer normally"), gated on the message looking stock-focused or a `$` prefix — advisory, not forcing. Also do NOT reuse the scanner blacklist as-is (it wrongly blocks SPY/QQQ). See `research/bounded.md` for the chat-specific policy.

### #37 stale test — `research/youtube.md` (committing this session)
- Add one line to `test_extract_evidence_parses_spans`: `patch("...fetch_youtube_duration", new=AsyncMock(return_value=600))` to force the single-pass path. All original assertions pass (verified). Then remove line 2 from `.test-baseline`.

### #38 doctor — `research/bounded.md` (partial this session)
- **Now:** `rm -rf /home/openclaw/.openclaw/extensions/brave` (duplicate; npm copy serves search; doctor shows Loaded 10/Errors 0).
- **Now (not deferred anymore):** #39 is built THIS session, so the 142 orphan `.deleted.*.jsonl` transcripts are needed now as the recall backtest/eval corpus. **Copy them to a restricted-perms archive first** (they hold secrets — see the #38 secret-retention `[codex revision]` in `research/bounded.md`), feed them to the #39 summarizer/eval (redacted), then the gated 30-day cleanup applies as designed. Don't bulk-delete the raw set.
- **Leave:** symlink dual-path, task-registry sidecar, missing OAuth dir — all intentional.

### #39 chat memory — `research/chat-memory.md`
- **Architecture (b):** a `chat_memory_rollups` SQLite table in `consensus.db` (per-channel dated summaries, never overwritten) + a `recall_chat_memory` retrieval the agent uses **on demand** + a **30-day cleanup cron gated** on a covering summary existing first. Recall PROVEN on real data: a 510 KB archive → 4.4 KB rollup (115×), correctly answered a 2-week-old question (and a skeptic confirmed it with 4 more questions + a hallucination trap).
- **Recall wiring:** prefer an OpenClaw tool (`defineToolPlugin` — supported on this version) but it's a Node build in a Python repo; the **simpler first build is the `_handle_mention` prepend-on-intent** (all Python, no OpenClaw wiring).
- **[review revision] Summarizer trigger = a scheduled nightly cron scan** for un-summarized `.deleted.*` archives — NOT a gateway-reconnect hook. Discord gateways reconnect constantly; a reconnect-triggered 130k-token summarization would burn LLM quota and block the event loop (a production-breaker). Skip channels already summarized.
- **[codex revision] Race-safety + backlog + redaction (supersedes the simpler gate above):** identify a covered archive by **`source_sha256` + `status='complete'`**, never by filename/date overlap (a date match can delete the wrong/un-summarized file); `UNIQUE(source_sha256)` makes re-runs idempotent. Throttle by a **budget (≤N archives / ≤M bytes / token cap) with a one-time catch-up pass**, not "one channel per night" — that can't drain the 229-archive backlog. **Redact secrets** (tool payloads, key/token/email patterns) before any permanent rollup is written. See `research/chat-memory.md` §5.1/§5.4 for the full schema + cleanup logic.
- **Also:** turn on file rotation (`truncateAfterCompaction: true`, `maxActiveTranscriptBytes: "5mb"`) so the live transcript stops ballooning; repoint the stale `memorySearch.extraPaths` to the live memory dir.
- **Bucket-4 sub-finding:** the `session-memory` hook only fires on `/new`+`/reset`, never on the bot's restart-resets — so it saves nothing today.

---

## 4. User decisions — ALL RESOLVED 2026-06-13 (these are now directives, not open questions)

The user greenlit the full build ("build everything, nothing deferred"; "switch on before session end unless broken"). The seven items below are the standing build directives:

1. **#26 IGV — RESOLVED: it's a BEAR thesis** (overrides the old "no active thesis" rec). Confirmed against Wolf's live emails (toppy pattern + neckline + counter-trend backtest of 200-day/$100 from below = a short waiting for a better entry). **The fix is NOT a manual flip — it's a root-cause prompt fix** (see `research/wolf.md` "ROOT CAUSE"): the `_DIRECTION_GUARD_RULE` contradicts itself — its "back-test a level → not bear" carve-out beats its "tagging the 200-day from below as resistance → bear" cue, so the model filed $100/$200 as bull `target`s (live id-140 proof) and even misread "200-**day**" as a $200 target. Fix = narrow the carve-out + add a topping-context override (back-test UP to a level *from below* + toppy/neckline/lower-high → resistance/bear) + stop "200-day"→"$200"; then correct id-140 `bull`→`bear`; A/B at N≥10 before flip. Same rule fixes SPX/NDX.
2. **#26 staleness — RESOLVED: build the codex-hardened design.** Stage-split caps (`imminent` ~14-21d, `forming`/`diverging` ~30d, `acting` ~90d, target/contradiction-aware); **demote-not-delete**; **clock-reset ONLY on explicit same-direction reaffirmation** (not target-reached/watchlist/contradicted — else the IGV bad-reaffirmation resets its own clock forever); `stale_review` state + manual override; polarity-signed same-complex map.
3. **#32 — RESOLVED: build + backtest against historical DB + flip ON this session.** Build the alert-preview/replay harness FIRST and validate each scoring change against `consensus.db` history (incl. E2-VIX across historical VIX regimes — that backtest IS the "shadow-first" Codex wanted, done in-session). Order: build I4-full → validate → flip E1, I15, I3, I10, E2-VIX (each validated via replay). Build the enablers so I7/I14 can flip too (seed `regime_daily`; consolidation out of shadow-only). Only I13 stays off (data-blocked); E2-FRED unbuildable.
4. **#34 — RESOLVED: SKIP + REMOVE the keys** (free per-ticker news already covered by `google_rss`; the only budget-viable actor is unreliable). No build. **Safety-checked: nothing in code/config/scripts reads Apify — it cannot accidentally trigger** (the keys are orphaned env vars; `xxxxxAPIFY2_TOKEN` already disable-prefixed). Cleanup step at build start: delete `APIFY_TOKEN`/`APIFY_PROXY_PASSWORD`/`xxxxxAPIFY2_TOKEN` from the 3 env files (`/home/openclaw/.openclaw/.env`, `.env.service`, `workspace/.env`), then `chown openclaw:openclaw` (ownership trap). Mark TODO #34 SKIPPED. (See `research/apify.md` DECISION block.)
5. **#39 — RESOLVED: build architecture (b) + flip on this session.** SQLite `chat_memory_rollups`, on-demand recall (prefer the real tool / an explicit `recall` command over intent-sniffing), nightly-cron summarizer; **identity-based cleanup gate** (`source_sha256` + `status='complete'`, never date-overlap); **mandatory redaction** before any permanent rollup (transcripts hold secrets/emails/tokens); budgeted backlog/catch-up drain (one-channel-per-night can't clear 229 archives); validate recall with an in-session eval set (traps + negatives) against the historical archives, then enable.
6. **#6 — RESOLVED: build both levers, backtest, flip ON this session.** `eps_revisions` in its OWN timeout (it lazy-fetches — the "zero latency" claim is false) + a pinned column-casing fixture; Stocktwits in-flight coalescing + negative caching + per-endpoint timeouts (not just a 15-min TTL). Validate via the !all replay/blind-compare, then enable.
7. **#35 — RESOLVED: build a chat-specific ticker policy.** Allow major ETFs (SPY/QQQ are blacklisted today and would silently not anchor) AND popular word-homograph stocks (**APP=Applovin, GAP=Gap are real popular stocks — anchor them, this was a user correction**). Keep a SMALL denylist of only slang/grammar-dominant tokens (WEN="when", ON, IT, ALL, …) that need `$`/stock-context; soft/advisory anchor.

---

## 5. Cross-model review (Gemini — first pass; Codex re-ran later, see §5b)

**Codex was initially unavailable** (the local CLI reported "Logged in" but every API call returned **401 — refresh token revoked**), so the first cross-model gate ran on **Gemini** (gemini-flash-latest; the pro model was quota-429'd), full plan bundle piped in. **Codex was then re-authenticated this session and DID run a full adversarial pass — see §5b**, which found 3 blockers Gemini missed (chief among them: the research files still contradicted this file's revised order).

**Gemini's verdict + what I changed (all folded into §3 above, tagged `[review revision]`):**

| Item | Gemini verdict | Action taken |
|---|---|---|
| #32 | RISKY — flipping inert I3/I10/E2-VIX is a deployment trap; they'd all activate at once when I4-full lands → alert-storm | **Revised:** flip E1+I15 only now; I4-full next; then I3/I10/E2-VIX one-at-a-time. |
| #39 | RISKY — reconnect-triggered summarizer = API-cost runaway + event-loop block | **Revised:** nightly cron scan, throttled; idempotent label-based cleanup gate. |
| #26 | RISKY — flat 45d age cap kills valid slow macro theses | **Revised:** tiered caps (90d acting/imminent, 30d forming/diverging) — also resolves the VIX-bear conflict. |
| #35 | RISKY — slang homographs ("WEN moon?"=when, GAP, APP) would wrongly anchor | **Revised:** soft/advisory anchor + stock-context/`$`-prefix gate. |
| #6 | RISKY — Stocktwits/yfinance fragile; could crash `!all`; no caching | **Revised:** strict try/except + ~3s timeout + omit-on-fail + 15-min cache + yfinance schema guard. |
| #34 | WRONG — don't build on a dead hobby API; suggested Yahoo RSS | **Partially folded:** Yahoo RSS smoke-tested → **404 (dead)**; google_rss already covers it → #34 likely skip. |
| #17/#37/#38 | SOUND | No change. |

**Production-breakers Gemini flagged (all now mitigated in the plan):** (1) #39 reconnect-trigger runaway → nightly cron; (2) #32 simultaneous activation → one-at-a-time after I4-full; (3) #6 unhandled yfinance schema → schema guard + try/except.

**Note on the review itself:** Gemini's one *concrete* alternative (Yahoo Finance RSS) was **stale** — the endpoint 404s now. Tested, not trusted — which is exactly why every external dependency in this plan was smoke-tested rather than assumed.

## 5b. Cross-model review — CODEX pass (2026-06-13, re-authenticated)

Codex was re-authenticated this session (`codex login --device-auth`, gpt-5.5, high reasoning). It can't read this VPS's files, so the **entire plan bundle (final-plan + all 7 research files, ~37k tokens) was pasted inline** into the prompt. Two of Codex's code-level claims were then **re-verified live** before acting on them (I don't relay an external verdict unchecked).

**Codex verdict: REVISE in specific spots — not a rewrite, but NOT safe to build as-is.** Reasons: several research files contradicted the revised order in this file, and several "proven" claims are only partly proven. All findings below are folded into §3 and the research files, tagged `[codex revision]`.

**Three BLOCKERS (all now fixed):**

1. **#32 — the research file contradicted this plan's activation order.** `research/signals-phase2.md` still listed **E2-VIX and I3 under "flip now"**, which contradicts §3's revised "flip E1+I15 only" order. A build agent reading the research file would have flipped them immediately. → **Fixed:** `signals-phase2.md` now has one authoritative order matching this file, with explicit "HOLD until after I4-full" / "DO NOT FLIP NOW" on I3/I10/E2-VIX.
2. **#32 — E2-VIX is not a flip-now item.** It turns on a LIVE ±15% scoring multiplier AND its shadow log simultaneously (no shadow-first mode), proven on only ONE live data point; ±15% can push a 66 over the ≥75 alert floor or drop an 86 below it — that's live alert behavior, not harmless logging. → **Fixed:** E2-VIX moved to "flip last, after I4-full + an offline replay across calm AND backwardation regimes; better, add a true shadow-only flag first."
3. **#39 — cleanup/summarization race.** The rollup schema identified a covered archive by date-range overlap + `bytes>0`, which can delete the wrong or un-summarized file (worsened by restart-wipe bursts). → **Fixed:** schema now pins `archive_path` + `source_sha256` + `status` with `UNIQUE(source_sha256)`; cleanup deletes only on an exact hash + `status='complete'` match.

**Codex findings → action (the rest):**

| Item | Codex finding | Action taken |
|---|---|---|
| #6 | "zero new latency" for `eps_revisions` is false (it lazy-fetches); schema casing inconsistent; Stocktwits cache allows stampede + 2 endpoints fail independently | **Verified live** `eps_revisions` does its own fetch + real columns `[upLast7days, upLast30days, downLast30days, downLast7Days]`. Folded: own timeout + measure latency + null independently; pin column casing with a fixture; add in-flight coalescing + negative caching + per-endpoint timeouts. |
| #26 | clock-reset-on-ANY-reaffirm keeps the IGV-type bad-reaffirmation alive forever; 90d for `imminent` too long; self-heal not guaranteed; "same complex" needs polarity | Folded: reset only on explicit same-direction conviction (not target-reached/watchlist/contradicted); split caps (imminent short / forming-diverging medium / acting long); add a `stale_review` state w/ manual override; explicit polarity map (VIX vs UVXY/VXX inverse). |
| #32 | E1's "9/204 fire" is the term rate, not the alert delta; I4-full should be simulated offline | Folded: **build an offline alert-pipeline replay harness** (alert-count delta, new @-pings, tier upgrades, examples) and gate every scoring flip on it. |
| #34 | "author-backend credit limit" cause is asserted not proven; re-probe anchored to the irrelevant Apify reset | **Verified this matches my own 2026-06-13 comm-check failure.** Folded: relabel the cause UNVERIFIABLE, plan around observed symptom (200-empty/500 unreliable); re-probe on a schedule, not the Apify reset. |
| #35 | reusing the scanner blacklist blocks valid chat ETF questions (SPY/QQQ) | **Verified live:** `is_valid_ticker` returns False for SPY/QQQ. Folded: a separate conversational policy — allow major ETFs **AND popular word-homograph stocks (APP=Applovin, GAP=Gap — user correction: these ARE real popular stocks, anchor them)**; keep a SMALL denylist of only slang/grammar tokens (WEN="when", ON, IT, ALL…) needing `$`/stock-context; Finnhub gate as the "real company" check. |
| #20 | calling Wolf "done/soak" hides 3 LIVE user-facing wrong theses | Reframed: #20 is **NOT done** — wrong active theses (IGV bull, SPX/NDX bull) are live production debt; #20 stays open until the #26 direction-guard + staleness fixes ship. |
| #38/#39 | full agent trajectories contain secrets; permanent rollups outlive the 30-day raw-archive deletion | Folded: redaction (drop tool payloads, mask key/token/email patterns) is a **precondition** of the #39 summarizer; restricted-perms on the preserved corpus; retention/purge policy for rollups. |
| #17 | 90-min "accept" rests on a thin sample; alarm is only a log line | Folded: keep "no build" but make the 6-window-cap truncation an operator-visible alert, not just a journal warning. |
| #37 | the test pairs an unrealistic fetched-duration (600) with parsed-duration (2340) | NIT — #37 is already committed (b326fe3). Optional polish: set the patched duration consistent with the JSON, or document that the test covers single-pass JSON parsing only. |

**The one cross-cutting prerequisite Codex surfaced:** there is currently **no offline alert-pipeline replay** that shows *user-visible alert deltas* before flipping any #32 scoring feature. Every "ready" claim proves term/score behavior, not how many Discord alerts actually change. **Build that replay first; it gates #32 (E1, I4-full, I3/I10/E2-VIX) and the #6 levers' before/after.**

**What Codex confirmed the plan got RIGHT (preserve on any future edit):** not building on the broken Apify actor now; preserving the deleted transcripts until #39 is decided; rejecting the harmful IGV hedged-bear prompt change; catching the circular YouTube coverage metric; and moving #32 off "flip inert flags before I4-full."

## 6. Status — PLAN FINALIZED & READY TO EXECUTE (2026-06-13)

Research + planning + plan-testing complete; revised after **both** the Gemini review (§5) and a full **Codex adversarial pass** (§5b); then revised again per the **user directives 2026-06-13** (build everything + flip-on this session; IGV=bear; APP/GAP are real stocks). All 3 Codex blockers fixed; all §4 decisions resolved into directives. **The plan is ready to execute.**

**Execution model (per §2):** build every buildable item → validate accuracy against the historical `consensus.db` via the alert-preview/replay harness + per-feature backtests → **flip ON before session end**, except the data-blocked/unbuildable exceptions (I13, E2-FRED, #34). The replay harness is the in-session test that lets us turn features on now instead of deferring.

**Build order (live wrong calls first):** (1) #20/#26 Wolf — correct IGV id-140 `bull→bear` + direction-guard + staleness; (2) #35 chat tickers + #6 !all levers; (3) #32 alert-preview harness → I4-full → flip the validated signals + build I7/I14 enablers; (4) #39 chat memory. All behind the regression gate at session close.

**Plan files (this run):** `.claude/discover/todo-sweep-2026-06-13/final-plan.md` (this file — the index/decisions), `research/wolf.md` (#20/#26), `research/all-command.md` (#6), `research/signals-phase2.md` (#32), `research/chat-memory.md` (#39), `research/bounded.md` (#35/#38), `research/youtube.md` (#17/#37), `research/apify.md` (#34), `state.json`. Codex review: `/tmp/codex-review/review.md`.
