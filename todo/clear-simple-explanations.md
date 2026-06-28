# Fix convoluted, inconsistent explanations

**Status:** OPEN
**Created:** 2026-06-27

## The problem (user's words)

> "your wording is never coherent, it's all over the place. if you say twice
> as many puts on one thing, then say twice as many calls for the other side.
> understand my point? You need to make your explanations clear and simple.
> you make them convoluted and discombobulated."

## The specific failure that triggered this

Explaining the Put/Call ratio scale, Claude mixed two reference frames in the
same breath:

- For 0.50 it said **"puts are half of calls"** (measuring puts against calls)
- For 2.00 it said **"twice as many calls as puts"** (measuring calls against puts)

Two different yardsticks → the reader has to re-orient mid-sentence. Incoherent.

The fix is to pick ONE frame and hold it across every example:

> - 0.50 → twice as many **calls as puts**
> - 1.00 → equal
> - 2.00 → twice as many **puts as calls**

Same structure ("X times as many ___ as ___"), only the two nouns swap. The
reader locks onto one pattern and never re-orients.

## Second example, same day (jargon explained with jargon)

Asked what "vol/OI" means, Claude answered: "contracts already held from
before... fresh money, not recycled." That uses the very terms (contract, open
interest, position) the listener didn't know — explaining jargon with jargon,
and assuming the reader knows what an options contract even is. User: "you're
not explaining that vol/OI part clearly. assume i know nothing about how the
bot is coded."

The clear version grounds every term from zero, then anchors with the real
numbers on screen:
- options contract = a bet on a stock
- open interest = bets already open from earlier days
- volume = bets placed today
- vol/OI = today's bets ÷ bets already open
- NVDA: 64 open, 15,094 today → 236× = a sudden flood of brand-new bets

Rule reinforced: when a label IS jargon, don't define it with more jargon —
define every word in plain terms and attach a concrete on-screen number. (Also
applies to the on-card footer text itself, not just chat explanations.)

## The behavior to fix (general, not just this one case)

When explaining anything with a scale, a ratio, or two opposing sides:
1. **One reference frame, held constant.** Never flip which side is the
   numerator/baseline between examples.
2. **Parallel sentence structure** across the examples so only the meaningful
   value changes, not the grammar.
3. **Simplest possible phrasing.** No nested clauses, no "half of X = twice the
   Y" inversions that force mental math.
4. Re-read before sending: would a non-coder track it on one pass, or do they
   have to back up? If they back up, rewrite.

This overlaps with `comm-check.md` Section 1 (clarity) but adds a new, sharper
rule: **coherence/consistency of framing**, which Section 1 doesn't currently
name explicitly. Consider adding a Section 6 ("Consistent framing — one
yardstick") to `comm-check.md` once the test below confirms the gap.

## How to verify (the user's explicit ask)

Test Claude's explanations against **real Gemini and real ChatGPT** answers to
the same prompt, to verify Claude's version is at least as clear and simple:

1. Pick 3-5 representative "explain this" prompts (e.g. the Put/Call scale, the
   vol/OI ratio, a score-band readout).
2. Ask the SAME prompt to Gemini and ChatGPT (via the available CLI/advisor
   paths — `omc ask`, Codex/Gemini CLIs, or web). Capture their raw answers.
3. Compare side by side: is Claude's answer as clear, as consistent in framing,
   and as free of mental-math inversions as the best of the three?
4. If Claude's loses on clarity, extract the specific pattern that made the
   other model clearer and fold it into a rule (CLAUDE.md Communication
   Discipline and/or a new comm-check Section).

## Files / where this lives

- `CLAUDE.md` (workspace) — Communication Discipline section (the rules)
- `comm-check.md` — the grading rubric; Section 1 = jargon/clarity
- Memory: `feedback_consistent_framing_explanations.md` (saved 2026-06-27)

## Open questions

- Which advisor path gives the cleanest apples-to-apples Gemini/ChatGPT
  comparison from this VPS (omc ask quota is small per memory)?
- Should the rule become a hard comm-check Section 6, or stay a memory-level
  feedback entry? Decide after the bake-off in "How to verify."
