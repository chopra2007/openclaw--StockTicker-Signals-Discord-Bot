# Build handoff — I3, I4, I7, #20 (and note on #46)

**Created:** 2026-06-17 · **For:** a fresh Claude Code session executing autonomously.
This file is self-contained. Everything below was verified first-hand (read the actual code + queried the real DB, then a second agent re-verified every file:line and number). Trust it, but re-open each cited line before editing — code can move.

---

## 0. Ground rules (read first — these override speed)

- **Repo:** `/home/openclaw/.openclaw/workspace`. Branch `master`.
- **User is a non-coder.** Every user-facing word: plain English, no jargon, short. (See `CLAUDE.md` → Communication Discipline.)
- **Definition of Done (`CLAUDE.md`):** test the WHOLE feature you touched, not just the line. Show ACTUAL output (an alert, a query result) — "service started" / "tests pass" is NOT proof. Judge output against the goal.
- **Always-on checks after every restart:** `consensus-engine.service` + `openclaw-gateway.service` both `active`; no `❌ GATEWAY drift` alert; `/root/.openclaw` still symlinks to `/home/openclaw/.openclaw`.
- **Regression gate:** baseline of known-failing tests is `.test-baseline` (currently just `test_wolf_digest` sunday_recap). No currently-passing test may newly fail. Run: `cd /home/openclaw/.openclaw/workspace && python3 -m pytest tests/ -n 2 -q`. A **separate** verifier agent (not the one who wrote the code) re-runs the suite at the end.
- **DB:** the real production DB is `consensus.db` (~489MB, has `decision_snapshots` + months of history). The other `*.db` files are empty stubs. Query it as the openclaw user: `sudo -u openclaw sqlite3 consensus.db "..."`.
- **conftest flag trap (`reference_conftest_flag_default_off`):** turning a feature flag ON in `config/consensus.yaml` breaks older tests that read live config. Fix = the autouse fixture in `tests/conftest.py` must force the newly-flipped flag OFF for legacy tests; the dedicated feature tests force it ON themselves.
- **Worktree isolation is BROKEN here** (`/root/.openclaw` symlink) — do NOT use `isolation: worktree`. Edit files directly; do builds sequentially.
- **Build → test on the DB → flip ON this session** is the standing rule (#41). A switch stays OFF at session end only if genuinely broken / data-blocked — name the exception.
- **Commit locally per item** (imperative messages). **Do NOT push** — push happens only at session close ("bye"), through the gate.
- **Recommended order:** I4 (safest) → #20 (mostly verify) → I3 (small, goes live) → I7 (biggest, new alert).

---

## ITEM 1 — I4: show ONE score, not two that disagree  ·  (user: "I want this fixed")

**Problem (verified live):** the Cross-Reference detail follow-up embed shows a "Breakdown" line that is the raw additive sum of source points (e.g. **105**), while the headline/title and "Precision Engine" field show the gated score (e.g. **72**). Two numbers, same alert. Reproduced with real config defaults (`single_score` OFF, `score_display_honesty` ON): title `Score: 72`, Breakdown `... = 105`.

**This is display-only.** The tier (STRONG/WATCHLIST/IGNORE) is decided in `main.py:1442-1452` BEFORE any of this. No alert/tier changes.

**The fix — one edit** in `consensus_engine/alerts/discord.py` (NOTE: `alerts/discord.py`, not `consensus_engine/discord.py`). At **line 507**:
```python
# current:
breakdown_text = " + ".join(parts) + f" = {total}"
```
Replace with (keeps the legacy both-flags-OFF path byte-identical):
```python
if headline_total != total and (single_score_on or honesty_on):
    breakdown_text = " + ".join(parts) + f" = {total} raw → {headline_total} after quality gates"
else:
    breakdown_text = " + ".join(parts) + f" = {total}"
```
`headline_total`, `single_score_on`, `honesty_on` are all already function-locals (defined at discord.py:358-360, overridden at 368/387). No main.py change needed. Result: the Breakdown line now ENDS at the same number as the headline (72), with a plain-English reason ("after quality gates").

**Flag:** leave `features.single_score` OFF (`config/consensus.yaml:807`). The already-ON `score_display_honesty` path supplies `headline_total`; the discord.py edit is the real fix. (If the user later wants the STRONG-floor / budget-fallback semantics, flip single_score ON too — the discord.py edit is required either way.)

**Verify:** (a) `python3 -m pytest tests/test_i4_full_single_score.py -v` (11 pass today) — extend it to assert the Breakdown number equals the title number when gated. (b) full suite vs baseline. (c) trigger a real alert / `!all` on a ticker and read the embed: title, Precision Engine field, and Breakdown must all show the SAME number, and the tier icon 🟢/🟡 unchanged.

**Note:** this is the small first slice of TODO **#46** (unified display scale). Use a clean formatting approach so #46 can generalize it later.

---

## ITEM 2 — #20: Wolf confluence in !all is ALREADY LIVE — add a "warn if it goes dark" watch

**The premise "waiting for data, flip when ready" is STALE.** Verified: `config/consensus.yaml:614 wolf_confluence_field_enabled: true` — live since 2026-06-09. The 15-min populator loop runs (`main.py:920-957`). **10 of 18 active Wolf theses render a real confluence line right now:** MU(3 agree), SMH(3 disagree), IGV(3 disagree), NVDA(divided), GOLD(divided), NDX(2 disagree), SPX(2 disagree), BTC(1 agree), OIL(1 disagree), GDX(1 agree). **Nothing to flip.**

**Do this instead:**
1. **Mark TODO #20's !all-confluence item SHIPPED/LIVE** and delete the stale "waiting for data" note (find it in `TODO.md` + its detail file).
2. **Build the inverse watch** (the genuinely useful thing): a scheduled check (systemd timer via `/root/task_system/scripts/create_task.sh`, with retries+logging+cleanup) that runs the renderable-count query and pings **only if it drops to 0** — i.e. the section silently goes blank because Wolf email ingestion stalled or all sources dried up. Write to `/root/task_system/notifications.log` (read at session start per `CLAUDE.md`) and/or post to #news.

**Queries:**
- Renderable count (the "is it healthy" metric, currently **10**):
  `sudo -u openclaw sqlite3 consensus.db "SELECT COUNT(*) FROM wolf_confluence_checks c JOIN macro_theses t ON c.thesis_id=t.id WHERE t.status='active' AND (c.agree_count+c.disagree_count)>0;"`
- Live end-to-end (same code path !all uses, read-only):
  `sudo -u openclaw python3 -c "import asyncio; from consensus_engine.alerts.all_command.aggregator import _wolf_confluence_lookup; from consensus_engine.alerts.wolf_news import _confluence_field; print(_confluence_field(asyncio.run(_wolf_confluence_lookup('MU'))))"`

**Watch the threshold:** define "dark" as renderable count = 0 (or < a small floor like 2). Don't count all 18 active theses — 8 of them legitimately render nothing (URA, MOO, REMX, TECHNOLOGY, DXY, YIELDS, VXX, UVXY have 0 agree/0 disagree, which is correct).

---

## ITEM 3 — I3: require 2+ opposing sources before a contradiction downgrade, then turn ON  ·  (user chose "A then turn it on")

**Goal:** today a STRONG alert can be downgraded to WATCHLIST when bearish signals contradict it. Require **≥2 distinct opposing sources** before that downgrade can fire (so one lone opposing source can't sink a thinly-supported STRONG), then flip the I3 producer flag ON.

**The edit — one line** in `consensus_engine/cross_reference.py` at **line 1678** (inside `score_ticker`; `n_opposing` is already computed in scope at ~line 1651 via `_count_opposing_actors`):
```python
# current:
result_ci = computed_ci if cfg.get("features.contradiction_index_live.enabled", False) else 0.0
```
Replace with (reuses the currently-dead `min_actors: 2` key at consensus.yaml:803):
```python
_min_opp = int(cfg.get("features.contradiction_index_live.min_actors", 2))
result_ci = computed_ci if (cfg.get("features.contradiction_index_live.enabled", False) and n_opposing >= _min_opp) else 0.0
```
Forcing `result_ci = 0.0` when `n_opposing < 2` makes both downgrade sites no-op automatically (engine.py:384 computes the verdict on 0.0 → below_threshold; main.py:1470 `if real_ci > 0.0` is skipped). No consumer change needed.

**Then flip the flag:** `config/consensus.yaml:803` → `contradiction_index_live: { enabled: true, min_actors: 2, downgrade_threshold: 0.5 }`.

**Also persist `n_opposing` for future backtesting** (do this — it's the only way to ever validate this on stored data): add `"n_opposing": n_opposing` to the feature-vector dict assembled around `main.py:1536-1569` (and/or the shadow block near cross_reference.py:1670-1676) so future `decision_snapshots.feature_vector_json` rows carry it.

**⚠️ Honesty / DoD exception (must tell the user):** a stored-data backtest is **IMPOSSIBLE** here — all 1949 `decision_snapshots` rows have `contradiction_index = 0.0` (the producer flag was always OFF) and `n_opposing` was never stored. So WITH-vs-WITHOUT can't be counted on history. Validation = the unit tests (`tests/test_i3_contradiction_producer.py`, 16 pass) + **forward shadow**. Turning the flag ON changes LIVE alerts (STRONG→WATCHLIST, logged `[A1]`). The user said turn it on — so do, BUT this is a legitimate "needs forward-collected data" case: after flipping, watch the `[A1]` log for the first real downgrades and confirm each had ≥2 opposing sources before declaring it proven.

**`_count_opposing_actors` taxonomy caveat:** opposing actors are drawn only from {youtube, options, sec} (the analyst/tweet cluster is hardcoded as SUPPORTING). So "2 distinct opposing sources" means 2 of those three disagree. That's sensible (a bullish STRONG contradicted by 2+ of youtube/options/sec), but note it — it is NOT "2 analysts disagree."

**conftest:** turning the flag ON in config will break legacy tests reading live config → add `contradiction_index_live.enabled = false` to the autouse OFF fixture in `tests/conftest.py`; the I3 tests force it ON themselves.

---

## ITEM 4 — I7: loud "SWARM" alert when 4+ analysts tweet the same ticker in 60 min  ·  (user's real ask)

**Key finding: the detector ALREADY EXISTS, is enabled, and is wired in — but it's silent and has never fired.** `consensus_engine/analysis/herding.py` `detect_cluster()` already: queries `signal_events` for distinct TweetShift analysts (`source_detail` = analyst handle) on a ticker within a window, dedups by analyst, and on fire writes a `cluster_events` row + marks members consumed. It's called from the tweet path at `main.py:1326-1335`. TWO things keep it useless:
1. On fire it only does `log.info("[A2] ...")` — **no Discord send**.
2. A **trust floor** (herding.py:144-154) requires 2+ analysts with `rolling_accuracy ≥ 0.5` from `source_performance` — and `source_performance` has **0 rows**, so it blocks 100% of fires. `cluster_events` = 0 rows ever.

**Backtest on real tweet history (already run, `consensus.db`, 3191 tweets / 33 analysts / 7 weeks):** 4-distinct-analysts-in-60-min, deduped, would fire **18 times across 8 tickers** (NVDA:8, AAPL:2, INTC:2, MU:2, CSCO/META/MSFT/TSLA:1 each) — ~2-3/week, loud but rare. (3+ = 60 fires, too noisy; 5+ = 7 fires, very rare.) **Use threshold 4.**

**Changes (reuse the detector — do NOT build a second one):**
1. `config/consensus.yaml:727-733` (`features.analyst_herding`): `min_cluster_size: 3 → 4`, `window_minutes: 30 → 60`, add `require_trusted: false`. (Optionally `panic_min_cluster_size: 4 → 5`.)
2. `herding.py:144-154` — gate the trust floor so it's bypassed by default:
   ```python
   if cfg.get("features.analyst_herding.require_trusted", False) and trusted_count < 2:
       return ClusterResult(..., reason="trust_floor_failed")
   ```
   (Volume of distinct analysts IS the signal for a "breaking news" detector; accuracy-weighting is what's kept it dead.)
3. Add a **loud Discord sender** (model it on `send_instant_ping`, ~`main.py:1352`). e.g. `send_cluster_alert(ticker, cluster_result, ...)`: red/orange embed, title like `🚨 SWARM: $NVDA — 4 analysts tweeting in 60 min`, list the analyst handles (link via `signal_events.source_link` where present — many historical rows are NULL, that's fine; new tweets populate it), show the window span (first..last), framing = "multiple independent analysts on the same name right now — something may be happening."
4. `main.py:1326-1335` — when `_cluster.fired and _cluster.cluster_id`, call the new sender (it currently only logs).

**Dedup:** already handled by `consumed_by_cluster_id` (a fired cluster's members are marked consumed and excluded from the next window) → one alert per cluster, no spam. **Open question for the user:** re-fire/escalate if the cluster keeps growing (4→7 analysts), or one-shot? Default = one-shot (current behavior).

**Open questions to settle (pick sensible defaults, tell the user):** which channel (default: the instant-ping alert channel; or a dedicated #breaking) and whether to @-mention/ping a role.

**New LIVE user-facing alert → DoD:** the 18-fires backtest is necessary but NOT sufficient. Add a unit test that simulates 4 analysts in 60 min and asserts the sender fires + embed shape. Run `python3 -m consensus_engine --dry-run --once`. Eyeball the first real fire. `main.py` is the ingest hot path (shared-file tripwire) — re-test the full `!all` and the normal alert path after.

**Leave `consensus_logodds` (I7 flag, consensus.yaml:808) OFF** — separate no-op, unrelated to this.

---

## NOT in this build (context so nothing gets resurrected)

- **Regime-adaptive bar (I14 widening + E2 cross_asset): SCRAPPED** by the user 2026-06-17. Both flags stay OFF. Do not build, do not re-add. They were also wired in OPPOSITE directions (I14 raised the bar in panic, E2 lowered it) — a design smell that's now moot.
- **Regime "mood" display line** (`features.regime_context_line.enabled`, currently ON, shows "Regime: normal (z=0.1)"): user said leave it ON for now. Its confusing z-score scale gets fixed under **#46**, not here.
- **#46 (unified display scale):** its own future effort. First step there is a FULL audit of every scale (the examples listed are not exhaustive). Not part of this session unless explicitly asked; just keep I4's fix tidy so #46 can build on it.

## Close-out

Run the full regression gate via a separate verifier agent, diff `.test-baseline`. Confirm always-on checks. Commit each item locally. Report to the user in plain English with ACTUAL output shown (a real alert, a query result), per the evidence standard. Open items left for the user: I7 channel/escalation choice; I3 forward-shadow watch.
