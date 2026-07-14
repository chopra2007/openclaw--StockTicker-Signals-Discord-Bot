# Research, plan, and build new features — the repeatable loop

**Status:** ONGOING — a standing capability, never "finished"
**Created:** 2026-07-14

**CURRENT STATUS (2026-07-14):** Set up and ready to run. This is the **generator** — it goes out and
finds NEW ideas. Its output feeds the **menu** in #76, which is the ledger of ideas already found.
Run this when #76's menu is exhausted, or when enough has changed (new data source, new API key, a
market regime shift) that a fresh look is worth the tokens. Last full run: **2026-07-08**
(`next-features-jul2026`), which produced the 113-idea list #76 now tracks.

## How to run it

Paste this into a fresh session:

```
ultracode — read todo/kickoffs/bot-research-and-build.md and execute it end to end
```

That kickoff file (built for #61, 2026-07-05, v2) is the whole task. It already contains the full
prompt: ground-truth verification against the real code first, six-lens deep research with citations,
an adversarial attack on the draft findings, a stop-and-ask so **you** pick what gets built, then the
build under the project's normal rules.

**Before running, check #76.** If the existing menu still has good un-picked ideas on it, building one
of those is cheaper than generating a new list. Only run this when the menu is thin.

## What the loop does, in order

1. **Ground truth** — verify every claim about the bot against the real code, logs, and database.
   No architecture claims from memory.
2. **Research** — six lenses, with citations (papers, GitHub, comparable open-source projects).
3. **Triage** — cut the long list down to the ideas with real merit, in plain English.
4. **Kill-test** — adversarially attack each survivor. The point is to *kill* ideas cheaply, before
   they cost a build. The July run killed 3 this way and one of them ("max-pain reliability label")
   turned out to rest on a false premise about our own code.
5. **You pick** — the run stops and presents plain-English choices. It does not choose for you.
6. **Build** — flag OFF by default, tested on real data, regression baseline, separate verifier.
7. **Log the outcome** — every idea's verdict lands in #76's ledger so it is never re-researched.

## Scope — this covers BOTH

- **New features** (a new signal, a new command, a new data source), and
- **Optimizing / updating existing features** (the July run's own output included fixing a latent
  scoring hazard and correcting a misread of our own options code).

## The one rule that makes it worth re-running

**Every idea's verdict must land in #76.** A research run whose "no" answers evaporate is a run that
will be paid for twice. The July run's 79 rejected ideas each carry a written reason — that is what
stops the next run from re-proposing crypto risk-on/off or position sizing for the tenth time.

## Files

- `todo/kickoffs/bot-research-and-build.md` — the prompt (v2, the one to run)
- `todo/kickoffs/bot-deep-research-merged.md` — paste-ready variant for an outside model (Codex/Gemini)
  that cannot see this machine
- `todo/feature-menu-ledger.md` — #76, where the output goes
- `.claude/discover/next-features-jul2026/` — the July run's full artifacts

## History

- **2026-07-05** — prompt written (#61).
- **2026-07-08** — run executed (`next-features-jul2026`): 113 ideas → 27 strong → 24 survived the
  kill-test → 16 built. #61 closed 2026-07-09.
- **2026-07-14** — the run's leftovers were found to be invisible: 8 ready-to-build ideas and ~100
  more sat in a run-artifacts folder with nothing on the TODO list pointing at them. Hence this item
  (the repeatable loop) and #76 (the ledger).
