# Show every score on one consistent scale (e.g. 0 = low, 100 = high)

**Status:** OPEN
**Created:** 2026-06-17

## The problem (user, 2026-06-17)

Every number the bot shows the user lives on a *different* scale, so the user can't tell at a glance whether a reading is high or low. The underlying code can keep its own units — but **what's displayed must be unified** (the user's suggestion: 1 = low, 100 = high, higher always = stronger/more).

### Concrete examples of the inconsistency (all verified in current code)

| What the user sees | Native scale today | "High" means | Where |
|---|---|---|---|
| Precision Engine score | 0–100 | 80+ = STRONG, 65+ = medium | `config/consensus.yaml:649-650` |
| `!all` / Cross-Reference **Breakdown** sum | raw additive points, **can exceed 100** (e.g. 105) | bigger = more sources stacked | `consensus_engine/alerts/discord.py:495-508` — this is exactly the #I4 confusion |
| Contradiction index | 0.0–1.0 | 0.5+ = sources disagree enough to downgrade | `config/consensus.yaml:725` |
| Regime "mood" line | z-score: **−1.0 = calm, 0 = normal, +0.5 = jumpy, +1.5 = panic** | counter-intuitive: calm is a *negative* number, panic is +1.5 | `consensus_engine/analysis/regime.py:168-178` |
| (scrapped) E2 / regime bar | cutoff 80 normal / 90 panic; multiplier 0.85–1.15 | mixed — a cutoff AND a multiplier | dropped 2026-06-17, but was a 4th different scale |
| LLM `confidence_score` | REAL field, scale unclear/undocumented | ? | `consensus_engine/models.py:170`, `db.py:97` |

The user named the regime mood line as the trigger: a "mood meter" where calm = −1.0 and panic = +1.5 makes no sense to read. **Good feature idea, bad execution** — the fix isn't to drop it, it's to show it (and everything else) on one human-readable scale.

## The goal

A single **display/presentation convention**: every score, index, or "level" the user sees is normalized to the same 0–100 (or 1–100) scale where **higher = stronger / more / more extreme**, with consistent wording. The user should never have to remember "0.5 is high here but 80 is high there and −1.0 is calm over there."

Examples of the target:
- Precision score 72 → shows as **72/100**.
- Contradiction 0.5 → shows as **50/100 disagreement**.
- Regime panic z=1.5 → shows as e.g. **"market stress: 85/100 (panic)"** instead of "z=1.5".
- Breakdown that sums to 105 → capped/normalized so it doesn't read above the headline number (ties directly to #I4).

## Step 0 — inventory EVERY scale first (the examples above are NOT exhaustive)

⚠️ The table above is only the handful the user happened to notice. **Do NOT treat it as the complete list.** The first task is a full sweep of the codebase + every user-facing surface to find *every* number, score, index, level, multiplier, threshold, percentage, ratio, or "confidence" the bot ever shows a human — alerts, `!all`, `#news`/Wolf digests, `@mention`/`!ask` answers, `!flags`/debug commands, any embed field.

Practical sweep:
- Grep the embed/narrator builders for every rendered numeric field (`discord.py`, `all_command/embed.py`, `all_command/narrator.py`, `wolf_news.py`, any other `format_*`/`_*_field` function).
- Grep `config/consensus.yaml` for every threshold/cutoff/multiplier/`*_z`/`*_score`/`*_max`/`*_min`.
- Check each analysis module that emits a user-visible figure (`precision_engine`, `cross_reference`, `regime`, `reliability`, `calibration`, options/RVOL/52wk, peer relative-strength, max-pain, ApeWisdom z-score, etc.).
- For each one found, record: native range, what "high" means, and where it's displayed.

Only after the full inventory exists do you design the single display scale. If you ship a "unified" scale that still leaves some readings on their old units, the task is not done.

## Scope / how to build it safely

- **Display layer ONLY.** Do NOT change the underlying scoring math or thresholds — that risks regressions across the whole alert pipeline. Add a normalization/formatting step at the point each number is rendered (the Discord embed builders + `!all` narrator/embed).
- Build one small helper (e.g. `to_display_scale(value, kind)`) that maps each native metric onto 0–100, and route every user-facing number through it.
- Keep a legend/anchor so the user knows what "70/100" means for each metric (a one-line "what's high" note, or consistent color/emoji bands: e.g. 0–40 low, 40–70 medium, 70–100 high).

## Relationship to other open items

- **#I4 (single score in alerts)** is a *narrower slice* of this same problem — it fixes the Breakdown-vs-headline mismatch for one alert. This #46 generalizes it to every metric. Build #I4 first (it's already specced); make sure its fix uses the same display helper so they don't diverge.
- The **regime mood line** (`features.regime_context_line.enabled`, currently ON, shows "Regime: normal (z=0.1)") should be folded in here: either re-expressed on the unified scale or turned off until this lands. (Decision pending with user — the bad z-score line can be flipped off immediately if they don't want to see it in the meantime.)

## Files / code involved

- `consensus_engine/alerts/discord.py` — alert embeds (Breakdown, Precision Engine, Regime, Contradiction lines)
- `consensus_engine/alerts/all_command/embed.py` + `narrator.py` — `!all` output
- `consensus_engine/analysis/regime.py` — z-score → label (source of the mood number)
- `config/consensus.yaml:649-650` (precision thresholds), `:725` (contradiction_max)
- `consensus_engine/models.py:170` — LLM `confidence_score` (confirm its real scale first)

## Open questions

- Exact target scale: 0–100 or 1–100? (user said "e.g. 1 is low, 100 is high".)
- One universal scale for *everything*, or per-metric 0–100 with a shared "higher = stronger" rule and consistent bands? (Latter is safer — a contradiction "index" and a price-momentum "score" aren't the same quantity, but both can read 0–100 low→high.)
- Show the raw native value in parentheses for power users, or hide it entirely?
- What is the LLM `confidence_score` native scale? (verify before mapping.)

## Anything else a cold session needs

- This was raised right after the user scrapped the regime-adaptive-bar feature (I14 widening + E2) on 2026-06-17 — those are gone; don't resurrect them. This task is about *display unification*, not re-adding adaptive scoring.

### Session notes — 2026-06-21 (discover run todo-20-46) — BUILT + LIVE
- **Shipped (commit 896c30a)** the unified-display-scale fix. New `consensus_engine/alerts/display_scale.py` (pure stdlib leaf): `regime_stress(z)→0-100` (calm z=-1→20, elevated z=0.5→50, panic z=1.5→85, clamped), `regime_emoji(label)` (dot driven by the engine LABEL so dot+word can never disagree), `disagreement(ci)→0-100`.
- **Wired (both surfaces already flag-ON live — verified):** the user's NAMED trigger `Regime: panic (z=1.5)` → **`🔴 Market stress: 85/100 (panic, z=1.5)`**; contradiction `0.45` → **`Disagreement: 45/100`** everywhere it shows (Risk Factors line w/ the 10-block bar kept, the invalidation sentence, and `!market-view`). Render-proven on real embeds: calm→🟢 16/100, normal→🟢 40/100, elevated→🟡 60/100, panic→🔴 85/100.
- **Scope decision (named, not silent):** the additive **"Score: 105" family** (headline title, `score/100 (uncalibrated)` lines, market-view Score) is **deliberately left to the separate #I4 reconciliation / I4-full flag** (tracked under #32/#36 go-live list, "flip one at a time"). Clamping any single site in isolation would re-introduce the title-vs-breakdown mismatch #I4 already fixed AND break its tests. So the additive-score headline reads 0-100 by flipping I4-full, not via this display helper. The #I4 "Breakdown ≤ headline" slice was already shipped 2026-06-17.
- **Left native on purpose:** prices, strikes, % moves, P/C & vol/OI ratios, analyst counts, win-rates, star bars, beneficiary dot, calibrated P(up)/P(down), and the precision score (already carries a magnitude-correct 🟢/🟡/🔴 icon). Forcing literal quantities onto 0-100 would destroy information.
- **Tests:** new `tests/test_display_scale.py` (8 cases). `tests/test_phase1_display.py` regime test updated to the new format. Full suite: **2264 passed**, only the 2 baseline known-failing tests remain — **0 regressions**.
- **LIVE:** engine restarted 2026-06-21 00:01 PDT, healthy (NRestarts=0, loops started, module imports clean in-process). Display-only/cosmetic change — same data, clearer presentation; no alert fires or suppresses differently, so the render-proof IS the user-visible verification.

### Update — 2026-06-21
- The "Score: 105 family" deferral noted above (line 78) is now **resolved**: **I4-full (`single_score`) was flipped ON 2026-06-21** (via #50), so the additive-score headline + the market-view Score now read the gated 0–100 number — exactly what this item said would happen "by flipping I4-full." Live soak starts Sun 11:00 PDT. Detail + evidence: `scan-marketview-score-coherence.md` and `.claude/go-live-evidence/features_single_score_enabled.md`.
