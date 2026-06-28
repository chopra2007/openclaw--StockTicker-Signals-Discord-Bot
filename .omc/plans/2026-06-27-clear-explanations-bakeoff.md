# Spec — #52 Clear, consistent explanations (clarity bake-off)

**Date:** 2026-06-27
**TODO:** #52 (`todo/clear-simple-explanations.md`)
**Status:** approved design, executing

## Goal

Settle, with evidence, how my explanations should read — then write the rule into
its permanent home. The user's complaint: my explanations flip reference frames
mid-sentence (Put/Call: "puts are half of calls" in one breath, "twice as many
calls as puts" in the next) and over-explain / lean on code instead of plain math.

## Definition of done

1. A two-round clarity bake-off has been run (real Gemini + real ChatGPT + Claude).
2. The judges' "why this wording is clearer" reasons are extracted into a concrete rule.
3. The rule is written into its chosen home (see Decision below) — full rule + test
   in `comm-check.md` as a new **Section 6**, plus one trigger line in `CLAUDE.md`'s
   pre-send checklist. Memory note stays as the failure log (no change).
4. The raw side-by-side answers are saved so the **user** is the final arbiter of clarity.
5. #52 marked done in `TODO.md` + detail file.

## The bake-off

### Round 1 — generate (cold, identical prompt to all three)

Three "explain this" prompts, all grounded in real numbers, worded identically for
every model and given **cold** (no model knows it's a clarity test or that
"consistent framing" is the target):

- **T1 putcall** — explain the Put/Call ratio scale at 0.50 / 1.00 / 2.00.
- **T2 voloi** — explain vol/OI using the real NVDA-style example (64 open, 15,094 today).
- **T3 scoreband** — explain a 0–100 banded confidence score using a real 72.

Models:
- **Claude** — a cold workflow subagent (same model as me, fresh context — so it's
  the realistic "Claude under test", not me consciously applying the rule).
- **ChatGPT** — `codex exec --skip-git-repo-check -o <file> - < promptfile` (gpt-5.5).
- **Gemini** — `GEMINI_CLI_TRUST_WORKSPACE=true gemini -p "<prompt>"`.

### Round 2 — judge (blind, all three judge)

For each topic, the three answers are pasted side by side, **anonymized A/B/C** in a
**rotated order** so each model sits in slot A once, B once, C once across the three
topics (kills both self-vote and position bias — no model is told which answer is
its own). Each of the three models judges: rank best→worst, name the specific
wording choices that make the winner clearer. Every judge ends with `WINNER: <A|B|C>`.

Rotation (letter → model):
- T1: A=Claude  B=ChatGPT C=Gemini
- T2: A=Gemini  B=Claude  C=ChatGPT
- T3: A=ChatGPT B=Gemini  C=Claude

### Round 3 — synthesize

Map letters back to models. Tally winners. Extract the recurring "why clearer"
reasons. If Claude wins/ties → lock the winning pattern in as the rule. If Claude
loses → steal the specific thing that made the winner clearer.

## Fairness controls

- Identical prompt strings to all three (defined once as constants).
- Cold generation; no model primed about the test.
- Blind, rotated, anonymized judging; self-votes recorded as a bias check.
- Raw CLI output captured to files and verified directly (no paraphrase).
- LLM votes inform the rule; the **user** gets the raw side-by-side and the final say.

## Decision — where the rule lives (my call, per user delegation)

- **Primary: `comm-check.md` Section 6 — "Consistent framing (one yardstick)"** — a
  real prompt, a gold answer, a checklist. That file is explicitly where new
  failure-mode tests go (its "Adding new sections" names "Section 6" as the example).
- **Plus: one line in `CLAUDE.md` pre-send checklist** (item 6) so it fires every
  session — a pointer, not a copy of the full rule.
- **Memory `feedback_consistent_framing_explanations.md` stays as-is** — the failure log.
- This is one full home + one pointer + one log = not "duplicated across all three."

## Honest limits

- n=3 prompts, LLM judges → subjective and small. The user is the real bar.
- The bake-off chiefly validates **lesson 1 (consistent framing / clear wording)**.
  **Lesson 2 (answer only what's asked, at the asker's level; don't explain via code)**
  is about audience-calibration and is only partly testable this way — captured in the
  rule text regardless of the vote.

## Tooling

- Orchestrated as a Workflow (`clear-explanations-bakeoff`): phases Generate → Judge → Synthesize.
- Raw artifacts under the session scratchpad: `gen_<topic>_<model>.txt`, `judge_<topic>_<model>.txt`.
