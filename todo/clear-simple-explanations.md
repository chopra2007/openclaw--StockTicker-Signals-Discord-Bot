# Fix convoluted, inconsistent explanations

**Status:** DONE 2026-06-27
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

## Second example, same day (answered the wrong question, then was lazy)

The user understands the stock and options market at a professional level. They
did NOT ask what vol/OI means. They asked about a **calculation**. Claude's two
mistakes:

1. **Answered an unasked question.** Claude explained what vol and OI *are* and
   how they work — basics the user never asked for and already knew — before
   getting to the actual calculation. That's talking down and padding, not
   helping.
2. **Lazy on the actual question.** When Claude did answer the calculation, it
   leaned on how the formula is *coded* — it assumed the user knew the
   implementation — instead of just stating the real computation plainly. User:
   "your answer about the calculation was lazy. it assumed I knew how the formula
   was coded."

Rules reinforced:
- **Answer the question that was asked — only that.** Don't prepend a primer the
  user didn't request. Gauge the asker's level from the question itself; an
  expert-level question gets an expert-level, direct answer.
- **Don't explain a calculation by pointing at the code.** State the actual math
  and what each input means in real terms, grounded in the on-screen numbers —
  e.g. NVDA: 64 contracts open from before, 15,094 traded today → 15,094 ÷ 64 =
  236×. The reader should not need to read the source to follow it.

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
- **Where does this frame of thinking/answering live?** Decide between three
  homes (after the bake-off in "How to verify"):
  1. `comm-check.md` — a hard new Section 6 ("Consistent framing — one yardstick").
  2. Memory files — keep it as the `feedback_consistent_framing_explanations.md`
     entry (and any sibling feedback entries).
  3. `CLAUDE.md` Communication Discipline — only if it needs to be load-bearing
     every session. If CLAUDE.md, it MUST be worded tightly (one short rule line,
     no examples in-file) so it does not bloat the file.
  Pick one primary home; don't duplicate the full rule across all three.

### Session notes — 2026-06-27
- **Worked on:** Ran the clarity bake-off the user asked for. Same 3 "explain this"
  prompts (Put/Call scale, vol/OI, score band) given cold to Claude, real ChatGPT
  (gpt-5.5 via codex CLI), real Gemini (gemini CLI). Then all three judged the
  answers blind (anonymized A/B/C, rotated). Orchestrated as a Workflow.
- **Result:** Claude won all 3 topics, 8 of 9 votes (only ChatGPT's self-vote on the
  minimal score-band answer dissented). Judges' reasons were identical across topics →
  became the rule. Full data: `.omc/plans/2026-06-27-clear-explanations-bakeoff-raw.json`
  + `-results.md`; spec at `-bakeoff.md`.
- **Decisions:** Both open questions answered. (1) Advisor path = codex CLI + gemini CLI
  (both live; omc ask not needed). (2) Home = `comm-check.md` **Section 6** (full rule +
  gold + checklist) as primary, plus one trigger line in `CLAUDE.md` pre-send item 6;
  memory stays the failure log. Sharpened the rule: target is "no mental math / no
  re-orient," so swapping nouns inside a fixed whole-number structure (with a constant
  anchor) is fine — mixing a fraction frame with a whole-number frame is what loses.
- **Next:** None to build. Soak: the real test is whether live-session explanations
  (not cold agents) actually follow Section 6. Remove from TODO only after the user
  confirms it's holding and OKs removal.
