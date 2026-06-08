# Session handoff — 2026-06-08 Wolf go-live + accuracy

Self-contained record of the 2026-06-08 session + prioritized next steps. The new session can act
from this file alone. User is NOT a coder — keep all user-facing text plain.

Trigger line that started this session:
`Read .claude/discover/full-audit-2026-06-06/SESSION-PLAN-2026-06-08.md and run it fully autonomously per its "Automation mode" section (plan -> one decision pause -> execute).`

Commits (local on master; PUSHED at this session's close): `9f24ab4` code+tests, `533456b` config go-live, `c24830d` docs (+ a docs/handoff commit after this file).

---

## What was done

### The 8 planned items — built, tested, committed, deployed
- **#1 IGV direction guard** — prompt rule (trade stance vs near-term price tick), flag `wolf.direction_guard.enabled` = **ON**.
- **#2 backfill** — ran `scripts/backfill_wolf.py --rebuild` (95 emails). Added `DELETE FROM wolf_beneficiaries` to `_REBUILD_CLEAR` (avoids id-renumber orphans). NOTE: vision was DISABLED for the backfill (`wolf_vision_calls`=0 temporarily) because a rapid chart-read burst 502-storms the free vision models — restored to 80 after. So the rebuilt theses are text-only (no chart levels); live emails refill levels going forward.
- **#3 confluence** — level-less agreement now shows on the board (`wolf.confluence.board_show_levelless`=ON) + clickable YouTube links (`wolf.confluence.links_enabled`=ON). Links built at the render layer (scorer stays I/O-free). Twitter links = design-only, NOT built.
- **#4 vision** — migrated Wolf chart-reads off direct-Gemini to a free OpenRouter chain `[nvidia/nemotron-nano-12b-v2-vl:free → google/gemma-4-31b-it:free]` (probed live; the other named models are 404/paid). Budget raised 30→80.
- **#5 silent-outage alarm** — folded into `chain_health_loop` (health.py). Per-feed thresholds in `health_check.feeds` (wolf 72h / youtube 120h — weekends give ~65h Wolf gaps, so the original 24h would false-alarm).
- **#6 audit / go-live** — flipped the approved flags (below). Wolf SHORT (`wolf.beneficiaries.shorts_enabled`=ON) → only ~5 eligible index/sector bears; picks show a green/yellow dot (not red); up to ~60-min throttle before first short appears.
- **#7 YouTube backlog** — failed/budget-skipped videos now retry (`youtube.max_retries`=5; `attempt_count`/`last_attempt_at` cols; `get_retryable_youtube_videos` drains oldest-first). 65 failed videos became retryable. "missing" (no caption track) stays terminal.
- **#8 SEC named insiders** — `cross_reference._run_sec_check` appends per-insider Form 4 detail when `sec_watcher.named_insiders_in_alert`=ON. NOTE: the enriched summary also feeds the LLM thesis prompt.

### Incident fixed (pre-existing, not from this session's plan)
- **6-hour Discord gateway outage.** `openclaw-gateway` was failed since 03:00 PDT: an overnight npm update (openclaw 2026.6.1) rewrote `/home/openclaw/.openclaw/openclaw.json` as **root** (0600) → gateway (runs as openclaw, uid 998) EACCES. Also `sources.json` went root-owned. Fixed: `chown openclaw:openclaw` both. This is the recurring openclaw.json ownership trap (see memory `reference_openclaw_json_ownership`). **Watch for it again after any openclaw update.**

### Wolf accuracy fixes — triggered by the user finding 4 wrong #news theses
The extractor turned descriptive/jargon text into confident calls (one even @-pinged the user). Fixed the PATTERNS in `consensus_engine/analysis/wolf_email_parser.py` (live):
- **Correlation misread** (BTC): "X is leading/dragging Y higher" / "relative strength" is commentary, not a stance → clause in `_DIRECTION_GUARD_RULE`. (BTC now reads bear, matching the user.)
- **"Most Shorted Index" jargon** (MSI): Wolf's internal breadth gauge ("MSI") was mistaken for the stock MSI/Motorola → dropped in `_coerce_thesis` when snippet says "most short".
- **Index levels on an ETF** (SMH): SOX index points (~12,616) pinned to the ~$270 SMH ETF → `scope_key=='SMH'` drops levels ≥1000.
- **Cross-contamination outliers** (URA/REMX both had a stray 4,500): drop any level >20x off the median when ≥3 levels exist.
Data stop-gaps: invalidated the live misreads (BTC/IGV/MSI), cleared SMH/URA/REMX bad levels, deleted 3 wrong #news posts. **The 6 fixes are live for FUTURE emails; the older theses were extracted with the buggy code — a full re-run would clean any stragglers (see Next steps).**

### Tests / gate
- Full suite: **1863 pass, 1 pre-existing fail** (`tests/test_wolf_digest.py::test_sunday_recap_and_addon_restart_safe` — confirmed failing on clean pre-session code; now in `.test-baseline`).
- Flipping the user-visible flags broke older tests that assumed default-OFF → fixed with an autouse `_audit_flags_default_off` fixture in `tests/conftest.py` (dedicated feature tests force their own flag and still pass). See memory `reference_conftest_flag_default_off`.
- `aggregator.py` smart-levels block wrapped fail-safe (can't crash !all on missing candles).

---

## Suggested next steps (prioritized)

1. **TODO #26 — catch Wolf's hedged direction changes + retire stale calls** (HIGHEST VALUE). The deeper reason IGV kept showing "bull": his software view turned bearish in a soft/hedged way the extractor misses, and nothing retires a completed call. Needs a gated prompt clause for stance-shifts ("now that the move to $X is done, I'm looking to short") + a staleness rule — both need careful A/B (over-extraction risk). `todo/wolf-hedged-stance-and-stale-theses.md`.
2. **Optional: re-run `--rebuild` to clean stragglers.** The current live theses were extracted with the OLD (buggy) code. The 6 fixes only apply going forward. A fresh `--rebuild` (with vision disabled via `wolf_vision_calls`=0, engine stopped) would re-extract all theses cleanly. ~30 min + brief engine downtime. Judgment call — the patterns are fixed and live emails refresh gradually, so only do this if the user wants a clean slate now. Scanned the current set: BTC/IGV/MSI/SMH/URA/REMX fixed; SILVER/TECHNOLOGY/VIX have weak-but-defensible latest evidence (left as-is).
3. **TODO #27 — sanitize A/B then flip OFF.** User-approved, deferred (providers were flaky). Run `!all` on NVDA/AMD/TSLA+1 with `all_command.sanitize_enabled` on vs off, confirm no invented numbers, then flip off. `todo/sanitize-ab-then-flip-off.md`.
4. **TODO #28 — evaluate SMART LEVELS shadow.** After ~1 day, read `.omc/logs/smart-levels-shadow.jsonl`, compare new vs current levels, decide go-live. `todo/smart-levels-shadow-evaluate.md`.
5. **Held go-live menu** (`.claude/discover/full-audit-2026-06-06/GO-LIVE-LIST.md`): chart-pattern field, sharper days-to-target, smarter YouTube scoring (#9-#12, changes which alerts fire — flip one at a time), per-number ticker tagging, smarter options selection. All built, flag-OFF, awaiting per-feature go.
6. **Watch:** new Wolf @-ping confluence alerts for accuracy now that the patterns are fixed; the YouTube backlog draining (was 65 failed videos); the silent-outage alarm firing appropriately.

## Always-on health (verified at close)
consensus-engine + openclaw-gateway both `active`; `/root/.openclaw` → `/home/openclaw/.openclaw`; consensus.db owned by openclaw; no app errors / drift alerts.
