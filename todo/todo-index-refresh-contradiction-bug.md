# Fix the todo list's status-update step so it stops contradicting itself

**Status:** OPEN
**Created:** 2026-07-12

**Possible next steps: intentionally not written here.** The user asked for the problem to be recorded in full, with no proposed fix and no opinion on the cause — a stronger model will design the fix in a future session. Everything below is verified fact (commit hashes, timestamps, exact file text), not speculation.

## The problem

`TODO.md` is supposed to be a short index that's trustworthy at a glance, without opening the detail file. Its own convention (`todo/CONVENTION.md`, "Lead with current status" section) requires that for any item not fully done, the first body line under `**File:**` is a `**CURRENT STATUS (YYYY-MM-DD):**` one-liner giving the true latest state, and that this line gets overwritten (with old history pushed below it, never left above it) every time the state changes.

That rule was violated twice, found on the same day (2026-07-12), in two different ways:

## Case 1 — item #20 (Wolf macro brain): a brand-new sentence that was already wrong when written

Timeline, from `git log`:

- `7edf7a4` (2026-07-12 01:54:43) — build commit. Widens the Wolf "confluence" input roster from 2 sources to 7, across 5 independence buckets, and adds a new confluence-timing gate. This is the exact piece of work that answers the previously-recorded open question on item #20: "widen the confluence/flow inputs — needs a definition of 'wider' before it's buildable."
- `99f6f1d` (2026-07-12 01:56:10) — "Log #55 + #20 build session notes." This commit adds a session-notes block to the detail file `todo/wolf-macro-brain.md` that says, in its own words: *"This closes the one thing the item was being kept open for — 'widen the confluence inputs, needs a definition of wider'. The definition landed: independence buckets."*
- `030bf46` (2026-07-12 08:05:14) — "Refresh TODO #55/#20 current-status lines after gap-fix session." This commit edits `TODO.md`'s index entry for #20 and adds a brand-new `**CURRENT STATUS (2026-07-12):**` line. That new line ends with: *"The one open idea (widen confluence inputs) is unchanged."*

The sentence added in `030bf46` is the opposite of what `99f6f1d` had already recorded, in the same file family, two hours earlier, in the same session. It was not a case of the text going stale over time — the sentence was already false at the moment it was committed. `030bf46`'s own commit message says it's a status *refresh*, meaning it was written specifically to bring the index up to date, and still got this wrong.

Below that same #20 entry, a second, older sentence carried the identical stale claim forward untouched: *"Kept OPEN (user, 2026-07-03) only for one unscoped idea: widen the confluence/flow inputs — today just 2 signals feed confluence... needs a definition of 'wider' before it's buildable."* This sentence predates `7edf7a4`/`99f6f1d`/`030bf46` entirely and was never revisited by any of those three commits, despite sitting in the same `## 20.` entry as the line that did get freshly (and wrongly) rewritten.

## Case 2 — item #57 (Schwab real-time options): an old sentence left in place under a header that already says done

`TODO.md`'s header for item #57 correctly reads: `## 57. Move live options data onto the Schwab real-time feed — DONE 2026-07-09 (thresholds tuned from measured outcomes; nightly grading live)`.

Immediately under that header, the **first line of the body** — the exact position the "Lead with current status" rule says must always hold the true latest state — is:

`**CURRENT STATUS (2026-07-08):** Two things keep this OPEN. (1) Thresholds still diverge — 4th compare in a row... the owed fix is still to tune options_flow.min_vol_oi/min_volume/min_premium_usd... (2) Schwab login — RENEWED 2026-07-08... Not marking DONE (blocked only on the threshold re-tune now). Next: tune thresholds for Schwab's real-time speed → then close.`

This paragraph is dated one day before the header's own `DONE 2026-07-09` resolution and says the opposite of the header two lines above it — that the item is still open and blocked on a specific piece of work (threshold tuning) that, per the detail file `todo/schwab-options-realtime.md`, was in fact completed and closed out on 2026-07-09 (real data graded 8,681 stored flow events, `min_vol_oi` moved 10→20, a nightly grading timer made permanent). No commit ever added a fresh `CURRENT STATUS (2026-07-09)` paragraph above this one; the header title was updated to say DONE, but the leading body paragraph — the part a quick scan actually reads — was left exactly as it was on 07-08.

## Why this matters

A person or model scanning `TODO.md` for "what's left to do" reads the first body line of an item, not the full commit history or the detail file. In both cases above, that first line gave an actively wrong answer:
- #20: claimed an idea was still open the same day it was closed.
- #57: claimed specific work was still owed and blocking, one day after that exact work was finished and the item marked DONE in its own header.

Anyone (human or agent) relying on `TODO.md` at face value — without independently re-deriving state from the detail files, commit history, or live config — will report stale/wrong status as current fact. This is exactly what happened in this session: item #57 was reported as needing threshold-tuning work today, and item #20 was reported as blocked on an undefined idea today, both incorrect.

## This is a confirmed recurrence, not a first occurrence

`todo/CONVENTION.md`'s "Lead with current status" section states its own rationale for existing: *"this happened with #32/#42 on 2026-06-27, but the real work is done, but the top is frozen at an old 'what remains' note."* That incident is what motivated the rule requiring the first body line to always be current. The two cases documented here (#20 and #57, 2026-07-12) show the same failure class recurring after the rule was already written and in force — once as a newly-written sentence that was wrong on arrival, once as an old sentence that was never replaced.

## Scope of what has and hasn't been checked

Only items #20 and #57 have been verified against their detail files and git history for this specific defect. No systematic sweep of the other ~70 items in `TODO.md` has been done, so it is unknown whether this is isolated to these two items or a broader pattern across the file. The mechanism by which `TODO.md`'s index lines get refreshed (whether it is invoked mid-session, at the "bye"/session-close trigger, both, manually, or by an automated step) has not been conclusively identified — commit `030bf46`'s timing (~4 hours after the build work, matching the wording of the session-close protocol's TODO-update instruction) is suggestive but not confirmed as the mechanism.

## Files / code involved

- `TODO.md` — the index file where both contradictions live (entries for #20 and #57).
- `todo/CONVENTION.md` — "Lead with current status" section, the existing rule this defect violates; also documents the prior #32/#42 incident this is a recurrence of.
- `todo/wolf-macro-brain.md` — #20's detail file; contains the correct, non-contradictory account ("this closes...").
- `todo/schwab-options-realtime.md` — #57's detail file; contains the correct, non-contradictory account (DONE 2026-07-09, three numbered findings, permanent nightly grading job).
- Relevant commits: `7edf7a4`, `99f6f1d`, `030bf46` (item #20 case); `0ad17f1` and the 2026-07-09 session-notes commits in `todo/schwab-options-realtime.md`'s own history (item #57 case).
- CLAUDE.md's "Session Close Trigger" step 1 ("Update the TODO list FIRST...") — the closest documented instruction to whatever produced `030bf46`; not confirmed as the actual trigger.

## Open questions (for a future session to investigate — not answered here)

- Is the update step that writes/refreshes `CURRENT STATUS` lines in `TODO.md` invoked automatically (e.g. at session close), manually, or both?
- Is it a human-only edit, an AI-assisted edit, or fully automated? (`030bf46` is co-authored by "Claude Fable 5.")
- Does the same defect exist on other items beyond #20 and #57? No sweep has been performed.
- Why did the existing "Lead with current status" rule, written specifically to prevent this class of bug, fail to prevent it here?
