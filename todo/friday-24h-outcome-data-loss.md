# Friday's scored tickers never get their 24-hour result — the soak that needs them can never finish

**Status:** OPEN
**Created:** 2026-07-13

**CURRENT STATUS (2026-07-13, second session, post-merge):** **Fix is LIVE.** PR #19 merged to master
(merge commit e34208e), engine restarted 11:53 PDT — clean boot, drift check passing, and the 24h
calibration immediately retrained on the recovered outcomes. Option A was chosen (grade a lost row
from stored daily prices at the next trading day's close): a catch-up fill (`_fill_alert_24h_catchup`
+ a 24h entry in `_SLOW_OUTCOME_HORIZONS`) grades any row older than the 48-hour live window from
historical daily bars, writing all three tables the live path writes (alert_history,
decision_snapshots, shadow label); a **completed-session guard** keeps a still-forming "today" bar
from ever being used as a close (also closed the same latent hole in the 5d/20d fill); regression
tests in `tests/test_friday_24h_catchup.py`; backfill script `scripts/backfill_alert_24h_outcomes.py`
already **recovered 637 of 729 lost rows** in the live DB. The 88 remaining recent rows are all
Friday 2026-07-10 — deferred task `1783959133_5bea2a` (now pointed at the main checkout) re-runs the
backfill at **13:20 PDT today** once Monday's close is final (4 ancient rows are delisted tickers,
genuinely unfillable). Soak counter moved n=0→2 pre-close. **What's left before closing:** (a) confirm
the 13:20 task filled the 88 (`/root/task_system/logs/1783959133_5bea2a.log`; failures also land in
notifications.log); (b) watch the auto-flip check's n climb at its next 09:00 PDT run; (c) the Part-3
switch decisions (Group A flips, blast-radius measurements, trading_halts yes/no, #67 soak-date
question) were deliberately deferred to #67 go-live work.

---

## Part 1 — The bug: Friday's 24-hour outcomes are thrown away, every week

### What happens

The engine writes a `decision_snapshots` row every time it scores a ticker, then comes back later to
record what the price did (`outcome_price_24h`). That backfill only runs inside a **24-to-48-hour
window** — `get_alerts_needing_price_update()` in `consensus_engine/db.py:2746-2748`:

```python
elif field == "price_24h_later":
    min_age = 86400      # at least 24 hours old
    max_age = 172800     # no older than 48 hours
```

Outside that window the row is **permanently unfillable** — 1h/24h read a *live spot price*, so an
aged-out row can never be graded.

The engine pauses **Friday 3pm → Sunday 3pm PDT** (`_is_weekend_pause()`, `consensus_engine/main.py:99`).
During the pause `main.py:894-932` runs **only the command listener** and then `continue`s — it never
reaches `main.py:996` where `price_outcome_loop` is created. So the backfill loop **does not run at all**
during the pause.

For anything scored on Friday, the 24–48h window (Sat + Sun) falls **entirely inside the pause**. By the
time the engine resumes Sunday 3pm, the rows are already older than 48h. They are lost.

### Measured evidence (live DB, 2026-07-13)

Resolution rate of `outcome_price_24h` by the weekday the snapshot was recorded:

| Day scored | Snapshots | Got their 24h result | Rate |
|---|---|---|---|
| Mon | 598 | 578 | 97% |
| Tue | 550 | 550 | 100% |
| Wed | 403 | 403 | 100% |
| Thu | 597 | 514 | 86% |
| **Fri** | **257** | **9** | **4%** |

Thursday's 86% is the same bug's tail — Thursday-afternoon rows need filling Friday-afternoon-to-Saturday,
and the Friday 3pm pause cuts that short.

Confirming detail: the last snapshot that *ever* received a 24h price is **id 3615, 2026-07-09 14:08 PDT**.
Nothing since. The 74 snapshots recorded Friday 2026-07-10 (05:19–13:23 PDT) all have an entry price and
**zero** have a 24h outcome.

### Why this blocks the auto-flip engine

`scripts/.../auto_flip_check.py` (at `/root/task_system/scripts/auto_flip_check.py`, daily 09:00 PDT timer
`auto-flip-check.timer`) needs **n>=90 resolved** rows to judge `fold_display_signals`. Its log
(`/root/task_system/logs/auto_flip_check.log`) says on every run:

```
fold_display_signals: NOT ready — n=0/need 90, metric=None (need >0.5).
```

The display-signal forward-logger **is working** — `consensus_engine/analysis/display_signals.py:324`
`log_display_signals()` fires on the alert path (`main.py:1761`), logged 75 times in the last 3 days,
and has written **101 snapshots** (ids 3631–3731, first at 2026-07-09 20:25 PDT) each with 15 fields /
5 canonical keys. The data is there.

But **0 of those 101 have a 24h outcome**, because of the bug above. So n=0. It is not a slow soak — it
is a soak that **cannot finish**, and it would keep bleeding every Friday even after it started moving.

**Important:** the earlier read of that log line ("forward-logger not built yet") is *wrong* and should
not be trusted — the logger is built and running. The checker is correctly reporting n=0 resolved; the
prose it prints about *why* is misleading.

### The decision needed (blocks the fix)

What does "24 hours later" mean for a ticker scored Friday morning? Saturday morning has **no market
price** — it does not exist.

- **Option A (recommended):** fill the outcome from **historical daily bars** instead of a live spot
  price, and grade at the **next trading day's close**. This is the mechanism `_fill_slow_outcomes` /
  the 5-day path (`main.py:1992`, `main.py:2031`) already uses successfully — `price_5d_later` deliberately
  has a wide `min_age 7d / max_age 30d` window *because* bars stay available. Reusing it lets the 24h
  window stay open for days, so Friday's rows get filled on Monday instead of being lost. Small, proven change.
- **Option B:** grade Friday at its own close (same-day). Different thing to measure; keeps "24h" meaning
  something closer to "intraday move".

This changes how alerts are **graded**, not which alerts **fire** — safe either way. But picking wrong
means re-running the soak from scratch, so it needs an explicit call.

### Also worth fixing while in here

The 5-day outcome (`outcome_price_5d`) last filled 2026-07-06. That is **not** a bug — `min_age` is 7 days,
so 2026-07-07 onward simply isn't due until 2026-07-14. Verify it resumes on schedule rather than assuming.

---

## Part 2 — The other auto-flip switch is working, and its verdict is "no edge yet"

`analyst_accuracy_promote` **reached its bar**: n=105 (needs 90). Its score is the blocker, not its data:

```
analyst_accuracy_promote: NOT ready — n=105/need 90, metric=0.429 (need >0.5).
tested 2 analysts; FDR+Wilson winners=[];
best={'entity': 'The_RockTrading', 'horizon': '24h', 'n': 105, 'wilson_lb': 0.429, 'p': 0.348}
```

Plain English: the best analyst tested is **not beating a coin flip** with statistical confidence
(0.429, needs above 0.50). `source_performance` has 26 rows at 24h and 28 at 5d.

This is a **real research result**, and right now it lives only in a log file that gets appended to and
could be lost. It belongs on the record. It is not a failure — the engine is correctly refusing to flip
a switch the evidence doesn't earn. Only **2 analysts** were tested, so the honest read is "not enough
distinct analysts yet", not "analysts are useless".

---

## Part 3 — Soak-clock finding: most OFF switches accrue nothing while OFF

TODO #67 is marked `SOAKING until 2026-07-15`. Two problems with that clock:

1. **The soak is shorter than it looks.** It started 2026-07-08. By 2026-07-15 that is about **five
   trading days**, not seven — two weekend days don't count. (Same trap as the "7-day soak that was really
   ~4 trading days" comm-check lesson.)
2. **For 7 of the switches the clock is meaningless** — they collect *nothing* while OFF. They compute
   fresh on demand each time a command runs. Waiting until the 15th gives them exactly zero additional
   evidence.

### Full switch inventory (verified against the code, 2026-07-13)

**Group A — can flip today, nothing to wait for (7).** All DISPLAY-ONLY: they add a line to a card and
**cannot** change a score or fire an alert. Verified by code trace — the max-pain dict that carries most
of them never reaches `cross_reference.py` or `engine.py`.

| Switch | Shows up as | Note |
|---|---|---|
| `features.skew_index` (r8) | `!all` SKEW field | on-demand `^SKEW` fetch |
| `features.dealer_gamma` (k4/k5) | `!all` Dealer Gamma field | free — reuses the already-fetched chain |
| `features.iv_skew` (r10) | `!all` IV Skew field | free — same chain |
| `features.oi_pinning` (r16) | `!all` OI Pinning field | free — same chain |
| `features.vol_squeeze` (r9) | `!all` Squeeze field | free — reuses daily candles |
| `features.market_breadth` (r20) | `!market` panel line | computes live; does NOT need the shadow table |
| `features.iv_rv_tag` (k7) | `!all` Vol Read field | **costs ~1–2s extra per `!all`** (adds a chain fetch) |

**Gate to flip:** look at one real `!all` and one real `!market` with them on, confirm the output reads
sensibly. That is the whole gate (TODO #67 already says "the 7 options-card readouts need no soak —
validate by eye once").

**Group B — change scores or send alerts. Need a blast-radius measurement, NOT more soak (4).**

- `features.short_interest.enabled` (r12) — adds up to **+3 points, LONG-only, additive-up**
  (`cross_reference.py:362`; `term_cap: 3`). **Already has months of data** — 8 FINRA settlement periods
  back to 2026-03-13, 3241 rows; at the latest period (2026-06-30) **42 of 212 tickers** would clear the
  gate (days_to_cover ≥3 AND rising). Soak is NOT the blocker. Blocker: "how many past alerts would change
  tier?"
  - **Stale comment caught:** consensus.yaml:879 claims "`!short` trend + confluence leg both stay gated on
    `.enabled` ONLY." That is **wrong** — `_handle_short` (`alerts/commands.py:2260-2298`) reads the history
    with **no flag check**, so `!short` already works today off the shadow-collected data. Only the score
    leg is gated. Fix the comment.
- `features.pead.enabled` (r17) — adds up to **+3 points, additive-up** (`cross_reference.py:386`). Computes
  on demand (no table needed), but **adds a yfinance fetch to the hot scoring path per ticker**. Same
  blast-radius measurement needed.
- `features.trading_halts.enabled` (r14) — the **only** switch that can send a message that would not
  otherwise be sent (instant alert on a tracked-ticker halt, `scanners/trading_halts.py:227-257`). Collects
  **nothing** while OFF (`trading_halts` table = 0 rows), so waiting gains nothing. Blocker: a yes/no on
  whether these pings are wanted.
- `features.cross_asset.nfci_leg_enabled` (r21) — **highest risk, and the only one that genuinely needs more
  time.** It does not add points; it **moves the STRONG cutoff itself** for every ticker at once, in both
  directions (`cross_asset.py:488` → `engine.py:331-336`; effective cutoff = `clamp(80/multiplier, 70, 90)`).
  Because `cross_asset.enabled` is already `true` in prod, flipping this perturbs the live multiplier
  immediately. Shadow data so far: **3 readings, all identical (-0.515)** — nowhere near enough variation to
  prove it adds anything. Needs weeks.

**Group C — collecting fine, but never wired to a display (owed work, not a switch).** `form144` (54 rows),
`insider_10b5_plans` (35), `congress_trades` (12) are all ON and writing, but nothing surfaces them to the
user yet. #67 already lists this as an owed follow-up ("wiring the Stage-6 insider context lines onto the
live `!sec`/`!all` surfaces"). Note `insider_10b5_plans` last wrote 2026-07-10 — that is **benign**, it only
writes when a new Form 4 carrying the plan flag arrives, and the weekend has none.

**Group D — deliberately off, leave alone.** `manufactured_agreement_gate` (user declined 2026-06-26 — do not
re-enable), `sector_rotation` / `factor_rotation` / `trend_regime` / `macro_legs` / `internal_breadth` (F1–F5,
proven NO-EDGE), `consensus_logodds` (needs code, not data), `social_family_dedup` (needs its own blast-radius
measurement), `stocktwits_enabled` (Cloudflare-blocked), `serpapi_enabled` (no credits).

---

## Health check — what IS working (verified live 2026-07-13, market open)

- `consensus-engine.service` + `openclaw-gateway.service` both **active**; engine scoring live this morning
  (TVTX, SNOW, ORCL at 07:36–07:43 PDT; 20 snapshots today).
- All shadow collectors writing: `finra_short_interest` 3241, `form144_filings` 54, `insider_10b5_plans` 35,
  `congress_trades` 12, `market_breadth_daily` 4, `macro_legs_daily` 3, `cross_asset_shadow` 12.
- **NFCI self-healed** as predicted — the last 3 `cross_asset_shadow` rows carry `nfci_index = -0.515`
  (the cold-start `None` on 2026-07-08 was a transient).
- Display-signal forward-logger firing normally (75 runs in 3 days).

### A smaller thing noticed, not chased

`macro_legs_daily` has **3 of its 5 legs permanently NULL** — `copper_gold_roc`, `semis_rs`, and
`cyc_def_div` are None on every row; `legs_used_json` is always `["dxy_roc", "real_yield_roc"]`. The F4
`macro_legs` feature is OFF/shadow and is in the proven-NO-EDGE group, so this changes nothing live — but if
that shadow data is ever meant to be evaluated, it is only carrying 2 of 5 legs. Worth a look before anyone
trusts it.

---

## Files / code involved

- `consensus_engine/db.py:2729-2754` — `get_alerts_needing_price_update()`, the 24–48h window (**the bug**)
- `consensus_engine/main.py:99` — `_is_weekend_pause()` (Fri 3pm → Sun 3pm PDT)
- `consensus_engine/main.py:894-932` — the pause branch that skips loop creation
- `consensus_engine/main.py:996` — where `price_outcome_loop` is created (never reached during the pause)
- `consensus_engine/main.py:2091-2145` — `price_outcome_loop`, the 1h/24h backfill
- `consensus_engine/main.py:1992` / `main.py:2031` — `_fill_slow_outcomes` / `_fill_alert_5d_outcomes`
  (the historical-bar mechanism Option A would reuse)
- `consensus_engine/analysis/display_signals.py:324` — `log_display_signals()` (working)
- `/root/task_system/scripts/auto_flip_check.py` + `/root/task_system/logs/auto_flip_check.log`
- `config/consensus.yaml` — line 879 stale `!short` comment; lines 876-914 the OFF switches

## Next steps, priority-ordered

1. **Get the Option A / Option B call** on how to grade a Friday snapshot (see "The decision needed").
2. Implement the fix; add a regression test that a Friday-recorded snapshot still resolves after the
   weekend pause.
3. **Backfill what is still recoverable** — historical bars go back years, so the lost Friday rows may be
   fillable retroactively under Option A. Check before writing them off.
4. Flip the 7 display-only switches (Group A) after one eyeball check of a real `!all` + `!market`.
5. Measure blast radius for `short_interest` and `pead` (how many past alerts change tier), then decide.
6. Fix the stale `!short` comment at consensus.yaml:879.
7. Record the analyst verdict (n=105, 0.429) somewhere durable — it is a real result currently living only
   in a rotating log.

## Open questions

- Option A or Option B for Friday grading? (blocks everything else)
- Are the already-lost Friday rows worth retroactively backfilling, or start clean from the fix date?
- `trading_halts`: are instant halt pings wanted at all? (it can never earn evidence while OFF)
- Should TODO #67's `SOAKING until 2026-07-15` date be dropped for the 7 switches it cannot possibly help?

### Session notes — 2026-07-13
- **Worked on:** implemented Option A end-to-end (catch-up fill in `db.py`/`main.py`, completed-session
  guard on the bar helper, `tests/test_friday_24h_catchup.py`, `scripts/backfill_alert_24h_outcomes.py`);
  ran the live backfill (637/729 recovered); scheduled task `1783959133_5bea2a` at 13:20 PDT for the 88
  Friday rows; fixed the stale `!short` comment (consensus.yaml); recorded the analyst verdict in
  project memory (`project_analyst_accuracy_interim_verdict.md`).
- **Decisions:** Option A (next trading day's close from stored bars) — Option B would measure a
  different, shorter thing and break comparability. All 729 recoverable historical rows backfilled,
  not just the soak-era ones (more resolved data for analyst grading too).
- **Next:** merge the PR + restart the engine; then confirm the 13:20 task filled Friday's 88 rows and
  the auto-flip check's n starts climbing (daily 09:00 run).
