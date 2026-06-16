# Make "build → backtest on DB → switch on same session" the standing rule for all feature builds

**Status:** DONE 2026-06-16 — rule written into CLAUDE.md "Definition of Done" as the "### Built switches default to ON" subsection (with the live-alert carve-out). See commit e509c4f.
**Created:** 2026-06-13

## The directive (user, 2026-06-13)

> "I want [build + test against the DB + switch on this session] to be the directive in all future
> feature builds." AND (same session): "all features built and switched off should be able to be
> switched on before the session ends (unless the feature is broken). Testing is not a good enough
> reason [to leave a feature off] since there's tons of historical data in the db to test against
> for feature accuracy."

In plain terms: stop the old habit of "ship it behind a flag, leave it OFF, flip it on in some future
session after a live/shadow soak." The new default is: **build it, prove its accuracy against the
months of history already in `consensus.db` (and any other historical artifacts), and flip it ON before
the session ends.** A feature may stay OFF at session end ONLY if it is genuinely broken or
data/dependency-blocked — never merely "untested" or "awaiting a shadow window."

## Why this is a real change

The current project conventions point the other way and would need updating:
- `CLAUDE.md` "Definition of Done" / "Real-World Testing" emphasise verification but don't say
  "flip the flag on this session."
- The recurring pattern in shipped work has been "build flag-OFF → soak/await sign-off → flip later"
  (e.g. !all levers, Phase-2 signals, Wolf flags). The user is overriding that default.
- "Shadow windows" (collect live data for N days, then decide) are explicitly disfavoured when the
  same question can be answered by backtesting historical DB data now.

## What needs deciding (this is the task)

The user wants to **figure out WHERE to codify this and HOW to word it without bloat** — not just drop
a paragraph somewhere. Options to weigh:
1. A short clause under `CLAUDE.md` → "Definition of Done" (e.g. a new bullet: "A flag-gated feature
   is not done until it's been validated against historical DB data and switched ON this session,
   unless broken/data-blocked — name the exception.").
2. A line under `CLAUDE.md` → "Real-World Testing".
3. A standalone short section ("Feature rollout rule").
Keep it to 1–3 sentences; avoid duplicating the existing DoD/verification text.

## The one legitimate exception class (must be named, not silent)

"Broken or data/dependency-blocked," e.g.:
- needs a key we don't have (no FRED key → the credit-spread leg),
- needs forward-accumulated data that can't be backfilled (ApeWisdom z-score baseline),
- depends on an unreliable external source (the Apify Seeking-Alpha actor),
- a genuine bug found during the backtest.
When a feature stays OFF, the session must say WHICH exception applies and why — never "we'll test it later."

## Tooling that supports this

The "alert-preview / replay harness" (being built for #32) is the general mechanism: replay historical
DB events through the changed code and show the user-visible delta (alerts changed, pings added, tiers
moved) before flipping. Reusable for any scoring/alert feature. Worth keeping generic.

## Open questions
- Exact home + wording (the main decision above).
- Should it be enforced mechanically (a checklist item / DoD tag) or just a written rule?
- Any feature classes that should be exempt by nature (e.g. ones that genuinely need live traffic,
  not historical data, to validate)?
