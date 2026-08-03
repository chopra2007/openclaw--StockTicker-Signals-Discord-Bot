# Make "verify before stating" actually fire without the user prompting

**Status:** DONE 2026-08-03 — built, live, and the false-alarm soak passed
**Created:** 2026-07-14

**CURRENT STATUS (2026-08-03) — DONE.** The live decision ledger contains 158
decisions: 121 ordinary no-claim allows, 22 escaped/hedged allows, 13 verified-claim
allows, and 2 blocks. Both blocks were the deliberate test sentences used when the
feature went live; neither was a false alarm. That is below the 5% false-block bar, so
the deferred AI escalation layer is not needed. The claim check and startup-banner
warning remain live.

## The problem (in the user's words)

Every session Claude assumes and states things as fact without checking. The user has learned
to distrust and question each claim; only when questioned does Claude verify — and it turns out
the claim was wrong. The user has to hand-hold to get verification that the rules already require.
Latest instance (2026-07-14): Claude relayed a SessionStart banner "Schwab login EXPIRED" as fact
in a completion summary. The user pushed back ("I logged in <24h ago"). On checking: the refresh
token was 21.5h old (valid ~7 days) and a live AAPL options pull worked — the feed was fine. The
alert was a transient blip stated as current truth.

This is the exact failure #40 named: **"I reliably possess the relevant rule or fact, but do not
apply it at the moment I produce an answer,"** shape #1: *trusting a verdict/status string instead
of the primary evidence.* It is ~the 7th+ logged instance of the same class.

## What's been tried and why it hasn't worked

1. **Passive knowledge** — CLAUDE.md "Verification ladder", comm-check.md §3, MEMORY.md, and ~30
   `comm-check-fail-*` memory entries all say "verify, don't assume." They *inform* but don't
   *interrupt* at the instant of answering, and they degrade as context fills. (#40 bottleneck:
   "Passive rules do not gate action.") Adding more of these is the failed pattern — the user
   called this out directly.
2. **#69 verify-on-done Stop hook** (`/root/.claude/hooks/verify-on-done.py`) — re-runs affected
   tests when work is claimed "done." Narrow: catches test regressions only, not "state a status
   string as fact." Did not address this class.
3. **OMC pre-tool advisories** (`.omc/state/.../pre-tool-advisory-throttle.json`) — inject reminder
   text before tool calls. This is the **context-bloat / sluggishness** the user has hit; even
   throttled it adds tokens every session. Injecting more text is not the answer.

## Hard constraints for any real fix (both must hold)

- **Must gate behavior at decision time**, not just add knowledge. A rule that isn't enforced at
  the moment of answering has already been proven not to work here.
- **Must NOT bloat context or slow Claude down.** Every prior *mechanical* attempt that injected
  standing text into the session is what made Claude sluggish. The fix cannot be "more preamble."

## Open design directions (for a future opus/ultracode session — NOT decided)

- A **deterministic, zero-context gate**: a hook that fires only on the narrow, detectable trigger
  — an outbound claim shaped like "X expired / down / failed / logged-in / authenticated" that has
  no matching verification tool-call in the recent turn — and blocks *just that message* asking for
  a probe first. Cost is one hook, no standing context. Risk: detecting "claim shaped like…" from
  message text is hard and may false-fire.
- **Source-tagging startup alerts**: banners like the Schwab one are machine snapshots of a moment.
  Rewrite the digest so such lines arrive labelled "UNVERIFIED as of <time> — probe before
  repeating," turning the input itself into the gate instead of relying on recall. Cheap; narrow to
  notification-relayed facts (a big share of the real incidents).
- **Sub-agent propagation**: #40's second unaddressed gap — rules don't carry into spawned agents,
  so a sub-agent returns a verdict Claude then relays unchecked. Any fix should cover delegated
  conclusions too.
- Explicitly reject: another CLAUDE.md/comm-check rule, or any always-on injected reminder.

## Files / prior art
- `todo/reasoning-failures-assessment-2026-06-13.md` (#40) — the diagnosis this builds on.
- `/root/.claude/hooks/verify-on-done.py` (#69) — the one working precedent for a gated hook.
- `/root/.claude/hooks/openclaw-digest.sh` — the SessionStart digest that emitted the false Schwab alert.
- CLAUDE.md "Verification ladder"; comm-check.md §3.

## Open question for the user
When you next run this (you mentioned opus/ultracode), do you want to start with the **cheapest,
narrowest** win — source-tagging startup alerts as UNVERIFIED — and only escalate to a general
claim-detecting gate if that isn't enough? That keeps context cost near zero and targets the
most common real failure (relaying a notification as fact).

### Session notes — 2026-07-17
- **Worked on:** Full discover run `verify-gate` (map → research → filter → kill-test → plan tournament → build). Shipped C9 claim tripwire (Stop+SubagentStop hook) + C3 banner relabel; C4 LLM escalation deferred pending ledger data. All 15 checklist items verified; full suite 2992 passed, 0 new vs baseline.
- **Decisions:** User kept all 3 shortlist candidates; adjudicated 2 security-classifier false alarms (subject-matter pattern: agents studying block mechanics); approved minimal-diff plan (won 8.7 vs 8.3); both features ON per built-switches-ON.
- **Next:** ~2026-07-31 read `/root/.claude/hooks/logs/claim-gate-*.log`: if false-fire rate of `block` records >5%, build C4 (Haiku escalation, spec in final-plan.md); else mark DONE.
