# Wolf cluster — TODO #20 + #26 (research, 2026-06-13)

Read-only sweep on the live VPS. DB queried with `sqlite3 -readonly consensus.db`.
3 named Wolf emails + 3 recent ones fetched via read-only Gmail API (token at
`/root/.openclaw/gmail/token.json`). Current extractor run live against them
(gpt-oss-120b:free via OpenRouter). No DB writes, no service touches.

---

## TL;DR

- **#20 (Wolf macro-brain): BUCKET = mostly DONE / done-soak.** Pipeline is fully alive
  and healthy. The two follow-ups the TODO still lists as "NEXT/deferred" — wire confluence
  into `!all`, shorts-side beneficiaries — are **already shipped and LIVE**. The 63d-RS-horizon
  item is a closed user decision (stays 21d). What's genuinely actionable is a **thesis-quality
  problem**, not a missing-feature problem (see below).
- **#26 (hedged stance-shift + staleness): BUCKET = #1 NOT BUILT (no staleness) + a real,
  REPRODUCED quality bug.** The proposed prompt-only fix (`_DIRECTION_GUARD_RULE` addendum)
  **FAILS** — it does not catch the hedged IGV bear shift, and it makes things WORSE elsewhere
  (suppresses valid theses on one email, over-extracts a wrong IGV bull on another). The honest
  recommendation: do NOT ship the generic prompt clause; the real wins are (a) a staleness sweep
  and (b) fixing a *separate* recurring direction bug (the "bounce to a lower high" → mislabeled
  bull leak), both found live this sweep.

---

## #20 — Wolf macro-brain: live health + bucket

### Pipeline health — ALL GREEN

Row counts / recency (PT):

| table | rows | latest activity |
|---|---|---|
| macro_theses | 65 (25 active) | last_updated 2026-06-12 13:01 |
| wolf_confluence_checks | 25 | checked 2026-06-13 09:36 |
| wolf_beneficiaries | 31 | computed 2026-06-13 09:26 |
| wolf_call_outcomes | 13 | computed 2026-06-10 01:40 |
| wolf_emails_processed | 112 (ALL parse_status='ok', 0 errors) | received 2026-06-12 13:00 |

Engine log (last 48h) confirms every loop is firing:
- `gmail_watcher`: ingested 06-11 "War is Over" (→4 events) + 06-12 emails (→1 each).
- `wolf_theses`: flip logic working (GOLD bear→bull, OIL bull→bear, SPX bear→bull, NDX bear→bull).
- `wolf_beneficiary_loop`: every ~15 min (latest 2026-06-13 09:42).
- `wolf_digest_loop`: armed; "Daily macro digest posted for 2026-06-12" at 04:04.

### Deferred follow-ups — status corrected vs the TODO

The `todo/wolf-macro-brain.md` header says **"NEXT: wire confluence into !all; shorts side
deferred to v1.1"**. Both are actually DONE and LIVE — the TODO header is stale:

1. **Confluence in `!all`: LIVE.** `consensus_engine/alerts/all_command/aggregator.py:188`
   `_wolf_confluence_lookup()` reads the stored confluence row for a ticker and renders a line
   in the `!all` embed (`embed.py:827`). Flag `all_command.wolf_confluence_field_enabled: true`
   (consensus.yaml:611, "#7 LIVE user go 2026-06-09"). Shipped in the full-audit-2026-06-06 run.
2. **Shorts-side beneficiaries: LIVE.** `wolf_beneficiaries.rank_shorts()` exists and is wired
   into the precompute loop (line 455), gated by `wolf.beneficiaries.shorts_enabled: true`
   (consensus.yaml:949, "#6 LIVE user go 2026-06-08"). DB currently holds 9 short rows
   (e.g. SMH bear → SMCI green / NVDA / AVGO shorts; OIL bear → DVN).
3. **63d RS horizon:** NOT actionable — closed user decision. `rs_window_days: 21` stays
   (consensus.yaml:940 comment: "user choice; 63d was the research rec").

→ **#20 has no genuinely-open feature work.** It is in done-soak. The one thing worth opening is
the thesis-quality issue below (which spans #20 and #26).

### #20 thesis-quality backtest — the active theses are PARTLY WRONG right now

`SELECT scope_key,direction,stage FROM macro_theses WHERE status='active'` returns 25 rows.
Cross-checked against the most recent real Wolf emails. Three of them are wrong, and they
all surface to the user (digest watchlist + confluence scoreboard + inferred beneficiary trades):

1. **IGV bull (id 140) — WRONG / stale-shift.** This is the exact #26 bug, RE-OCCURRED. The
   earlier IGV bull (id 97) was hand-invalidated 2026-06-08; a NEW IGV bull (id 140) was created
   2026-06-11 from the "War is Over" email. Wolf's real current stance (06-04/06-05 emails) is
   "the bull move is done, watching to short." Harm right now:
   - `wolf_beneficiaries` has 3 LONG ideas off it: **FTNT (green), GTLB (green), WDAY (yellow)** —
     "buy" suggestions when Wolf is watching to short.
   - `wolf_confluence_checks` rates it **critical (3 agree, 0 disagree)** — @-ping-eligible
     reinforcement of a call Wolf abandoned.
2. **SPX bull (id 143) + NDX bull (id 144) — WRONG (direction-guard leak).** Created 2026-06-12.
   Both evidence snippets are explicitly BEARISH: *"the bounce to a lower high in the SPX/NDX is
   probable"* and *"SPX and NDX bounce, maybe fill the gap, but to a lower high, forming a small
   H&S top."* A bounce to a lower high forming a head-and-shoulders top is a SHORT setup, not a
   bull stance — but the extractor read the up-move as bull and FLIPPED the prior correct SPX/NDX
   bear (ids 126/114) to bull on 06-12. (See #26 finding 2.)
   - Net effect on the digest's "Wolf's market lean" line: it now counts 2 bull / 3 bear
     broad-market calls — diluting/contradicting Wolf's actually-bearish regime read.

Other active theses spot-checked read correctly (SMH bear, OIL bear, GOLD bull, BTC bear,
DXY bull, YIELDS bull, RUT bear, DJIA bear).

### #20 minor hygiene bug (bounded harm)

The beneficiary loop (`wolf_beneficiaries.py:438`) only iterates ACTIVE theses and never deletes
rows for a thesis that got invalidated/flipped. So `wolf_beneficiaries` still has COIN-short rows
for thesis ids **114 (NDX) and 126 (SPX)** which were invalidated 2026-06-12 when those theses
flipped to bull. The digest reads beneficiaries by ACTIVE thesis id with a freshness gate
(`wolf_digest.py:123`), so these orphans don't surface — bounded harm, hygiene only. Fix = clear
beneficiary rows on `invalidate_thesis`, or a periodic orphan sweep.

---

## #26 — hedged stance-shift + staleness: the KEY backtest

### Buckets

- **Staleness decay: BUCKET 1 (NOT BUILT).** Grep confirms NO thesis-level staleness/decay/
  target-reached code anywhere (`wolf_theses.py`, `wolf_outcomes.py`, `main.py`). The only
  age-decay in the codebase is on confluence *source* rows (`wolf_confluence.py:_age_decay`),
  not on Wolf's own theses. A thesis stays active forever until a FLIP (opposite-direction call,
  `wolf_theses.py:191`) or the sprawl-cap evicts the oldest one. Nothing retires a thesis when
  Wolf moves on.
- **Hedged stance-shift extraction: BUCKET 2 (the bug is real and reproduced).** Current
  extractor misses the hedged IGV bear shift; the proposed prompt fix does not solve it.

### Reproduction of the bug (current extractor, real emails)

Ran the live `_extract_theses_llm` (gpt-oss-120b:free, direction_guard ON) on the 3 named emails.
Real output:

- **06-04 "Semis Show Cracks" (id 19e93fa7362eb2d4):** captures the SOX/SMH bear (the CLEAR
  stance) most runs; **never** an IGV thesis. ✓ matches the TODO.
- **06-05a "Rotation into Laggards" (id 19e96023b60514d2)** — THE key email. Wolf's hedged IGV
  bear shift, verbatim from the decoded body:
  - *"Recall that my entire Software hypothesis was that IGV would trade up to its 200-day/$100
    level… just as IGV is doing now."* (old bull target reached)
  - *"the recent surge in software stocks is driven entirely by technicals and positioning, not
    fundamentals."* (delegitimizes the move)
  - *"Now that Software (IGV) has a nice bounce 30% above its key trend line and the risk/reward
    is appealing, I'm looking for leading signals from price, credit and 3C."* (the pivot)
  - *"the renewed gating counts as exactly the kind of signal I was watching for once price
    finished the expected move up to $100."* (bear trigger forming)
  - **Current extractor: NO IGV thesis (MISS).** It extracts unrelated reads (GOLD/YIELDS/oil/
    copper/dollar depending on run) but never IGV. ✓ bug reproduced with real output.
- **06-05b "Long Duration / Higher Rates" (id 19e991ef58f54757):** correctly captures SMH bear
  (acting, intent=adding — "I'm up for adding to a Semi short I started"), plus DXY bull, BTC bear,
  GOLD bear, SPX bear. The CLEAR semis short works fine — confirms the miss is specific to the
  hedged language, not a broken extractor.

Smoke-test + cost: gpt-oss-120b:free answered on every email (10–31s each). It is a **free**
OpenRouter model → **$0 marginal cost** for these calls.

### A/B of the proposed `_DIRECTION_GUARD_RULE` addendum — IT FAILS

Prototyped the "hedged stance-shift = a new stance" clause described in the TODO (full text in
`/tmp/ab_extract.py`) and A/B'd CURRENT vs CURRENT+clause over 6 real emails. Both arms go through
the identical `_coerce_thesis`. Results (one trial each; gpt-oss is mildly nondeterministic at
temp 0.1):

| email | CURRENT | PROPOSED | verdict |
|---|---|---|---|
| 06-04 Semis Cracks | SMH bear | (none) | proposed DROPPED the clear semis read |
| **06-05a IGV shift** | GOLD only — **IGV MISS** | YIELDS only — **IGV MISS** | proposed STILL misses IGV |
| 06-05b Long Duration | BTC,DXY,GOLD,SMH,SPX | BTC,DXY,GOLD,SMH,SPX (identical) | no over-extraction (good) |
| 06-12 Afternoon | SPX **bull**, NDX **bull** | SPX **bull**, NDX **bull** | both mislabel "bounce to lower high" as bull (separate bug) |
| 06-12 War Over | GOLD, SPX bear | GOLD, SPX bear, **+IGV bull**, +MOO | proposed OVER-extracts a WRONG IGV BULL |
| 06-11 Worm Turning | 8 theses (BTC,DJIA,DXY,GOLD,NDX,OIL,SPX,YIELDS) | only 4 (dropped DXY,GOLD,OIL,YIELDS) | proposed SUPPRESSED 4 valid theses |

**Conclusion: the generic prompt addendum is counterproductive — DO NOT SHIP it.**
- It never caught the 06-05a IGV bear shift (the whole point).
- On 06-12 "War Over" it ADDED an IGV **bull** (wrong direction) and an extra MOO — i.e. it
  over-extracts, the exact failure gpt-oss-120b was chosen to avoid.
- On 06-11 it SUPPRESSED 4 valid theses (cut 8→4).
- **Multi-trial IGV catch rate (N=3 per arm, 06-05a) — the decisive number:**
  - CURRENT: IGV bear **0/3**, IGV bull 0/3 (never extracts IGV at all — the miss).
  - PROPOSED: IGV bear **0/3** (still never the bear shift), IGV **bull 2/3** (it mis-reads the
    "trade up to 200-day/$100" target language as a FRESH bull). And it added a spurious VIX bear 2/3.
  - i.e. the addendum NEVER catches the hedged bear (0/3) and instead manufactures a WRONG IGV
    bull 2 of 3 times. Control 06-04: both arms SMH bear 3/3 (stable, no harm).
  - **This is the core proof: the proposed fix does NOT demonstrably catch the hedged IGV shift —
    it makes the IGV call wrong in the opposite direction.**

Why a prompt-only fix is weak here: the 06-05a IGV passage is a genuinely soft "the bull move is
done, now I'm watching for the turn" buried in a 19k-char recap email. Wolf never says "I'm
shorting IGV" — he says "I'm looking for leading signals." A conservative free model reasonably
declines to invent a fresh bear. Pushing the prompt to fire here is exactly what produces the
06-12 over-extraction and the 06-11 suppression.

### A SEPARATE, cleaner direction bug found this sweep (higher-value)

The 06-12 afternoon email exposes a DIFFERENT, more tractable leak in the LIVE direction guard:
Wolf wrote *"SPX and NDX bounce, maybe fill the gap, but to a lower high, forming a small H&S
top"* and the extractor labeled SPX/NDX **bull**. The current `_DIRECTION_GUARD_RULE` has a
carve-out: *"Do NOT treat plain upside-target language (fill the gap, back-test a level…) as bear
by itself."* That carve-out is **over-firing** — it's swallowing a clear "bounce-to-a-lower-high-
to-fade / forming a top" stance as bull. This is the same FAMILY as #26 (a hedged up-move he
intends to fade) but with a crisp, repeatable trigger phrase ("lower high", "H&S top",
"failed breakout to fade") — much more catchable than the IGV soft-watch.

**Recommendation:** tighten the guard's carve-out so "bounce/fill the gap **to a lower high**" or
"**forming a top / H&S / failed breakout**" reads BEAR, while a plain "fill the gap" target stays
bull. This directly fixes the live SPX/NDX (and would have prevented the 06-12 bull flip). It
should be A/B-tested the same way (must not flip genuine "fill the gap" bulls).

---

## Staleness-decay design (#26 step 2)

Inputs available (all already in the schema / helpers):
- `macro_theses.last_updated` → days since last reaffirmation.
- `macro_theses.key_levels_json` with `role:"target"` → the stated target.
- `wolf_scope.proxy_symbol(scope_type, scope_key)` → tradeable ticker (IGV→IGV, SPX→SPY, etc.).
- `wolf_outcomes._fetch_proxy_series()` → blocking yfinance latest close + a vol band.
- `wolf_news.build_backdrop()` already surfaces the active market-bear regime — a hook for the
  cross-thesis check.

Current staleness landscape (days since reaffirm, live):
VIX bear **43d**, SILVER bull 32d, KWEB bull 30d, TECHNOLOGY bear 25d, NVDA bear 22d, MU bull 17d.
Note VIX bear (id 84) also CONTRADICTS the fresh UVXY/VXX bull (volatility longs = market bear);
VIX bear = market bull. A stale + cross-contradicted thesis.

Proposed rule (a periodic sweep in `wolf_theses.py` or a sibling loop, run nightly):

A thesis is demoted/invalidated when ANY of:
1. **Target reached + stale.** It has a `role:"target"` level AND the proxy's latest close has
   crossed it in the thesis's favor AND it hasn't been reaffirmed in ≥ N days (e.g. 7).
   *Caveat (proven live):* IGV's target is $100 but Wolf treats the "measured move to the 200-day"
   (~$90) as complete — so an exact-price target test would NOT fire for IGV (close $90.70 < $100).
   So this rule helps SILVER/MU-type clean targets, not the IGV case.
2. **Stale + sector flipped.** Not reaffirmed in ≥ N days (e.g. 14) AND a higher-conviction
   (imminent/acting) thesis of the OPPOSITE direction is active on the SAME complex
   (semis/tech: SMH/IGV/NVDA/MU/TECHNOLOGY; vol: VIX/UVXY/VXX; market: SPX/NDX/DJIA/RUT).
   This is the cross-thesis consistency check (#26 step 3) and the one that would catch a stale
   IGV bull while SMH bear is "acting" — IF IGV weren't being bullishly reaffirmed every few days
   (it is, so even this needs the direction fix to truly solve IGV).
3. **Hard age cap.** Not reaffirmed in ≥ M days (e.g. 45) → auto-demote to a "stale" display
   state or invalidate. Catches VIX bear (43d).

Guardrails (must not kill valid long-running theses):
- Only act on `forming`/`diverging` theses (never an `acting`/`imminent` call Wolf is live in).
- A reaffirmation (any new evidence_log entry for the thesis) RESETS the clock — so a genuinely
  long-running thesis Wolf keeps mentioning never ages out.
- Prefer DEMOTE (mark stale, drop from confluence/beneficiary eligibility, keep visible) over
  hard INVALIDATE, so a one-off quiet week doesn't erase a real call.
- Thresholds (N=7/14, M=45) are starting guesses — should be config keys and tuned on backfill.

---

## The open USER DECISION (surface + recommendation)

**Question:** Should a hedged "watching to short" lean (06-05a IGV) fire as a fresh BEAR thesis,
or is "no active thesis" the honest state until Wolf actually shorts?

**Recommendation: "no active thesis" is the honest state for IGV — do NOT force a fresh bear.**
Evidence: in 06-05a Wolf explicitly says he is *"looking for leading signals from price, credit
and 3C"* — i.e. watching, not short. The very next day (06-12 "War Over") he writes *"I'm still
hopeful IGV will bounce to back-test the 200-day and/or $100 area"* — he's still describing the
unfinished bull target, not a short. Firing a bear thesis off the soft 06-05a language would have
been WRONG by 06-12. The A/B confirms it: when we pushed the model to fire on hedged shifts, it
produced a wrong IGV BULL on 06-12 and suppressed valid theses elsewhere.

So the right outcome for the IGV problem is NOT "extract a hedged bear." It is:
1. **Don't carry the stale bull as `critical`-confluence + inferred LONGs** — the staleness sweep
   (rule 2/3) demotes it out of confluence/beneficiary eligibility once the sector has flipped
   bearish and it's gone quiet, leaving "no active high-conviction IGV call" — the honest state.
2. **Fix the separate "bounce-to-a-lower-high → bull" leak** (SPX/NDX), which is a clear
   mislabel, not a judgment call.

---

## Risks / caveats

- gpt-oss-120b is nondeterministic at temp 0.1 — single-trial A/B rows can flip a clear read on
  or off (06-04 SMH appeared in CURRENT but not PROPOSED in one trial). Any prompt change MUST be
  A/B'd over multiple trials AND the full backfill, not a single pass. The multi-trial run here
  (N=3) is a floor; a real change needs N≥10 + the conftest flag-off fixtures.
- A staleness sweep that hard-invalidates is dangerous (could kill a valid quiet thesis). Demote-
  not-delete + clock-reset-on-reaffirm + acting/imminent exemption are load-bearing.
- The "same complex" map for the cross-thesis check is a new artifact to maintain — keep it small
  and explicit (don't reuse sector_map.yaml, which memory flags as too coarse).
- All findings here are read-only/offline reproductions; none touch the live DB or services.

## Files
- Parser: `consensus_engine/analysis/wolf_email_parser.py` (`_EXTRACTION_USER_TMPL` ~59-103,
  `_DIRECTION_GUARD_RULE` ~108-123, `_extract_theses_llm` ~334).
- Ingest/flip: `consensus_engine/analysis/wolf_theses.py:191` (flip), `:58` (sprawl cap) —
  staleness sweep would live here or as a sibling loop.
- Consumers of active theses (where wrong theses surface): `wolf_digest.py:67`,
  `wolf_beneficiaries.py:438`, `wolf_confluence.py`, `all_command/aggregator.py:188`.
- Proxy/price helpers for target-reached: `wolf_scope.proxy_symbol`, `wolf_outcomes._fetch_proxy_series`.
- Repro scripts (ephemeral): `/tmp/fetch_wolf_emails.py`, `/tmp/repro_extract.py`,
  `/tmp/ab_extract.py`, `/tmp/ab_trials.py`. Decoded emails: `/tmp/wolf_06-04.txt` etc.
