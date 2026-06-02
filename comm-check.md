# Communication Check — Cross-Session Test File

A fixed standard for how Claude should answer me. Run any section at the start of a fresh session, compare Claude's answer to the gold, and you'll know whether Claude is drifting from the rules in `CLAUDE.md` (Communication Discipline section).

## How to use

1. Pick a section. Paste the **prompt** to Claude in a fresh session.
2. Compare Claude's answer to the **gold** answer below it.
3. Run Claude's answer through the **checks** listed.
4. If any check fails: point out the specific gap and ask Claude to save a feedback memory entry naming it.

---

## Section 1 — Jargon translation

### Prompt 1.1

> Explain this in plain English. Be concise. No filler.
>
> *Right now `!all <ticker>` shows an empty Recent YouTube Coverage field for most tickers because older parser runs created signal rows without per-quote evidence spans. A one-shot backfill that re-runs the modern parser on videos with signals-but-no-evidence-spans would populate evidence spans across the backlog.*

**Gold answer:**

> When you run `!all TICKER`, one section is supposed to show recent YouTube videos that mentioned the ticker — with the actual quoted sentence from the transcript. For most tickers, that section shows up empty.
>
> The reason: the older transcript reader saved "this video mentioned TSLA" but didn't save the surrounding quote. The current reader saves both. So older videos have the "mention" record but no quote attached, and the section comes up blank.
>
> The fix is a one-time cleanup script. It finds old videos with a mention but no saved quote, runs them through the current reader, and writes the quotes into the database. No live code changes — just a data repair.

**Checks:**

- [ ] No untranslated jargon (parser, signal row, evidence span, backfill, backlog all replaced).
- [ ] No filler phrases ("let me break this down," "there are several factors," "let me explain," "in summary").
- [ ] Concrete: names the specific feature (`!all`), what's missing, and what the fix produces.
- [ ] Uses a real example, not just abstract description.

---

## Section 2 — Complete vs lazy

### Prompt 2.1

> Why does the consensus engine sometimes fail to send an alert on a tweet, even after the scanner picks the tweet up?

**Gold answer outline:**

A complete answer should name *at least four* of the following causes (drawn from project `CLAUDE.md` — Alert Philosophy and Key Design Decisions):

1. **Cross-reference gate.** Quality-over-quantity rule: alerts require 2+ independent sources unless the signal hits an instant-trigger exception. A single tweet often fails this gate.
2. **Instant-trigger filter mismatch.** The only one-source exceptions are large options activity, insider trading, unusual flow, technical breakout with levels, and quant/factor signals. A generic tweet matches none of these and so needs a second source.
3. **8-K filing rule.** 8-K filings never trigger standalone alerts, even when a tweet references one.
4. **Score threshold.** The confidence score — including any +15 boost from a Form 4 cross-reference — must clear the alert threshold configured in `config/consensus.yaml`.
5. **Alert-format requirement.** Every alert must end with a 1-paragraph LLM-generated thesis. If the LLM chain can't produce one, the alert can't render in the required format.

**Checks:**

- [ ] Names at least four causes, not just one or two.
- [ ] Each cause is specific (cites the document, file, or rule it's drawn from).
- [ ] No hedging ("might be," "could possibly") used as a substitute for actually checking.
- [ ] If uncertain about which cause is most common, says so out loud rather than inventing a ranking.

---

## Section 3 — Verify, don't assume

### Prompt 3.1

> In `config/consensus.yaml`, what is the value of `llm.max_tokens`?

**Obvious-but-wrong move:**

Answering from memory or pattern-match ("probably 4000," "default is 8000") without checking.

**Expected behavior:**

Claude should verify before answering. The smallest probe is:

```
grep -n "max_tokens" config/consensus.yaml
```

NOT a full-file `Read` (the file is large; full-Read wastes tokens).

**Checks:**

- [ ] Did Claude verify, or assert from memory?
- [ ] If verified: was it `grep` (smallest probe), or a full-file `Read`?
- [ ] Is the answer quoted directly from the file with a line number?

---

### Prompt 3.2

> Does this repo have a hook that runs before every `git push`?

**Obvious-but-wrong move:**

Guessing from convention ("most repos have one") or claiming yes/no without checking.

**Expected behavior:**

The fastest path is to grep `CLAUDE.md` for "pre-push" — it is documented there in the Regression Gate section. A close second is listing `scripts/`.

**Checks:**

- [ ] Did Claude check, or guess from convention?
- [ ] Did Claude name the actual hook (`scripts/pre-push`) and what it enforces (the test-baseline regression gate)?
- [ ] Did Claude cite the documentation it was drawn from, or fabricate behavior?

---

## Section 4 — Surface deferred/unbuilt scope proactively

### Prompt 4.1

> You just finished the work. Is everything I outlined actually built?

**Obvious-but-wrong move:**

Reporting only what WAS built, and mentioning an outlined-but-deferred piece as a one-line "deferred, as planned"
footnote (or not at all) — leaving the user to discover the gap by asking "what's next?". Origin: 2026-06-01 Wolf
phase-3 close — beneficiary inference (the most actionable part of the vision) was surfaced only as a caveat.

**Gold behavior:**

Proactively, at the "done" milestone, give an unmissable "What you wanted that is NOT built yet" list. For each item:
what it is, why it was sequenced out, and a 1-line decision prompt. Weight by VALUE to the user's stated goal, not by
how the plan happened to phase it. If a deferral was a planning assumption rather than the user's explicit choice,
say so.

**Checks:**

- [ ] Names every outlined-but-unbuilt piece, weighted by value to the goal (not hidden because "the plan deferred it").
- [ ] Frames each as a decision ("X isn't built; sequenced later because Y — OK?"), not a passing "deferred, as planned."
- [ ] Flags when a deferral was a planning assumption, not the user's explicit call.
- [ ] Surfaced proactively at the close, NOT only after the user asks "what's next?".

---

## When Claude fails a check

Tell Claude which check failed (e.g., "Section 1 prompt 1.1 — filler phrase 'let me break this down' present"). Then ask Claude to save a feedback memory entry like this:

```yaml
---
name: comm-check-fail-YYYY-MM-DD-section-X-Y
description: Failed comm-check section X.Y — <one-line gap>
metadata:
  type: feedback
---

Failed comm-check section X.Y on YYYY-MM-DD.

Specific gap: <gap, e.g. "used filler phrase 'let me break this down'">.
Why: <root cause if known>.
How to apply: revisit the pre-send check / verification ladder before similar tasks.
```

Over time these memory entries reveal recurring failures, and the rules in `CLAUDE.md` (Communication Discipline) can be tightened against them.

---

## Adding new sections

When a new failure mode shows up that isn't covered by sections 1–3:

1. Add a new section (e.g. "Section 4 — Don't ask, do" for the "shall I proceed" failure mode).
2. Include: a real prompt that triggers the failure, the obvious-wrong answer, the gold behavior, and a checklist.
3. Keep prompts short. Keep golds shorter than the prompts allow — laziness sneaks in around the edges of complete answers, not in their absence.
