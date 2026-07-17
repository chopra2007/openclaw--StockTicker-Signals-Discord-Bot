# Pass 2: Filtered Candidate Recommendations

## Summary

Three candidates survive feasibility screening. The top-ranked deterministic Stop-hook gate (c9) reuses proven precedent from TODO #69, guards against false-fires with a two-condition AND rule, and avoids per-message cost. The second candidate (c3) cheaply hardens the SessionStart digest via machine-readable tagging. The third (c4) remains a fallback LLM escalation layer, reserved only if deterministic detection proves too coarse in practice.

---

## Candidate C9: Deterministic Stop-hook claim-shape gate
**Rank: 1** — **Status: Recommended for first ship**

Reuses the verify-on-done.py precedent from TODO #69. Registers a Stop hook firing on turn-end, detects claim-shapes matching a fixed narrow verb list (expired/down/failed/logged-in/authenticated), and blocks the message only if NO verification tool-call (Read/Bash/Grep/WebFetch) probed a relevant source since the last user message.

### Failure Modes

- False-fire on hedged/quoted/hypothetical claims that share the verb shape ('the log SAID it expired', 'if the token expired')
- Regex verb list grows past a handful of patterns and starts blocking legitimate messages (documented failure at ~45 patterns in c8's evidence)
- `last_assistant_message` is only the FINAL message of the turn — a claim made in an intermediate message then continued is not seen (acceptable: the target incidents are completion-summary claims, which ARE final messages)
- 'no verification tool-call this turn' check needs transcript_path parsing; the docs note transcript_path 'may lag behind the in-memory conversation'
- Stop hook fires on every turn-end and could hit the 8-consecutive-block cap if it loops

### Safeguards

- Gate on TWO conditions ANDed: claim-shape present AND no Read/Bash/Grep/WebFetch on a relevant source since the last user message (c5's peer-validated steer: key on the checkable tool-call fact, not text regex alone) — a claim that DID probe passes silently
- Keep the verb list narrow and fixed (expired/down/failed/logged-in/authenticated); never widen to chase more shapes (c8 evidence)
- Fail OPEN on any error/timeout exactly like verify-on-done.py (lines 245–249); never trap the agent on the hook's own bug
- Honor `stop_hook_active` + a recursion sentinel to respect the 8-block cap (verify-on-done.py line 134 pattern)
- Register the SAME hook on SubagentStop — docs confirm it receives `last_assistant_message` — to catch relayed subagent verdicts unchecked (the diagnosis's 'Apify actor is dead' failure)
- Add an escape: message carrying a file:line / URL / quoted tool-output citation for the claim passes

### Prior Outcome

First implementation; builds on verify-on-done.py success.

---

## Candidate C3: Source-tag the SessionStart digest
**Rank: 2** — **Status: Recommended for concurrent ship**

Rewrites openclaw-digest.sh so machine snapshots (Schwab login status, gateway state, etc.) arrive labelled 'UNVERIFIED as of <time> — probe before repeating'. The tag is additive to existing action-item framing and signals the need for verification without blocking or slowing the agent. Deterministic, zero per-message cost, and directly targets the exact logged incident (Schwab-banner false verdict).

### Failure Modes

- Tagging alone is not enforced — the model can silently drop or restate the label in its own words (c7's provenance-tagging caveat: 'the model still sees everything')
- Only fixes the digest input path; does nothing for other trust-string sources (Codex 'Logged in', subagent verdicts, cached status checks)
- notifications.log entries may carry no timestamp/source field to build '<time>' from (map gap) — must synthesize from file mtime or print-time date
- Over-loud per-line tagging could bury the genuine action-item framing the banner already carries

### Safeguards

- Pair with c9 as the enforcer — tagging is the input-side nudge, the Stop-hook is the decision-time gate (c7: enforcement must live outside the model)
- Synthesize the timestamp deterministically from notifications.log mtime or date at print time when entries lack one
- Keep the existing action-item framing; the 'UNVERIFIED — probe first' tag is additive, one short line per snapshot entry
- Ship this first (cheapest, zero per-message cost, one script edit) since it directly addresses the exact logged Schwab-banner incident

### Prior Outcome

First implementation; single-script change to openclaw-digest.sh.

---

## Candidate C4: Selective LLM escalation
**Rank: 3** — **Status: Fallback layer**

Pairs a deterministic keyword pre-filter with a Stop prompt-hook that judges only claim-shaped messages using a language model. Escalates to a stronger model only if needed. Reserved as a fallback if c9's pure-regex+tool-call gate proves too coarse in practice (false-fire rate unacceptable).

### Failure Modes

- Adds per-turn LLM cost whenever a claim-shape fires — the user explicitly wants 'no LLM cost per message unless clearly justified'
- A prompt-hook Haiku judge's accuracy is 'strongly dependent on model capability' (c6 evidence) and can itself misjudge
- Only justified if c9's pure-regex+tool-call gate proves too blunt (too many false-fires) in practice — otherwise redundant

### Safeguards

- Keep as a fallback layer, NOT the first ship: build c9 deterministic first, add LLM escalation only if regex false-fire rate is unacceptable
- Deterministic pre-filter ensures the LLM runs on the small claim-shaped subset only, so common turns stay zero-cost
- Use type:'prompt' Stop hook (docs-confirmed) with Haiku default to cap cost; escalate model only if needed

### Prior Outcome

Contingent; not recommended for initial implementation.

---

## Redundancy-Verifier Evidence

(No prior independent cross-checks available at this stage.)
