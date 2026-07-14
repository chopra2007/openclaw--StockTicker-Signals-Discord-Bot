# Research, plan, and build new features — the repeatable loop

**Status:** ONGOING — a standing capability, never "finished"
**Created:** 2026-07-14

**CURRENT STATUS (2026-07-14):** Set up and ready to run. This is the **generator** — it goes out and
finds NEW ideas. Its output feeds the **menu** in #76, which is the ledger of ideas already found.
Run this when #76's menu is exhausted, or when enough has changed (new data source, new API key, a
market regime shift) that a fresh look is worth the tokens. Last full run: **2026-07-08**
(`next-features-jul2026`), which produced the 113-idea list #76 now tracks.

## How to run it — a discover run

This is a **discover run**. That is how the last one was actually done (#67 was launched with
`discover: build next-features-jul2026`) and it is the mechanism to use again. Type this in a fresh
session:

```
discover: find new features and optimizations for the bot
```

Discover then asks you to name the run (short kebab-case, e.g. `next-features-oct2026`). **Write the
name down** — it is the resume key: if the session dies or context compacts, `discover: <name>`
picks up from the last completed pass, and `discover: build <name>` re-enters the build stage.

Discover is deliberately heavyweight and explicit-invocation-only — it will NOT fire on "add a
feature" or "improve the bot". It needs the literal `discover:` prefix or `/discover`.

**Before running, check #76.** If the existing menu still has good un-picked ideas on it, building one
of those is far cheaper than generating a whole new list. Only run this when the menu is thin.

## What the run does — discover's 5 passes

1. **Existing-system analysis** — read the real code, logs, and database first. No claims about our
   own architecture from memory. (Pass 0 also saves a reusable codebase map, so a later run doesn't
   re-pay the scan — that is what discover v1.3 added.)
2. **External research** — go find what others have done (papers, GitHub, comparable projects).
3. **Filter / prioritize** — cut the long list down to the ideas with real merit, in plain English.
4. **Adversarial kill-test** — attack each survivor and try to *kill* it cheaply, before it costs a
   build. The July run killed 3 this way, and one ("max-pain reliability label") turned out to rest
   on a false premise about our own code — caught for free.
5. **Plan tournament → you pick → build** — competing plans are scored, then the run **stops and asks
   you** in plain English what to build. It does not choose for you. Builds land flag-OFF, tested on
   real data, with a regression baseline and a separate verifier.

Then: **log every verdict into #76** so nothing is ever researched twice.

## The other, heavier option (#61's prompt)

There is a second, non-discover path on disk: `todo/kickoffs/bot-research-and-build.md`, written for
#61 and run with `ultracode — read todo/kickoffs/bot-research-and-build.md and execute it end to end`.
It uses the deep-research plugin with six research lenses and a Codex adversarial pass.

**Use the discover run by default.** Reach for this one only if you specifically want the deep-research
plugin's citation-heavy sweep rather than discover's 5-pass workflow. It is not the normal path.

## Scope — this covers BOTH

- **New features** (a new signal, a new command, a new data source), and
- **Optimizing / updating existing features** (the July run's own output included fixing a latent
  scoring hazard and correcting a misread of our own options code).

## The one rule that makes it worth re-running

**Every idea's verdict must land in #76.** A research run whose "no" answers evaporate is a run that
will be paid for twice. The July run's 79 rejected ideas each carry a written reason — that is what
stops the next run from re-proposing crypto risk-on/off or position sizing for the tenth time.

## Files

- **The discover skill** — installed plugin (`chopra2007/claude-discover`, v1.3.0). Its own version
  history and next changes are **#68**, a separate item about the tool itself.
- `todo/feature-menu-ledger.md` — **#76**, where every verdict must land
- `.claude/discover/next-features-jul2026/` — the July run's full artifacts (the resume key pattern:
  each run gets its own dir here)
- `todo/kickoffs/discover-next-features-resume.md` — the July run's resume brief; a worked example of
  what a mid-run handoff looks like
- `todo/kickoffs/bot-research-and-build.md` — the alternative non-discover prompt (#61)
- `todo/kickoffs/bot-deep-research-merged.md` — paste-ready variant of that for an outside model
  (Codex/Gemini) that cannot see this machine

## History

- **2026-07-05** — the alternative deep-research prompt written (#61).
- **2026-07-08** — the **discover run** `next-features-jul2026` executed (trigger:
  `discover: build next-features-jul2026`, Stages 2–6 autonomous per user directive): the candidate
  sweep → 27 strong → 24 survived the kill-test → 16 built, all flag-OFF. #61 closed 2026-07-09.
- **2026-07-14** — the run's leftovers were found to be invisible: 8 ready-to-build ideas and ~100
  more sat in a run-artifacts folder with nothing on the TODO list pointing at them. Hence this item
  (the repeatable loop) and #76 (the ledger).
