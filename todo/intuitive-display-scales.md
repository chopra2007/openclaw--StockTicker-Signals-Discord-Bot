# Make every bot reading display on an intuitive, shared scale

**Status:** DONE 2026-06-27
**Created:** 2026-06-27

## Goal

Systematize what the `!options` Put/Call → percentage fix did, across every
readable number the bot shows in Discord. Internal math can use whatever scale
is correct; the **displayed** value should be converted to an intuitive scale at
the render layer. And readings of the same *type* should share one scale, so a
user who can read one reading can intuit all of them.

## The north star — why the % bar is intuitive (the rule to copy)

The percentage bar removes the translation steps between what's on screen and
what it means:

1. **Bounded (0–100).** You know where a value sits without knowing the metric.
   (Raw P/C ran 0→∞ — "2.0" meant nothing without the scale.)
2. **Part-of-a-whole.** "67% calls" is a pie-slice everyone reads instantly; no
   units to decode.
3. **Symmetric, meaningful middle.** 50/50 = even; 67% is exactly as lopsided as
   33%. (Raw P/C's middle was 1.0 with calls in 0–1 and puts in 1–∞, so equal
   lopsidedness looked unequal.)
4. **Visual magnitude is pre-attentive.** Bar length is decoded by the eye
   before any digit is read; the number is backup.
5. **Runs the right way.** Bullish fills toward green/right — no inversion to
   undo (raw P/C went *down* as bullishness went *up*).

A good display needs ~0 translation steps. The raw ratio needed 4.

## The principle to apply everywhere

- **Convert at the display layer.** If a reading is computed in a non-intuitive
  internal scale (ratio, z-score, log, raw count), translate it to an intuitive
  scale only when rendering to Discord. Don't change the math; change the label.
- **One canonical scale per reading *type*.** Group readings by what they are,
  give each type a single scale, and reuse it:
  - **Leaning / share** (two-sided, exact magnitude not needed — "which way and
    how hard") → **0–100% split with a bar**, like P/C now. Optionally a signed
    −100…+100 meter for pure sentiment.
  - **Strength / intensity** (one-sided, "how strong/extreme") → **0–100 score**.
    Precedent already shipped: TODO #46 put regime z-score + contradiction onto a
    0–100 display scale (see memory [[project_unified_display_scale_shipped]]).
  - **Multiples where the actual count matters** (e.g. vol/OI "236×", RVOL
    "2.3×") → keep the multiple, but pair it with a plain-English anchor so the
    glance still works ("236× — today's volume is 236× the open positions").
- **Shared scale = transferable intuition.** Once a user learns "50 = middle,
  fills toward green = bullish," every leaning reading reads the same way.

## Approach

1. **Survey** — grep the render/embed code for every user-facing numeric or
   leaning reading the bot emits (commands: `!scan`, `!all`, `!options`, `!em`,
   `!technical`, `!market-view`, `!google-trends`, alert bodies, Wolf digests).
   List each reading + its current displayed scale.
2. **Classify** each as leaning / strength / count-multiple / other.
3. **Flag mismatches** — readings shown in a non-intuitive scale (raw ratios,
   z-scores, unbounded numbers) or in a scale that conflicts with a same-type
   sibling.
4. **Convert at display** — pick the canonical scale per type and translate.
   Keep internal math untouched; only the rendered string changes.
5. **Verify** against real output (and, per TODO #52, sanity-check clarity vs
   how Gemini/ChatGPT would present the same number).

## Candidate readings to audit (starting points — complete via the survey)

- Put/Call flow → **DONE** (now a call/put % split in `!options` — see the
  Shipped reference below).
- vol/OI ratio ("236×") — count-multiple; keep × but anchor in words.
- Confidence / score + 🟢🟡🔴 band — confirm it's the canonical 0–100.
- Regime "Market stress N/100" — already 0–100 (#46); use as the strength
  template.
- RVOL / relative volume, RS (relative strength) peer rank, Google-Trends spike
  % — classify and align.
- Any z-score, log, or raw-ratio still surfaced to users.

## Shipped reference — the `!options` card (2026-06-27)

The full `!options` rework is the working reference implementation this rollout
generalizes from. What shipped (all live + verified on NVDA/AMD/AAPL/TSLA/SPY):

**Display / scale (the part #53 is about):**
- **Put/Call ratio → call/put % split.** The raw ratio (0→∞, ran backwards) is
  gone. Card shows `🟢 Calls 65%  /  🔴 Puts 35%`. A prototype **bar**
  (`████████░░░░`) was built and then **dropped** — in the compact two-column
  layout the plain "65% / 35%" text was cleaner than the bar. Lesson: the
  intuitive unit is the **percentage**, not necessarily the bar; pick the
  lightest rendering that still reads at a glance.
- **Near-tie decimals.** A genuine ~50/50 (AMD was 49.6/50.4) rounded to a
  suspicious exact `50% / 50%`. Now, only when both sides round to 50, it shows
  one decimal so the real lean is visible. Lesson: rounding can manufacture a
  fake tie — show precision exactly where the round number misleads.
- **Colour follows the robust aggregate**, not one outlier: card edge =
  green/red/gold by the call/put *volume* split, so a single cheap far-OTM print
  can't paint the whole card the wrong colour.

**Contract selection (not display-scale, but part of the same rework):**
- **Two-column "B2" layout** — contract (volume vs OI, $ traded, spot) on the
  left; call/put flow + per-side peak vol/OI on the right. Green/red **dot before
  the strike** = the headline bet's side. **Date only**, no time.
- **Scope unified** — headline, per-side peaks, and the % split all span the
  **2 nearest expirations** (they used to disagree: a 236× headline next to a
  155× "hottest call" because they read different expiry sets).
- **Directional moneyness gate** — a contract can headline only if its strike is
  **≤30% OTM or ≤10% ITM** (OTM/ITM judged per side). Drops far-OTM lottery
  tickets (AMD: a $305 put 42% below spot, $77K, high vol/OI only because OI≈49)
  and deep-ITM hedges (NVDA: a $155 call 19% ITM that moves ~1:1 with the stock).
  A fixed **$ floor was explicitly rejected** — it doesn't scale across price
  levels and misses the real defect (distance from spot, not dollar size).
- **Put/Call NaN bug fixed** — a single NaN-volume row poisoned the volume total
  and forced the ratio to 0.00.

Commits: see master around 2026-06-27 (`Refactor !options …` through
`!options: filter to directional contracts …`).

## Files / where this lives

- `consensus_engine/alerts/commands.py` — most command embeds
- `consensus_engine/alerts/all_command/` — `!all` rendering
- `consensus_engine/alerts/` — alert bodies, wolf digests
- Precedent: the #46 unified-scale work (`project_unified_display_scale_shipped`)

## Open questions

- One scale for ALL leaning readings vs allowing a signed −100…+100 variant for
  sentiment — decide after the survey shows how many leaning readings exist.
- For count-multiples (×), is a word anchor enough, or should some become a
  bounded scale too?

### Session notes — 2026-06-27
- **Worked on:** SHIPPED via discover run `intuitive-display-scales` (commit 2160e5d, local). Surveyed all 71 user-facing numbers across every command/alert; only a handful were genuinely non-intuitive. Generalized the !options call/put-% fix into one canonical `display_scale.call_put_split` helper and applied it to the 3 Put/Call surfaces (auto-alert, !all, and the !options card itself). Dropped the unitless Reddit `momentum` number; chart-pattern `0.72`→`72% confidence`; vol/OI label on auto-alert.
- **Decisions:** display-layer only (no math). Convert from RAW COUNTS, never the put_call_ratio (0.0 on a one-sided day would invert the split). Basis labels load-bearing: "(today's volume)" vs "(open interest)". Thin-OI (<50 contracts) split suppressed in !all. CUT as over-engineering: Wolf market-lean (already labelled), RSI/EMA relabel, Max-Pain distance, Stocktwits delta, confluence counts. OUT OF SCOPE: additive Score family (#I4) and standard finance metrics (PEG/Beta/PE).
- **Verified:** 2319 pass / baseline-only failure; independent reviewer APPROVE; single-sided + thin-OI edge cases proven; live Discord before/after demo on real GOOGL approved by user; engine restarted clean (Gateway READY).
- **Next:** auto-alert split (C1/C4) is weekend-paused — first real automatic alert renders it Sun 2026-06-28 3pm PDT when the engine resumes. Command surfaces (!options/!all/!trend) live now. At session close: mark TODO.md #53 header `— DONE 2026-06-27` and push via the gate.
