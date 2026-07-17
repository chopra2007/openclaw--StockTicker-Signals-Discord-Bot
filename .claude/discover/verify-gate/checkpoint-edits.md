# Checkpoint edits — run verify-gate

## 2026-07-15 — Shortlist review

User decision (AskUserQuestion, multi-select): keep ALL THREE candidates for the kill-test —
- C9 Tripwire gate (deterministic Stop-hook claim-shape gate)
- C3 Banner relabel (source-tag the SessionStart digest as UNVERIFIED)
- C4 AI-judge fallback (kept as written contingency only; not to be built now)

No rewordings, no added conditions, no drops.

## 2026-07-16 — Security-flag adjudication (kill-test burst)

The harness security classifier flagged skeptic:code-reality during Pass 3 (its probing of
Stop-hook/message-blocking internals pattern-matched "reconnaissance to evade a verification
gate"; that probing was the lens's assigned task). Claude reviewed the agent's output
(pass-3-kill-report.md) and found nothing evasive; per the permission system, the final call
was put to the user. User decision (AskUserQuestion): "Proceed to planning" — flag adjudicated
by the user, kill report accepted as input to Pass 4.

## 2026-07-17 — Second security flag (plan:minimal-diff) + standing instruction

Pass 4 halted on a transient 529 at tournament-judge; a second same-class security flag fired on
plan:minimal-diff ("final entry not a genuine tool call / classifier manipulation"). Claude pulled
that agent's transcript: the final entries are a plain research note (hooks I/O contract verified
against official docs), a genuine StructuredOutput tool call, and its success ack — the flag's
factual claim does not match the transcript. User decision (AskUserQuestion): "Resume; ask only if
novel" — resume Pass 4 from cache; for further flags of this same subject-matter class (agents
discussing message-block mechanics, which is the feature itself), Claude reads the flagged
transcript each time, notes the finding, and continues; anything genuinely novel still pauses for
the user.
