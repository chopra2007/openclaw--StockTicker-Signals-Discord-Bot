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

## Sweep of the rest of the list (2026-07-12) — 11 more items checked

Following the two cases above, a targeted sweep checked every other item in `TODO.md` that carries a non-plain-DONE marker or a `CURRENT STATUS` line (the only items where this defect is possible): #6, #32, #42, #47, #54, #55, #56, #59, #61, #67, #68. Results below, split by confidence.

### Confirmed — same mechanism as Case 2 (#57): header updated, first body line never replaced

- **#59** (regression-gate auto-fixer). Header: `SOAKING until 2026-07-25 (v3 race done 2026-07-11; pinned deepseek-v4-flash)`. First body line: `**CURRENT STATUS (2026-07-10 late) — REOPENED; NEW TEST PLAN READY, EXECUTE IT NEXT.**` — describes the state *before* the race ran. The detail file's own top line, `todo/regression-gate-auto-recovery.md`, is dated one day later: `**CURRENT STATUS (2026-07-11) — v3 RACE DONE. Pinned deepseek/deepseek-v4-flash.** Executed .omc/plans/ci-fixer-race-v3-2026-07-10.md end to end... SOAKING until 2026-07-25...` TODO.md's header reflects the 07-11 resolution; its first body paragraph does not.
- **#61** (research-and-build run). Header: `DONE 2026-07-09 (last dependency #62 landed)`. First body line: `**CURRENT STATUS (2026-07-05) — RUN EXECUTED.**` ... ending `**DEFERRED to #62-#65** (need dedicated sessions / live shadow checks). Stays OPEN until those land.` The detail file's top line, `todo/bot-deep-research-prompt.md`, is dated 2026-07-09: `**CURRENT STATUS (2026-07-09) — DONE.** The last open dependency, #62's two forward-loggers, landed today... Nothing further for a human to do.` Same pattern: header updated, first body paragraph frozen at an earlier, superseded state.

### Related — a DONE item whose body still contains an unresolved, never-dated-closed loose end

- **#32** and **#42** (same underlying signal-flip work, two separate index entries). Both headers: `DONE 2026-06-29`; both detail files' `**Status:**` lines also say `DONE 2026-06-29` — headers agree with each other. But both entries' first `CURRENT STATUS` body line is still dated **2026-06-27** and reads conditionally: *"One live-check is owed: E2 hasn't touched a real alert yet... an automatic check runs Mon 2026-06-29 4pm PDT and pings notifications.log. If that's ✅, this item is fully done."* Neither `TODO.md` nor either detail file contains any dated sentence recording that Monday's check actually ran or what it found. The `DONE` marker was applied, but the specific evidence the marker depends on was never written down anywhere. Note: #32 and #42 are the exact two items `todo/CONVENTION.md`'s "Lead with current status" rule already cites as the reason the rule exists — meaning even the fix for the original incident left this particular loose thread (the Monday check's outcome) unresolved.
- **#54** (reliability hardening soak). Header: `DONE 2026-07-04`. Body (matching the detail file `todo/reliability-hardening-soak.md` verbatim) ends: *"One live watch owed: confirm the breaker opens `exa`... eyeball it next trading day."* `git log` on the detail file shows exactly 2 commits, both from 2026-07-04 — untouched since. No record anywhere that this eyeball check ever happened. Same shape as #32/#42: a DONE item with an explicit, still-open, undated verification step inside it.

### Reverse-direction case — the short index is correct, the detail file is what's stale

- **#67** (feature-idea sweep). `TODO.md`'s own summary (dated 2026-07-08) correctly states all 6 build stages shipped, 16 features live-behind-flags. But the detail file, `todo/next-features-jul2026-resume.md`, has not been touched since 2026-07-07 — its `**Status:**` line still says `OPEN`, and its latest dated section describes the state as "sweep done, awaiting the user's build pick," a decision that (per `TODO.md` itself) was made and acted on the very next day. Anyone reading the detail file alone gets the stale, pre-build picture while the short index has the correct one — the same class of defect as Cases 1/2, just with staleness on the opposite file.

### Minor / unconfirmed — flagged, not established as instances of the bug

- **#6** (`!all` quality menu). No contradiction; `TODO.md`'s own running log is *ahead* of its detail file, `todo/all-command-quality.md`, by about three weeks (detail file's newest section is 2026-06-13; TODO.md has a 2026-07-03 entry not yet mirrored into the detail file).
- **#47** (market top/bottom detector). Content agrees between `TODO.md` and `todo/vol-indicator-accuracy-research.md`, but the two files use different status vocabulary for the same fact: `TODO.md`'s header says `PARKED`, while the detail file's own `**Status:**` line opens with the word `OPEN` before going on to describe the same parked-on-paid-data state in the same sentence.
- **#55** (forward-data collection). `TODO.md` states "169 scored calls, 60 fully graded"; the detail file `todo/forward-data-collection.md`'s last recorded count is "43→112 rows (57 graded)." Could be a later nightly-timer run that added rows after the detail file's last note but before TODO.md's line was written — not confirmed as wrong, just an unreconciled number.
- **#56, #68** — checked, no contradiction found; both files agree with each other on content, date, and status marker.

## Why this matters

A person or model scanning `TODO.md` for "what's left to do" reads the first body line of an item, not the full commit history or the detail file. In both cases above, that first line gave an actively wrong answer:
- #20: claimed an idea was still open the same day it was closed.
- #57: claimed specific work was still owed and blocking, one day after that exact work was finished and the item marked DONE in its own header.

Anyone (human or agent) relying on `TODO.md` at face value — without independently re-deriving state from the detail files, commit history, or live config — will report stale/wrong status as current fact. This is exactly what happened in this session: item #57 was reported as needing threshold-tuning work today, and item #20 was reported as blocked on an undefined idea today, both incorrect.

## This is a confirmed recurrence, not a first occurrence

`todo/CONVENTION.md`'s "Lead with current status" section states its own rationale for existing: *"this happened with #32/#42 on 2026-06-27, but the real work is done, but the top is frozen at an old 'what remains' note."* That incident is what motivated the rule requiring the first body line to always be current. The two cases documented here (#20 and #57, 2026-07-12) show the same failure class recurring after the rule was already written and in force — once as a newly-written sentence that was wrong on arrival, once as an old sentence that was never replaced.

## Scope of what has and hasn't been checked

As of the 2026-07-12 sweep, 13 of the ~72 items in `TODO.md` have been checked against their detail files and git history: #20, #57 (original two cases), plus #6, #32, #42, #47, #54, #55, #56, #59, #61, #67, #68 (the sweep). The sweep targeted every item that carries a non-plain-DONE status marker (`ONGOING`, `SOAKING`, `PARKED`) or a `CURRENT STATUS` line, since those are the only items where this defect is structurally possible — a plain `DONE YYYY-MM-DD` item with no such line has nothing to contradict. Of those 13: 4 are confirmed instances of the defect (#20, #57, #59, #61), 3 more show a related but distinct symptom — a DONE item containing an explicit, still-open verification step with no dated record it was ever resolved (#32, #42, #54), 1 is the reverse case where the detail file is stale and the index is correct (#67), and 3 are minor/unconfirmed or clean (#6, #47, #55 minor; #56, #68 clean).

The remaining ~59 items in `TODO.md` are plain `DONE YYYY-MM-DD` with no `CURRENT STATUS` line and were not individually re-verified against their detail files or git history — they were excluded from the sweep by construction (no live status line to contradict), not confirmed clean. The mechanism by which `TODO.md`'s index lines get refreshed (whether it is invoked mid-session, at the "bye"/session-close trigger, both, manually, or by an automated step) has not been conclusively identified — commit `030bf46`'s timing (~4 hours after the build work, matching the wording of the session-close protocol's TODO-update instruction) is suggestive but not confirmed as the mechanism.

## Files / code involved

- `TODO.md` — the index file; contains confirmed contradictions in the entries for #20, #57, #59, #61, plus the related DONE-with-unresolved-loose-end symptom in #32, #42, #54, plus the reverse (stale detail file) case for #67.
- `todo/CONVENTION.md` — "Lead with current status" section, the existing rule this defect violates; also documents the prior #32/#42 incident this is a recurrence of.
- `todo/wolf-macro-brain.md` — #20's detail file; contains the correct, non-contradictory account ("this closes...").
- `todo/schwab-options-realtime.md` — #57's detail file; contains the correct, non-contradictory account (DONE 2026-07-09, three numbered findings, permanent nightly grading job).
- `todo/regression-gate-auto-recovery.md` — #59's detail file; correct, dated 2026-07-11.
- `todo/bot-deep-research-prompt.md` — #61's detail file; correct, dated 2026-07-09.
- `todo/signal-features-phase2.md` / `todo/signal-flip-status-2026-06-15.md` — #32 / #42's detail files; both `Status: DONE 2026-06-29` but contain the same unresolved 2026-06-27 conditional check as TODO.md.
- `todo/reliability-hardening-soak.md` — #54's detail file; contains the same unresolved "eyeball it" line, untouched since 2026-07-04.
- `todo/next-features-jul2026-resume.md` — #67's detail file; the stale side of that item's contradiction (still says OPEN, untouched since 2026-07-07).
- Relevant commits: `7edf7a4`, `99f6f1d`, `030bf46` (item #20 case); `0ad17f1` and the 2026-07-09 session-notes commits in `todo/schwab-options-realtime.md`'s own history (item #57 case).
- CLAUDE.md's "Session Close Trigger" step 1 ("Update the TODO list FIRST...") — the closest documented instruction to whatever produced `030bf46`; not confirmed as the actual trigger.

## Open questions (for a future session to investigate — not answered here)

- Is the update step that writes/refreshes `CURRENT STATUS` lines in `TODO.md` invoked automatically (e.g. at session close), manually, or both?
- Is it a human-only edit, an AI-assisted edit, or fully automated? (`030bf46` is co-authored by "Claude Fable 5.")
- Does the same defect exist among the ~59 plain-DONE items not covered by this sweep (excluded only because they carry no `CURRENT STATUS` line to check — not verified clean)?
- Why did the existing "Lead with current status" rule, written specifically to prevent this class of bug, fail to prevent it here — and fail again on #32/#42, the very items it was written about, in the form of an unresolved verification step inside an item already marked DONE?
- What should happen to a DONE item (#32, #42, #54) whose closure depends on a specific check that has no dated record of ever running — is the check itself missing, or did it run somewhere not reflected in either file?
- Should the reverse case (#67: index correct, detail file stale) be treated as the same bug class, or a separate one — a detail file that stops being updated once an item is effectively finished, rather than an index line that gets the summary wrong?

### Session notes — 2026-07-12

- **Worked on:** Diagnosis + fix design (the "future session with a stronger model" this file was waiting for). Evidence spot-checked against git before concluding: `030bf46` really wrote the wrong #20 sentence (later corrected by `6836d91`, so that one instance is fixed); #57 and #59 still lead with stale paragraphs in `TODO.md` today.

- **Diagnosis:** The same status fact is hand-typed in four places (index header marker, index first body line, detail-file `**Status:**`, detail-file `CURRENT STATUS`) and nothing ever checks they agree. The updates are written by the AI at session close (`030bf46` is Co-Authored-By Claude, timed to the close protocol) **from session memory, not from the detail file** — so a "refresh" can be wrong on arrival (#20), and partial edits (header changed, body line forgotten: #57/#59/#61) have no tripwire. The "Lead with current status" rule failed because it's prose — it describes the desired end state but nothing executes or verifies it. The convention already learned this exact lesson once for config switches ("copies drift — derive live state, never hand-copy") and fixed it with `scripts/todo_switch_state.py` + a daily timer; the status lines never got the same treatment.

- **Decisions (proposed design, awaiting user go):**
  1. **One writing spot.** Status prose is written ONLY in the detail file (`**Status:**` marker + `CURRENT STATUS` line). `TODO.md`'s header marker and first body line become machine-mirrored — never hand-edited again.
  2. **New `scripts/todo_status_sync.py`** (reuse `todo_switch_state.py`'s parsers). `--fix`: copy detail `Status` → index header marker, detail `CURRENT STATUS` line → index first body line; touch nothing else (hand-written history paragraphs stay). `--check`: flag (a) header vs detail `Status` mismatch (#67/#47 shape), (b) index lead-line date older than the detail file's (#57/#59/#61 shape), (c) DONE/SOAKING items whose lead line predates the DONE date and still contains forward-looking phrases ("Next:", "Not marking DONE", "stays OPEN", "owed", "eyeball it") with no later dated resolution (#32/#42/#54 shape).
  3. **Wire `--check` in twice:** into the existing daily drift timer (append to `notifications.log`, same proven pattern as switch drift), and into session close — CLAUDE.md step 1 becomes "update the DETAIL file, run `--fix`, `--check` must be clean before commit."
  4. **One-time cleanup pass:** repair #57/#59/#61 lead lines; run down whether #32/#42's Monday E2 check and #54's exa-breaker eyeball ever happened (logs/notifications) and write the dated answer into both files; fix #67's detail `Status:` line; align #47's OPEN-vs-PARKED vocabulary.
  - **Rejected alternative:** fully generating `TODO.md` from the detail files — structurally cleanest, but it would destroy the hand-written index summaries the user scans, for no extra safety over mirror-plus-check.

- **Next:** On user go: build `todo_status_sync.py` + tests, wire the timer + close protocol (CLAUDE.md/CONVENTION.md edits need explicit user approval per standing rule), then the one-time cleanup pass.
